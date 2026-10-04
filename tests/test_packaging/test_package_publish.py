"""Focused proof for the production Studio package handoff boundary."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.cloud.package_publish import (
    PackagePublishError,
    PublishReport,
    extract_package,
    import_rows,
    main,
    provision_optional_data,
    publish_artifacts,
    validate_staged_package,
)
from scripts.studio.data_package import PackageError, pack
from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.artifacts.checksum import sha256_file
from src.services.orchestration.artifacts.remote import RemoteObject
from src.services.orchestration.jobs.database import RuntimeDatabase


class MemoryStore:
    """Small immutable object-store double with the production metadata contract."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def head(self, key: str) -> RemoteObject | None:
        """Return object size and the stored SHA-256 metadata."""
        value = self.objects.get(key)
        if value is None:
            return None
        payload, checksum = value
        return RemoteObject(key=key, size_bytes=len(payload), checksum=checksum)

    def put_file(self, key: str, path: Path, checksum: str) -> None:
        """Store bytes while rejecting a conflicting immutable key."""
        payload = path.read_bytes()
        existing = self.objects.get(key)
        if existing is not None and existing[1] != checksum:
            raise AssertionError("the test store must never overwrite an immutable key")
        self.objects[key] = (payload, checksum)


def _make_package(
    tmp_path: Path,
    *,
    status: str = "SUCCEEDED",
    current_stage: str = "ST-INPUT-VALIDATE",
    include_bundle: bool = False,
    include_null_artifact_event: bool = False,
    keep_seed_accounts: bool = False,
) -> tuple[Path, str]:
    """Create a minimal sanitized package with one terminal job artifact."""
    source = tmp_path / "source"
    database_path = source / "data/studio_local/runtime.db"
    artifacts = source / "data/studio_local/artifacts/jobs/job-a/manifests"
    artifacts.mkdir(parents=True)
    database = RuntimeDatabase(f"sqlite:///{database_path}")

    manifest = artifacts / "job_manifest.json"
    manifest.write_text(json.dumps({"status": status}), encoding="utf-8")
    manifest_checksum = sha256_file(manifest)
    artifact_uri = "artifact://jobs/job-a/manifests/job_manifest.json"
    reference = json.dumps({"artifact_uri": artifact_uri, "artifact_checksum": manifest_checksum})
    user = {
        "user_id": "user-seed-a" if keep_seed_accounts else "user-archived",
        "email": "seed-a@example.invalid" if keep_seed_accounts else "archived@example.invalid",
        "display_name": "Seed operator" if keep_seed_accounts else "Archived operator",
        "role": "editor",
        "password_hash": (
            "scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==$BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
            if keep_seed_accounts
            else "disabled-in-data-package"
        ),
        "active": keep_seed_accounts,
        "created_at": "2026-01-01T00:00:00+00:00",
        "daily_job_quota": 10,
    }
    second_user = {
        "user_id": "user-seed-b",
        "email": "seed-b@example.invalid",
        "display_name": "Seed reviewer",
        "role": "reviewer",
        "password_hash": "scrypt$16384$8$1$CCCCCCCCCCCCCCCCCCCCCC==$DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=",
        "active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "daily_job_quota": 10,
    }
    with database.transaction(write=True) as transaction:
        transaction.execute(
            "INSERT INTO r2s_users(user_id,email,payload) VALUES (?,?,?)",
            (user["user_id"], user["email"], json.dumps(user)),
        )
        if keep_seed_accounts:
            transaction.execute(
                "INSERT INTO r2s_users(user_id,email,payload) VALUES (?,?,?)",
                (second_user["user_id"], second_user["email"], json.dumps(second_user)),
            )
        transaction.execute(
            "INSERT INTO r2s_projects(project_id,payload) VALUES (?,?)",
            ("project-a", json.dumps({"project_id": "project-a", "created_by": user["user_id"]})),
        )
        transaction.execute(
            "INSERT INTO r2s_uploads(upload_id,payload) VALUES (?,?)",
            (
                "upload-a",
                json.dumps({"upload_id": "upload-a", "artifact_uri": artifact_uri, "checksum": manifest_checksum}),
            ),
        )
        transaction.execute(
            "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES (?,?,?,?)",
            ("job-a", "project-a", 1, reference),
        )
        transaction.execute(
            "INSERT INTO r2s_job_events(job_id,version,payload) VALUES (?,?,?)",
            ("job-a", 1, json.dumps({"status": status, "current_stage": current_stage})),
        )
        transaction.execute(
            "INSERT INTO r2s_scene_requests(job_id,status,payload) VALUES (?,?,?)",
            ("job-a", "done", json.dumps({"job_id": "job-a", "status": "done"})),
        )
        transaction.execute(
            "INSERT INTO r2s_audit_log(entry_id,at,user_id,action,payload) VALUES (?,?,?,?,?)",
            (
                "audit-a",
                "2026-01-01T00:00:00+00:00",
                user["user_id"],
                "job.created",
                json.dumps({"job_id": "job-a", "actor_name": "Archived operator"}),
            ),
        )
        transaction.execute(
            "INSERT INTO r2s_resource_usage(usage_id,job_id,recorded_at,payload) VALUES (?,?,?,?)",
            (
                "usage-a",
                "job-a",
                "2026-01-01T00:00:00+00:00",
                json.dumps({"worker_id": "worker-archived", "gpu_seconds": 12}),
            ),
        )
    optional_files = {
        "data/demo/library/demo.mp4": b"demo",
        "data/asset_previews/asset.glb": b"preview",
        "data/rerun_recordings/job-a.rrd": b"rerun",
        "data/studio_local/thumbnail_cache/job-a.webp": b"thumbnail",
    }
    for relative, payload in optional_files.items():
        optional_path = source / relative
        optional_path.parent.mkdir(parents=True, exist_ok=True)
        optional_path.write_bytes(payload)
    if include_bundle:
        nested_path = source / "data/studio_local/artifacts/jobs/job-a/visual/scene.sog"
        nested_path.parent.mkdir(parents=True, exist_ok=True)
        nested_path.write_bytes(b"nested visual artifact")
        nested_checksum = sha256_file(nested_path)
        bundle = {
            "artifact_type": "ReconstructionBundle",
            "artifact_uri": "artifact://jobs/job-a/reconstruction/bundle.json",
            "artifact_checksum": "sha256:" + "0" * 64,
            "visual_artifact_ref": {
                "artifact_uri": "artifact://jobs/job-a/visual/scene.sog",
                "artifact_checksum": nested_checksum,
            },
        }
        bundle["artifact_checksum"] = canonical_content_checksum(bundle, "artifact_checksum")
        bundle_path = source / "data/studio_local/artifacts/jobs/job-a/reconstruction/bundle.json"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(json.dumps(bundle, sort_keys=True) + "\n", encoding="utf-8")
    if include_null_artifact_event:
        event_path = source / "data/studio_local/artifacts/jobs/job-a/events/0000.json"
        event_path.parent.mkdir(parents=True, exist_ok=True)
        event_path.write_text(
            json.dumps(
                {
                    "stage_id": "ST-REC11",
                    "status": "SKIPPED",
                    "artifact_uri": None,
                    "artifact_checksum": None,
                    "error": "no artifact emitted",
                }
            )
            + "\n",
            encoding="utf-8",
        )
    archive_path = tmp_path / "studio-data.zip"
    pack(source, archive_path, keep_seed_accounts=keep_seed_accounts)
    return archive_path, artifact_uri.removeprefix("artifact://")


