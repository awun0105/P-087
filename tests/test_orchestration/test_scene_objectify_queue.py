"""Tách theo vật: thử lại, dừng chờ người dùng chọn, và hàng đợi "chạy lại / dùng hộp" do worker thực hiện.

Fixture proof: provider GPU được thay bằng hàm giả; chỉ chứng minh điều phối + trạng thái, không phải
chất lượng tách vật.
"""

import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.models.contracts.reconstruction import ReconstructionBundle
from src.services.orchestration.scene import extraction as scene_extraction
from src.services.orchestration.scene import objectify as scene_objectify
from src.services.orchestration.scene import objectify_queue as scene_objectify_queue
from src.services.orchestration.scene.errors import SceneRevisionConflictError
from src.services.orchestration.scene.extraction import extract_scene
from src.services.orchestration.scene.objectify import AWAITING_CHOICE, ObjectifyError, objectify_with_retry
from src.services.orchestration.scene.objectify_queue import ObjectifyRequestError
from src.services.process_control import run_cancellable_process
from tests.test_orchestration.test_finalize_flow import _confirmed
from tests.test_orchestration.test_scene_extraction import _FIXTURE, _collision


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Job đã xác nhận hệ mét + bundle mẫu + Settings có "runtime" (file giả) trên máy này."""
    registry, job, _ = _confirmed(tmp_path)
    text = _FIXTURE.read_text(encoding="utf-8").replace("job-fixture-001", job.job_id)
    bundle = ReconstructionBundle.model_validate_json(text)
    bundle = bundle.model_copy(update={"canonical_geometry_ref": _collision(registry, job.job_id)})
    python, checkpoint = tmp_path / "python", tmp_path / "sam2.pt"
    python.write_text("")
    checkpoint.write_text("")
    settings = Settings(
        product_scene_runtime_python=python,
        product_sam2_checkpoint=checkpoint,
        product_worker_root=tmp_path / "workers",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
    )

    def enough_resources(_self, _job, *, gpu_required):  # noqa: ANN001, ANN202
        from src.services.orchestration.jobs.admission import OperationResourceProfile

        return OperationResourceProfile(
            required_gb={"vram": 0.1 if gpu_required else 0.0, "ram": 0.1, "disk": 0.1},
            danger_ratio=0.9,
            measured=True,
            gpu_required=gpu_required,
        )

    monkeypatch.setattr(scene_objectify_queue.ResourceAdmission, "operation_profile_for_job", enough_resources)
    monkeypatch.setattr(
        scene_objectify_queue.ResourceAdmission,
        "_resource_snapshot",
        lambda _: (
            {"vram": 8.0, "ram": 64.0, "disk": 1000.0},
            {"vram": 8.0, "ram": 64.0, "disk": 1000.0},
        ),
    )
    monkeypatch.setattr(
        "src.services.orchestration.jobs.admission.bound_gpu",
        lambda: SimpleNamespace(uuid="GPU-test", name="test GPU"),
    )
    monkeypatch.setattr(scene_objectify_queue, "box_candidates_require_gpu", lambda _: True)
    monkeypatch.setattr(scene_objectify_queue, "job_bundle", lambda *_: bundle)
    return registry, job, bundle, settings


def _always_fail(*_: object, **__: object) -> None:
    raise ObjectifyError("hết VRAM")


def test_retry_succeeds_on_third_attempt_with_separate_workspaces(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    seen: list[str] = []

    def flaky(_registry, _job, _bundle, _settings, workspace, _publish, **_kwargs):  # noqa: ANN001, ANN202
        seen.append(workspace.name)
        if len(seen) < 3:
            raise ObjectifyError("hết VRAM")
        return "kết quả"

    monkeypatch.setattr(scene_objectify, "objectify", flaky)

    assert objectify_with_retry(registry, job, bundle, settings, tmp_path / "w", lambda r, _: r) == "kết quả"
    assert seen == ["attempt-1", "attempt-2", "attempt-3"]


def test_retry_gives_up_after_configured_attempts(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    calls: list[int] = []

    def fail(*_: object, **__: object) -> None:
        calls.append(1)
        raise ObjectifyError("hết VRAM")

    monkeypatch.setattr(scene_objectify, "objectify", fail)

    with pytest.raises(ObjectifyError, match="sau 3 lần: hết VRAM"):
        objectify_with_retry(registry, job, bundle, settings, tmp_path / "w", lambda r, _: r)
    assert len(calls) == 3


def test_failed_objectify_publishes_environment_only_scene_awaiting_choice(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    boxes_called: list[int] = []
    monkeypatch.setattr(scene_extraction, "box_candidates", lambda *_: boxes_called.append(1))

    extract_scene(registry, job, bundle, settings, tmp_path / "work")

    scene = registry.scene.current(job.job_id).scene
    assert scene.objects == [] and scene.provenance["object_extraction"] == AWAITING_CHOICE
    assert "hết VRAM" in scene.provenance["note"]
    # Không tự lùi về hộp: đường hộp không được gọi.
    assert boxes_called == []
    state = scene_objectify_queue.state(registry, settings, job.job_id)
    assert state.awaiting_choice and not state.object_centric and state.available and state.status == "idle"


def test_user_chooses_boxes_and_worker_publishes_next_revision(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    monkeypatch.setattr(scene_extraction, "_sam2_runtime", lambda _: None)  # đường hộp → tách hình học
    monkeypatch.setattr("src.services.orchestration.jobs.stage_views.job_bundle", lambda *_: bundle)

    queued = scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")
    assert (queued.status, queued.mode, queued.base_revision) == ("queued", "boxes", "rev-001")
    with pytest.raises(ObjectifyRequestError, match="Đang có"):
        scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")

    assert scene_objectify_queue.process_next(registry, settings) is True
    assert scene_objectify_queue.process_next(registry, settings) is False

    done = scene_objectify_queue.state(registry, settings, job.job_id)
    assert (done.status, done.result_revision, done.awaiting_choice) == ("done", "rev-002", False)
    scene = registry.scene.current(job.job_id).scene
    assert len(scene.objects) == 1 and scene.provenance["object_extraction"] == "geometric_voxel_components_v1"
    assert scene.provenance["edited_from"] == "rev-001"


def test_rerun_failure_is_recorded_and_can_be_requested_again(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    monkeypatch.setattr(scene_objectify_queue, "reobjectify", _always_fail)

    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")
    scene_objectify_queue.process_next(registry, settings)

    failed = scene_objectify_queue.state(registry, settings, job.job_id)
    assert failed.status == "failed" and "hết VRAM" in (failed.error or "") and failed.awaiting_choice
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-001"
    # Lỗi rồi thì yêu cầu lại được.
    assert scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify").status == "queued"


def test_request_rejects_stale_revision_and_missing_runtime(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")

    with pytest.raises(SceneRevisionConflictError):
        scene_objectify_queue.request(registry, settings, job.job_id, "rev-009", "objectify")
    bare = settings.model_copy(update={"product_scene_runtime_python": None})
    with pytest.raises(ObjectifyRequestError, match="runtime"):
        scene_objectify_queue.request(registry, bare, job.job_id, "rev-001", "objectify")
    # Dùng hộp không cần runtime tách theo vật.
    assert scene_objectify_queue.request(registry, bare, job.job_id, "rev-001", "boxes").status == "queued"


def test_worker_restart_marks_only_orphaned_requests_failed(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")

    def crash(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(scene_objectify_queue, "reobjectify", crash)
    with pytest.raises(KeyboardInterrupt):
        scene_objectify_queue.process_next(registry, settings)
    assert scene_objectify_queue.state(registry, settings, job.job_id).status == "running"

    # Worker lease còn hạn không bị scan cùng host huỷ.
    assert scene_objectify_queue.recover_interrupted(settings) == 0
    with scene_objectify_queue._database(settings).transaction(write=True) as tx:
        record = scene_objectify_queue._read(tx, job.job_id, lock=True)
        assert record is not None
        expired = record.model_copy(update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        scene_objectify_queue._write(tx, job.job_id, expired)
    # Recovery chỉ thu hồi lease đã hết hạn; token cũ sẽ bị fencing kể cả worker còn sống.
    assert scene_objectify_queue.recover_interrupted(settings) == 1
    assert scene_objectify_queue.state(registry, settings, job.job_id).status == "failed"
    assert scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes").status == "queued"


def test_second_worker_cannot_claim_a_request_already_taken(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")

    assert scene_objectify_queue._claim(settings) is not None
    assert scene_objectify_queue._claim(settings) is None


def test_two_workers_on_same_host_atomically_claim_only_once(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    from concurrent.futures import ThreadPoolExecutor

    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")
    worker_ids = iter(("same-host:worker-a", "same-host:worker-b"))
    monkeypatch.setattr(
        scene_objectify_queue,
        "worker_identity",
        lambda: (next(worker_ids), "same-host", 12345),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: scene_objectify_queue._claim(settings), range(2)))

    assert sum(claim is not None for claim in claims) == 1


def test_resource_wait_keeps_request_checksums_and_does_not_start_geometry(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    from src.services.orchestration.jobs.admission import OperationResourceProfile

    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    queued = scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")
    with scene_objectify_queue._database(settings).transaction() as tx:
        before = scene_objectify_queue._read(tx, job.job_id)
    calls: list[str] = []
    monkeypatch.setattr(scene_objectify_queue, "use_boxes", lambda *args, **kwargs: calls.append("boxes"))
    monkeypatch.setattr(
        scene_objectify_queue.ResourceAdmission,
        "operation_profile_for_job",
        lambda _self, _job, *, gpu_required: OperationResourceProfile(
            required_gb={"vram": None, "ram": None, "disk": None},
            danger_ratio=None,
            measured=False,
            gpu_required=gpu_required,
        ),
    )

    assert scene_objectify_queue.process_next(registry, settings) is False

    with scene_objectify_queue._database(settings).transaction() as tx:
        after = scene_objectify_queue._read(tx, job.job_id)
    assert before is not None and after is not None
    assert after.status == "queued" and after.resource_wait is not None
    assert after.resource_wait.status == "waiting_resources"
    assert after.resource_wait.waiting_on == ["vram", "ram", "disk"]
    assert (after.operation_id, after.input_checksum, after.config_checksum) == (
        before.operation_id,
        before.input_checksum,
        before.config_checksum,
    )
    assert queued.base_revision == after.base_revision == "rev-001"
    assert calls == []


def test_worker_rejects_runtime_config_changed_after_request(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")
    changed = settings.model_copy(update={"product_scene_timeout_seconds": settings.product_scene_timeout_seconds + 1})
    calls: list[str] = []
    monkeypatch.setattr(scene_objectify_queue, "use_boxes", lambda *args, **kwargs: calls.append("boxes"))

    assert scene_objectify_queue.process_next(registry, changed) is True

    result = scene_objectify_queue.state(registry, settings, job.job_id)
    assert result.status == "failed"
    assert "configuration changed" in (result.error or "")
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-001"
    assert calls == []


def test_user_edit_while_boxes_compute_wins_over_stale_operation(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    monkeypatch.setattr(scene_extraction, "_sam2_runtime", lambda _: None)
    monkeypatch.setattr(scene_objectify_queue, "box_candidates_require_gpu", lambda _: False)
    monkeypatch.setattr("src.services.orchestration.jobs.stage_views.job_bundle", lambda *_: bundle)
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")

    def edit_during_geometry(_registry, _job, _bundle, _settings, _workspace, _publish, **_kwargs):  # noqa: ANN001, ANN202
        current = registry.scene.current(job.job_id).scene
        registry.scene.publish_next(
            job.job_id,
            "rev-001",
            current.model_copy(update={"provenance": {**current.provenance, "user_edit": "kept"}}),
            "user_edit",
        )
        return [], "geometric_voxel_components_v1", "mock geometry"

    monkeypatch.setattr(scene_extraction, "box_candidates", edit_during_geometry)
    assert scene_objectify_queue.process_next(registry, settings) is True

    current = registry.scene.current(job.job_id).scene
    result = scene_objectify_queue.state(registry, settings, job.job_id)
    assert current.scene_revision == "rev-002"
    assert current.provenance["user_edit"] == "kept"
    assert result.status == "failed" and "đã đổi" in (result.error or "")


def test_queued_cancel_prevents_objectify_worker_start(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    monkeypatch.setattr(
        scene_objectify_queue,
        "reobjectify",
        lambda *_args, **_kwargs: pytest.fail("cancelled queued operation must not start geometry"),
    )

    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")
    cancelled = scene_objectify_queue.cancel(registry, settings, job.job_id)

    assert cancelled.status == "cancelled" and cancelled.cancellation_requested
    assert cancelled.finished_at is not None
    assert scene_objectify_queue.process_next(registry, settings) is False


def test_running_cancel_kills_child_before_releasing_operation(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "initial")
    child_pid_path = tmp_path / "objectify-child.pid"
    entered = Event()
    releases: list[str] = []

    def blocking_reobjectify(
        _registry,
        _job_id,
        _settings,
        _workspace,
        *,
        expected_revision,
        commit_guard,
        cancel_event,
    ):  # noqa: ANN001, ANN202
        script = "import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
        with (tmp_path / "objectify-child.log").open("w") as output:
            entered.set()
            run_cancellable_process(
                [sys.executable, "-c", script, str(child_pid_path)],
                cwd=tmp_path,
                timeout_seconds=30,
                output=output,
                cancel_event=cancel_event,
            )
        pytest.fail("cancelled child must not return a completed scene")

    monkeypatch.setattr(scene_objectify_queue, "reobjectify", blocking_reobjectify)
    admission_type = scene_objectify_queue.ResourceAdmission
    release = admission_type.release_operation

    def verify_child_reaped(self, request):  # noqa: ANN001, ANN202
        assert child_pid_path.is_file()
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        releases.append(request.operation_id)
        return release(self, request)

    monkeypatch.setattr(admission_type, "release_operation", verify_child_reaped)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            scene_objectify_queue.process_next(registry, settings)
        except Exception as error:  # noqa: BLE001 - thread errors are asserted below.
            errors.append(error)

    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")
    thread = Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=5)
    deadline = time.monotonic() + 5
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_pid_path.exists(), "objectify subprocess did not start"

    requested = scene_objectify_queue.cancel(registry, settings, job.job_id)
    assert requested.status == "running" and requested.cancellation_requested
    thread.join(timeout=8)

    assert not thread.is_alive() and errors == []
    assert len(releases) == 1
    final = scene_objectify_queue.state(registry, settings, job.job_id)
    assert final.status == "cancelled" and final.result_revision is None
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-001"


def test_committed_scene_wins_over_late_cancel_request(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "initial")
    published = Event()
    return_from_operation = Event()

    def publish_then_wait(
        _registry,
        job_id,
        _settings,
        _workspace,
        *,
        expected_revision,
        commit_guard,
        cancel_event,
    ):  # noqa: ANN001, ANN202
        current = registry.scene.current(job_id).scene
        result = registry.scene.publish_next(
            job_id,
            expected_revision,
            current.model_copy(update={"provenance": {**current.provenance, "objectify": "committed"}}),
            "objectify",
            commit_guard=commit_guard,
        )
        published.set()
        assert return_from_operation.wait(timeout=5)
        return result.revision.scene.scene_revision

    monkeypatch.setattr(scene_objectify_queue, "reobjectify", publish_then_wait)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            scene_objectify_queue.process_next(registry, settings)
        except Exception as error:  # noqa: BLE001 - thread errors are asserted below.
            errors.append(error)

    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")
    thread = Thread(target=worker)
    thread.start()
    assert published.wait(timeout=5)
    requested = scene_objectify_queue.cancel(registry, settings, job.job_id)
    assert requested.status == "running" and requested.cancellation_requested
    return_from_operation.set()
    thread.join(timeout=8)

    assert not thread.is_alive() and errors == []
    final = scene_objectify_queue.state(registry, settings, job.job_id)
    assert final.status == "done" and not final.cancellation_requested
    assert final.result_revision == "rev-002"


def test_unexpected_operation_exception_is_terminal_and_releases_reservation(world, monkeypatch, tmp_path) -> None:
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "initial")

    def fail_unexpectedly(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("unexpected operation failure")

    monkeypatch.setattr(scene_objectify_queue, "reobjectify", fail_unexpectedly)
    admission_type = scene_objectify_queue.ResourceAdmission
    release = admission_type.release_operation
    released: list[str] = []

    def tracked_release(self, request):  # noqa: ANN001, ANN202
        released.append(request.operation_id)
        return release(self, request)

    monkeypatch.setattr(admission_type, "release_operation", tracked_release)
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")

    assert scene_objectify_queue.process_next(registry, settings) is True

    final = scene_objectify_queue.state(registry, settings, job.job_id)
    assert final.status == "failed" and "unexpected operation failure" in (final.error or "")
    assert len(released) == 1


def test_expired_lease_late_worker_cannot_commit_or_overwrite_new_attempt(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")
    claimed = scene_objectify_queue._claim(settings)
    assert claimed is not None
    job_id, old_lease = claimed

    with scene_objectify_queue._database(settings).transaction(write=True) as tx:
        current = scene_objectify_queue._read(tx, job_id, lock=True)
        assert current is not None
        scene_objectify_queue._write(
            tx,
            job_id,
            current.model_copy(update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
        )
    assert scene_objectify_queue.recover_interrupted(settings) == 1

    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")
    second_claim = scene_objectify_queue._claim(settings)
    assert second_claim is not None
    _, new_lease = second_claim
    assert new_lease.lease_generation == old_lease.lease_generation + 1
    assert new_lease.lease_token != old_lease.lease_token

    old_guard = lambda tx: scene_objectify_queue._lease_is_current(  # noqa: E731
        tx, job_id, old_lease.lease_token or "", old_lease.lease_generation
    )
    current_scene = registry.scene.current(job.job_id).scene
    with pytest.raises(SceneRevisionConflictError):
        registry.scene.publish_next(
            job.job_id,
            "rev-001",
            current_scene.model_copy(update={"provenance": {**current_scene.provenance, "late": True}}),
            "late_objectify",
            commit_guard=old_guard,
        )
    assert not scene_objectify_queue._finish(
        settings,
        job_id,
        old_lease,
        {"status": "done", "result_revision": "rev-002"},
    )
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-001"
    with scene_objectify_queue._database(settings).transaction() as tx:
        latest = scene_objectify_queue._read(tx, job_id)
    assert latest is not None and latest.status == "running" and latest.lease_token == new_lease.lease_token


def test_api_and_worker_on_different_machines_share_requests_and_revisions(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """Hai máy: đĩa artifact và workspace riêng, chỉ chung DB runtime + kho file (ADR 0003)."""
    from src.services.orchestration.artifacts import ArtifactRemote, ArtifactResolver
    from src.services.orchestration.scene.editor import SceneEditor
    from tests.test_orchestration.memory_object_store import MemoryObjectStore

    worker_registry, job, bundle, settings = world
    remote = ArtifactRemote(MemoryObjectStore())
    worker_registry.runtime_resolver.remote = remote
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(worker_registry, job, bundle, settings, tmp_path / "work")
    worker_registry.runtime_resolver.sync_up(job.job_id)

    # "Máy API": đĩa trống, không có runtime GPU, không thấy workspace của worker.
    api_resolver = ArtifactResolver(tmp_path / "api-disk", remote)
    from src.services.orchestration.scene.heads import SceneHeadRepository

    head_repository = SceneHeadRepository(worker_registry.persistence.database)
    api_scene = SceneEditor(worker_registry.scene.fixture_scene_path.parents[1], api_resolver, head_repository)
    api_settings = settings.model_copy(
        update={
            "product_scene_runtime_python": None,
            "product_worker_root": tmp_path / "api-workers",
            "product_objectify_remote_worker": True,
        }
    )
    assert api_scene.current(job.job_id).scene.scene_revision == "rev-001"  # tải từ kho file
    monkeypatch.setattr(worker_registry, "scene", api_scene)  # API đọc scene qua đĩa của chính nó
    queued = scene_objectify_queue.request(worker_registry, api_settings, job.job_id, "rev-001", "boxes")
    assert queued.status == "queued" and queued.available

    # "Máy worker": nhận yêu cầu từ DB, dựng hộp, đẩy revision mới lên kho file.
    worker_scene = SceneEditor(
        api_scene.fixture_scene_path.parents[1], worker_registry.runtime_resolver, head_repository
    )
    monkeypatch.setattr(worker_registry, "scene", worker_scene)
    monkeypatch.setattr(scene_extraction, "_sam2_runtime", lambda _: None)
    monkeypatch.setattr("src.services.orchestration.jobs.stage_views.job_bundle", lambda *_: bundle)
    monkeypatch.setattr(scene_objectify_queue, "box_candidates_require_gpu", lambda _: False)
    assert scene_objectify_queue.process_next(worker_registry, settings) is True

    # API thấy kết quả mà không cần chung đĩa hay khởi động lại.
    monkeypatch.setattr(worker_registry, "scene", api_scene)
    done = scene_objectify_queue.state(worker_registry, api_settings, job.job_id)
    assert (done.status, done.result_revision) == ("done", "rev-002")
    assert api_scene.current(job.job_id).scene.scene_revision == "rev-002"
    assert not (tmp_path / "api-workers").exists()


def test_api_process_sees_revision_published_by_another_process(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    from src.services.orchestration.scene.editor import SceneEditor

    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    other = SceneEditor(registry.scene.fixture_scene_path.parents[1], registry.runtime_resolver)
    assert other.current(job.job_id).scene.scene_revision == "rev-001"
    monkeypatch.setattr(scene_extraction, "_sam2_runtime", lambda _: None)
    monkeypatch.setattr("src.services.orchestration.jobs.stage_views.job_bundle", lambda *_: bundle)

    scene_extraction.use_boxes(registry, job.job_id, settings, tmp_path / "boxes")

    # `other` đã giữ rev-001 trong bộ nhớ; lần đọc kế tiếp phải thấy rev-002 trên đĩa.
    assert other.current(job.job_id).scene.scene_revision == "rev-002"


def test_reobjectify_binds_source_collision_ownership_to_the_new_objects(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """New object-centric candidates must own their source region, or confirming them breaks the export."""
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "_sam2_runtime", lambda _: None)
    monkeypatch.setattr("src.services.orchestration.jobs.stage_views.job_bundle", lambda *_: bundle)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    first = registry.scene.current(job.job_id).scene
    (box_object,) = first.objects
    assert box_object.source_collision is not None
    replaced = box_object.model_copy(
        update={
            "id": "candidate-007",
            "local_frame": "candidate-007",
            "transform": box_object.transform.model_copy(update={"local_frame": "candidate-007"}),
            "source_collision": None,
            "collider": None,
        },
        deep=True,
    )
    monkeypatch.setattr(
        scene_objectify,
        "objectify_with_retry",
        lambda *_, **__: scene_objectify.ObjectifyResult(
            first.environment, [replaced], {"object_extraction": "sampro3d"}
        ),
    )

    revision = scene_objectify.reobjectify(
        registry, job.job_id, settings, tmp_path / "again", expected_revision="rev-001"
    )

    scene = registry.scene.revision(job.job_id, revision).scene
    (new_object,) = scene.objects
    ownership = new_object.source_collision
    assert ownership is not None and ownership.object_id == "candidate-007"
    assert ownership.extraction_revision == "rev-001"
    assert ownership.source_geometry_ref == scene.environment.geometry_ref
    assert ownership.source_transform.translation_xyz == new_object.transform.translation_xyz
