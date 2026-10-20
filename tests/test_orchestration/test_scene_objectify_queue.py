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

import numpy as np
import pytest

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import ReconstructionBundle
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.processing.observed import processing_seconds
from src.services.orchestration.processing.telemetry import ResourceSampler, ResourceUsage
from src.services.orchestration.scene import extraction as scene_extraction
from src.services.orchestration.scene import objectify as scene_objectify
from src.services.orchestration.scene import objectify_queue as scene_objectify_queue
from src.services.orchestration.scene.errors import SceneRevisionConflictError
from src.services.orchestration.scene.extraction import extract_scene
from src.services.orchestration.scene.floor_evidence import load_floor_fit_evidence
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


def test_floor_failure_keeps_evidence_and_stops_retries(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    x, y = np.meshgrid(np.linspace(-2, 2, 30), np.linspace(-2, 2, 30))
    rows = np.zeros(x.size, dtype=[(name, "<f4") for name in ("x", "y", "z", "opacity", "scale_0", "rot_0", "f_dc_0")])
    rows["x"], rows["y"] = x.ravel(), y.ravel()
    rows["z"] = np.random.default_rng(19).normal(0, 0.05, x.size)
    payload = scene_objectify.gaussian_split.write_gaussian_ply(rows)
    ref = ProductArtifactRef(
        artifact_type="GaussianPLY",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job.job_id}/rec06/test/visual.ply",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.VISUAL_RECON,
        job_id=job.job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(ref, payload)
    monkeypatch.setattr(scene_objectify, "metric_visual_master", lambda *_: ref)
    view = SimpleNamespace(center=(0, 0, 1), image=ref, model_dump=lambda **_: {})
    monkeypatch.setattr(scene_objectify, "camera_views", lambda *_: [view])
    workspace = tmp_path / "work"

    extract_scene(registry, job, bundle, settings, workspace)

    scene = registry.scene.current(job.job_id).scene
    fit = scene.provenance["floor_fit"]
    evidence = load_floor_fit_evidence(
        ProductArtifactRef.model_validate(fit["artifact_ref"]),
        registry.runtime_resolver.require,
        expected_source_artifact_ref=ref,
    )
    assert evidence.floor_model.fallback_reason == "excessive_noise"
    assert scene.objects == []
    assert "vượt ngưỡng" in scene.provenance["note"]
    assert not (workspace / "objectify/attempt-2").exists()
    state = scene_objectify_queue.state(registry, settings, job.job_id)
    assert state.retryable is False and state.floor_fit == fit
    with pytest.raises(ObjectifyRequestError, match="Dữ liệu"):
        scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")
    assert scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes").status == "queued"


def test_rerun_records_non_retryable_floor_failure_without_changing_scene(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")

    def fail(*args: object, **kwargs: object) -> None:
        raise ObjectifyError("mặt sàn chưa đủ tin cậy", retryable=False, floor_fit={"status": "uncertain"})

    monkeypatch.setattr(scene_objectify_queue, "reobjectify", fail)
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")
    scene_objectify_queue.process_next(registry, settings)
    state = scene_objectify_queue.state(registry, settings, job.job_id)
    assert state.status == "failed" and state.retryable is False
    assert state.floor_fit == {"status": "uncertain"}
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-001"
    with pytest.raises(ObjectifyRequestError, match="Dữ liệu"):
        scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "objectify")


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


def test_uncertain_box_floor_does_not_publish_an_empty_success_revision(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    monkeypatch.setattr("src.services.orchestration.jobs.stage_views.job_bundle", lambda *_: bundle)
    monkeypatch.setattr(
        scene_extraction,
        "box_candidates",
        lambda *args, **kwargs: (
            [],
            "geometric_voxel_components_v1",
            "floor fit uncertain",
            {"status": "uncertain", "fallback_reason": "excessive_noise"},
        ),
    )
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")

    assert scene_objectify_queue.process_next(registry, settings) is True

    state = scene_objectify_queue.state(registry, settings, job.job_id)
    assert state.status == "failed" and state.result_revision is None
    assert state.floor_fit["fallback_reason"] == "excessive_noise"
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-001"


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
        return [], "geometric_voxel_components_v1", "mock geometry", None

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


@pytest.mark.parametrize("finish", ["success", "quality_failure", "queued_cancel", "running_cancel", "stale"])
def test_membership_queue_reuses_admission_revision_fence_and_cancellation(world, monkeypatch, tmp_path, finish):
    from src.models.contracts.object_membership import ObjectMembershipReassignCommand
    from src.services.process_control import ProcessCancelledError

    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    initial = registry.scene.current(job.job_id).scene
    reference = initial.environment.geometry_ref.model_copy(update={"artifact_type": "ObjectAwareEnvironmentManifest"})
    from src.models.contracts.coordinates import CoordinateSystem
    from src.models.contracts.object_membership import ObjectMembershipArtifact

    membership = ObjectMembershipArtifact(
        source_visual_ref=initial.environment.geometry_ref.model_copy(update={"artifact_type": "GaussianPLY"}),
        source_geometry_ref=initial.environment.geometry_ref,
        labels_ref=initial.environment.geometry_ref.model_copy(update={"artifact_type": "ObjectMembershipLabels"}),
        gaussian_count=5,
        label_to_object_id={"0": "object-a", "1": "object-b"},
        coordinate_system=CoordinateSystem(),
        extraction_revision=initial.scene_revision,
    )
    draft = initial.model_copy(
        update={
            "environment": initial.environment.model_copy(
                update={
                    "object_aware_collision_ref": reference,
                    "membership": membership,
                    "collider_ref": initial.environment.geometry_ref,
                }
            )
        }
    )
    base = registry.scene.publish_next(job.job_id, initial.scene_revision, draft, "fixture").revision.scene
    command = ObjectMembershipReassignCommand(
        expected_scene_revision=base.scene_revision,
        membership_checksum="sha256:" + "a" * 64,
        source_visual_checksum="sha256:" + "b" * 64,
        source_gaussian_indices=[1, 3],
        source_object_id="object-a",
        target_object_id="object-b",
    )
    monkeypatch.setattr(scene_objectify_queue, "preview_correction", lambda *a: {})
    calls = []

    def operation(
        registry,
        job_id,
        settings,
        workspace,
        *,
        command,
        actor_id,
        expected_revision,
        commit_guard,
        cancel_event,
        progress,
    ):
        calls.append(command)
        assert actor_id == "fixture-user"
        progress("surface_quality")
        assert scene_objectify_queue.state(registry, settings, job_id).phase == "surface_quality"
        if finish == "quality_failure":
            raise ValueError("surface quality gate failed")
        if finish == "running_cancel":
            scene_objectify_queue.cancel(registry, settings, job_id)
            # The CAS guard must reject even before the polling thread notices.
            with pytest.raises(SceneRevisionConflictError):
                registry.scene.publish_next(job_id, expected_revision, base, "correction", commit_guard=commit_guard)
            raise ProcessCancelledError("cancelled")
        return registry.scene.publish_next(
            job_id, expected_revision, base, "correction", commit_guard=commit_guard
        ).revision.scene.scene_revision

    monkeypatch.setattr(scene_objectify_queue, "regenerate_membership", operation)
    accepted = scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "membership", correction=command, actor_id="fixture-user"
    )
    assert accepted.mode == "membership" and accepted.status == "queued"
    with pytest.raises(ObjectifyRequestError, match="operation changed"):
        scene_objectify_queue.cancel(registry, settings, job.job_id, expected_operation_id="old-operation")
    assert scene_objectify_queue.state(registry, settings, job.job_id).status == "queued"

    with pytest.raises(ObjectifyRequestError):
        scene_objectify_queue.request(
            registry,
            settings,
            job.job_id,
            base.scene_revision,
            "membership",
            correction=command,
            actor_id="fixture-user",
        )
    if finish == "queued_cancel":
        scene_objectify_queue.cancel(registry, settings, job.job_id)
    elif finish == "stale":
        registry.scene.publish_next(job.job_id, base.scene_revision, base, "concurrent-edit")
    scene_objectify_queue.process_next(registry, settings)
    state = scene_objectify_queue.state(registry, settings, job.job_id)
    if finish == "success":
        assert state.status == "done" and state.result_revision != base.scene_revision
    else:
        assert state.status == ("cancelled" if "cancel" in finish else "failed")
        assert state.result_revision is None
        assert registry.scene.current(job.job_id).scene.environment == base.environment
    assert len(calls) == (0 if finish in {"queued_cancel", "stale"} else 1)
    # Repeating a failed or cancelled correction uses a new durable operation.
    if finish in {"quality_failure", "queued_cancel", "running_cancel"}:
        assert (
            scene_objectify_queue.request(
                registry,
                settings,
                job.job_id,
                base.scene_revision,
                "membership",
                correction=command,
                actor_id="fixture-user",
            ).status
            == "queued"
        )


def _geometry_draft(world, monkeypatch, tmp_path):  # noqa: ANN001, ANN202
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "geometry-source")
    current = registry.scene.current(job.job_id).scene
    draft = current.model_copy(
        update={"provenance": {**current.provenance, "object_geometry": "awaiting_review", "geometry_method": "shell"}}
    )
    return registry.scene.publish_next(job.job_id, current.scene_revision, draft, "fixture-draft").revision.scene