def test_publish_is_idempotent_then_imports_rows_atomically(tmp_path: Path) -> None:
    """Same package can be retried and a clean target receives stable rows."""
    archive_path, relative_key = _make_package(tmp_path)
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)
    package = validate_staged_package(staging)
    store = MemoryStore()

    first = publish_artifacts(package.artifacts, store, prefix="prod")
    second = publish_artifacts(package.artifacts, store, prefix="prod")

    assert first == PublishReport(
        uploaded_files=1, skipped_files=0, uploaded_bytes=len(b'{"status": "SUCCEEDED"}'), artifact_files=1
    )
    assert second == PublishReport(uploaded_files=0, skipped_files=1, uploaded_bytes=0, artifact_files=1)
    assert "prod/" + relative_key in store.objects

    target = RuntimeDatabase(f"sqlite:///{tmp_path / 'target.db'}")
    imported = import_rows(target, package.rows)
    assert imported["r2s_projects"] == 1
    with target.transaction() as transaction:
        assert transaction.execute("SELECT COUNT(*) FROM r2s_jobs").fetchone() == (1,)
        assert transaction.execute("SELECT COUNT(*) FROM r2s_audit_log").fetchone() == (1,)
        assert transaction.execute("SELECT COUNT(*) FROM r2s_resource_usage").fetchone() == (1,)
        assert transaction.execute("SELECT COUNT(*) FROM r2s_sessions").fetchone() == (0,)
    with pytest.raises(PackagePublishError, match="not empty"):
        import_rows(target, package.rows)


