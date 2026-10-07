"""Đóng gói, kiểm tra và khôi phục state của Real2Sim Studio.

Gói là một ZIP tự chứa metadata, database SQLite đã loại bỏ credential/session,
published artifacts và các cache cần để Studio hiển thị đúng scene.  Script chỉ
dùng thư viện chuẩn để có thể chạy trước khi cài toàn bộ dependency của ứng dụng::

    python scripts/studio/data_package.py --root . pack --out r2s-studio-data.zip
    python scripts/studio/data_package.py verify r2s-studio-data.zip
    python scripts/studio/data_package.py --root . unpack r2s-studio-data.zip

`pack` không sao chép cả thư mục data vào staging: chỉ database snapshot nhỏ được
đặt vào temporary directory; file lớn được hash và stream trực tiếp vào ZIP tạm.
Archive chỉ được đổi tên atomic sau khi source-consistency check hoàn tất.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE = Path("data/studio_local")
MANIFEST_NAME = "DATA_PACKAGE.json"
DEFAULT_NAME = "r2s-studio-data.zip"
PACKAGE_VERSION = 1
COMPRESSION_METHODS = {
    "stored": zipfile.ZIP_STORED,
    "deflated": zipfile.ZIP_DEFLATED,
}
RUNTIME_DB_MEMBER = (STATE / "runtime.db").as_posix()

# SQLite state and published files needed by the Web Studio.  Runtime binaries,
# worker scratch, QA captures, trash and local backups are deliberately outside
# this list and therefore can never silently enter a package.
REQUIRED_PATHS = (STATE / "runtime.db", STATE / "artifacts")
OPTIONAL_PATHS = (
    STATE / "thumbnail_cache",
    Path("data/demo/library"),
    Path("data/asset_previews"),
    Path("data/rerun_recordings"),
)
PAYLOAD_PREFIXES = (
    "data/studio_local/artifacts/",
    "data/studio_local/thumbnail_cache/",
    "data/demo/library/",
    "data/asset_previews/",
    "data/rerun_recordings/",
)
PAYLOAD_EXACT = {"data/studio_local/runtime.db"}
LOCKFILES = (
    Path("requirements.lock.txt"),
    Path("requirements-dev.lock.txt"),
    Path("frontend/package-lock.json"),
)

# These rows are host/session state, rather than product history.  Resource
# usage remains in the snapshot because it is historical telemetry displayed by
# the jobs view; active reservations/waits are rejected before packing.
SANITIZE_TABLES = (
    "r2s_sessions",
    "r2s_invites",
    "r2s_resource_reservations",
    "r2s_resource_waits",
    "r2s_workers",
    "r2s_upload_sessions",
    "r2s_scene_publications",
)
ACTIVE_JOB_STATUSES = {"QUEUED", "RUNNING"}
ACTIVE_IMPORT_STATUSES = {"UPLOADING", "PACKAGING", "RUNNING", "PENDING", "PROCESSING", "VERIFYING"}
ACTIVE_UPLOAD_STATUSES = {"UPLOADING", "PENDING", "PROCESSING", "VERIFYING"}
ACTIVE_REQUEST_STATUSES = {"QUEUED", "RUNNING", "PROCESSING"}
METRIC_STAGE = "ST-METRIC-CANONICALIZE"
TRASH_TABLE = "r2s_trash"
PASSWORD_SENTINEL = "disabled-in-data-package"
ACCOUNT_MODE_SCRUB = "scrub-all"
ACCOUNT_MODE_SELECTED = "keep-selected-passwords"
ACCOUNT_MODE_SEED = "keep-seed-accounts"
_PASSWORD_HASH = re.compile(r"^scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9+/=_-]+\$[A-Za-z0-9+/=_-]+$")
TEXT_SUFFIXES = {".json", ".log", ".txt", ".usda"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_URI = re.compile(r"artifact://jobs/[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)+")
_CREDENTIAL_KEY = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"session[_-]?token|token|authorization|bearer|private[_-]?key|client[_-]?secret|token[_-]?hash|code[_-]?hash)"
)
_CREDENTIAL_VALUE_OK = {"", "none", "null", "redacted", "<redacted>", PASSWORD_SENTINEL}


class PackageError(RuntimeError):
    """Lỗi đóng gói/kiểm tra/khôi phục có thể hiển thị cho người vận hành."""


@dataclass(frozen=True)
class FileRecord:
    """Checksum và kích thước của một file payload trong archive."""

    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        """Serialize record theo schema manifest ổn định."""
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class PackageSummary:
    """Kết quả kiểm tra an toàn, không chứa nội dung riêng tư của database."""

    package: Path
    file_count: int
    total_bytes: int
    project_count: int
    artifact_reference_count: int

    def as_dict(self) -> dict[str, object]:
        """Serialize summary cho CLI/tests."""
        return {
            "package": str(self.package),
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "project_count": self.project_count,
            "artifact_reference_count": self.artifact_reference_count,
        }


@dataclass(frozen=True)
class _VerifiedPackage:
    summary: PackageSummary
    manifest: dict[str, Any]
    records: tuple[FileRecord, ...]


@dataclass(frozen=True)
class _FileStat:
    """Metadata đủ để phát hiện source đổi trong lúc stream archive."""

    inode: int
    size: int
    mtime_ns: int
    mode: int


def _root_path(root: Path) -> Path:
    """Resolve checkout root và từ chối root không tồn tại."""
    resolved = Path(root).expanduser().resolve()
    if not resolved.is_dir():
        raise PackageError(f"Không có checkout root: {resolved}")
    return resolved


def _sqlite_readonly(path: Path) -> sqlite3.Connection:
    """Mở SQLite read-only, không tạo file mới khi audit/pack."""
    if not path.is_file() or path.is_symlink():
        raise PackageError("runtime.db không phải file thường")
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    """Lấy tên table user state mà không phụ thuộc schema version cụ thể."""
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    """Lấy cột table từ pragma nội bộ, table name chỉ đến từ sqlite_master."""
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _json_object(value: str, context: str) -> dict[str, Any]:
    """Parse payload JSON và giữ lỗi có context nhưng không in nội dung riêng tư."""
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        raise PackageError(f"payload JSON hỏng trong {context}") from error
    if not isinstance(parsed, dict):
        raise PackageError(f"payload trong {context} không phải object")
    return parsed


def _iter_database_strings(database: Path) -> Iterable[str]:
    """Yield mọi string column để kiểm tra các logical artifact URI."""
    connection = _sqlite_readonly(database)
    try:
        for table in sorted(_table_names(connection)):
            columns = _table_columns(connection, table)
            if not columns:
                continue
            quoted = ",".join(f'"{column}"' for column in columns)
            for row in connection.execute(f'SELECT {quoted} FROM "{table}"'):
                yield from (value for value in row if isinstance(value, str))
    finally:
        connection.close()


def _artifact_member(uri: str) -> str:
    """Map safe logical URI sang canonical ZIP member path."""
    if not uri.startswith("artifact://jobs/") or "\\" in uri:
        raise PackageError("artifact URI không hợp lệ")
    raw = uri.removeprefix("artifact://")
    parts = raw.split("/")
    if len(parts) < 3 or any(not part or part in {".", ".."} for part in parts):
        raise PackageError("artifact URI chứa path không an toàn")
    if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part) is None for part in parts[1:]):
        raise PackageError("artifact URI chứa segment không hỗ trợ")
    return f"data/studio_local/artifacts/{raw}"


def _find_artifact_uris(text: str) -> set[str]:
    """Tìm logical URI trong JSON/text và validate từng URI bắt đầu bằng prefix."""
    return {match.group(0) for match in _ARTIFACT_URI.finditer(text)}


def _safe_credential_value(value: object) -> bool:
    """Cho phép giá trị rỗng/redacted trong metadata mà không coi là secret."""
    if value is None or value is False:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _CREDENTIAL_VALUE_OK
    return False


def _reject_credential_fields(value: object, context: str) -> None:
    """Từ chối credential nằm trong metadata thay vì âm thầm sửa artifact."""
    if isinstance(value, dict):
        for key, child in value.items():
            if _CREDENTIAL_KEY.search(str(key)) and not _safe_credential_value(child):
                raise PackageError(f"Metadata chứa credential trong {context}")
            _reject_credential_fields(child, context)
    elif isinstance(value, list):
        for child in value:
            _reject_credential_fields(child, context)


_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?:[\"']?)(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"session[_-]?token|token|authorization|bearer|private[_-]?key|client[_-]?secret|token[_-]?hash|code[_-]?hash)"
    r"(?:[\"']?\s*[:=]\s*[\"']?)([^\s,\"'\]}]+)"
)


def _reject_text_credentials(text: str, context: str, suffix: str) -> None:
    """Scan JSON recursively and text logs for credential assignments."""
    if suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            _reject_credential_fields(parsed, context)
            return
    for match in _CREDENTIAL_ASSIGNMENT.finditer(text):
        if not _safe_credential_value(match.group(2)):
            raise PackageError(f"Metadata chứa credential trong {context}")


def _scan_text_credentials(entries: Iterable[tuple[str, Path]]) -> None:
    """Reject secrets in package text payloads before archive creation."""
    for name, path in entries:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as error:
            raise PackageError(f"Không đọc được metadata text ({path.name})") from error
        _reject_text_credentials(text, name, path.suffix)


def _record_artifact_json(
    value: object,
    references: set[str],
    checksums: dict[str, set[str]],
    *,
    skip_self_checksum: bool = False,
) -> None:
    """Collect byte-checksum refs; root contract checksum may be canonical content."""
    if isinstance(value, dict):
        uri_fields = {
            str(key): child
            for key, child in value.items()
            if isinstance(child, str) and child.startswith("artifact://jobs/")
        }
        for key, child in uri_fields.items():
            _artifact_member(child)
            references.update(_find_artifact_uris(child))
            candidate_keys = {"checksum", "artifact_checksum"}
            if key.endswith("_uri"):
                candidate_keys.add(f"{key[:-4]}_checksum")
            for candidate in candidate_keys:
                if skip_self_checksum and key == "artifact_uri" and candidate == "artifact_checksum":
                    continue
                expected = value.get(candidate)
                if isinstance(expected, str):
                    checksums.setdefault(child, set()).add(expected)
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                _record_artifact_json(child, references, checksums)
            elif isinstance(child, str):
                references.update(_find_artifact_uris(child))
    elif isinstance(value, list):
        for child in value:
            _record_artifact_json(child, references, checksums)
    elif isinstance(value, str):
        references.update(_find_artifact_uris(value))


def _record_artifact_text(text: str, suffix: str, references: set[str], checksums: dict[str, set[str]]) -> None:
    """Collect URI/checksum pairs from JSON and URI-bearing text."""
    if suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            _record_artifact_json(parsed, references, checksums, skip_self_checksum=True)
            return
    references.update(_find_artifact_uris(text))


def _collect_artifact_refs_and_checksums(
    database: Path, artifact_files: Iterable[Path], root: Path
) -> tuple[set[str], dict[str, set[str]]]:
    """Thu thập refs và checksum cặp từ DB/text, không đọc binary lớn vào RAM."""
    references: set[str] = set()
    checksums: dict[str, set[str]] = {}
    for value in _iter_database_strings(database):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            _record_artifact_json(parsed, references, checksums)
        else:
            references.update(_find_artifact_uris(value))
    for path in artifact_files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as error:
            raise PackageError(f"Không đọc được artifact text ({path.name})") from error
        _record_artifact_text(text, path.suffix, references, checksums)
    # root is intentionally part of the signature: callers cannot accidentally
    # pass a path from another checkout while mapping the refs below.
    del root
    return references, checksums


def _collect_artifact_refs(database: Path, artifact_files: Iterable[Path], root: Path) -> set[str]:
    """Tương thích helper cũ: chỉ trả về URI refs."""
    return _collect_artifact_refs_and_checksums(database, artifact_files, root)[0]


def _validate_artifact_checksums(
    root: Path, references: Iterable[str], expected: dict[str, set[str]], members: set[str]
) -> None:
    """Verify every URI/checksum pair against the published artifact bytes."""
    reference_set = set(references)
    for uri, checksums in expected.items():
        if uri not in reference_set:
            raise PackageError("Checksum metadata trỏ tới URI không được ghi nhận")
        if not checksums:
            continue
        member = _artifact_member(uri)
        if member not in members:
            raise PackageError("Checksum metadata trỏ tới artifact không tồn tại")
        actual = "sha256:" + _sha256_file(root / Path(member))
        if any(
            not isinstance(value, str) or not value.startswith("sha256:") or _SHA256.fullmatch(value[7:]) is None
            for value in checksums
        ):
            raise PackageError("Artifact checksum không hợp lệ")
        if any(value != actual for value in checksums):
            raise PackageError("Artifact checksum không khớp bytes published")


def _source_file_list(root: Path) -> list[tuple[str, Path]]:
    """Liệt kê canonical payload files, reject symlink/special/hidden entries."""
    entries: list[tuple[str, Path]] = []
    for relative in (*REQUIRED_PATHS, *OPTIONAL_PATHS):
        source = root / relative
        if not source.exists():
            if relative in REQUIRED_PATHS:
                raise PackageError(f"Thiếu dữ liệu bắt buộc: {relative.as_posix()}")
            continue
        if source.is_symlink():
            raise PackageError(f"Không nhận symlink trong data package: {relative.as_posix()}")
        if source.is_file():
            entries.append((relative.as_posix(), source))
            continue
        if not source.is_dir():
            raise PackageError(f"Dữ liệu không phải file/thư mục: {relative.as_posix()}")
        for child in sorted(source.rglob("*")):
            child_relative = child.relative_to(root)
            if any(part.startswith(".") for part in child_relative.parts):
                raise PackageError(f"Không nhận file ẩn trong data package: {child_relative.as_posix()}")
            if child.is_symlink():
                raise PackageError(f"Không nhận symlink trong data package: {child_relative.as_posix()}")
            if child.is_file():
                entries.append((child_relative.as_posix(), child))
            elif not child.is_dir():
                raise PackageError(f"Không nhận special file trong data package: {child_relative.as_posix()}")
    names = [name for name, _ in entries]
    if len(names) != len(set(names)):
        raise PackageError("Canonical data paths bị trùng")
    return sorted(entries)


def _file_stat(path: Path) -> _FileStat:
    """Lấy lstat metadata mà không follow symlink."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise PackageError(f"Source file không còn là regular file: {path.name}")
    return _FileStat(info.st_ino, info.st_size, info.st_mtime_ns, stat.S_IMODE(info.st_mode))