def test_geometry_request_freezes_draft_and_excludes_other_modes(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base = _geometry_draft(world, monkeypatch, tmp_path)
    # Geometry needs no SAM2 checkpoint; it uses the existing scene membership.
    settings = settings.model_copy(update={"product_sam2_checkpoint": None})
    queued = scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "geometry", actor_id="local"
    )
    assert queued.status == "queued" and queued.mode == "geometry"
    assert queued.base_revision == base.scene_revision and queued.operation_id
    assert queued.phase is None
    with pytest.raises(ObjectifyRequestError):
        scene_objectify_queue.request(registry, settings, job.job_id, base.scene_revision, "boxes")
    with pytest.raises(SceneRevisionConflictError):
        scene_objectify_queue.request(registry, settings, job.job_id, "rev-stale", "geometry")


def test_geometry_request_rejects_ready_scene(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "ready")
    current = registry.scene.current(job.job_id).scene
    with pytest.raises(ObjectifyRequestError, match="Scene đã có hình học; dùng chỉnh vùng để dựng lại vật."):
        scene_objectify_queue.request(registry, settings, job.job_id, current.scene_revision, "geometry")


@pytest.mark.parametrize(
    "finish", ["success", "failure", "queued_cancel", "running_cancel", "stale", "lease_lost", "resource_wait"]
)
def test_geometry_worker_reuses_progress_cancellation_and_fences(world, monkeypatch, tmp_path, finish) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base = _geometry_draft(world, monkeypatch, tmp_path)
    phases = []
    calls = []
    profiles = []
    previous_profile = scene_objectify_queue.ResourceAdmission.operation_profile_for_job

    def profile(self, current_job, *, gpu_required):  # noqa: ANN001, ANN202
        profiles.append(gpu_required)
        return previous_profile(self, current_job, gpu_required=gpu_required)

    monkeypatch.setattr(scene_objectify_queue.ResourceAdmission, "operation_profile_for_job", profile)
    monkeypatch.setattr(scene_objectify_queue, "box_candidates_require_gpu", lambda _: False)

    def operation(registry, settings, job_id, *, expected_revision, workspace, commit_guard, cancel_event, progress):  # noqa: ANN001, ANN202
        from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError
        from src.services.process_control import ProcessCancelledError

        calls.append(expected_revision)
        assert isinstance(cancel_event, Event)
        for phase in ["shell", "quality", "collider", "environment", "publish"]:
            progress(phase)
            phases.append(scene_objectify_queue.state(registry, settings, job_id).phase)
        if finish == "failure":
            raise ObjectGeometryBuildError(
                "Vỏ của Ghế 1 không dựng được: QA failed", object_id="chair", retryable=False
            )
        if finish == "running_cancel":
            scene_objectify_queue.cancel(registry, settings, job_id, expected_operation_id=accepted.operation_id)
            with pytest.raises(SceneRevisionConflictError):
                registry.scene.publish_next(job_id, expected_revision, base, "geometry", commit_guard=commit_guard)
            # The polling thread also forwards durable cancellation to the service event.
            assert cancel_event.wait(3)
            raise ProcessCancelledError("cancelled")
        if finish == "lease_lost":
            with scene_objectify_queue._database(settings).transaction(write=True) as tx:
                record = scene_objectify_queue._read(tx, job_id)
                scene_objectify_queue._write(
                    tx, job_id, record.model_copy(update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)})
                )
            with pytest.raises(SceneRevisionConflictError):
                registry.scene.publish_next(job_id, expected_revision, base, "geometry", commit_guard=commit_guard)
            raise ProcessCancelledError("lease lost")
        ready = base.model_copy(update={"provenance": {**base.provenance, "object_geometry": "ready"}})
        return registry.scene.publish_next(
            job_id, expected_revision, ready, "geometry", commit_guard=commit_guard
        ).revision.scene.scene_revision

    monkeypatch.setattr(scene_objectify_queue, "build_object_geometry", operation, raising=False)
    accepted = scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "geometry", actor_id="fixture-user"
    )
    if finish == "queued_cancel":
        scene_objectify_queue.cancel(registry, settings, job.job_id, expected_operation_id=accepted.operation_id)
    elif finish == "stale":
        registry.scene.publish_next(job.job_id, base.scene_revision, base, "concurrent-edit")
    elif finish == "resource_wait":
        monkeypatch.setattr(
            scene_objectify_queue.ResourceAdmission,
            "_resource_snapshot",
            lambda _: ({"vram": 0.0, "ram": 64.0, "disk": 1000.0}, {"vram": 8.0, "ram": 64.0, "disk": 1000.0}),
        )
    scene_objectify_queue.process_next(registry, settings)
    if finish == "lease_lost":
        scene_objectify_queue.recover_interrupted(settings)
    state = scene_objectify_queue.state(registry, settings, job.job_id)
    current = registry.scene.current(job.job_id).scene
    if finish == "success":
        assert state.status == "done" and state.result_revision == current.scene_revision != base.scene_revision
        assert current.provenance["object_geometry"] == "ready"
        assert phases == ["shell", "quality", "collider", "environment", "publish"]
    elif finish == "resource_wait":
        assert state.status == "queued" and state.resource_wait is not None
        assert state.operation_id == accepted.operation_id
        assert not calls
    elif finish in {"queued_cancel", "running_cancel"}:
        assert state.status == "cancelled" and state.result_revision is None
        assert current.scene_revision == base.scene_revision
    else:
        assert state.status == "failed" and state.result_revision is None
        if finish == "failure":
            assert "Ghế 1" in state.error and state.retryable is False
            assert current == base
            # A new request can run after the user has corrected the input.
            monkeypatch.setattr(
                scene_objectify_queue,
                "build_object_geometry",
                lambda registry, settings, job_id, **kwargs: (
                    registry.scene.publish_next(
                        job_id,
                        kwargs["expected_revision"],
                        base.model_copy(update={"provenance": {**base.provenance, "object_geometry": "ready"}}),
                        "retry",
                        commit_guard=kwargs["commit_guard"],
                    ).revision.scene.scene_revision
                ),
            )
            retry = scene_objectify_queue.request(registry, settings, job.job_id, base.scene_revision, "geometry")
            assert retry.operation_id != accepted.operation_id
            scene_objectify_queue.process_next(registry, settings)
            assert scene_objectify_queue.state(registry, settings, job.job_id).status == "done"
    if finish not in {"queued_cancel", "stale"}:
        assert profiles and all(profiles)


