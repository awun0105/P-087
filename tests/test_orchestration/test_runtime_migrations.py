"""Migration runtime DB có thứ tự trên SQLite và PostgreSQL (ADR 0003 §5).

PostgreSQL chỉ chạy khi có `R2S_TEST_POSTGRES_URL` (URL tới database quản trị, vd
`postgresql://r2s:r2s-test@127.0.0.1:15432/postgres`); mỗi test tạo database riêng.
"""

import sqlite3
from pathlib import Path

import pytest

from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs import database as database_module
from src.services.orchestration.jobs.database import (
    LATEST_SCHEMA_VERSION,
    RuntimeDatabase,
    RuntimeStateConflictError,
)
from src.services.orchestration.uploads import VideoUploadService


def _tables(database: RuntimeDatabase) -> set[str]:
    query = (
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        if database.postgres
        else "SELECT name FROM sqlite_master WHERE type='table'"
    )
    with database.transaction() as tx:
        return {row[0] for row in tx.execute(query).fetchall()}


def test_fresh_database_reaches_latest_version(runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    assert database.schema_version() == LATEST_SCHEMA_VERSION
    assert {
        "r2s_projects",
        "r2s_jobs",
        "r2s_job_events",
        "r2s_uploads",
        "r2s_upload_sessions",
        "r2s_validation_runs",
        "r2s_validation_selections",
        "r2s_release_seals",
        "r2s_release_seal_failures",
    } <= _tables(database)
    database.ping()
    # Khởi động lại (process khác) không chạy lại migration, không lỗi.
    assert RuntimeDatabase(runtime_database_url).schema_version() == LATEST_SCHEMA_VERSION


def test_newer_schema_is_refused(runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    with database.transaction(write=True) as tx:
        tx.execute("UPDATE r2s_schema SET version=? WHERE id=1", (LATEST_SCHEMA_VERSION + 1,))
    database_module._READY.clear()  # mô phỏng tiến trình mới khởi động
    with pytest.raises(RuntimeError, match="cập nhật code"):
        RuntimeDatabase(runtime_database_url)


def test_legacy_v1_sqlite_upgrades_without_losing_rows(tmp_path: Path) -> None:
    """DB tạo bởi bản trước migration: schema v1 + bảng Studio đã có sẵn dữ liệu."""
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as legacy:
        legacy.execute("CREATE TABLE r2s_schema (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)")
        legacy.execute("INSERT INTO r2s_schema VALUES (1, 1)")
        legacy.execute("CREATE TABLE r2s_projects (project_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        legacy.execute("INSERT INTO r2s_projects VALUES ('project-a', '{}')")
        legacy.execute("CREATE TABLE r2s_uploads (upload_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        legacy.execute("INSERT INTO r2s_uploads VALUES ('upload-a', '{}')")

    database = RuntimeDatabase(f"sqlite:///{path}")
    assert database.schema_version() == LATEST_SCHEMA_VERSION
    with database.transaction() as tx:
        assert tx.execute("SELECT project_id FROM r2s_projects").fetchall() == [("project-a",)]
        assert tx.execute("SELECT upload_id FROM r2s_uploads").fetchall() == [("upload-a",)]
    assert "r2s_upload_sessions" in _tables(database)


def test_v8_database_adds_validation_history_without_losing_rows(tmp_path: Path) -> None:
    """Migrations 9–11 are additive and keep pre-existing project/job state intact."""
    path = tmp_path / "legacy-v8.db"
    with sqlite3.connect(path) as legacy:
        legacy.execute("CREATE TABLE r2s_schema (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)")
        legacy.execute("INSERT INTO r2s_schema VALUES (1, 0)")
        for version, statements in database_module.MIGRATIONS:
            if version > 8:
                continue
            for statement in statements:
                legacy.execute(statement)
            legacy.execute("UPDATE r2s_schema SET version=? WHERE id=1", (version,))
        legacy.execute("INSERT INTO r2s_projects(project_id,payload) VALUES ('project-preserved','{}')")
        legacy.execute(
            "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES ('job-preserved','project-preserved',1,'artifact://jobs/job-preserved/manifest.json')"
        )

    database = RuntimeDatabase(f"sqlite:///{path}")
    assert database.schema_version() == LATEST_SCHEMA_VERSION == 11
    assert {
        "r2s_validation_runs",
        "r2s_validation_selections",
        "r2s_release_seals",
        "r2s_release_seal_failures",
    } <= _tables(database)
    with database.transaction() as tx:
        assert tx.execute("SELECT project_id FROM r2s_projects").fetchall() == [("project-preserved",)]
        assert tx.execute("SELECT job_id FROM r2s_jobs").fetchall() == [("job-preserved",)]


def test_v9_database_adds_release_seals_without_losing_rows(tmp_path: Path) -> None:
    """Migration 10 adds intent storage without rewriting existing project/job state."""
    path = tmp_path / "legacy-v9.db"
    with sqlite3.connect(path) as legacy:
        legacy.execute("CREATE TABLE r2s_schema (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)")
        legacy.execute("INSERT INTO r2s_schema VALUES (1, 0)")
        for version, statements in database_module.MIGRATIONS:
            if version > 9:
                continue
            for statement in statements:
                legacy.execute(statement)
            legacy.execute("UPDATE r2s_schema SET version=? WHERE id=1", (version,))
        legacy.execute("INSERT INTO r2s_projects(project_id,payload) VALUES ('project-v9','{}')")
        legacy.execute(
            "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES ('job-v9','project-v9',1,'artifact://jobs/job-v9/manifest.json')"
        )

    database = RuntimeDatabase(f"sqlite:///{path}")

    assert database.schema_version() == LATEST_SCHEMA_VERSION == 11
    assert {"r2s_release_seals", "r2s_release_seal_failures"} <= _tables(database)
    with database.transaction() as tx:
        assert tx.execute("SELECT project_id FROM r2s_projects").fetchall() == [("project-v9",)]
        assert tx.execute("SELECT job_id FROM r2s_jobs").fetchall() == [("job-v9",)]


def test_v10_database_adds_release_seal_diagnostics_without_losing_intents(tmp_path: Path) -> None:
    """Migration 11 adds retry diagnostics and preserves already frozen release intents."""
    path = tmp_path / "legacy-v10.db"
    with sqlite3.connect(path) as legacy:
        legacy.execute("CREATE TABLE r2s_schema (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)")
        legacy.execute("INSERT INTO r2s_schema VALUES (1, 0)")
        for version, statements in database_module.MIGRATIONS:
            if version > 10:
                continue
            for statement in statements:
                legacy.execute(statement)
            legacy.execute("UPDATE r2s_schema SET version=? WHERE id=1", (version,))
        legacy.execute(
            """INSERT INTO r2s_release_seals
               (job_id,candidate_checksum,validation_report_checksum,approval_record_checksum,generation,intent_checksum,payload)
               VALUES ('job-v10','c','r','a',1,'i','{}')"""
        )

    database = RuntimeDatabase(f"sqlite:///{path}")

    assert database.schema_version() == LATEST_SCHEMA_VERSION == 11
    assert {"r2s_release_seals", "r2s_release_seal_failures"} <= _tables(database)
    with database.transaction() as tx:
        assert tx.execute("SELECT job_id FROM r2s_release_seals").fetchall() == [("job-v10",)]


def test_upload_records_and_row_locks_work(runtime_database_url: str, tmp_path: Path) -> None:
    """Đường ghi thật (INSERT, SELECT … FOR UPDATE trên Postgres, CAS) chạy trên cả hai DB."""
    database = RuntimeDatabase(runtime_database_url)
    service = VideoUploadService(database, ArtifactResolver(tmp_path / "artifacts"), 1024)
    pending = service.begin("kho.mp4")
    pending.publication.write(b"\x00\x00\x00\x14ftypqt  " + b"video")
    record = service.finish(pending)
    assert service.get(record.upload_id).checksum == record.checksum
    service.link_project(record.upload_id, "project-a")
    with pytest.raises(RuntimeStateConflictError):
        service.link_project(record.upload_id, "project-a")
    assert service.list()[0].project_ids == ["project-a"]


def test_registry_project_job_lifecycle(runtime_database_url: str, tmp_path: Path) -> None:
    """Luồng Studio thật trên DB: upload → project → job QUEUED → CAS RUNNING; revision cũ bị từ chối."""
    from src.models.contracts.manifests import JobStatus
    from src.services.orchestration.jobs.models import TransitionRequest
    from src.services.orchestration.jobs.profile import ExecutionProfile
    from src.services.orchestration.projects.models import JobCreateInput, UploadProjectInput
    from src.services.orchestration.projects.registry import ProjectRegistry

    database = RuntimeDatabase(runtime_database_url)
    probe = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry = ProjectRegistry(
        runtime_root=tmp_path / "artifacts",
        database=database,
        execution_profile=ExecutionProfile(
            config_checksum=probe._fixture_config_checksum(),
            runtime_manifest_checksum=probe._fixture_runtime_checksum(),
            seed=7,
        ),
    )
    uploads = VideoUploadService(database, registry.runtime_resolver, 1024)
    pending = uploads.begin("kho.mp4")
    pending.publication.write(b"\x00\x00\x00\x14ftypqt  " + b"video-bytes")
    upload = uploads.finish(pending)
    project = registry.create_project_from_upload(
        upload,
        UploadProjectInput(
            upload_id=upload.upload_id,
            name="Kho A",
            attestation={
                "data_origin": "self_collected_no_pii",
                "declared_owner": "QA",
                "declared_purpose": "Kiểm tra DB",
                "rights_to_use_confirmed": True,
                "anonymization_confirmed": True,
                "retention_acknowledged": True,
            },
        ),
        "self_attested",
    )
    job = registry.create_job(JobCreateInput(project_id=project.project_id))
    assert job.status == JobStatus.QUEUED

    running = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.RUNNING), expected_checksum=job.job_manifest_checksum
    )
    assert registry.get_job(job.job_id).status == JobStatus.RUNNING
    with pytest.raises(RuntimeStateConflictError):
        registry.transition_job(
            job.job_id,
            TransitionRequest(target_status=JobStatus.CANCELLED),
            expected_checksum=job.job_manifest_checksum,
        )
    assert [item.job_id for item in registry.list_jobs(project.project_id)] == [running.job_id]