def _source_stats(entries: Iterable[tuple[str, Path]]) -> dict[str, _FileStat]:
    """Snapshot metadata của payload, bỏ qua metadata vật lý của SQLite DB.

    SQLite có thể thay đổi mtime/size khi checkpoint WAL hoặc worker lease được
    cập nhật. Nội dung product của DB được kiểm tra riêng bằng fingerprint logic;
    các file payload khác vẫn dùng metadata để bắt thay đổi trong lúc stream.
    """
    return {name: _file_stat(path) for name, path in entries if name != RUNTIME_DB_MEMBER}


def _database_identity(database: Path) -> tuple[int, int]:
    """Return device/inode identity while rejecting missing or symlinked DB."""
    try:
        info = database.lstat()
    except OSError as error:
        raise PackageError("runtime.db biến mất trong lúc đóng gói") from error
    if not stat.S_ISREG(info.st_mode):
        raise PackageError("runtime.db không còn là regular file")
    return info.st_dev, info.st_ino


def _append_sensitive_values(value: object, values: set[bytes], key: str | None = None) -> None:
    """Collect raw credential-like values for the post-scrub negative check."""
    if key is not None and _CREDENTIAL_KEY.search(key) and not _safe_credential_value(value):
        if isinstance(value, bytes) and len(value) >= 4:
            values.add(value)
        elif isinstance(value, str) and value:
            values.add(value.encode("utf-8"))
    if isinstance(value, dict):
        for child_key, child in value.items():
            _append_sensitive_values(child, values, str(child_key))
    elif isinstance(value, list):
        for child in value:
            _append_sensitive_values(child, values)