def _ready_region_request(world, monkeypatch, tmp_path):
    from src.models.contracts.object_membership import ObjectRegionCommand

    registry, job, _, settings = world
    base = _geometry_draft(world, monkeypatch, tmp_path)
    base = registry.scene.publish_next(
        job.job_id,
        base.scene_revision,
        base.model_copy(update={"provenance": {**base.provenance, "object_geometry": "ready"}}),
        "fixture-ready",
    ).revision.scene
    command = ObjectRegionCommand(
        expected_scene_revision=base.scene_revision,
        membership_checksum="sha256:" + "a" * 64,
        boxes=[{"op": "add", "center_m": [0, 0, 0], "half_extents_m": [1, 1, 1], "yaw_rad": 0}],
    )
    monkeypatch.setattr(scene_objectify_queue, "validate_region_rebuild", lambda *a: None)
    return base, command


@pytest.mark.parametrize(
    "finish",
    ["success", "queued_cancel", "running_cancel", "stale", "failure", "tampered", "resource_wait", "lease_lost"],
)
def test_region_queue_durable_command_progress_and_fencing(world, monkeypatch, tmp_path, finish):
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError
    from src.services.process_control import ProcessCancelledError

    registry, job, _, settings = world
    base, command = _ready_region_request(world, monkeypatch, tmp_path)
    calls = []
    profiles = []
    profile = scene_objectify_queue.ResourceAdmission.operation_profile_for_job

    def resources(self, job, *, gpu_required):
        profiles.append(gpu_required)
        return profile(self, job, gpu_required=gpu_required)

    monkeypatch.setattr(scene_objectify_queue.ResourceAdmission, "operation_profile_for_job", resources)

    def operation(
        registry_arg,
        settings_arg,
        job_id,
        workspace,
        *,
        object_id,
        command,
        actor_id,
        expected_revision,
        progress,
        commit_guard,
        cancel_event,
    ):
        calls.append(command)
        assert object_id == "object-a" and actor_id == "reviewer"
        for phase in ("shell", "quality", "collider", "environment", "publish"):
            progress(phase)
            assert scene_objectify_queue.state(registry, settings, job_id).phase == phase
        if finish == "failure":
            raise ObjectGeometryBuildError("Object A: shell failed", object_id=object_id, retryable=False)
        if finish == "running_cancel":
            scene_objectify_queue.cancel(registry, settings, job_id)
            with pytest.raises(SceneRevisionConflictError):
                registry.scene.publish_next(job_id, expected_revision, base, "region", commit_guard=commit_guard)
            assert cancel_event.wait(3)
            raise ProcessCancelledError("cancelled")
        if finish == "lease_lost":
            with scene_objectify_queue._database(settings).transaction(write=True) as tx:
                record = scene_objectify_queue._read(tx, job_id)
                scene_objectify_queue._write(
                    tx, job_id, record.model_copy(update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)})
                )
            with pytest.raises(SceneRevisionConflictError):
                registry.scene.publish_next(job_id, expected_revision, base, "region", commit_guard=commit_guard)
            raise ProcessCancelledError("lost lease")
        return registry.scene.publish_next(
            job_id, expected_revision, base, "region", commit_guard=commit_guard
        ).revision.scene.scene_revision

    monkeypatch.setattr(scene_objectify_queue, "rebuild_region_ready", operation)
    queued = scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "region", region=("object-a", command), actor_id="reviewer"
    )
    assert queued.mode == "region" and queued.status == "queued"
    with scene_objectify_queue._database(settings).transaction() as tx:
        record = scene_objectify_queue._read(tx, job.job_id)
        assert record.region_command == command and record.region_object_id == "object-a"
        assert record.actor_id == "reviewer"
    with pytest.raises(ObjectifyRequestError):
        scene_objectify_queue.request(registry, settings, job.job_id, base.scene_revision, "boxes")
    if finish == "queued_cancel":
        scene_objectify_queue.cancel(registry, settings, job.job_id, expected_operation_id=queued.operation_id)
    elif finish == "stale":
        registry.scene.publish_next(job.job_id, base.scene_revision, base, "concurrent")
    elif finish == "tampered":
        with scene_objectify_queue._database(settings).transaction(write=True) as tx:
            record = scene_objectify_queue._read(tx, job.job_id)
            scene_objectify_queue._write(tx, job.job_id, record.model_copy(update={"region_object_id": "object-b"}))
    elif finish == "resource_wait":
        monkeypatch.setattr(
            scene_objectify_queue.ResourceAdmission,
            "_resource_snapshot",
            lambda _: ({"vram": 0.0, "ram": 64.0, "disk": 1000.0}, {"vram": 8.0, "ram": 64.0, "disk": 1000.0}),
        )
    scene_objectify_queue.process_next(registry, settings)
    if finish == "lease_lost":
        scene_objectify_queue.recover_interrupted(settings)
    state = scene_objectify_queue.state(registry, settings, job.job_id)
    if finish == "success":
        assert state.status == "done" and state.result_revision != base.scene_revision
    elif finish == "resource_wait":
        assert state.status == "queued" and state.resource_wait is not None and not calls
    else:
        assert state.status == ("cancelled" if "cancel" in finish else "failed")
        assert state.result_revision is None
        if finish != "stale":
            assert registry.scene.current(job.job_id).scene == base
        if finish == "failure":
            assert state.retryable is False and "shell failed" in state.error
    assert len(calls) == (0 if finish in {"queued_cancel", "stale", "tampered", "resource_wait"} else 1)
    if calls:
        assert calls == [command] and profiles == [True]


