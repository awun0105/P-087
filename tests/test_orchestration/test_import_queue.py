"""Durable scene-import queue transactions and restart recovery."""

import os
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads import VideoUploadService
from src.services.orchestration.uploads import scene_imports as import_module
from src.services.orchestration.uploads.scene_imports import ImportedScene, ImportService, SceneImportError
from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess, VoxelRuntimeSettings
from tests.test_reconstruction.support.sog_fixtures import sog_archive
from tests.test_reconstruction.test_input_detection import _gaussian


@pytest.fixture
def import_world(tmp_path: Path):  # noqa: ANN201
    database_url = f"sqlite:///{tmp_path / 'runtime.db'}"
    database = RuntimeDatabase(database_url)
    resolver = ArtifactResolver(tmp_path / "artifacts")
    uploads = VideoUploadService(database, resolver, 8 * 1024 * 1024)
    service = ImportService(
        database, resolver, tmp_path / "worker" / "imports", max_uncompressed_bytes=16 * 1024 * 1024
    )
    return database_url, database, resolver, uploads, service


def _upload(uploads: VideoUploadService):
    pending = uploads.begin("warehouse.ply")
    pending.publication.write(_gaussian(count=4))
    return uploads.finish(pending)


def _fake_package(source: Path, workspace: Path, gpu_index: int | None, **_: object) -> Path:
    workspace.mkdir(parents=True)
    output = workspace / "scene.sog"
    output.write_bytes(sog_archive(sh_bands=3, count=4))
    return output


def _enable_fake_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(import_module, "package_splat", _fake_package)
    monkeypatch.setattr(import_module, "validate_sog_runtime", lambda *args, **kwargs: None)


def _expire_lease(service: ImportService, import_id: str) -> None:
    operation = service._operation_record(import_id)
    expired = operation.model_copy(update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    with service.database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_import_operations SET lease_expires_at=?, payload=? WHERE operation_id=?",
            (expired.lease_expires_at.isoformat(), expired.model_dump_json(), expired.operation_id),
        )


class _Admission:
    def __init__(self, *statuses: str) -> None:
        self.statuses = list(statuses or ("admitted",))
        self.requests = []
        self.released = []

    def operation_profile_for_import(self, **_: object):
        from src.services.orchestration.jobs.admission import OperationResourceProfile

        return OperationResourceProfile(
            required_gb={"vram": 1.0, "ram": 2.0, "disk": 1.0},
            danger_ratio=0.9,
            measured=False,
            gpu_required=True,
        )

    def admit_operation(self, request):  # noqa: ANN001
        self.requests.append(request)
        status = self.statuses.pop(0)
        return SimpleNamespace(
            status=status,
            waiting_on=["ram"] if status != "admitted" else [],
            reasons={"ram": "unmeasured"} if status != "admitted" else {},
        )

    def touch_operation(self, request):  # noqa: ANN001
        return True

    def release_operation(self, request):  # noqa: ANN001
        self.released.append(request)
        return True


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
        max_uncompressed_bytes=16 * 1024 * 1024,
    )
    assert restarted.get(record.import_id).operation is not None
    assert restarted.get(record.import_id).operation.status == "QUEUED"
    _enable_fake_runtime(monkeypatch)

    admission = _Admission()
    assert restarted.process_next(admission=admission, worker_id="test-worker") is True
    ready = restarted.get(record.import_id)
    assert ready.status == "READY" and ready.operation is not None
    assert ready.operation.status == "SUCCEEDED" and ready.operation.attempt == 1
    assert admission.requests[0].input_checksum == upload.checksum
    assert admission.requests[0].config_checksum == service._config_checksum(record.input_kind, None)
    assert len(admission.released) == 1
    assert restarted.process_next(admission=admission, worker_id="test-worker") is False


def test_resource_wait_preserves_config_and_does_not_start_packaging(import_world, monkeypatch) -> None:  # noqa: ANN001
    _, _, _, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    operation = service._operation_record(record.import_id)
    monkeypatch.setattr(import_module, "package_splat", lambda *_: pytest.fail("must not package while waiting"))

    waiting_admission = _Admission("waiting_resources")
    assert service.process_next(admission=waiting_admission, worker_id="waiting-worker") is False
    waiting = service.get(record.import_id)
    assert waiting.status == "PACKAGING" and waiting.operation is not None
    assert waiting.operation.status == "WAITING" and waiting.operation.attempt == 0
    assert waiting.operation.failure_code == "resource_wait"
    assert waiting.operation.error == "Worker đang chờ tài nguyên: ram (unmeasured)."
    assert waiting_admission.requests[0].input_checksum == upload.checksum
    assert waiting_admission.requests[0].config_checksum == operation.packaging_config_checksum
    assert waiting_admission.released == []

    _enable_fake_runtime(monkeypatch)
    assert service.process_next(admission=_Admission(), worker_id="ready-worker") is True
    ready = service.get(record.import_id)
    assert ready.status == "READY" and ready.operation is not None and ready.operation.attempt == 1


