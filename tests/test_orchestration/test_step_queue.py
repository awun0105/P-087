"""T-073: hàng đợi theo từng bước — sinh bước tất định, chuyển trạng thái, CAS nhận bước, làn CPU/GPU."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobManifest, JobStatus, StageArtifact, StageId, StageStatus
from src.services.orchestration.jobs import steps, worker_cli
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.progress import awaiting_pose_step, awaiting_scene_extract
from src.services.orchestration.jobs.steps import (
    RANK_CONTINUATION,
    RANK_NEW_JOB,
    RANK_USER_WAITING,
    claim_step,
    enqueue_view_lod,
    job_step_views,
    pending_step_counts,
    plan_steps,
    read_rows,
    release_claim,
    runnable_step,
    step_rank,
)
from src.services.orchestration.jobs.worker_cli import dispatch_next, step_candidates
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction import FinalizeResult
from tests.test_orchestration.test_anonymization_review import _acceptance, _after_prepare
from tests.test_orchestration.test_finalize_flow import _confirmed, _publish, _stage
from tests.test_orchestration.test_prepared_queue import _attach_frames, _frame_stage, _registry

_PROJECT = "project-fixture-001"


def _states(job: JobManifest) -> dict[str, str]:
    return {step.step_id: step.state for step in plan_steps(job)}


def _rows(registry: ProjectRegistry, job_id: str) -> dict[str, steps.StepRow]:
    assert registry.persistence is not None
    with registry.persistence.database.transaction() as tx:
        return read_rows(tx, job_id)


def _input_stage(job_id: str) -> StageArtifact:
    return StageArtifact(
        stage_id=StageId.INPUT_VALIDATE,
        status=StageStatus.SUCCEEDED,
        artifact_type="InputValidationReport",
        artifact_uri=f"artifact://jobs/{job_id}/rec02a/input.json",
        artifact_checksum="sha256:" + "c" * 64,
        data_class="derived",
        completed_at=datetime.now(UTC),
    )


def _prepared(registry: ProjectRegistry) -> JobManifest:
    """Job video vừa xong bước chuẩn bị: RUNNING ở bước tách frame, có frame set, không worker nào giữ."""
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    job = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.RUNNING), expected_checksum=job.job_manifest_checksum
    )
    job = registry.record_stage_progress(job, StageId.FRAME_EXTRACT)
    return _attach_frames(registry, job, _input_stage(job.job_id), _frame_stage(job.job_id))


def _geometry_done(tmp_path: Path) -> tuple[ProjectRegistry, JobManifest]:
    registry, job, confirmation = _confirmed(tmp_path)
    job = registry.record_stage_progress(job, StageId.RGB_GEOMETRY)
    geometry = _publish(registry, job.job_id, "collision.glb", "RgbGeometry", StageId.RGB_GEOMETRY)
    bundle = _publish(registry, job.job_id, "bundle.json", "ReconstructionBundle", StageId.METRIC_CANONICALIZE)
    result_ref = _publish(registry, job.job_id, "result.json", "RecFinalizeResult", StageId.METRIC_CANONICALIZE)
    result = FinalizeResult(
        job_id=job.job_id,
        attempt_id="finalize-1",
        confirmation_ref=confirmation,
        geometry_ref=geometry,
        bundle_ref=bundle,
        stage_artifacts=[_stage(geometry, StageId.RGB_GEOMETRY), _stage(bundle, StageId.METRIC_CANONICALIZE)],
    )
    return registry, registry.record_geometry(job, result, result_ref)


# --- Sinh bước tất định ---------------------------------------------------------------------------------------------


def test_new_video_job_starts_with_a_cpu_prepare_step(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    planned = plan_steps(job)
    assert [(step.step_id, step.kind, step.state) for step in planned] == [
        ("prepare", "cpu", "ready"),
        ("pose_visual", "gpu", "pending"),
        ("metric_confirm", "user", "pending"),
        ("canonical_geometry", "cpu", "pending"),
        ("scene_extract", "gpu", "pending"),
    ]
    assert [step.depends_on for step in planned][1:3] == [("prepare",), ("pose_visual",)]
    assert plan_steps(job) == planned  # tất định
    assert runnable_step(job) == "prepare" and step_rank(job, "prepare") == RANK_NEW_JOB


def test_dataset_job_with_published_frames_has_no_prepare_step(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    job = _attach_frames(registry, job, _frame_stage(job.job_id))
    assert "prepare" not in _states(job)
    assert _states(job)["pose_visual"] == "ready" and runnable_step(job) == "pose_visual"


def test_prepared_job_waits_for_the_gpu_pose_step(tmp_path: Path) -> None:
    job = _prepared(_registry(tmp_path))
    assert awaiting_pose_step(job)
    assert _states(job) == {
        "prepare": "done",
        "pose_visual": "ready",
        "metric_confirm": "pending",
        "canonical_geometry": "pending",
        "scene_extract": "pending",
    }
    assert step_rank(job, "pose_visual") == RANK_CONTINUATION


def test_redacted_frames_wait_for_the_user_then_release_the_pose_step(tmp_path: Path) -> None:
    registry, job = _after_prepare(tmp_path)
    assert _states(job)["anonymization_review"] == "waiting_user" and runnable_step(job) is None
    accepted = registry.record_anonymization_acceptance(job, _acceptance(registry, job.job_id))
    assert _states(accepted)["anonymization_review"] == "done"
    assert runnable_step(accepted) == "pose_visual" and step_rank(accepted, "pose_visual") == RANK_USER_WAITING


def test_metric_confirmation_is_a_user_step_and_geometry_goes_first(tmp_path: Path) -> None:
    registry, job, _ = _confirmed(tmp_path)
    assert _states(job)["metric_confirm"] == "done"
    assert runnable_step(job) == "canonical_geometry" and step_rank(job, "canonical_geometry") == RANK_USER_WAITING


def test_geometry_then_scene_extract_are_separate_steps(tmp_path: Path) -> None:
    registry, job = _geometry_done(tmp_path)
    assert job.status == JobStatus.RUNNING and job.current_stage == StageId.RGB_GEOMETRY
    assert awaiting_scene_extract(job)
    assert _states(job)["canonical_geometry"] == "done" and runnable_step(job) == "scene_extract"
    claimed = registry.record_stage_progress(job, StageId.OBJECT_EXTRACT)
    assert _states(claimed)["scene_extract"] == "running" and not awaiting_scene_extract(claimed)
    done = registry.record_scene_extract(claimed, [])
    assert done.status == JobStatus.SUCCEEDED and done.current_stage == StageId.RGB_GEOMETRY
    assert set(_states(done).values()) == {"done"}


def test_cancel_skips_unfinished_steps_and_failure_marks_the_active_step(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _prepared(registry)
    cancelled = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.CANCELLED), expected_checksum=job.job_manifest_checksum
    )
    assert _states(cancelled) == {
        "prepare": "done",
        "pose_visual": "skipped",
        "metric_confirm": "skipped",
        "canonical_geometry": "skipped",
        "scene_extract": "skipped",
    }
    rows = _rows(registry, job.job_id)
    assert {step_id: row.state for step_id, row in rows.items()} == _states(cancelled)


def test_retry_runs_only_the_failed_step_again(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _prepared(registry)
    running = registry.record_stage_progress(job, StageId.CAMERA_POSE)
    assert _rows(registry, job.job_id)["pose_visual"].state == "running"
    failed = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.FAILED), expected_checksum=running.job_manifest_checksum
    )
    rows = _rows(registry, job.job_id)
    assert rows["pose_visual"].state == "failed" and rows["prepare"].state == "done"
    assert rows["pose_visual"].finished_at is not None
    queued = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.QUEUED), expected_checksum=failed.job_manifest_checksum
    )
    rows = _rows(registry, job.job_id)
    assert runnable_step(queued) == "pose_visual"
    assert rows["pose_visual"].state == "ready" and rows["pose_visual"].attempt == 2
    assert rows["prepare"].state == "done" and rows["prepare"].attempt == 1


# --- Bảng bước và CAS nhận bước ------------------------------------------------------------------------------------


def test_every_job_revision_rewrites_its_steps_in_the_same_commit(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    rows = _rows(registry, job.job_id)
    assert rows["prepare"].state == "ready" and rows["prepare"].job_manifest_checksum == job.job_manifest_checksum
    running = registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    rows = _rows(registry, job.job_id)
    assert rows["prepare"].state == "running" and rows["prepare"].started_at is not None
    assert rows["prepare"].job_manifest_checksum == running.job_manifest_checksum


def test_claim_is_compare_and_set_on_the_current_revision(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _prepared(registry)
    assert registry.persistence is not None
    database, load = registry.persistence.database, registry.persistence.job_from_pointer
    first = claim_step(database, job, "pose_visual", "worker-a", load_job=load)
    assert first is not None
    assert claim_step(database, job, "pose_visual", "worker-b", load_job=load) is None  # đã có worker nhận
    row = _rows(registry, job.job_id)["pose_visual"]
    assert row.state == "claimed" and row.worker_id == "worker-a"
    assert {view.step_id: view.state for view in job_step_views(database, job)}["pose_visual"] == "claimed"
    release_claim(database, first)
    assert _rows(registry, job.job_id)["pose_visual"].state == "ready"
    newer = registry.record_stage_progress(job, StageId.CAMERA_POSE)
    assert claim_step(database, job, "pose_visual", "worker-b", load_job=load) is None  # revision cũ
    assert _rows(registry, job.job_id)["pose_visual"].state == "running"
    assert newer.current_stage == StageId.CAMERA_POSE


def test_expired_claim_returns_to_ready(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _prepared(registry)
    assert registry.persistence is not None
    database, load = registry.persistence.database, registry.persistence.job_from_pointer
    past = datetime.now(UTC) - steps.CLAIM_TTL - timedelta(minutes=1)
    assert claim_step(database, job, "pose_visual", "dead-worker", load_job=load, now=past) is not None
    assert claim_step(database, job, "pose_visual", "worker-b", load_job=load) is not None


def test_job_without_rows_from_before_v27_is_backfilled_on_claim(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _prepared(registry)
    assert registry.persistence is not None
    database = registry.persistence.database
    with database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_job_steps WHERE job_id=?", (job.job_id,))
    # Màn tiến trình vẫn có bước (suy từ manifest) khi bảng chưa có dòng nào.
    assert [view.state for view in job_step_views(database, job)][:2] == ["done", "ready"]
    claim = claim_step(database, job, "pose_visual", "worker-a", load_job=registry.persistence.job_from_pointer)
    assert claim is not None and _rows(registry, job.job_id)["prepare"].state == "done"


def test_pending_counts_split_by_resource_kind(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.create_job(JobCreateInput(project_id=_PROJECT))
    _prepared(registry)
    assert registry.persistence is not None
    assert pending_step_counts(registry.persistence.database) == {"gpu": 1, "cpu": 1}


def test_view_lod_is_a_background_step_after_the_job_succeeds(tmp_path: Path) -> None:
    registry, job = _geometry_done(tmp_path)
    done = registry.record_scene_extract(registry.record_stage_progress(job, StageId.OBJECT_EXTRACT), [])
    assert registry.persistence is not None
    database = registry.persistence.database
    enqueue_view_lod(database, done)
    enqueue_view_lod(database, done)  # lặp lại không tạo dòng thứ hai
    assert steps.ready_view_lods(database) == [done.job_id]
    assert step_rank(done, "view_lod") == steps.RANK_BACKGROUND
    views = job_step_views(database, done)
    assert views[-1].step_id == "view_lod" and views[-1].waiting_on == "gpu"
    assert pending_step_counts(database) == {"gpu": 0, "cpu": 0}  # bộ LOD không thuê thêm máy


# --- Làn CPU/GPU của worker ----------------------------------------------------------------------------------------


def _with_video_input(registry: ProjectRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    """Project fixture không có InputManifest; bước chuẩn bị chỉ nhận project có video đã publish."""
    original = registry.get_project

    def get_project(project_id: str):  # noqa: ANN202
        return original(project_id).model_copy(update={"input_manifest_ref": object()})

    monkeypatch.setattr(registry, "get_project", get_project)


def test_gpu_worker_prefers_gpu_steps_and_cpu_lane_takes_only_cpu_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _with_video_input(registry, monkeypatch)
    new_job = registry.create_job(JobCreateInput(project_id=_PROJECT))  # chờ bước chuẩn bị (CPU)
    prepared = _prepared(registry)  # chờ bước dựng camera (GPU)
    order = [(item.job.job_id, item.step) for item in step_candidates(registry, ("gpu", "cpu"))]
    assert order == [(prepared.job_id, "pose_visual"), (new_job.job_id, "prepare")]
    assert [(item.job.job_id, item.step) for item in step_candidates(registry, ("cpu",))] == [
        (new_job.job_id, "prepare")
    ]

    calls: list[tuple[str, str]] = []

    def record(step: str):  # noqa: ANN202
        def run(job_id: str, *args: object, expected_checksum: str | None = None) -> None:
            calls.append((step, job_id))

        return run

    unexpected = record("unexpected")
    assert dispatch_next(
        registry,
        runner=unexpected,
        video_runner=record("prepare"),
        finalize_runner=unexpected,
        reviewed_runner=unexpected,
        scene_runner=unexpected,
        lanes=("cpu",),
    )
    assert calls == [("prepare", new_job.job_id)]


def test_cpu_step_of_one_job_and_gpu_step_of_another_run_side_by_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker làn CPU nhận bước chuẩn bị của job A trong khi worker GPU nhận bước dựng camera của job B."""
    registry = _registry(tmp_path)
    _with_video_input(registry, monkeypatch)
    job_a = registry.create_job(JobCreateInput(project_id=_PROJECT))
    job_b = _prepared(registry)
    log: list[str] = []

    def prepare(job_id: str, *, expected_checksum: str) -> None:
        log.append(f"cpu:{job_id}:start")
        # Trong lúc bước CPU của A còn chạy (lease A đang giữ), worker GPU vẫn nhận được bước GPU của B.
        assert dispatch_next(registry, reviewed_runner=pose, video_runner=_forbidden, lanes=("gpu",))
        log.append(f"cpu:{job_id}:end")

    def pose(job_id: str, *, expected_checksum: str) -> None:
        log.append(f"gpu:{job_id}")

    assert dispatch_next(registry, video_runner=prepare, reviewed_runner=_forbidden, lanes=("cpu",))
    assert log == [f"cpu:{job_a.job_id}:start", f"gpu:{job_b.job_id}", f"cpu:{job_a.job_id}:end"]