def test_publisher_preserves_explicit_seed_accounts_without_sessions(tmp_path: Path) -> None:
    """The authorized two-account mode keeps login material while sessions stay empty."""
    archive_path, _ = _make_package(tmp_path, keep_seed_accounts=True)
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)
    package = validate_staged_package(staging)

    users = {row[0]: json.loads(row[2]) for row in package.rows["r2s_users"]}
    assert set(users) == {"user-seed-a", "user-seed-b"}
    assert all(user["active"] is True for user in users.values())
    assert all(user["password_hash"].startswith("scrypt$") for user in users.values())

    target = RuntimeDatabase(f"sqlite:///{tmp_path / 'target.db'}")
    import_rows(target, package.rows)
    with target.transaction() as transaction:
        assert transaction.execute("SELECT COUNT(*) FROM r2s_users").fetchone() == (2,)
        assert transaction.execute("SELECT COUNT(*) FROM r2s_sessions").fetchone() == (0,)
        assert transaction.execute("SELECT COUNT(*) FROM r2s_invites").fetchone() == (0,)


def test_default_cli_is_non_mutating_for_empty_sqlite_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator must opt into migrations, uploads, and row inserts with --apply."""
    archive_path, _ = _make_package(tmp_path)
    target_path = tmp_path / "not-created-by-dry-run.db"
    report_path = tmp_path / "publish-report.json"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target_path}")

    assert main(["--package", str(archive_path), "--report", str(report_path)]) == 0
    assert not target_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["account_policy"] == {"mode": "scrub-all", "kept_user_count": 0}
    assert "password_hash" not in report_path.read_text(encoding="utf-8")


def test_provision_merges_only_optional_files_and_is_immutable(tmp_path: Path) -> None:
    """The volume helper never restores runtime.db/artifacts and is retry-safe."""
    archive_path, _ = _make_package(tmp_path)
    volume = tmp_path / "volume"

    first = provision_optional_data(archive_path, volume)
    assert first.copied_files == 4
    assert first.skipped_files == 0
    assert (volume / "demo/library/demo.mp4").read_bytes() == b"demo"
    assert (volume / "asset_previews/asset.glb").read_bytes() == b"preview"
    assert (volume / "rerun_recordings/job-a.rrd").read_bytes() == b"rerun"
    assert (volume / "studio_local/thumbnail_cache/job-a.webp").read_bytes() == b"thumbnail"
    assert not (volume / "studio_local/runtime.db").exists()
    assert not (volume / "studio_local/artifacts").exists()

    second = provision_optional_data(archive_path, volume)
    assert second.copied_files == 0
    assert second.skipped_files == 4

    (volume / "asset_previews/asset.glb").write_bytes(b"different")
    with pytest.raises(PackagePublishError, match="differs"):
        provision_optional_data(archive_path, volume)
    assert (volume / "demo/library/demo.mp4").read_bytes() == b"demo"


def test_provision_cli_does_not_need_database_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional Railway-volume seeding is independent from the Postgres publish."""
    archive_path, _ = _make_package(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert main(["provision", "--package", str(archive_path), "--target-root", str(tmp_path / "volume")]) == 0


def test_provision_rejects_symlinked_destination_ancestor(tmp_path: Path) -> None:
    """A mounted data target cannot redirect copies through a symlink ancestor."""
    archive_path, _ = _make_package(tmp_path)
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    symlink_root = tmp_path / "linked-root"
    symlink_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(PackagePublishError, match="symlinked ancestor"):
        provision_optional_data(archive_path, symlink_root / "volume")
    assert not (real_root / "volume").exists()


def test_bundle_root_identity_checksum_skips_only_self_and_checks_nested_bytes(tmp_path: Path) -> None:
    """A ReconstructionBundle identity checksum must not be compared to file bytes."""
    archive_path, _ = _make_package(tmp_path, include_bundle=True)
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)

    package = validate_staged_package(staging)
    bundle_path = package.artifacts / "jobs/job-a/reconstruction/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["artifact_checksum"] != sha256_file(bundle_path)
    assert package.artifacts.joinpath("jobs/job-a/visual/scene.sog").is_file()


