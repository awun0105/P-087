"""Durable scene-import queue transactions and restart recovery."""

import sqlite3
from pathlib import Path

import pytest

from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.uploads import VideoUploadService
from src.services.orchestration.uploads.scene_imports import ImportedScene, ImportService, SceneImportError
from tests.test_reconstruction.test_input_detection import _gaussian


@pytest.fixture
def import_world(tmp_path: Path):  # noqa: ANN201
    database_url = f"sqlite:///{tmp_path / 'runtime.db'}"
    database = RuntimeDatabase(database_url)
    resolver = ArtifactResolver(tmp_path / "artifacts")
    uploads = VideoUploadService(database, resolver, 8 * 1024 * 1024)
    service = ImportService(database, resolver, tmp_path / "worker" / "imports")
    return database_url, database, resolver, uploads, service


def _upload(uploads: VideoUploadService):
    pending = uploads.begin("warehouse.ply")
    pending.publication.write(_gaussian(count=4))
    return uploads.finish(pending)


def _fake_package(source: Path, workspace: Path, gpu_index: int | None) -> Path:
    workspace.mkdir(parents=True)
    output = workspace / "scene.sog"
    output.write_bytes(b"SOG output:" + source.read_bytes())
    return output


def test_import_row_and_queue_rollback_together_on_enqueue_failure(import_world) -> None:  # noqa: ANN001
    _, database, _, uploads, service = import_world
    upload = _upload(uploads)
    with database.transaction(write=True) as tx:
        tx.execute(
            "CREATE TRIGGER reject_import_operation BEFORE INSERT ON r2s_import_operations "
            "BEGIN SELECT RAISE(ABORT, 'forced queue insert failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced queue insert failure"):
        service.create(upload, "Warehouse", "user-1")

    with database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_imports").fetchone() == (0,)
        assert tx.execute("SELECT COUNT(*) FROM r2s_import_operations").fetchone() == (0,)


def test_queued_import_survives_api_process_restart_and_worker_finds_it(
    import_world, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    database_url, _, resolver, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    assert record.operation is not None and record.operation.status == "QUEUED"

    restarted = ImportService(
        RuntimeDatabase(database_url),
        resolver,
        Path(database_url.removeprefix("sqlite:///")).parent / "worker" / "imports",
    )
    assert restarted.get(record.import_id).operation is not None
    assert restarted.get(record.import_id).operation.status == "QUEUED"
    monkeypatch.setattr("src.services.orchestration.uploads.scene_imports.package_splat", _fake_package)

    assert restarted.process_next(None, worker_id="test-worker") is True
    ready = restarted.get(record.import_id)
    assert ready.status == "READY" and ready.operation is not None
    assert ready.operation.status == "SUCCEEDED" and ready.operation.attempt == 1
    assert restarted.process_next(None, worker_id="test-worker") is False


def test_repeated_idempotency_key_replays_only_the_same_request(import_world) -> None:  # noqa: ANN001
    _, _, _, uploads, service = import_world
    upload = _upload(uploads)

    first = service.create(upload, "Warehouse", "user-1", idempotency_key="request-abc")
    replay = service.create(upload, "Warehouse", "user-1", idempotency_key="request-abc")
    assert replay.import_id == first.import_id
    with pytest.raises(SceneImportError, match="Idempotency-Key"):
        service.create(upload, "Another name", "user-1", idempotency_key="request-abc")
    assert service.create(upload, "Warehouse", "user-1").import_id != first.import_id
    assert len(service.list()) == 2


def test_legacy_packaging_is_queued_once_and_ready_record_is_not_reprocessed(import_world) -> None:  # noqa: ANN001
    _, database, _, uploads, service = import_world
    upload = _upload(uploads)
    old_packaging = ImportedScene(
        import_id="import-legacy-packing",
        upload_id=upload.upload_id,
        name="Old packaging",
        input_kind="gaussian_ply",
        status="PACKAGING",
        created_at=upload.received_at,
    )
    old_ready = ImportedScene(
        import_id="import-legacy-ready",
        upload_id=upload.upload_id,
        name="Old ready",
        input_kind="gaussian_ply",
        status="READY",
        created_at=upload.received_at,
    )
    with database.transaction(write=True) as tx:
        for record in (old_packaging, old_ready):
            tx.execute(
                "INSERT INTO r2s_imports(import_id, upload_id, payload) VALUES (?, ?, ?)",
                (record.import_id, record.upload_id, record.model_dump_json()),
            )

    assert service.recover_legacy_packaging() == 1
    assert service.recover_legacy_packaging() == 0
    assert service.get(old_packaging.import_id).operation.status == "QUEUED"  # type: ignore[union-attr]
    assert service.get(old_ready.import_id).operation is None