def _forbidden(*_: object, **__: object) -> None:
    raise AssertionError("làn này không được nhận bước đó")


def test_view_lod_runs_only_on_a_gpu_lane_with_the_lod_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job = _geometry_done(tmp_path)
    done = registry.record_scene_extract(registry.record_stage_progress(job, StageId.OBJECT_EXTRACT), [])
    assert registry.persistence is not None
    enqueue_view_lod(registry.persistence.database, done)
    calls: list[str] = []

    def lod(job_id: str, *, expected_checksum: str | None) -> None:
        calls.append(job_id)

    monkeypatch.setattr(worker_cli, "idle_lod_cli", lambda: None)
    assert not dispatch_next(registry, lod_runner=lod)
    assert not dispatch_next(registry, lod_runner=lod, lanes=("cpu",))
    monkeypatch.setattr(worker_cli, "idle_lod_cli", lambda: Path("/bin/true"))
    assert dispatch_next(registry, lod_runner=lod)
    assert calls == [done.job_id]
    assert _rows(registry, done.job_id)["view_lod"].state == "done"
    assert not dispatch_next(registry, lod_runner=lod)


def test_parse_lanes() -> None:
    assert worker_cli.parse_lanes("gpu,cpu") == ("gpu", "cpu")
    assert worker_cli.parse_lanes(" cpu ") == ("cpu",)
    assert worker_cli.parse_lanes("gpu,gpu") is None
    assert worker_cli.parse_lanes("tpu") is None
    assert worker_cli.parse_lanes("") is None