def _database_sensitive_values(connection: sqlite3.Connection) -> set[bytes]:
    """Read only credential-like values that must disappear from the snapshot."""
    values: set[bytes] = set()
    for table in sorted(_table_names(connection)):
        columns = _table_columns(connection, table)
        if not columns:
            continue
        for row in connection.execute(f'SELECT * FROM "{table}"'):
            for index, column in enumerate(columns):
                value = row[index]
                if _CREDENTIAL_KEY.search(column):
                    _append_sensitive_values(value, values, column)
                if column == "payload" and isinstance(value, str):
                    try:
                        _append_sensitive_values(json.loads(value), values)
                    except json.JSONDecodeError:
                        continue
    return values


def _normalize_keep_user_ids(user_ids: Iterable[str] | None) -> frozenset[str]:
    """Normalize the explicit two-account preservation allow-list."""
    values = tuple(str(value).strip() for value in (user_ids or ()))
    if any(not value for value in values):
        raise PackageError("keep-user-id không được rỗng")
    if len(values) not in {0, 2} or len(set(values)) != len(values):
        raise PackageError("Chỉ được giữ đúng hai seed user bằng --keep-user-id")
    return frozenset(values)


def _is_password_hash(value: object) -> bool:
    """Recognize the repository's stdlib scrypt hash format, never plaintext."""
    return isinstance(value, str) and _PASSWORD_HASH.fullmatch(value) is not None


def _validate_keep_user_ids(connection: sqlite3.Connection, user_ids: frozenset[str]) -> None:
    """Ensure selected accounts exist and contain reusable password hashes."""
    if not user_ids:
        return
    tables = _table_names(connection)
    if "r2s_users" not in tables:
        raise PackageError("Không thể giữ seed account khi database thiếu r2s_users")
    columns = _table_columns(connection, "r2s_users")
    if not {"user_id", "payload"}.issubset(columns):
        raise PackageError("r2s_users thiếu user_id/payload cho seed account")
    user_index = columns.index("user_id")
    payload_index = columns.index("payload")
    records: dict[str, dict[str, Any]] = {}
    for row in connection.execute('SELECT * FROM "r2s_users"'):
        user_id = str(row[user_index])
        if user_id in user_ids:
            records[user_id] = _json_object(row[payload_index], f"r2s_users/{user_id}")
    missing = sorted(user_ids - records.keys())
    if missing:
        raise PackageError("Không tìm thấy đủ seed account được chọn")
    for user_id, record in records.items():
        password_hash = record.get("password_hash")
        if not _is_password_hash(password_hash):
            raise PackageError(f"Seed account {user_id} không có password hash hợp lệ")
        if not isinstance(record.get("active"), bool):
            raise PackageError(f"Seed account {user_id} thiếu active state boolean")


def _resolve_keep_user_ids(
    database: Path, user_ids: Iterable[str] | None, keep_seed_accounts: bool
) -> tuple[frozenset[str], str]:
    """Resolve explicit IDs or the guarded exactly-two seed convenience mode."""
    explicit = tuple(user_ids or ())
    if explicit and keep_seed_accounts:
        raise PackageError("Chỉ chọn một trong --keep-user-id và --keep-seed-accounts")
    connection = _sqlite_readonly(database)
    try:
        if keep_seed_accounts:
            tables = _table_names(connection)
            if "r2s_users" not in tables:
                raise PackageError("Không thể giữ seed account khi database thiếu r2s_users")
            columns = _table_columns(connection, "r2s_users")
            user_index = columns.index("user_id")
            selected = frozenset(str(row[user_index]) for row in connection.execute('SELECT * FROM "r2s_users"'))
            if len(selected) != 2:
                raise PackageError("--keep-seed-accounts yêu cầu đúng hai user trong source")
            _validate_keep_user_ids(connection, selected)
            return selected, ACCOUNT_MODE_SEED
        selected = _normalize_keep_user_ids(explicit)
        _validate_keep_user_ids(connection, selected)
        return selected, ACCOUNT_MODE_SELECTED if selected else ACCOUNT_MODE_SCRUB
    finally:
        connection.close()


def _account_policy(manifest: dict[str, Any]) -> tuple[str, frozenset[str]]:
    """Parse account policy, accepting older all-scrub manifests."""
    raw = manifest.get("account_policy")
    if raw is None:
        return ACCOUNT_MODE_SCRUB, frozenset()
    if not isinstance(raw, dict):
        raise PackageError("Manifest account_policy không hợp lệ")
    mode = raw.get("mode")
    raw_ids = raw.get("kept_user_ids", [])
    if mode not in {ACCOUNT_MODE_SCRUB, ACCOUNT_MODE_SELECTED, ACCOUNT_MODE_SEED}:
        raise PackageError("Manifest account_policy mode không hỗ trợ")
    if not isinstance(raw_ids, list) or any(not isinstance(value, str) or not value for value in raw_ids):
        raise PackageError("Manifest account_policy user IDs không hợp lệ")
    selected = frozenset(raw_ids)
    if len(selected) != len(raw_ids):
        raise PackageError("Manifest account_policy user IDs bị trùng")
    if mode == ACCOUNT_MODE_SCRUB and selected:
        raise PackageError("Manifest scrub-all không được giữ user ID")
    if mode in {ACCOUNT_MODE_SELECTED, ACCOUNT_MODE_SEED} and len(selected) != 2:
        raise PackageError("Manifest account_policy phải giữ đúng hai user")
    return mode, selected


def _fingerprint_value(value: object) -> object:
    """Convert SQLite scalar to deterministic JSON-safe representation."""
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _fingerprint_json(value: object, table: str, preserve_credentials: bool = False) -> object:
    """Normalize payload while excluding only fields changed by sanitization."""
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, child in value.items():
            if table == "r2s_users" and not preserve_credentials and key in {"password_hash", "active"}:
                continue
            normalized[str(key)] = _fingerprint_json(child, table, preserve_credentials)
        return normalized
    if isinstance(value, list):
        return [_fingerprint_json(child, table, preserve_credentials) for child in value]
    return _fingerprint_value(value)