def test_membership_queue_accepts_ready_shell_without_objectgs_marker(world, monkeypatch, tmp_path):
    from src.models.contracts.object_membership import ObjectMembershipReassignCommand

    registry, job, _, settings = world
    base, _ = _ready_region_request(world, monkeypatch, tmp_path)
    assert base.environment.object_aware_collision_ref is None
    command = ObjectMembershipReassignCommand(
        expected_scene_revision=base.scene_revision,
        membership_checksum="sha256:" + "a" * 64,
        source_visual_checksum="sha256:" + "b" * 64,
        source_gaussian_indices=[0],
        source_object_id="a",
        target_object_id="b",
    )
    monkeypatch.setattr(scene_objectify_queue, "preview_correction", lambda *a: {})
    queued = scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "membership", correction=command, actor_id="reviewer"
    )
    assert queued.status == "queued" and queued.mode == "membership"


def test_state_reports_object_geometry_for_the_ui(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """T-021: ready, awaiting_review; a missing key is the legacy flow (None); an unknown value re-locks as awaiting_review."""
    registry, job, _, settings = world
    _geometry_draft(world, monkeypatch, tmp_path)
    assert scene_objectify_queue.state(registry, settings, job.job_id).object_geometry == "awaiting_review"
    for extra, expected in [
        ({"object_geometry": "ready"}, "ready"),
        ({"object_geometry": "building"}, "awaiting_review"),
    ]:
        current = registry.scene.current(job.job_id).scene
        provenance = {**current.provenance, **extra}
        registry.scene.publish_next(
            job.job_id, current.scene_revision, current.model_copy(update={"provenance": provenance}), "fixture-state"
        )
        assert scene_objectify_queue.state(registry, settings, job.job_id).object_geometry == expected
    current = registry.scene.current(job.job_id).scene
    provenance = {k: v for k, v in current.provenance.items() if k != "object_geometry"}
    registry.scene.publish_next(
        job.job_id, current.scene_revision, current.model_copy(update={"provenance": provenance}), "fixture-legacy"
    )
    assert scene_objectify_queue.state(registry, settings, job.job_id).object_geometry is None


@pytest.mark.parametrize(
    ("geometry", "record", "expected"),
    [
        (None, None, None),
        (None, ("running", "geometry", "rev-001"), None),
        ("awaiting_review", None, "waiting"),
        ("awaiting_review", ("queued", "geometry", "rev-001"), "running"),
        ("awaiting_review", ("running", "geometry", "rev-001"), "running"),
        ("awaiting_review", ("failed", "geometry", "rev-001"), "failed"),
        ("awaiting_review", ("cancelled", "geometry", "rev-001"), "failed"),
        ("awaiting_review", ("failed", "geometry", "rev-000"), "waiting"),
        ("awaiting_review", ("running", "objectify", "rev-001"), "waiting"),
        ("ready", None, None),
        ("ready", ("running", "region", "rev-001"), "running"),
        ("ready", ("running", "membership", "rev-001"), "running"),
        ("ready", ("failed", "region", "rev-001"), None),
    ],
)
def test_geometry_review_for_the_scene_list(world, geometry, record, expected) -> None:  # noqa: ANN001
    """Danh sách scene dùng cùng quy tắc với hàng "Duyệt vật & Tạo mesh": Draft chờ/lỗi, đang dựng; Ready và scene cũ: None."""
    _, job, _, settings = world
    if record is not None:
        status, mode, base = record
        with scene_objectify_queue._database(settings).transaction(write=True) as tx:
            scene_objectify_queue._write(
                tx,
                job.job_id,
                scene_objectify_queue._Record(
                    status=status, mode=mode, base_revision=base, requested_at=datetime.now(UTC)
                ),
            )
    assert scene_objectify_queue.geometry_review(settings, job.job_id, geometry, "rev-001") == expected


def _scene_usages(settings: Settings) -> list[ResourceUsage]:
    with scene_objectify_queue._database(settings).transaction() as tx:
        rows = tx.execute("SELECT payload FROM r2s_resource_usage").fetchall()
    return [ResourceUsage.model_validate_json(row[0]) for row in rows]


def _region_stub(registry, base, finish):  # noqa: ANN001, ANN202
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError
    from src.services.process_control import ProcessCancelledError

    def operation(  # noqa: ANN202
        registry_arg,
        settings_arg,
        job_id,
        workspace,
        *,
        object_id,
        command,
        actor_id,
        expected_revision,
        progress,
        commit_guard,
        cancel_event,
    ):
        time.sleep(0.05)  # bảo đảm duration_seconds > 0 với sampler thật
        if finish == "failure":
            raise ObjectGeometryBuildError("Object A: shell failed", object_id=object_id, retryable=False)
        if finish == "cancelled":
            raise ProcessCancelledError("cancelled")
        return registry.scene.publish_next(
            job_id, expected_revision, base, "region", commit_guard=commit_guard
        ).revision.scene.scene_revision

    return operation


@pytest.mark.parametrize(
    ("finish", "expected"), [("success", "completed"), ("failure", "failed"), ("cancelled", "cancelled")]
)
def test_region_run_records_one_scene_usage_with_its_outcome(world, monkeypatch, tmp_path, finish, expected) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base, command = _ready_region_request(world, monkeypatch, tmp_path)
    monkeypatch.setattr(scene_objectify_queue, "rebuild_region_ready", _region_stub(registry, base, finish))
    queued = scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "region", region=("object-a", command), actor_id="reviewer"
    )
    assert scene_objectify_queue.process_next(registry, settings) is True
    usages = _scene_usages(settings)
    assert [(u.tool, u.outcome, u.attempt_id, u.job_id) for u in usages] == [
        ("scene.region", expected, queued.operation_id, job.job_id)
    ]
    assert usages[0].duration_seconds > 0
    expected_seconds = {job.job_id: usages[0].duration_seconds} if expected == "completed" else {}
    assert processing_seconds(usages) == expected_seconds