def test_cancel_during_resource_wait_is_not_overwritten_by_waiting_state(import_world) -> None:  # noqa: ANN001
    _, _, _, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")

    class CancelDuringAdmission(_Admission):
        def admit_operation(self, request):  # noqa: ANN001
            service.cancel(record.import_id)
            return super().admit_operation(request)

    assert service.process_next(admission=CancelDuringAdmission("waiting"), worker_id="cancel-race") is False
    cancelled = service.get(record.import_id)
    assert cancelled.status == "CANCELLED"
    assert cancelled.operation is not None
    assert cancelled.operation.status == "CANCELLED"
    assert cancelled.operation.cancel_requested is True


def test_queued_cancel_prevents_worker_start(import_world) -> None:  # noqa: ANN001
    _, _, _, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")

    cancelled = service.cancel(record.import_id)

    assert cancelled.status == "CANCELLED"
    assert cancelled.operation is not None and cancelled.operation.status == "CANCELLED"
    assert service.process_next(admission=_Admission(), worker_id="after-cancel") is False


def test_retryable_publish_failure_keeps_attempt_history(import_world, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, resolver, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    _enable_fake_runtime(monkeypatch)
    original_publish = service._publish_or_reuse
    failures = 0

    def fail_once(*args: object, **kwargs: object) -> None:
        nonlocal failures
        failures += 1
        if failures == 1:
            raise ArtifactStoreError("remote unavailable")
        original_publish(*args, **kwargs)

    monkeypatch.setattr(service, "_publish_or_reuse", fail_once)
    assert service.process_next(admission=_Admission(), worker_id="first-attempt") is True
    failed = service.get(record.import_id)
    assert failed.status == "FAILED" and failed.operation is not None
    assert failed.operation.retryable is True
    assert [attempt.status for attempt in failed.operation.attempt_history] == ["FAILED"]
    assert resolver.require_uri(upload.artifact_uri, upload.checksum).is_file()

    queued = service.retry(record.import_id)
    assert queued.status == "PACKAGING" and queued.operation is not None
    assert queued.operation.status == "QUEUED" and queued.operation.attempt == 1
    assert service.process_next(admission=_Admission(), worker_id="second-attempt") is True
    ready = service.get(record.import_id)
    assert ready.status == "READY" and ready.operation is not None
    assert ready.operation.attempt == 2
    assert [attempt.status for attempt in ready.operation.attempt_history] == ["FAILED", "SUCCEEDED"]


def test_invalid_source_failure_cannot_be_retried(import_world) -> None:  # noqa: ANN001
    _, _, _, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    changed_upload = upload.model_copy(update={"checksum": f"sha256:{'a' * 64}"})
    with service.database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_uploads SET payload=? WHERE upload_id=?",
            (changed_upload.model_dump_json(), upload.upload_id),
        )

    assert service.process_next(admission=_Admission(), worker_id="invalid-source") is True
    failed = service.get(record.import_id)
    assert failed.operation is not None and failed.operation.failure_code == "invalid_source"
    assert failed.operation.retryable is False
    with pytest.raises(SceneImportError, match="không cho phép thử lại"):
        service.retry(record.import_id)


