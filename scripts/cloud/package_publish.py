"""Verify a sanitized Studio package and publish it to production stores.

This command is the production handoff boundary for a package created on a
trusted workstation.  It deliberately does not restore SQLite into a running
deployment.  Instead it verifies the read-only SQLite snapshot, publishes
immutable logical artifacts to the configured object store, and imports the
stable rows into an empty RuntimeDatabase transaction.

Example (credentials are read from the environment, never from the package)::

    python -m scripts.cloud.package_publish \
        --package /secure/inbox/r2s-studio-data.zip

The command is intentionally conservative: a non-empty target database, an
active job, a checksum mismatch, a path traversal member, or an account outside
the package's explicit scrub/seed policy aborts the operation before product
rows are written.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from scripts.studio.data_package import ACCOUNT_MODE_SCRUB, ACCOUNT_MODE_SEED, ACCOUNT_MODE_SELECTED
from scripts.studio.data_package import PackageError as StudioPackageError
from scripts.studio.data_package import unpack as unpack_data_package
from scripts.studio.data_package import verify as verify_data_package
from src.services.orchestration.artifacts.checksum import sha256_file
from src.services.orchestration.artifacts.remote import RemoteObject, S3ObjectStore
from src.services.orchestration.jobs.database import LATEST_SCHEMA_VERSION, RuntimeDatabase

PACKAGE_METADATA = PurePosixPath("data/studio_local/DATA_PACKAGE.json")
PACKAGE_DATABASE = PurePosixPath("data/studio_local/runtime.db")
ARTIFACT_PACKAGE_PREFIX = PurePosixPath("data/studio_local/artifacts")
OPTIONAL_PROVISION_FAMILIES = (
    (PurePosixPath("data/demo/library"), PurePosixPath("demo/library")),
    (PurePosixPath("data/asset_previews"), PurePosixPath("asset_previews")),
    (PurePosixPath("data/rerun_recordings"), PurePosixPath("rerun_recordings")),
    (PurePosixPath("data/studio_local/thumbnail_cache"), PurePosixPath("studio_local/thumbnail_cache")),
)

# These are the rows whose state is meaningful after a package handoff.  The
# target schema itself is always created by RuntimeDatabase's canonical
# migrations, never copied from SQLite.
IMPORT_COLUMNS: dict[str, tuple[str, ...]] = {
    "r2s_users": ("user_id", "email", "payload"),
    "r2s_projects": ("project_id", "payload"),
    "r2s_uploads": ("upload_id", "payload"),
    "r2s_imports": ("import_id", "upload_id", "payload"),
    "r2s_jobs": ("job_id", "project_id", "version", "manifest_ref"),
    "r2s_job_events": ("job_id", "version", "payload"),
    "r2s_scene_requests": ("job_id", "status", "payload"),
    "r2s_audit_log": ("entry_id", "at", "user_id", "action", "payload"),
    "r2s_resource_usage": ("usage_id", "job_id", "recorded_at", "payload"),
}
IMPORT_ORDER = tuple(IMPORT_COLUMNS)
REQUIRED_SOURCE_TABLES = frozenset(IMPORT_COLUMNS)
TRANSIENT_TABLES = (
    "r2s_sessions",
    "r2s_invites",
    "r2s_upload_sessions",
    "r2s_workers",
    "r2s_resource_waits",
    "r2s_resource_reservations",
)
TARGET_EMPTY_TABLES = (*IMPORT_ORDER, *TRANSIENT_TABLES, "r2s_trash")
BUSY_STATUSES = frozenset({"queued", "running", "uploading", "processing", "pending", "waiting"})
CHECKSUM_KEYS = ("artifact_checksum", "checksum")
SAFE_ARTIFACT_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*$")


class PackagePublishError(ValueError):
    """A package or destination violates the production handoff contract."""


class PublishStore(Protocol):
    """Minimum object-store surface required by the publisher and its tests."""

    def head(self, key: str) -> RemoteObject | None:
        """Return immutable object metadata, or ``None`` when the key is absent."""

    def put_file(self, key: str, path: Path, checksum: str) -> None:
        """Upload one file with the checksum metadata used by ArtifactRemote."""


@dataclass(frozen=True)
class StagedPackage:
    """A validated package extracted into a private temporary directory."""

    root: Path
    database: Path
    artifacts: Path
    metadata: dict[str, Any]
    rows: dict[str, list[tuple[Any, ...]]]


@dataclass(frozen=True)
class PublishReport:
    """Observable counts from the object-store part of a publish."""

    uploaded_files: int
    skipped_files: int
    uploaded_bytes: int
    artifact_files: int


@dataclass(frozen=True)
class ProvisionReport:
    """Counts from the optional filesystem-family provisioning step."""

    copied_files: int
    skipped_files: int
    copied_bytes: int


def _optional_files(root: Path) -> list[tuple[Path, Path]]:
    """List optional package files and their destination-relative paths."""
    files: list[tuple[Path, Path]] = []
    for source_relative, destination_relative in OPTIONAL_PROVISION_FAMILIES:
        source_root = root.joinpath(*source_relative.parts)
        if not source_root.exists():
            continue
        if source_root.is_symlink() or not source_root.is_dir():
            raise PackagePublishError(f"optional package family is not a directory: {source_relative}")
        for source in sorted(source_root.rglob("*")):
            relative = source.relative_to(source_root)
            if source.is_symlink():
                raise PackagePublishError(f"optional package family contains a symlink: {source_relative / relative}")
            if source.is_dir():
                continue
            if not source.is_file() or any(part.startswith(".") for part in relative.parts):
                raise PackagePublishError(
                    f"optional package family contains an unsafe file: {source_relative / relative}"
                )
            files.append((source, Path(*destination_relative.parts, *relative.parts)))
    return files


def _ensure_directory_chain(root: Path, target: Path) -> None:
    """Reject symlink/file components in a destination directory chain."""
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise PackagePublishError(f"provision destination is not a directory: {root}")
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise PackagePublishError("provision target escapes its destination root") from error
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise PackagePublishError(f"provision destination contains an unsafe path: {current}")


def _reject_symlink_ancestors(path: Path) -> Path:
    """Return an absolute path after rejecting symlinked ancestors."""
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise PackagePublishError(f"provision destination has a symlinked ancestor: {current}")
    return absolute


def provision_optional_data(package: Path, destination: Path) -> ProvisionReport:
    """Merge optional demo/preview/Rerun/cache files into a mounted data root.

    The canonical package is verified and unpacked into an empty temporary root
    first.  Only optional filesystem families are then copied.  The production
    database and logical artifact tree never enter ``destination``.
    Existing files are immutable: identical bytes are skipped and a different
    checksum aborts before any copy begins.
    """
    destination = _reject_symlink_ancestors(destination)
    if destination.is_symlink():
        raise PackagePublishError(f"provision destination must not be a symlink: {destination}")
    created_files: list[Path] = []
    created_directories: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="r2s-package-provision-") as temporary:
        staged = Path(temporary) / "package"
        extract_package(package, staged)
        candidates = _optional_files(staged)
        planned: list[tuple[Path, Path, int]] = []
        skipped_files = 0
        for source, relative in candidates:
            target = destination / relative
            _ensure_directory_chain(destination, target.parent)
            size = source.stat().st_size
            if target.exists():
                if target.is_symlink() or not target.is_file():
                    raise PackagePublishError(f"provision target is not a regular file: {relative}")
                if target.stat().st_size != size or sha256_file(target) != sha256_file(source):
                    raise PackagePublishError(f"provision target differs from package: {relative}")
                skipped_files += 1
                continue
            planned.append((source, target, size))

        copied_bytes = 0
        try:
            if planned and not destination.exists():
                destination.mkdir(parents=True)
                created_directories.append(destination)
            for _, target, _ in planned:
                current = destination
                for part in target.parent.relative_to(destination).parts:
                    current /= part
                    if not current.exists():
                        current.mkdir()
                        created_directories.append(current)
                    elif current.is_symlink() or not current.is_dir():
                        raise PackagePublishError(f"provision destination contains an unsafe path: {current}")
            for source, target, size in planned:
                temporary_target = target.with_name(f".{target.name}.provision-{os.getpid()}-{len(created_files)}.tmp")
                try:
                    shutil.copy2(source, temporary_target)
                    os.link(temporary_target, target)
                finally:
                    temporary_target.unlink(missing_ok=True)
                created_files.append(target)
                copied_bytes += size
        except (FileExistsError, OSError, PackagePublishError) as error:
            for target in reversed(created_files):
                target.unlink(missing_ok=True)
            for directory in sorted(created_directories, key=lambda path: len(path.parts), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise PackagePublishError(f"provision failed for mounted data root: {error}") from error
    return ProvisionReport(
        copied_files=len(created_files),
        skipped_files=skipped_files,
        copied_bytes=copied_bytes,
    )


def extract_package(package: Path, destination: Path) -> None:
    """Verify and unpack the canonical ZIP through the shared Studio helper."""
    package = package.expanduser().resolve()
    if not package.is_file():
        raise PackagePublishError(f"package does not exist: {package}")
    destination.mkdir(parents=True, exist_ok=False)
    try:
        # verify() hashes every member and validates the manifest before
        # unpack() is allowed to write the empty staging directory.  Suppress
        # the helper's human CLI line; the publisher emits one JSON report.
        with contextlib.redirect_stdout(io.StringIO()):
            verify_data_package(package)
            unpack_data_package(destination, package, force=False)
    except (StudioPackageError, OSError, sqlite3.Error) as error:
        raise PackagePublishError(f"cannot verify package {package.name}: {error}") from error


def _read_json_object(raw: str | bytes, context: str) -> dict[str, Any]:
    """Parse a row payload and require a JSON object."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise PackagePublishError(f"invalid JSON in {context}") from error
    if not isinstance(value, dict):
        raise PackagePublishError(f"expected JSON object in {context}")
    return value


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    """Return user tables from a package database."""
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _load_rows(connection: sqlite3.Connection, tables: set[str]) -> dict[str, list[tuple[Any, ...]]]:
    """Read only the stable import rows using constant table/column names."""
    missing = REQUIRED_SOURCE_TABLES - tables
    if missing:
        raise PackagePublishError(f"package database is missing canonical tables: {', '.join(sorted(missing))}")
    rows: dict[str, list[tuple[Any, ...]]] = {}
    for table, columns in IMPORT_COLUMNS.items():
        selected = ", ".join(columns)
        rows[table] = list(connection.execute(f"SELECT {selected} FROM {table} ORDER BY 1"))
    return rows