def test_sampler_failures_never_change_the_region_result(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base, command = _ready_region_request(world, monkeypatch, tmp_path)
    monkeypatch.setattr(scene_objectify_queue, "rebuild_region_ready", _region_stub(registry, base, "success"))

    def broken_sample(self, root):  # noqa: ANN001, ANN202
        raise RuntimeError("probe unavailable")

    monkeypatch.setattr(ResourceSampler, "sample", broken_sample)
    scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "region", region=("object-a", command), actor_id="reviewer"
    )
    scene_objectify_queue.process_next(registry, settings)
    state = scene_objectify_queue.state(registry, settings, job.job_id)
    assert state.status == "done" and state.result_revision is not None


def test_geometry_build_records_one_scene_geometry_usage(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base = _geometry_draft(world, monkeypatch, tmp_path)
    monkeypatch.setattr(scene_objectify_queue, "box_candidates_require_gpu", lambda _: False)

    def operation(
        registry_arg, settings_arg, job_id, *, expected_revision, workspace, commit_guard, cancel_event, progress
    ):  # noqa: ANN001, ANN202
        time.sleep(0.05)  # bảo đảm duration_seconds > 0 với sampler thật
        ready = base.model_copy(update={"provenance": {**base.provenance, "object_geometry": "ready"}})
        return registry.scene.publish_next(
            job_id, expected_revision, ready, "geometry", commit_guard=commit_guard
        ).revision.scene.scene_revision

    monkeypatch.setattr(scene_objectify_queue, "build_object_geometry", operation, raising=False)
    accepted = scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "geometry", actor_id="fixture-user"
    )
    assert scene_objectify_queue.process_next(registry, settings) is True
    usages = _scene_usages(settings)
    assert [(u.tool, u.outcome, u.attempt_id) for u in usages] == [
        ("scene.geometry", "completed", accepted.operation_id)
    ]
    assert usages[0].duration_seconds > 0