def test_running_cancel_kills_and_reaps_geometry_child(
    import_world, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    _enable_fake_runtime(monkeypatch)
    child_pid_path = tmp_path / "geometry-child.pid"
    entered = Event()

    def blocking_package(source: Path, workspace: Path, gpu_index: int | None, **kwargs: object) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        script = (
            "import os, pathlib, time; "
            f"pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid())); "
            "time.sleep(30)"
        )
        entered.set()
        process = VoxelProcess(
            VoxelRuntimeSettings(cli=Path(sys.executable), module_path=tmp_path, node_command=(sys.executable,))
        )
        process.run(("-c", script), (workspace, "blocking-test"), cancel_event=kwargs["cancel_event"])
        return _fake_package(source, workspace, gpu_index)

    monkeypatch.setattr(import_module, "package_splat", blocking_package)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            service.process_next(admission=_Admission(), worker_id="cancel-worker")
        except Exception as error:  # noqa: BLE001 - thread errors are asserted below.
            errors.append(error)

    thread = Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=5)
    deadline = time.monotonic() + 5
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_pid_path.exists(), "geometry subprocess did not start"
    child_pid = int(child_pid_path.read_text())

    requested = service.cancel(record.import_id)
    assert requested.status == "PACKAGING"
    thread.join(timeout=5)

    assert not thread.is_alive() and errors == []
    cancelled = service.get(record.import_id)
    assert cancelled.status == "CANCELLED" and cancelled.operation is not None
    assert [attempt.status for attempt in cancelled.operation.attempt_history] == ["CANCELLED"]
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_source_checksum_mismatch_fails_before_admission(import_world) -> None:  # noqa: ANN001
    _, _, resolver, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    resolver.resolve(upload.artifact_uri).write_bytes(b"tampered source")
    admission = _Admission()

    assert service.process_next(admission=admission, worker_id="checksum-worker") is True
    failed = service.get(record.import_id)
    assert failed.status == "FAILED" and failed.operation is not None
    assert failed.operation.failure_code == "invalid_source" and failed.operation.retryable is False
    assert admission.requests == []


def test_publish_failure_is_typed_retryable_and_keeps_source(import_world, monkeypatch) -> None:  # noqa: ANN001
    _, _, resolver, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    _enable_fake_runtime(monkeypatch)

    def reject_publication(_: str) -> None:
        raise ArtifactStoreError("remote unavailable")

    monkeypatch.setattr(resolver, "published", reject_publication)
    assert service.process_next(admission=_Admission(), worker_id="publish-worker") is True
    failed = service.get(record.import_id)
    assert failed.status == "FAILED" and failed.operation is not None
    assert failed.operation.failure_code == "publication_failure" and failed.operation.retryable is True
    assert resolver.require_uri(upload.artifact_uri, upload.checksum).is_file()


def test_crash_after_sog_publish_reclaims_lease_and_reuses_verified_uri(
    import_world, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    _, _, resolver, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    _enable_fake_runtime(monkeypatch)
    finish = service._finish

    def crash_after_publish(*args: object, **kwargs: object):
        if kwargs.get("status") == "READY":
            raise RuntimeStateConflictError("simulated worker crash after publish")
        return finish(*args, **kwargs)

    monkeypatch.setattr(service, "_finish", crash_after_publish)
    assert service.process_next(admission=_Admission(), worker_id="first-worker") is True
    assert service.get(record.import_id).status == "PACKAGING"
    _expire_lease(service, record.import_id)
    monkeypatch.setattr(service, "_finish", finish)

    assert service.process_next(admission=_Admission(), worker_id="recovery-worker") is True
    ready = service.get(record.import_id)
    assert ready.status == "READY" and ready.delivery_ref is not None and ready.operation is not None
    published = resolver.require(ready.delivery_ref)
    assert service._checksum_file(published) == ready.delivery_ref.artifact_checksum
    assert ready.operation.attempt == 2


def test_expired_worker_cannot_publish_ready_after_new_fenced_owner(
    import_world, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    _, _, _, uploads, service = import_world
    upload = _upload(uploads)
    record = service.create(upload, "Warehouse", "user-1")
    _enable_fake_runtime(monkeypatch)
    monkeypatch.setattr(import_module, "_IMPORT_HEARTBEAT_SECONDS", 0.02)
    entered = Event()
    resume = Event()
    calls = 0

    def blocking_package(source: Path, workspace: Path, gpu_index: int | None, **_: object) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert resume.wait(timeout=5)
        return _fake_package(source, workspace, gpu_index)

    monkeypatch.setattr(import_module, "package_splat", blocking_package)
    errors: list[Exception] = []

    def old_worker() -> None:
        try:
            service.process_next(admission=_Admission(), worker_id="old-worker")
        except Exception as error:  # noqa: BLE001 - thread errors are asserted below.
            errors.append(error)

    thread = Thread(target=old_worker)
    thread.start()
    assert entered.wait(timeout=5)
    _expire_lease(service, record.import_id)
    time.sleep(0.08)
    assert service.process_next(admission=_Admission(), worker_id="new-worker") is True
    resume.set()
    thread.join(timeout=5)

    current = service.get(record.import_id)
    assert not thread.is_alive() and errors == []
    assert current.status == "READY" and current.operation is not None
    assert current.operation.status == "SUCCEEDED" and current.operation.attempt == 2


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