def _table_count(connection: sqlite3.Connection, table: str, tables: set[str]) -> int:
    """Count a known table, treating a pre-migration table as empty."""
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if table in tables else 0


def _iter_artifact_refs(
    value: Any,
    context: str,
    *,
    skip_self_checksum: bool = False,
    require_checksum: bool = True,
) -> Iterator[tuple[str, str]]:
    """Yield canonical byte refs while matching the shared JSON verifier.

    Artifact event records can legitimately carry ``artifact_uri: null`` when a
    stage did not publish an artifact.  ``data_package._record_artifact_json``
    only treats a string beginning with ``artifact://jobs/`` as a reference;
    applying the same predicate here prevents those status records from being
    mistaken for byte refs.
    """
    if isinstance(value, dict):
        uri_fields = {
            str(key): child
            for key, child in value.items()
            if isinstance(child, str) and child.startswith("artifact://jobs/")
        }
        for uri_key, uri_value in uri_fields.items():
            checksum_keys = list(CHECKSUM_KEYS)
            if uri_key.endswith("_uri"):
                checksum_keys.append(f"{uri_key[:-4]}_checksum")
            yielded = False
            for checksum_key in dict.fromkeys(checksum_keys):
                checksum = value.get(checksum_key)
                if not isinstance(checksum, str) or not checksum:
                    continue
                if skip_self_checksum and uri_key == "artifact_uri" and checksum_key == "artifact_checksum":
                    continue
                yield uri_value, checksum
                yielded = True
            if (
                require_checksum
                and not yielded
                and not (skip_self_checksum and uri_key == "artifact_uri" and value.get("artifact_checksum"))
            ):
                raise PackagePublishError(f"artifact reference without URI/checksum in {context}.{uri_key}")
        for key, child in value.items():
            yield from _iter_artifact_refs(child, f"{context}.{key}", require_checksum=require_checksum)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_artifact_refs(child, f"{context}[{index}]", require_checksum=require_checksum)