def test_missing_sampler_still_publishes_and_records_nothing(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base, command = _ready_region_request(world, monkeypatch, tmp_path)
    monkeypatch.setattr(scene_objectify_queue, "rebuild_region_ready", _region_stub(registry, base, "success"))
    monkeypatch.setattr(scene_objectify_queue, "build_sampler", lambda *args: None)
    scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "region", region=("object-a", command), actor_id="reviewer"
    )
    scene_objectify_queue.process_next(registry, settings)
    assert scene_objectify_queue.state(registry, settings, job.job_id).status == "done"
    assert _scene_usages(settings) == []


def _scene_requests(settings: Settings, job_id: str) -> list:
    from src.services.orchestration.jobs.database import RuntimeDatabase
    from src.services.orchestration.value import list_events

    return list_events(RuntimeDatabase(settings.database_url), job_id, {"scene_request"})


def test_geometry_request_records_one_human_scene_request(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base = _geometry_draft(world, monkeypatch, tmp_path)
    settings = settings.model_copy(update={"product_sam2_checkpoint": None})

    queued = scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "geometry", actor_id="local"
    )

    (event,) = _scene_requests(settings, job.job_id)
    assert event.actor_id == "local"
    assert event.payload == {
        "mode": "geometry",
        "base_revision": base.scene_revision,
        "operation_id": queued.operation_id,
        "origin": "human",
    }