def _database_fingerprint(database: Path, keep_user_ids: frozenset[str] = frozenset()) -> str:
    """Fingerprint committed product rows, including edits held in SQLite WAL."""
    connection = _sqlite_readonly(database)
    try:
        rows: list[str] = []
        for table in sorted(_table_names(connection)):
            if table in SANITIZE_TABLES:
                continue
            columns = _table_columns(connection, table)
            if not columns:
                continue
            user_index = columns.index("user_id") if table == "r2s_users" and "user_id" in columns else None
            normalized_rows: list[object] = []
            for row in connection.execute(f'SELECT * FROM "{table}"'):
                preserve_credentials = (
                    table == "r2s_users" and user_index is not None and str(row[user_index]) in keep_user_ids
                )
                values: list[object] = []
                for index, column in enumerate(columns):
                    value = row[index]
                    if table == "r2s_users" and not preserve_credentials and column in {"password_hash", "active"}:
                        continue
                    if column == "payload" and isinstance(value, str):
                        try:
                            values.append(_fingerprint_json(json.loads(value), table, preserve_credentials))
                        except json.JSONDecodeError:
                            values.append(value)
                    else:
                        values.append(_fingerprint_value(value))
                normalized_rows.append(values)
            rows.append(
                json.dumps(
                    {"table": table, "columns": columns, "rows": sorted(normalized_rows, key=repr)}, sort_keys=True
                )
            )
        digest = hashlib.sha256()
        for row in rows:
            digest.update(row.encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()
    finally:
        connection.close()


def _sha256_file(path: Path) -> str:
    """Hash file theo chunk, không nạp artifact vào RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lock_hashes(root: Path) -> dict[str, str | None]:
    """Hash lockfiles nếu checkout có; path không chứa secret."""
    return {
        relative.as_posix(): _sha256_file(root / relative) if (root / relative).is_file() else None
        for relative in LOCKFILES
    }


def _git_metadata(root: Path) -> tuple[str | None, bool | None]:
    """Đọc commit/dirty flag mà không làm thay đổi git checkout."""
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    if commit.returncode != 0:
        return None, None
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return commit.stdout.strip() or None, bool(status.stdout.strip()) if status.returncode == 0 else None


def _job_manifest_path(root: Path, manifest_ref: str) -> Path | None:
    """Resolve DB JobManifest ref for the active-work gate."""
    try:
        reference = _json_object(manifest_ref, "r2s_jobs.manifest_ref")
        uri = reference.get("artifact_uri")
        if not isinstance(uri, str):
            return None
        member = _artifact_member(uri)
    except PackageError:
        return None
    return root / Path(member)


def _human_metric_waiting(root: Path, event: dict[str, Any], manifest_ref: str | None) -> bool:
    """Allow the intentional RUNNING state awaiting user metric confirmation."""
    if event.get("status") != "RUNNING" or event.get("current_stage") != METRIC_STAGE:
        return False
    if not manifest_ref:
        return False
    path = _job_manifest_path(root, manifest_ref)
    if path is None or not path.is_file():
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    stages = manifest.get("stage_artifacts", [])
    return isinstance(stages, list) and not any(
        isinstance(stage, dict) and stage.get("stage_id") == METRIC_STAGE for stage in stages
    )


def _reject_nonempty_trash(connection: sqlite3.Connection, operation: str) -> None:
    """Fail closed when product trash still contains recoverable records."""
    if TRASH_TABLE not in _table_names(connection):
        return
    count = int(connection.execute(f'SELECT COUNT(*) FROM "{TRASH_TABLE}"').fetchone()[0])
    if count:
        raise PackageError(
            f"Không thể {operation} khi {TRASH_TABLE} còn {count} record; "
            "hãy restore các item đã trash hoặc chờ transaction kết thúc rồi chạy lại "
            "(tool không tự purge)"
        )


def _active_work_gate(root: Path, database: Path) -> dict[str, int]:
    """Reject mutable work; return count of the explicit metric-wait exception."""
    connection = _sqlite_readonly(database)
    waiting_metric = 0
    try:
        tables = _table_names(connection)
        _reject_nonempty_trash(connection, "đóng gói")
        if "r2s_scene_publications" in tables:
            count = int(connection.execute("SELECT COUNT(*) FROM r2s_scene_publications").fetchone()[0])
            if count:
                raise PackageError("Không thể đóng gói khi còn scene publication đang chờ commit hoặc cần phục hồi")
        if "r2s_resource_reservations" in tables:
            count = int(connection.execute("SELECT COUNT(*) FROM r2s_resource_reservations").fetchone()[0])
            if count:
                raise PackageError("Không thể đóng gói khi worker đang giữ resource reservation")
        if "r2s_resource_waits" in tables:
            count = int(connection.execute("SELECT COUNT(*) FROM r2s_resource_waits").fetchone()[0])
            if count:
                raise PackageError("Không thể đóng gói khi job đang chờ resource")
        if "r2s_imports" in tables:
            columns = _table_columns(connection, "r2s_imports")
            if "payload" in columns:
                payload_index = columns.index("payload")
                active = 0
                for row in connection.execute('SELECT * FROM "r2s_imports"'):
                    payload = _json_object(row[payload_index], "r2s_imports.payload")
                    if str(payload.get("status", "")).upper() in ACTIVE_IMPORT_STATUSES:
                        active += 1
                if active:
                    raise PackageError(f"Không thể đóng gói khi có {active} import đang chạy")
        if "r2s_upload_sessions" in tables:
            columns = _table_columns(connection, "r2s_upload_sessions")
            if "payload" in columns:
                payload_index = columns.index("payload")
                active = 0
                for row in connection.execute('SELECT * FROM "r2s_upload_sessions"'):
                    payload = _json_object(row[payload_index], "r2s_upload_sessions.payload")
                    if str(payload.get("status", "")).upper() in ACTIVE_UPLOAD_STATUSES:
                        active += 1
                if active:
                    raise PackageError(f"Không thể đóng gói khi có {active} upload session đang chạy")
        if "r2s_scene_requests" in tables:
            columns = _table_columns(connection, "r2s_scene_requests")
            if "status" in columns:
                status_index = columns.index("status")
                active = sum(
                    str(row[status_index]).upper() in ACTIVE_REQUEST_STATUSES
                    for row in connection.execute('SELECT * FROM "r2s_scene_requests"')
                )
                if active:
                    raise PackageError(f"Không thể đóng gói khi có {active} objectify request đang chạy")
        if "r2s_validation_runs" in tables:
            terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
            active_runs = [
                (str(run_id), str(status))
                for run_id, status in connection.execute("SELECT run_id, status FROM r2s_validation_runs")
                if str(status).upper() not in terminal_statuses
            ]
            if active_runs:
                raise PackageError(f"Không thể đóng gói khi có {len(active_runs)} validation run chưa kết thúc hợp lệ")
        if "r2s_jobs" not in tables or "r2s_job_events" not in tables:
            return {"human_metric_waiting_jobs": 0}
        job_columns = _table_columns(connection, "r2s_jobs")
        job_index = {column: job_columns.index(column) for column in ("job_id", "manifest_ref")}
        refs = {
            str(row[job_index["job_id"]]): str(row[job_index["manifest_ref"]])
            for row in connection.execute('SELECT * FROM "r2s_jobs"')
        }
        event_columns = _table_columns(connection, "r2s_job_events")
        event_index = {column: event_columns.index(column) for column in ("job_id", "version", "payload")}
        latest: dict[str, tuple[int, dict[str, Any]]] = {}
        for row in connection.execute('SELECT * FROM "r2s_job_events"'):
            job_id = str(row[event_index["job_id"]])
            version = int(row[event_index["version"]])
            if job_id not in latest or version > latest[job_id][0]:
                latest[job_id] = (version, _json_object(row[event_index["payload"]], "r2s_job_events.payload"))
        active = 0
        for job_id, (_, event) in latest.items():
            status = str(event.get("status", "")).upper()
            if status not in ACTIVE_JOB_STATUSES:
                continue
            if status == "RUNNING" and _human_metric_waiting(root, event, refs.get(job_id)):
                waiting_metric += 1
                continue
            active += 1
        if active:
            raise PackageError(f"Không thể đóng gói khi có {active} job đang chạy hoặc đang xếp hàng")
        return {"human_metric_waiting_jobs": waiting_metric}
    finally:
        connection.close()


def _snapshot_database_details(
    source: Path, target: Path, keep_user_ids: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """SQLite backup nhất quán rồi scrub credential/session trong bản copy."""
    origin = _sqlite_readonly(source)
    copy = sqlite3.connect(target)
    sensitive_values: set[bytes] = set()
    allowed_password_values: set[bytes] = set()
    try:
        _validate_keep_user_ids(origin, keep_user_ids)
        sensitive_values = _database_sensitive_values(origin)
        if keep_user_ids and "r2s_users" in _table_names(origin):
            columns = _table_columns(origin, "r2s_users")
            user_index = columns.index("user_id")
            payload_index = columns.index("payload")
            password_index = columns.index("password_hash") if "password_hash" in columns else None
            for row in origin.execute('SELECT * FROM "r2s_users"'):
                if str(row[user_index]) not in keep_user_ids:
                    continue
                record = _json_object(row[payload_index], "r2s_users.payload")
                allowed_password_values.add(str(record["password_hash"]).encode("utf-8"))
                if password_index is not None and row[password_index] is not None:
                    allowed_password_values.add(str(row[password_index]).encode("utf-8"))
        origin.backup(copy)
        tables = _table_names(copy)
        copy.execute("PRAGMA secure_delete=ON")
        with copy:
            for table in SANITIZE_TABLES:
                if table in tables:
                    copy.execute(f'DELETE FROM "{table}"')
            if "r2s_users" in tables:
                columns = _table_columns(copy, "r2s_users")
                required = {"user_id", "email", "payload"}
                if not required.issubset(columns):
                    raise PackageError("r2s_users thiếu cột cần scrub")
                for user_id, email, payload in copy.execute(
                    'SELECT user_id, email, payload FROM "r2s_users"'
                ).fetchall():
                    if str(user_id) in keep_user_ids:
                        continue
                    record = _json_object(payload, "r2s_users.payload")
                    record.update(password_hash=PASSWORD_SENTINEL, active=False)
                    assignments = ["payload=?"]
                    parameters: list[object] = [json.dumps(record, ensure_ascii=False, separators=(",", ":"))]
                    if "password_hash" in columns:
                        assignments.append('"password_hash"=?')
                        parameters.append(PASSWORD_SENTINEL)
                    if "active" in columns:
                        assignments.append('"active"=?')
                        parameters.append(False)
                    parameters.append(user_id)
                    copy.execute(
                        f'UPDATE "r2s_users" SET {", ".join(assignments)} WHERE user_id=?',
                        parameters,
                    )
        # secure_delete clears deleted pages; VACUUM compacts the temporary DB
        # so deleted session/token pages cannot remain in freelist bytes.
        copy.execute("VACUUM")
        integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise PackageError("Database snapshot không qua integrity_check")
        project_count = (
            int(copy.execute("SELECT COUNT(*) FROM r2s_projects").fetchone()[0]) if "r2s_projects" in tables else 0
        )
        row_counts = {
            table: int(copy.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in sorted(tables)
            if table.startswith("r2s_")
        }
        result = {
            "project_count": project_count,
            "row_counts": row_counts,
            "sanitized_tables": list(SANITIZE_TABLES),
            "kept_user_ids": sorted(keep_user_ids),
        }
    except sqlite3.Error as error:
        raise PackageError("Không thể tạo database snapshot") from error
    finally:
        origin.close()
        copy.close()
    try:
        raw_snapshot = target.read_bytes()
    except OSError as error:
        raise PackageError("Không đọc được database snapshot để kiểm tra scrub") from error
    if any(
        secret not in allowed_password_values and secret != PASSWORD_SENTINEL.encode() and secret in raw_snapshot
        for secret in sensitive_values
    ):
        raise PackageError("Database snapshot còn bytes credential/session sau khi scrub")
    return result


def snapshot_database(source: Path, target: Path, keep_user_ids: Iterable[str] | None = None) -> int:
    """Tương thích helper cũ: tạo snapshot đã scrub và trả số project."""
    selected = _normalize_keep_user_ids(keep_user_ids)
    return int(_snapshot_database_details(source, target, selected)["project_count"])


def _canonical_member(name: str) -> PurePosixPath:
    """Validate archive member path trước khi dùng với filesystem."""
    if not name or "\\" in name or name.startswith("/"):
        raise PackageError("Archive member path không an toàn")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise PackageError("Archive member path chứa traversal")
    if name != path.as_posix():
        raise PackageError("Archive member path không canonical")
    return path


def _allowed_payload_member(name: str) -> bool:
    """Chỉ cho phép canonical data roots trong package."""
    return name in PAYLOAD_EXACT or any(name.startswith(prefix) for prefix in PAYLOAD_PREFIXES)


def _validate_source_consistency(root: Path, before: dict[str, _FileStat], database_identity: tuple[int, int]) -> None:
    """Phát hiện payload đổi và SQLite DB bị thay bằng file khác trong lúc stream."""
    database = root / STATE / "runtime.db"
    if _database_identity(database) != database_identity:
        raise PackageError("runtime.db bị thay thế trong lúc đóng gói; chạy lại khi stack đã dừng")
    after_entries = _source_file_list(root)
    after = _source_stats(after_entries)
    if set(before) != set(after):
        raise PackageError("Source data thay đổi trong lúc đóng gói; chạy lại khi stack đã dừng")
    changed = [name for name in before if before[name] != after[name]]
    if changed:
        raise PackageError("Source data thay đổi trong lúc đóng gói; chạy lại khi stack đã dừng")


def _write_stream(zf: zipfile.ZipFile, source: Path, member: str) -> FileRecord:
    """Stream một file vào ZIP và hash đúng bytes đã ghi."""
    _canonical_member(member)
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as stream, zf.open(member, "w", force_zip64=True) as target:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except OSError as error:
        raise PackageError(f"Không stream được dữ liệu ({source.name})") from error
    return FileRecord(member, size, digest.hexdigest())


def _package_output(path: Path) -> Path:
    """Chuẩn hóa output và từ chối overwrite/symlink."""
    output = path.expanduser()
    if not output.is_absolute():
        output = Path.cwd() / output
    output = output.resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise PackageError(f"Output đã tồn tại, không overwrite: {output}")
    partial = Path(str(output) + ".partial")
    if partial.exists() or partial.is_symlink():
        raise PackageError(f"Output tạm đã tồn tại, không overwrite: {partial}")
    return output


def _output_inside_source(root: Path, output: Path) -> bool:
    """Output không được nằm trong managed data tree đang được stream."""
    for relative in (*REQUIRED_PATHS, *OPTIONAL_PATHS):
        managed = (root / relative).resolve(strict=False)
        try:
            output.relative_to(managed)
        except ValueError:
            continue
        return True
    return False


def pack(
    root: Path,
    out: Path,
    keep_user_ids: Iterable[str] | None = None,
    keep_seed_accounts: bool = False,
    compression: str = "deflated",
) -> Path:
    """Tạo ZIP portable từ state canonical, giữ source nguyên vẹn."""
    checkout = _root_path(root)
    output = _package_output(Path(out))
    compression = compression.strip().lower()
    if compression not in COMPRESSION_METHODS:
        raise PackageError(f"Compression không hỗ trợ: {compression}")
    if _output_inside_source(checkout, output):
        raise PackageError("Output phải nằm ngoài các thư mục data được đóng gói")
    database = checkout / STATE / "runtime.db"
    database_identity = _database_identity(database)
    selected_user_ids, account_mode = _resolve_keep_user_ids(database, keep_user_ids, keep_seed_accounts)
    _active_work_gate(checkout, database)
    entries = _source_file_list(checkout)
    _scan_text_credentials(entries)
    before = _source_stats(entries)
    database_fingerprint = _database_fingerprint(database, selected_user_ids)
    artifact_entries = [path for name, path in entries if name.startswith("data/studio_local/artifacts/")]
    refs, artifact_checksums = _collect_artifact_refs_and_checksums(database, artifact_entries, checkout)
    artifact_members = {name for name, _ in entries if name.startswith("data/studio_local/artifacts/")}
    missing = sorted(_artifact_member(uri) for uri in refs if _artifact_member(uri) not in artifact_members)
    if missing:
        raise PackageError(f"Artifact reference thiếu file published ({len(missing)} refs)")
    _validate_artifact_checksums(checkout, refs, artifact_checksums, artifact_members)
    commit, dirty = _git_metadata(checkout)
    lock_hashes = _lock_hashes(checkout)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(output) + ".partial")
    database_info: dict[str, Any]
    records: list[FileRecord] = []
    try:
        with tempfile.TemporaryDirectory(prefix="r2s-data-package-") as staging:
            snapshot = Path(staging) / "runtime.db"
            database_info = _snapshot_database_details(database, snapshot, selected_user_ids)
            snapshot_record_name = (STATE / "runtime.db").as_posix()
            with zipfile.ZipFile(
                partial,
                "w",
                compression=COMPRESSION_METHODS[compression],
                **({"compresslevel": 1} if compression == "deflated" else {}),
                allowZip64=True,
            ) as archive:
                records.append(_write_stream(archive, snapshot, snapshot_record_name))
                for name, source in entries:
                    if name == snapshot_record_name:
                        continue
                    records.append(_write_stream(archive, source, name))
                _validate_source_consistency(checkout, before, database_identity)
                if _database_fingerprint(database, selected_user_ids) != database_fingerprint:
                    raise PackageError("SQLite product state thay đổi trong lúc đóng gói; chạy lại khi stack đã dừng")
                manifest = {
                    "package_format": PACKAGE_VERSION,
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "git_commit": commit,
                    "git_dirty": dirty,
                    "lockfiles": lock_hashes,
                    "contents": [record.path for record in records],
                    "files": [record.as_dict() for record in sorted(records, key=lambda item: item.path)],
                    "file_count": len(records),
                    "total_bytes": sum(record.size for record in records),
                    "database": database_info,
                    "database_source_fingerprint": database_fingerprint,
                    "account_policy": {"mode": account_mode, "kept_user_ids": sorted(selected_user_ids)},
                    "compression": compression,
                    "artifact_reference_count": len(refs),
                    "active_work_gate": _active_work_gate(checkout, database),
                }
                payload = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
                archive.writestr(MANIFEST_NAME, payload)
        partial.replace(output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    print(f"[data] {len(records)} files, {sum(record.size for record in records)} bytes → {output}")
    return output


def _manifest_from_archive(archive: zipfile.ZipFile) -> tuple[dict[str, Any], list[zipfile.ZipInfo]]:
    """Validate names/duplicates and đọc manifest trước mọi extraction."""
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise PackageError("Archive chứa member trùng tên")
    if MANIFEST_NAME not in names:
        raise PackageError("Archive thiếu DATA_PACKAGE.json")
    for info in infos:
        if info.is_dir():
            raise PackageError("Archive không được chứa directory entry")
        _canonical_member(info.filename)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise PackageError("Archive chứa symlink")
    try:
        raw = archive.read(MANIFEST_NAME)
        manifest = json.loads(raw.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackageError("DATA_PACKAGE.json không hợp lệ") from error
    if not isinstance(manifest, dict) or manifest.get("package_format") != PACKAGE_VERSION:
        raise PackageError("Không hỗ trợ package format này")
    compression = manifest.get("compression", "deflated")
    if compression not in COMPRESSION_METHODS:
        raise PackageError("Manifest compression không hợp lệ")
    expected_compression = COMPRESSION_METHODS[compression]
    if any(info.compress_type != expected_compression for info in infos):
        raise PackageError("Archive compression không khớp manifest")
    return manifest, infos


def _manifest_records(manifest: dict[str, Any], infos: list[zipfile.ZipInfo]) -> tuple[FileRecord, ...]:
    """Validate manifest/file inventory đúng một lần trước khi hash payload."""
    raw_records = manifest.get("files")
    if not isinstance(raw_records, list):
        raise PackageError("Manifest thiếu files inventory")
    records: list[FileRecord] = []
    for raw in raw_records:
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise PackageError("Manifest có file record không hợp lệ")
        path = raw["path"]
        _canonical_member(path)
        if path == MANIFEST_NAME or not _allowed_payload_member(path):
            raise PackageError("Manifest chứa member ngoài data package")
        size = raw.get("size")
        digest = raw.get("sha256")
        if not isinstance(size, int) or size < 0 or not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise PackageError("Manifest có size/checksum không hợp lệ")
        records.append(FileRecord(path, size, digest))
    if len({record.path for record in records}) != len(records):
        raise PackageError("Manifest chứa path trùng")
    actual = {info.filename for info in infos if info.filename != MANIFEST_NAME}
    expected = {record.path for record in records}
    if actual != expected:
        raise PackageError("Archive members không khớp manifest inventory")
    if manifest.get("file_count") != len(records) or manifest.get("total_bytes") != sum(
        record.size for record in records
    ):
        raise PackageError("Manifest totals không khớp inventory")
    contents = manifest.get("contents")
    if not isinstance(contents, list) or set(contents) != expected or len(contents) != len(records):
        raise PackageError("Manifest contents không khớp inventory")
    source_fingerprint = manifest.get("database_source_fingerprint")
    if not isinstance(source_fingerprint, str) or _SHA256.fullmatch(source_fingerprint) is None:
        raise PackageError("Manifest thiếu database source fingerprint")
    _account_policy(manifest)
    return tuple(sorted(records, key=lambda item: item.path))


def _hash_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, expected: FileRecord) -> None:
    """Hash member stream và không ghi nó ra filesystem."""
    if info.file_size != expected.size:
        raise PackageError(f"Archive size không khớp: {expected.path}")
    digest = hashlib.sha256()
    size = 0
    try:
        with archive.open(info, "r") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise PackageError("Không đọc được archive member") from error
    if size != expected.size or digest.hexdigest() != expected.sha256:
        raise PackageError(f"Checksum không khớp: {expected.path}")


def _validate_archive_artifact_checksums(
    references: Iterable[str], expected: dict[str, set[str]], records: dict[str, FileRecord]
) -> None:
    """Verify URI/checksum pairs against checksums recorded in package inventory."""
    reference_set = set(references)
    for uri, checksums in expected.items():
        if uri not in reference_set:
            raise PackageError("Checksum metadata trỏ tới URI không được ghi nhận")
        member = _artifact_member(uri)
        record = records.get(member)
        if record is None:
            raise PackageError("Checksum metadata trỏ tới artifact không tồn tại")
        actual = "sha256:" + record.sha256
        if any(
            not isinstance(value, str) or not value.startswith("sha256:") or _SHA256.fullmatch(value[7:]) is None
            for value in checksums
        ):
            raise PackageError("Artifact checksum không hợp lệ")
        if any(value != actual for value in checksums):
            raise PackageError("Artifact checksum không khớp package bytes")


def _read_member_text(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    """Đọc text artifact nhỏ/đã chọn để kiểm tra closure URI."""
    try:
        with archive.open(info, "r") as stream:
            return stream.read().decode("utf-8", errors="ignore")
    except (OSError, zipfile.BadZipFile) as error:
        raise PackageError("Không đọc được text artifact trong archive") from error


def _verify_sanitized_database(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, keep_user_ids: frozenset[str]
) -> tuple[int, set[str], dict[str, set[str]]]:
    """Kiểm integrity, scrubbed credential và lấy DB artifact refs."""
    with tempfile.TemporaryDirectory(prefix="r2s-package-verify-") as staging:
        path = Path(staging) / "runtime.db"
        try:
            with archive.open(info, "r") as source, path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        except (OSError, zipfile.BadZipFile) as error:
            raise PackageError("Không đọc được database snapshot") from error
        connection = sqlite3.connect(path)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PackageError("Database snapshot không qua integrity_check")
            tables = _table_names(connection)
            _reject_nonempty_trash(connection, "verify package")
            for table in SANITIZE_TABLES:
                if table in tables and int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) != 0:
                    raise PackageError(f"Database package còn local state: {table}")
            project_count = (
                int(connection.execute("SELECT COUNT(*) FROM r2s_projects").fetchone()[0])
                if "r2s_projects" in tables
                else 0
            )
            if "r2s_users" in tables:
                user_columns = _table_columns(connection, "r2s_users")
                observed_user_ids: set[str] = set()
                for row in connection.execute('SELECT * FROM "r2s_users"'):
                    user_id = str(row[user_columns.index("user_id")])
                    observed_user_ids.add(user_id)
                    email = row[user_columns.index("email")]
                    payload = row[user_columns.index("payload")]
                    record = _json_object(payload, "package r2s_users.payload")
                    if email != record.get("email"):
                        raise PackageError("Database package lệch email actor metadata")
                    if user_id in keep_user_ids:
                        if not _is_password_hash(record.get("password_hash")):
                            raise PackageError("Database package thiếu password hash seed account")
                        if record["password_hash"] == PASSWORD_SENTINEL:
                            raise PackageError("Database package đã scrub seed account được chọn")
                        if not isinstance(record.get("active"), bool):
                            raise PackageError("Database package thiếu active state seed account")
                        if "password_hash" in user_columns and not row[user_columns.index("password_hash")]:
                            raise PackageError("Database package thiếu password hash column seed account")
                    else:
                        if record.get("password_hash") != PASSWORD_SENTINEL or record.get("active") is not False:
                            raise PackageError("Database package còn credential/active user")
                        if (
                            "password_hash" in user_columns
                            and row[user_columns.index("password_hash")] != PASSWORD_SENTINEL
                        ):
                            raise PackageError("Database package còn password hash user")
                        if "active" in user_columns and row[user_columns.index("active")] not in (0, False):
                            raise PackageError("Database package còn active user")
                if not keep_user_ids.issubset(observed_user_ids):
                    raise PackageError("Database package thiếu seed account được manifest khai báo")
            elif keep_user_ids:
                raise PackageError("Database package thiếu r2s_users cho seed account")
            secrets = _database_sensitive_values(connection)
            allowed: set[bytes] = set()
            if "r2s_users" in tables and keep_user_ids:
                user_columns = _table_columns(connection, "r2s_users")
                user_index = user_columns.index("user_id")
                payload_index = user_columns.index("payload")
                password_index = user_columns.index("password_hash") if "password_hash" in user_columns else None
                for row in connection.execute('SELECT * FROM "r2s_users"'):
                    if str(row[user_index]) not in keep_user_ids:
                        continue
                    record = _json_object(row[payload_index], "package r2s_users.payload")
                    allowed.add(str(record["password_hash"]).encode("utf-8"))
                    if password_index is not None and row[password_index] is not None:
                        allowed.add(str(row[password_index]).encode("utf-8"))
            if any(secret not in allowed and secret != PASSWORD_SENTINEL.encode() for secret in secrets):
                raise PackageError("Database package còn credential metadata")
            references: set[str] = set()
            checksums: dict[str, set[str]] = {}
            for value in _iter_database_strings(path):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = None
                if parsed is not None:
                    _record_artifact_json(parsed, references, checksums)
                else:
                    references.update(_find_artifact_uris(value))
            return project_count, references, checksums
        finally:
            connection.close()


def _verify_package(package: Path) -> _VerifiedPackage:
    """Verify inventory, checksum, scrubbed DB và artifact reference closure."""
    archive_path = package.expanduser().resolve()
    if not archive_path.is_file() or archive_path.is_symlink():
        raise PackageError(f"Không thấy package file: {archive_path}")
    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise PackageError("Package không phải ZIP hợp lệ") from error
    with archive:
        manifest, infos = _manifest_from_archive(archive)
        _, kept_user_ids = _account_policy(manifest)
        records = _manifest_records(manifest, infos)
        by_name = {info.filename: info for info in infos}
        for record in records:
            _hash_member(archive, by_name[record.path], record)
        database_record = next((record for record in records if record.path == "data/studio_local/runtime.db"), None)
        if database_record is None:
            raise PackageError("Manifest thiếu runtime.db")
        project_count, db_refs, db_checksums = _verify_sanitized_database(
            archive, by_name[database_record.path], kept_user_ids
        )
        artifact_refs = set(db_refs)
        artifact_checksums = dict(db_checksums)
        members = {record.path for record in records}
        record_by_path = {record.path: record for record in records}
        for record in records:
            if Path(record.path).suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = _read_member_text(archive, by_name[record.path])
            _reject_text_credentials(text, record.path, Path(record.path).suffix)
            if not record.path.startswith("data/studio_local/artifacts/"):
                continue
            _record_artifact_text(text, Path(record.path).suffix, artifact_refs, artifact_checksums)
        missing = {_artifact_member(uri) for uri in artifact_refs if _artifact_member(uri) not in members}
        if missing:
            raise PackageError(f"Package thiếu {len(missing)} artifact được tham chiếu")
        _validate_archive_artifact_checksums(artifact_refs, artifact_checksums, record_by_path)
        expected_ref_count = manifest.get("artifact_reference_count")
        if not isinstance(expected_ref_count, int) or expected_ref_count != len(artifact_refs):
            raise PackageError("Manifest artifact reference count không khớp")
        summary = PackageSummary(
            archive_path, len(records), sum(record.size for record in records), project_count, len(artifact_refs)
        )
        return _VerifiedPackage(summary, manifest, records)


def verify(
    package: Path,
    expected_user_ids: Iterable[str] | None = None,
    expect_seed_accounts: bool = False,
) -> PackageSummary:
    """Verify package mà không ghi filesystem và trả summary an toàn."""
    verified = _verify_package(Path(package))
    mode, kept_user_ids = _account_policy(verified.manifest)
    if expected_user_ids is not None:
        expected = _normalize_keep_user_ids(expected_user_ids)
        if expected != kept_user_ids:
            raise PackageError("Package account policy không khớp keep-user-id được yêu cầu")
    if expect_seed_accounts and mode != ACCOUNT_MODE_SEED:
        raise PackageError("Package không được tạo với keep-seed-accounts")
    return verified.summary


def _ensure_no_symlink_components(root: Path, target: Path) -> None:
    """Không resolve symlink khi restore vào checkout."""
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PackageError("Destination chứa symlink; từ chối restore")


def _managed_targets(root: Path) -> list[Path]:
    """Tất cả file/thư mục có thể bị unpack thay thế."""
    return [
        root / STATE / "runtime.db",
        root / STATE / "artifacts",
        root / STATE / "thumbnail_cache",
        root / STATE / MANIFEST_NAME,
        root / "data/demo/library",
        root / "data/asset_previews",
        root / "data/rerun_recordings",
    ]


def _extract_record(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, record: FileRecord, destination: Path, root: Path
) -> None:
    """Stream một member ra temporary file rồi atomic replace."""
    _ensure_no_symlink_components(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    digest = hashlib.sha256()
    size = 0
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        with os.fdopen(descriptor, "wb") as target, archive.open(info, "r") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            target.flush()
            os.fsync(target.fileno())
        if size != record.size or digest.hexdigest() != record.sha256:
            raise PackageError(f"Checksum thay đổi trong lúc restore: {record.path}")
        os.replace(temporary_name, destination)
        temporary_name = None
    except (OSError, zipfile.BadZipFile) as error:
        raise PackageError(f"Không restore được member: {record.path}") from error
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def unpack(root: Path, package: Path, force: bool = False) -> None:
    """Verify trước, rồi restore với backup/rollback cho mọi managed target."""
    checkout = _root_path(root)
    verified = _verify_package(Path(package))
    targets = _managed_targets(checkout)
    collisions = [target for target in targets if target.exists() or target.is_symlink()]
    if collisions and not force:
        raise PackageError("Destination đã có data; dùng --force để backup rồi thay toàn bộ managed data")
    for target in targets:
        _ensure_no_symlink_components(checkout, target)
    state = checkout / STATE
    if collisions:
        _ensure_no_symlink_components(checkout, state / "backups")
    archive = zipfile.ZipFile(Path(package).expanduser().resolve(), "r")
    backups: list[tuple[Path, Path]] = []
    created_targets: set[Path] = set()
    backup_root: Path | None = None
    try:
        state.mkdir(parents=True, exist_ok=True)
        if collisions:
            backup_root = state / "backups" / f"before-unpack-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
            backup_root.mkdir(parents=True)
            for target in collisions:
                backup_target = backup_root / target.relative_to(checkout)
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup_target))
                backups.append((target, backup_target))
        infos = {info.filename: info for info in archive.infolist()}
        for record in verified.records:
            destination = checkout / Path(record.path)
            if not _allowed_payload_member(record.path):
                raise PackageError("Package member ngoài managed data")
            if record.path == "data/studio_local/runtime.db":
                created_targets.add(checkout / STATE / "runtime.db")
            elif record.path.startswith("data/studio_local/artifacts/"):
                created_targets.add(checkout / STATE / "artifacts")
            elif record.path.startswith("data/studio_local/thumbnail_cache/"):
                created_targets.add(checkout / STATE / "thumbnail_cache")
            elif record.path.startswith("data/demo/library/"):
                created_targets.add(checkout / "data/demo/library")
            elif record.path.startswith("data/asset_previews/"):
                created_targets.add(checkout / "data/asset_previews")
            elif record.path.startswith("data/rerun_recordings/"):
                created_targets.add(checkout / "data/rerun_recordings")
            _extract_record(archive, infos[record.path], record, destination, checkout)
        manifest_destination = checkout / STATE / MANIFEST_NAME
        manifest_destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest_destination.with_name(f".{manifest_destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(verified.manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, manifest_destination)
        created_targets.add(manifest_destination)
    except BaseException:
        # Remove only the managed roots touched by this restore, then put the
        # original objects back in reverse order.  Backup remains if rollback
        # itself fails, so recovery is still possible by hand.
        for target in sorted(created_targets, key=lambda item: len(item.parts), reverse=True):
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        for target, backup_target in reversed(backups):
            if backup_target.exists() or backup_target.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(backup_target), str(target))
        raise
    finally:
        archive.close()
    if backup_root is not None:
        print(f"[data] dữ liệu cũ được backup tại {backup_root}")
    print(f"[data] restore thành công: {verified.summary.file_count} files, {verified.summary.project_count} projects")


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help="checkout root (mặc định: repo chứa script này)")
    commands = parser.add_subparsers(dest="command", required=True)
    packer = commands.add_parser("pack", help="tạo ZIP data package")
    packer.add_argument("--out", type=Path, default=Path(DEFAULT_NAME))
    packer.add_argument(
        "--keep-user-id",
        action="append",
        default=[],
        help="giữ password hash/active state của đúng hai seed user (lặp lại hai lần)",
    )
    packer.add_argument(
        "--keep-seed-accounts",
        action="store_true",
        help="giữ đúng hai user hiện có trong source; fail nếu source không có đúng hai user",
    )
    packer.add_argument(
        "--compression",
        choices=tuple(COMPRESSION_METHODS),
        default="deflated",
        help="kiểu nén ZIP: stored nhanh hơn với file đã nén, deflated mặc định",
    )
    verifier = commands.add_parser("verify", help="verify ZIP mà không ghi data")
    verifier.add_argument("package", type=Path)
    verifier.add_argument("--keep-user-id", action="append", default=None, help="yêu cầu package giữ đúng hai user này")
    verifier.add_argument("--expect-seed-accounts", action="store_true", help="yêu cầu policy keep-seed-accounts")
    unpacker = commands.add_parser("unpack", help="restore ZIP vào data canonical")
    unpacker.add_argument("package", type=Path)
    unpacker.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint, trả exit code 0/2."""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "pack":
            pack(args.root, args.out, args.keep_user_id, args.keep_seed_accounts, args.compression)
        elif args.command == "verify":
            summary = verify(args.package, args.keep_user_id, args.expect_seed_accounts)
            print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True))
        else:
            unpack(args.root, args.package, args.force)
    except (PackageError, OSError, sqlite3.Error, zipfile.BadZipFile) as error:
        print(f"[data] lỗi: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