def _artifact_path(artifacts: Path, uri: str) -> Path:
    """Map a logical artifact URI to a safe staged path."""
    prefix = "artifact://"
    if not uri.startswith(prefix):
        raise PackagePublishError(f"artifact URI must use artifact://: {uri!r}")
    relative = PurePosixPath(uri.removeprefix(prefix))
    if len(relative.parts) < 3 or relative.parts[0] != "jobs":
        raise PackagePublishError(f"artifact URI must use artifact://jobs/<job>/<path>: {uri!r}")
    if any(part in {"", ".", ".."} for part in relative.parts) or "\\" in uri:
        raise PackagePublishError(f"artifact URI contains an unsafe path: {uri!r}")
    if any(SAFE_ARTIFACT_SEGMENT.fullmatch(part) is None for part in relative.parts):
        raise PackagePublishError(f"artifact URI contains an unsafe path: {uri!r}")
    path = artifacts.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(artifacts.resolve()):
        raise PackagePublishError(f"artifact URI escapes the package: {uri!r}")
    return path


def _validate_artifact_tree(artifacts: Path) -> list[Path]:
    """Return regular artifact files and reject links/temp files in the package."""
    if not artifacts.exists():
        return []
    if not artifacts.is_dir():
        raise PackagePublishError("data/studio_local/artifacts must be a directory")
    files: list[Path] = []
    for path in sorted(artifacts.rglob("*")):
        relative = path.relative_to(artifacts)
        if path.is_symlink():
            raise PackagePublishError(f"artifact tree contains a symlink: {relative}")
        if any(part.startswith(".") for part in relative.parts):
            raise PackagePublishError(f"artifact tree contains a temporary/hidden member: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PackagePublishError(f"artifact tree contains a non-file: {relative}")
        if not relative.parts or relative.parts[0] != "jobs":
            raise PackagePublishError(f"artifact is outside jobs/: {relative}")
        if any(SAFE_ARTIFACT_SEGMENT.fullmatch(part) is None for part in relative.parts):
            raise PackagePublishError(f"artifact path contains an unsupported segment: {relative}")
        files.append(path)
    return files


def _account_policy(metadata: Mapping[str, Any]) -> tuple[str, frozenset[str]]:
    """Read the canonical account mode without exposing password material."""
    raw = metadata.get("account_policy")
    if raw is None:
        return ACCOUNT_MODE_SCRUB, frozenset()
    if not isinstance(raw, Mapping):
        raise PackagePublishError("DATA_PACKAGE.json has an invalid account_policy")
    mode = raw.get("mode")
    raw_ids = raw.get("kept_user_ids", [])
    if mode not in {ACCOUNT_MODE_SCRUB, ACCOUNT_MODE_SELECTED, ACCOUNT_MODE_SEED}:
        raise PackagePublishError("DATA_PACKAGE.json has an unsupported account_policy mode")
    if not isinstance(raw_ids, list) or any(not isinstance(value, str) or not value for value in raw_ids):
        raise PackagePublishError("DATA_PACKAGE.json has invalid account policy user IDs")
    kept_user_ids = frozenset(raw_ids)
    if len(kept_user_ids) != len(raw_ids):
        raise PackagePublishError("DATA_PACKAGE.json has duplicate account policy user IDs")
    if mode == ACCOUNT_MODE_SCRUB and kept_user_ids:
        raise PackagePublishError("scrub-all account policy cannot keep user IDs")
    if mode in {ACCOUNT_MODE_SELECTED, ACCOUNT_MODE_SEED} and len(kept_user_ids) != 2:
        raise PackagePublishError("account policy must keep exactly two users")
    return str(mode), kept_user_ids


def _validate_users(
    connection: sqlite3.Connection,
    tables: set[str],
    metadata: Mapping[str, Any],
) -> tuple[str, int]:
    """Validate scrubbed users or the explicitly authorized two seed accounts."""
    if "r2s_users" not in tables:
        mode, kept_user_ids = _account_policy(metadata)
        if kept_user_ids:
            raise PackagePublishError("account policy keeps users but package has no r2s_users table")
        return mode, 0
    mode, kept_user_ids = _account_policy(metadata)
    columns = {str(row[1]): index for index, row in enumerate(connection.execute('PRAGMA table_info("r2s_users")'))}
    required = {"user_id", "email", "payload"}
    if not required.issubset(columns):
        raise PackagePublishError("package r2s_users table is missing canonical columns")
    observed_user_ids: set[str] = set()
    for row in connection.execute('SELECT * FROM "r2s_users"'):
        user_id = str(row[columns["user_id"]])
        observed_user_ids.add(user_id)
        payload = row[columns["payload"]]
        record = _read_json_object(payload, f"r2s_users/{user_id}")
        if record.get("email") != row[columns["email"]]:
            raise PackagePublishError(f"user {user_id!r} has inconsistent email metadata")
        if user_id in kept_user_ids:
            password_hash = record.get("password_hash")
            if not isinstance(password_hash, str) or not password_hash or password_hash == "disabled-in-data-package":
                raise PackagePublishError(f"kept user {user_id!r} has no reusable password hash")
            active = record.get("active")
            if not isinstance(active, bool):
                raise PackagePublishError(f"kept user {user_id!r} has no boolean active state")
            if "password_hash" in columns and row[columns["password_hash"]] != password_hash:
                raise PackagePublishError(f"kept user {user_id!r} password fields do not match")
            if "active" in columns and row[columns["active"]] not in (active, int(active)):
                raise PackagePublishError(f"kept user {user_id!r} active fields do not match")
            continue
        if record.get("active") is not False or record.get("password_hash") != "disabled-in-data-package":
            raise PackagePublishError(
                f"user {user_id!r} is not a disabled attribution record; create production users after import"
            )
        if "password_hash" in columns and row[columns["password_hash"]] != "disabled-in-data-package":
            raise PackagePublishError(f"user {user_id!r} still has password material")
        if "active" in columns and row[columns["active"]] not in (0, False):
            raise PackagePublishError(f"user {user_id!r} is still active")
    if not kept_user_ids.issubset(observed_user_ids):
        raise PackagePublishError("account policy references a user missing from the package")
    return mode, len(kept_user_ids)


def _human_metric_waiting(event: Mapping[str, Any], manifest: Mapping[str, Any]) -> bool:
    """Allow the intentional RUNNING state waiting for metric confirmation."""
    if event.get("status") != "RUNNING" or event.get("current_stage") != "ST-METRIC-CANONICALIZE":
        return False
    stages = manifest.get("stage_artifacts", [])
    if not isinstance(stages, list) or any(
        isinstance(stage, dict) and stage.get("stage_id") == "ST-METRIC-CANONICALIZE" for stage in stages
    ):
        return False
    return True


def _validate_transient_tables(
    connection: sqlite3.Connection,
    tables: set[str],
    rows: Mapping[str, Sequence[tuple[Any, ...]]],
) -> None:
    """Reject local sessions, worker leases, or in-flight reservations."""
    present = [table for table in TRANSIENT_TABLES if table in tables and _table_count(connection, table, tables)]
    if present:
        raise PackagePublishError(f"package contains local/transient rows: {', '.join(present)}")
    if "r2s_scene_requests" in tables:
        for job_id, status in connection.execute("SELECT job_id, status FROM r2s_scene_requests"):
            if str(status).casefold() in BUSY_STATUSES:
                raise PackagePublishError(f"job {job_id!r} has an active scene request: {status}")
    for table in ("r2s_uploads", "r2s_imports"):
        for row in rows[table]:
            payload = _read_json_object(row[-1], f"{table}[{row[0]}]")
            status = payload.get("status")
            if isinstance(status, str) and status.casefold() in BUSY_STATUSES:
                raise PackagePublishError(f"{table} {row[0]!r} is still active: {status}")


def _validate_job_manifests(rows: Mapping[str, Sequence[tuple[Any, ...]]], artifacts: Path) -> None:
    """Require every packaged job to point to a terminal, checksummed manifest."""
    latest_events: dict[str, tuple[int, dict[str, Any]]] = {}
    for job_id, version, payload in rows["r2s_job_events"]:
        key = str(job_id)
        parsed = _read_json_object(payload, f"r2s_job_events/{job_id}")
        if key not in latest_events or int(version) > latest_events[key][0]:
            latest_events[key] = (int(version), parsed)
    for job_id, _project_id, _version, raw_reference in rows["r2s_jobs"]:
        if not raw_reference:
            raise PackagePublishError(f"job {job_id!r} has no manifest reference")
        reference = _read_json_object(raw_reference, f"r2s_jobs/{job_id}.manifest_ref")
        uri = reference.get("artifact_uri")
        checksum = reference.get("artifact_checksum")
        if not isinstance(uri, str) or not isinstance(checksum, str):
            raise PackagePublishError(f"job {job_id!r} has an incomplete manifest reference")
        path = _artifact_path(artifacts, uri)
        if not path.is_file() or sha256_file(path) != checksum:
            raise PackagePublishError(f"job {job_id!r} manifest is missing or has a checksum mismatch")
        manifest = _read_json_object(path.read_text(encoding="utf-8"), f"manifest {uri}")
        status = manifest.get("status")
        event = latest_events.get(str(job_id), (0, {}))[1]
        waiting_metric = _human_metric_waiting(event, manifest)
        if isinstance(status, str) and status.casefold() in BUSY_STATUSES and not waiting_metric:
            raise PackagePublishError(f"job {job_id!r} is still active: {status}")


def _validate_row_payloads(rows: Mapping[str, Sequence[tuple[Any, ...]]]) -> list[tuple[str, str]]:
    """Parse import payloads and collect all logical artifact references."""
    references: list[tuple[str, str]] = []
    for table, table_rows in rows.items():
        for row in table_rows:
            for index, value in enumerate(row):
                if table == "r2s_jobs" and index == 3:
                    payload = _read_json_object(value, f"{table}.manifest_ref")
                elif isinstance(value, str) and index == len(row) - 1:
                    # Payload columns are the final string in every table except
                    # r2s_jobs, whose manifest_ref was handled above.  Invalid
                    # payload JSON must fail closed; it is not an optional field.
                    payload = _read_json_object(value, f"{table}[{row[0]}]")
                else:
                    continue
                references.extend(_iter_artifact_refs(payload, f"{table}[{row[0]}]"))
    return references


def _validate_json_artifact_refs(files: Sequence[Path]) -> list[tuple[str, str]]:
    """Validate byte refs nested inside JSON artifacts, preserving root identity checksums."""
    references: list[tuple[str, str]] = []
    for path in files:
        if path.suffix.lower() != ".json":
            continue
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # The shared package verifier already applies its text-closure
            # policy.  Only valid JSON objects/lists can contain structured
            # refs that this publisher can validate again.
            continue
        if isinstance(parsed, (dict, list)):
            references.extend(
                _iter_artifact_refs(
                    parsed,
                    f"artifact/{path.name}",
                    skip_self_checksum=True,
                    require_checksum=False,
                )
            )
    return references


def validate_staged_package(root: Path) -> StagedPackage:
    """Validate metadata, SQLite integrity, sanitization, active state, and checksums."""
    root = root.resolve()
    database = root / Path(*PACKAGE_DATABASE.parts)
    metadata_path = root / Path(*PACKAGE_METADATA.parts)
    artifacts = root / Path(*ARTIFACT_PACKAGE_PREFIX.parts)
    if not database.is_file() or not metadata_path.is_file():
        raise PackagePublishError("package must contain data/studio_local/runtime.db and DATA_PACKAGE.json")
    metadata = _read_json_object(metadata_path.read_text(encoding="utf-8"), "DATA_PACKAGE.json")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise PackagePublishError("runtime.db failed SQLite integrity_check")
        tables = _sqlite_tables(connection)
        schema_row = connection.execute("SELECT version FROM r2s_schema WHERE id=1").fetchone()
        if schema_row is None or int(schema_row[0]) != LATEST_SCHEMA_VERSION:
            raise PackagePublishError(
                f"package schema must be v{LATEST_SCHEMA_VERSION}; observed {schema_row[0] if schema_row else 'missing'}"
            )
        rows = _load_rows(connection, tables)
        _validate_users(connection, tables, metadata)
        _validate_transient_tables(connection, tables, rows)
    files = _validate_artifact_tree(artifacts)
    _validate_job_manifests(rows, artifacts)
    refs = _validate_row_payloads(rows)
    refs.extend(_validate_json_artifact_refs(files))
    verified: dict[Path, str] = {}
    for uri, checksum in refs:
        path = _artifact_path(artifacts, uri)
        if not path.is_file():
            raise PackagePublishError(f"referenced artifact is missing: {uri}")
        observed = verified.setdefault(path, sha256_file(path))
        if observed != checksum:
            raise PackagePublishError(f"artifact checksum mismatch for {uri}: expected {checksum}, observed {observed}")
    # The manifest check above can be the only check for a small package.  All
    # unreferenced files are still hashed during publication and cannot escape
    # the immutable jobs/ namespace.
    if not files and rows["r2s_jobs"]:
        raise PackagePublishError("package has jobs but no artifact files")
    return StagedPackage(root=root, database=database, artifacts=artifacts, metadata=metadata, rows=rows)


def _safe_prefix(prefix: str) -> str:
    """Normalise an object-store prefix and reject key traversal."""
    cleaned = prefix.strip("/")
    if not cleaned:
        return ""
    parts = cleaned.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise PackagePublishError("ARTIFACT_S3_PREFIX contains an unsafe path")
    return "/".join(parts)


def publish_artifacts(artifacts: Path, store: PublishStore, prefix: str = "") -> PublishReport:
    """Upload immutable artifact files, skipping only verified same-checksum keys."""
    safe_prefix = _safe_prefix(prefix)
    files = _validate_artifact_tree(artifacts)
    uploaded = skipped = uploaded_bytes = 0
    for path in files:
        relative = path.relative_to(artifacts).as_posix()
        key = f"{safe_prefix}/{relative}" if safe_prefix else relative
        checksum = sha256_file(path)
        size = path.stat().st_size
        existing = store.head(key)
        if existing is not None:
            if existing.checksum != checksum:
                raise PackagePublishError(f"object exists with a different checksum: {key}")
            if existing.size_bytes != size:
                raise PackagePublishError(f"object exists with a different size: {key}")
            skipped += 1
            continue
        store.put_file(key, path, checksum)
        observed = store.head(key)
        if observed is None or observed.checksum != checksum or observed.size_bytes != size:
            raise PackagePublishError(f"object-store verification failed after upload: {key}")
        uploaded += 1
        uploaded_bytes += size
    return PublishReport(
        uploaded_files=uploaded,
        skipped_files=skipped,
        uploaded_bytes=uploaded_bytes,
        artifact_files=len(files),
    )


def _target_counts(database: RuntimeDatabase) -> dict[str, int]:
    """Read counts for all imported tables from a target schema."""
    with database.transaction() as transaction:
        return {
            table: int(transaction.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in TARGET_EMPTY_TABLES
        }


def assert_target_empty(database: RuntimeDatabase) -> None:
    """Refuse to import over any existing product or attribution rows."""
    counts = _target_counts(database)
    _raise_if_occupied(counts)


def _raise_if_occupied(counts: Mapping[str, int]) -> None:
    """Raise the common non-empty target error for observed table counts."""
    occupied = {table: count for table, count in counts.items() if count}
    if occupied:
        details = ", ".join(f"{table}={count}" for table, count in sorted(occupied.items()))
        raise PackagePublishError(f"target RuntimeDatabase is not empty; refusing replacement ({details})")


def _target_counts_without_migration(database_url: str) -> dict[str, int]:
    """Inspect a target without creating its schema, for the default dry-run."""
    if database_url.startswith("sqlite:///"):
        value = database_url.removeprefix("sqlite:///")
        if not value or value == ":memory:" or "?" in value:
            raise PackagePublishError("dry-run requires a file SQLite URL or a PostgreSQL URL")
        path = Path(value).expanduser().resolve()
        if not path.exists():
            return {table: 0 for table in TARGET_EMPTY_TABLES}
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                tables = _sqlite_tables(connection)
                return {
                    table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    if table in tables
                    else 0
                    for table in TARGET_EMPTY_TABLES
                }
        except sqlite3.Error as error:
            raise PackagePublishError(f"cannot inspect SQLite target: {error}") from error
    if database_url.startswith(("postgresql://", "postgres://")):
        try:
            import psycopg
        except ImportError as error:
            raise PackagePublishError("PostgreSQL dry-run needs psycopg 3") from error
        try:
            with psycopg.connect(database_url, autocommit=True, connect_timeout=10) as connection:
                counts: dict[str, int] = {}
                for table in TARGET_EMPTY_TABLES:
                    exists = connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
                    counts[table] = (
                        int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if exists else 0
                    )
                return counts
        except (psycopg.Error, ValueError) as error:
            raise PackagePublishError("cannot inspect PostgreSQL target") from error
    raise PackagePublishError("DATABASE_URL chỉ hỗ trợ sqlite:/// hoặc postgresql://")


def assert_target_url_empty(database_url: str) -> None:
    """Refuse to proceed when a dry-run can observe existing target rows."""
    _raise_if_occupied(_target_counts_without_migration(database_url))


def import_rows(database: RuntimeDatabase, rows: Mapping[str, Sequence[tuple[Any, ...]]]) -> dict[str, int]:
    """Insert verified rows in one transaction into an already-migrated empty DB."""
    assert_target_empty(database)
    with database.transaction(write=True) as transaction:
        for table in IMPORT_ORDER:
            columns = IMPORT_COLUMNS[table]
            placeholders = ", ".join("?" for _ in columns)
            statement = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            for row in rows[table]:
                transaction.execute(statement, tuple(row))
    return {table: len(rows[table]) for table in IMPORT_ORDER}


def _required_env(name: str) -> str:
    """Read a required operator value from the environment only."""
    value = os.environ.get(name)
    if not value:
        raise PackagePublishError(f"missing {name}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    """Create the publisher CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("publish", "provision"),
        default="publish",
        help="publish stable DB/artifacts (default) or provision optional local data families",
    )
    parser.add_argument("--package", type=Path, required=True, help="verified Studio .zip package")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="upload to R2 and import rows; without this flag the command is a non-mutating dry-run",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        help="mounted data root for the provision command (only optional demo/preview/Rerun/cache files are merged)",
    )
    parser.add_argument("--report", type=Path, help="optional JSON report path")
    return parser


def _write_report(path: Path | None, report: Mapping[str, Any]) -> None:
    """Write a non-secret JSON report atomically when requested."""
    if path is None:
        return
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run verification, publication, and transactional import."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "provision":
            if arguments.apply:
                raise PackagePublishError("provision không dùng --apply")
            if arguments.target_root is None:
                raise PackagePublishError("provision cần --target-root")
            provisioned = provision_optional_data(arguments.package, arguments.target_root)
            report = {
                "provision": {
                    "copied_files": provisioned.copied_files,
                    "skipped_files": provisioned.skipped_files,
                    "copied_bytes": provisioned.copied_bytes,
                },
                "database": "untouched",
                "artifacts": "untouched",
            }
            _write_report(arguments.report, report)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        if arguments.target_root is not None:
            raise PackagePublishError("--target-root chỉ dùng với lệnh provision")
        database_url = _required_env("DATABASE_URL")
        with tempfile.TemporaryDirectory(prefix="r2s-package-") as temporary:
            staging = Path(temporary) / "package"
            extract_package(arguments.package, staging)
            package = validate_staged_package(staging)
            if arguments.apply:
                bucket = _required_env("ARTIFACT_S3_BUCKET")
                access_key = _required_env("ARTIFACT_S3_ACCESS_KEY_ID")
                secret_key = _required_env("ARTIFACT_S3_SECRET_ACCESS_KEY")
                store = S3ObjectStore(
                    bucket,
                    endpoint_url=os.environ.get("ARTIFACT_S3_ENDPOINT"),
                    region=os.environ.get("ARTIFACT_S3_REGION", "auto"),
                    access_key_id=access_key,
                    secret_access_key=secret_key,
                )
                database = RuntimeDatabase(database_url)
                assert_target_empty(database)
            else:
                assert_target_url_empty(database_url)
            account_mode, kept_user_ids = _account_policy(package.metadata)
            report: dict[str, Any] = {
                "metadata": {
                    "git_commit": package.metadata.get("git_commit", "unknown"),
                    "scenes": package.metadata.get("scenes"),
                },
                "account_policy": {
                    "mode": account_mode,
                    "kept_user_count": len(kept_user_ids),
                },
                "schema_version": LATEST_SCHEMA_VERSION,
                "target_rows": {table: len(package.rows[table]) for table in IMPORT_ORDER},
                "auxiliary_data": "local-only; demo, asset_previews, and rerun_recordings are not uploaded",
            }
            if not arguments.apply:
                report["dry_run"] = True
            else:
                published = publish_artifacts(package.artifacts, store, os.environ.get("ARTIFACT_S3_PREFIX", ""))
                imported = import_rows(database, package.rows)
                report["object_store"] = {
                    "uploaded_files": published.uploaded_files,
                    "skipped_files": published.skipped_files,
                    "uploaded_bytes": published.uploaded_bytes,
                    "artifact_files": published.artifact_files,
                }
                report["imported_rows"] = imported
                report["dry_run"] = False
            _write_report(arguments.report, report)
            print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (PackagePublishError, OSError, sqlite3.Error, RuntimeError) as error:
        print(f"package publish refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