def test_boxes_request_records_one_human_scene_request(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "boxes")
    current = registry.scene.current(job.job_id).scene

    scene_objectify_queue.request(registry, settings, job.job_id, current.scene_revision, "boxes")

    (event,) = _scene_requests(settings, job.job_id)
    assert event.payload["mode"] == "boxes" and event.payload["origin"] == "human"


def test_region_request_records_one_human_scene_request(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base, command = _ready_region_request(world, monkeypatch, tmp_path)

    scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "region", region=("object-a", command), actor_id="reviewer"
    )

    (event,) = _scene_requests(settings, job.job_id)
    assert event.actor_id == "reviewer"
    assert event.payload["mode"] == "region"
    assert event.payload["region_object_id"] == "object-a"
    assert event.payload["origin"] == "human"


def test_membership_request_records_one_human_scene_request(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    from src.models.contracts.object_membership import ObjectMembershipReassignCommand

    registry, job, _, settings = world
    base, _ = _ready_region_request(world, monkeypatch, tmp_path)
    command = ObjectMembershipReassignCommand(
        expected_scene_revision=base.scene_revision,
        membership_checksum="sha256:" + "a" * 64,
        source_visual_checksum="sha256:" + "b" * 64,
        source_gaussian_indices=[0],
        source_object_id="a",
        target_object_id="b",
    )
    monkeypatch.setattr(scene_objectify_queue, "preview_correction", lambda *a: {})

    scene_objectify_queue.request(
        registry, settings, job.job_id, base.scene_revision, "membership", correction=command, actor_id="reviewer"
    )

    (event,) = _scene_requests(settings, job.job_id)
    assert event.payload["mode"] == "membership" and event.payload["origin"] == "human"


def test_rejected_request_records_no_scene_request(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, _, settings = world
    base = _geometry_draft(world, monkeypatch, tmp_path)
    settings = settings.model_copy(update={"product_sam2_checkpoint": None})
    scene_objectify_queue.request(registry, settings, job.job_id, base.scene_revision, "geometry")

    with pytest.raises(SceneRevisionConflictError):
        scene_objectify_queue.request(registry, settings, job.job_id, "rev-stale", "boxes")
    with pytest.raises(ObjectifyRequestError, match="Đang có một yêu cầu"):
        scene_objectify_queue.request(registry, settings, job.job_id, base.scene_revision, "geometry")

    assert len(_scene_requests(settings, job.job_id)) == 1


def _beat_until(abort_reason: list, cancel_event, seconds: float) -> None:  # noqa: ANN001
    import time as _time

    deadline = _time.monotonic() + seconds
    while _time.monotonic() < deadline and not cancel_event.is_set():
        _time.sleep(0.05)


def test_objectify_heartbeat_survives_one_locked_database_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-049: one locked-database blip must not cancel a long geometry build."""
    import sqlite3
    from threading import Event
    from types import SimpleNamespace

    from src.services.orchestration.scene import objectify_queue as queue

    calls = {"n": 0}

    def cancel_reason(*args: object) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(queue, "_cancel_reason", cancel_reason)
    cancel_event, abort_reason = Event(), [None]
    record = SimpleNamespace(lease_token="t", lease_generation=1)
    stop, thread = queue._start_heartbeat(
        SimpleNamespace(), "job-x", record, SimpleNamespace(), [None], cancel_event, abort_reason
    )
    _beat_until(abort_reason, cancel_event, 1.5)
    stop.set()
    thread.join(timeout=2)
    assert calls["n"] >= 2
    assert abort_reason[0] is None and not cancel_event.is_set()


def test_objectify_heartbeat_aborts_on_persistent_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3
    from datetime import timedelta
    from threading import Event
    from types import SimpleNamespace

    from src.services.orchestration.scene import objectify_queue as queue

    def cancel_reason(*args: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(queue, "_cancel_reason", cancel_reason)
    monkeypatch.setattr(queue, "_LEASE_TTL", timedelta(seconds=1.2))
    cancel_event, abort_reason = Event(), [None]
    record = SimpleNamespace(lease_token="t", lease_generation=1)
    stop, thread = queue._start_heartbeat(
        SimpleNamespace(), "job-x", record, SimpleNamespace(), [None], cancel_event, abort_reason
    )
    _beat_until(abort_reason, cancel_event, 4)
    stop.set()
    thread.join(timeout=2)
    assert abort_reason[0] == "lease_lost" and cancel_event.is_set()


def _waiting(reason: str):  # noqa: ANN202
    from src.services.orchestration.jobs.admission import OperationAdmissionResult

    def admit(_self, request):  # noqa: ANN001, ANN202
        return OperationAdmissionResult(
            request=request,
            status="waiting_resources",
            required_gb={"vram": 1.0, "ram": None, "disk": None},
            available_gb={"vram": None, "ram": None, "disk": None},
            capacity_gb={"vram": None, "ram": None, "disk": None},
            waiting_on=["vram"],
            reasons={"vram": reason},
        )

    return admit


def _queued_boxes(world, monkeypatch, tmp_path, reason: str):  # noqa: ANN001, ANN202
    registry, job, bundle, settings = world
    monkeypatch.setattr(scene_extraction, "objectify_with_retry", _always_fail)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    scene_objectify_queue.request(registry, settings, job.job_id, "rev-001", "boxes")
    monkeypatch.setattr(scene_objectify_queue, "use_boxes", lambda *args, **kwargs: None)
    monkeypatch.setattr(scene_objectify_queue.ResourceAdmission, "admit_operation", _waiting(reason))
    return registry, job, settings


def _age_wait(settings, job_id: str, minutes: int) -> None:  # noqa: ANN001
    from datetime import UTC, datetime, timedelta

    with scene_objectify_queue._database(settings).transaction(write=True) as tx:
        record = scene_objectify_queue._read(tx, job_id, lock=True)
        since = datetime.now(UTC) - timedelta(minutes=minutes)
        scene_objectify_queue._write(tx, job_id, record.model_copy(update={"resource_wait_since": since}))


def test_objectify_wait_fails_after_limit(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """T-050: a wait that is not caused by a busy machine ends as a retryable failure after 30 minutes."""
    registry, job, settings = _queued_boxes(world, monkeypatch, tmp_path, "gate_error")
    assert scene_objectify_queue.process_next(registry, settings) is False
    _age_wait(settings, job.job_id, 31)
    scene_objectify_queue.process_next(registry, settings)
    with scene_objectify_queue._database(settings).transaction() as tx:
        record = scene_objectify_queue._read(tx, job.job_id)
    assert record.status == "failed" and record.retryable is True
    assert "cổng tài nguyên lỗi" in (record.error or "")


def test_objectify_busy_wait_never_fails(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, settings = _queued_boxes(world, monkeypatch, tmp_path, "busy")
    scene_objectify_queue.process_next(registry, settings)
    _age_wait(settings, job.job_id, 600)
    scene_objectify_queue.process_next(registry, settings)
    with scene_objectify_queue._database(settings).transaction() as tx:
        record = scene_objectify_queue._read(tx, job.job_id)
    assert record.status == "queued"


def test_first_wait_records_since_and_keeps_it(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    registry, job, settings = _queued_boxes(world, monkeypatch, tmp_path, "unmeasured")
    scene_objectify_queue.process_next(registry, settings)
    with scene_objectify_queue._database(settings).transaction() as tx:
        first = scene_objectify_queue._read(tx, job.job_id).resource_wait_since
    scene_objectify_queue.process_next(registry, settings)
    with scene_objectify_queue._database(settings).transaction() as tx:
        second = scene_objectify_queue._read(tx, job.job_id).resource_wait_since
    assert first is not None and first == second


def test_old_record_without_wait_since_reads() -> None:
    legacy = (
        '{"status":"queued","mode":"geometry","base_revision":"rev-002",'
        '"requested_at":"2026-10-18T08:00:00+00:00","phase":null}'
    )
    record = scene_objectify_queue._Record.model_validate_json(legacy)
    assert record.resource_wait_since is None