def test_artifact_event_without_published_uri_is_ignored(tmp_path: Path) -> None:
    """A status event with a null artifact URI is not a byte-reference contract."""
    archive_path, _ = _make_package(tmp_path, include_null_artifact_event=True)
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)

    package = validate_staged_package(staging)
    assert package.artifacts.joinpath("jobs/job-a/events/0000.json").is_file()


def test_external_artifact_uri_field_is_validated(tmp_path: Path) -> None:
    """URI fields such as visual_artifact_uri retain their external checksum."""
    archive_path, _ = _make_package(tmp_path, include_bundle=True)
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)
    bundle_path = staging / "data/studio_local/artifacts/jobs/job-a/reconstruction/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    visual_path = staging / "data/studio_local/artifacts/jobs/job-a/visual/scene.sog"
    bundle["external_visual"] = {
        "visual_artifact_uri": "artifact://jobs/job-a/visual/scene.sog",
        "visual_artifact_checksum": sha256_file(visual_path),
    }
    bundle_path.write_text(json.dumps(bundle, sort_keys=True) + "\n", encoding="utf-8")

    package = validate_staged_package(staging)
    assert package.artifacts.joinpath("jobs/job-a/visual/scene.sog").is_file()


def test_external_artifact_uri_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    """A non-standard URI field cannot bypass nested byte verification."""
    archive_path, _ = _make_package(tmp_path, include_bundle=True)
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)
    bundle_path = staging / "data/studio_local/artifacts/jobs/job-a/reconstruction/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["external_visual"] = {
        "visual_artifact_uri": "artifact://jobs/job-a/visual/scene.sog",
        "visual_artifact_checksum": "sha256:" + "0" * 64,
    }
    bundle_path.write_text(json.dumps(bundle, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PackagePublishError, match="checksum mismatch"):
        validate_staged_package(staging)


def test_nested_artifact_reference_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    """Ignoring a bundle identity checksum must not weaken nested byte checks."""
    archive_path, _ = _make_package(tmp_path, include_bundle=True)
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)
    bundle_path = staging / "data/studio_local/artifacts/jobs/job-a/reconstruction/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["visual_artifact_ref"]["artifact_checksum"] = "sha256:" + "0" * 64
    bundle_path.write_text(json.dumps(bundle, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PackagePublishError, match="checksum mismatch"):
        validate_staged_package(staging)


def test_publish_rejects_existing_object_with_different_checksum(tmp_path: Path) -> None:
    """An existing object without the exact checksum can never be overwritten."""
    archive_path, _ = _make_package(tmp_path)
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)
    package = validate_staged_package(staging)
    store = MemoryStore()
    store.objects["prod/jobs/job-a/manifests/job_manifest.json"] = (b"different", "sha256:wrong")

    with pytest.raises(PackagePublishError, match="different checksum"):
        publish_artifacts(package.artifacts, store, prefix="prod")


def test_pack_rejects_active_job_before_publisher_receives_it(tmp_path: Path) -> None:
    """The shared packer blocks a package while a worker may still mutate it."""
    with pytest.raises(PackageError, match="đóng gói"):
        _make_package(tmp_path, status="RUNNING")


def test_human_metric_wait_is_preserved_as_shippable_state(tmp_path: Path) -> None:
    """RUNNING at metric confirmation is a user wait, not mutable worker work."""
    archive_path, _ = _make_package(
        tmp_path,
        status="RUNNING",
        current_stage="ST-METRIC-CANONICALIZE",
    )
    staging = tmp_path / "staging"
    extract_package(archive_path, staging)

    assert validate_staged_package(staging).rows["r2s_jobs"]


def test_extraction_rejects_path_traversal(tmp_path: Path) -> None:
    """The archive boundary rejects members outside the package allow-list."""
    archive_path = tmp_path / "unsafe.zip"
    outside = tmp_path / "outside.txt"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "DATA_PACKAGE.json",
            json.dumps({"package_format": 1, "files": [], "file_count": 0, "total_bytes": 0}),
        )
        archive.writestr("../outside.txt", "unsafe")

    with pytest.raises(PackagePublishError, match="path"):
        extract_package(archive_path, tmp_path / "staging")
    assert not outside.exists()
