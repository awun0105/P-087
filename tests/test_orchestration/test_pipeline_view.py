"""T-059: one ordered list of real steps from the job, recorded marks and scene state."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobStatus, StageArtifact, StageId
from src.services.orchestration.jobs.progress import JobProgress, StageProgress, studio_pipeline
from src.services.orchestration.jobs.step_marks import StepMark
from src.services.orchestration.pipeline.view import compose_steps, current_step, is_usable
from src.services.orchestration.scene.objectify_queue import ObjectifyState
from tests.test_orchestration.test_pipeline_timing import _registry

_T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
_JOB_STAGES = [
    StageId.INPUT_VALIDATE,
    StageId.PRIVACY_GATE,
    StageId.FRAME_EXTRACT,
    StageId.CAMERA_POSE,
    StageId.VISUAL_RECON,
    StageId.METRIC_CANONICALIZE,
    StageId.RGB_GEOMETRY,
    StageId.OBJECT_EXTRACT,
]


@pytest.fixture
def job(tmp_path: Path):  # noqa: ANN201
    registry, job_id = _registry(tmp_path)
    return registry.get_job(job_id)


def _progress(states: dict[StageId, str], *, status: JobStatus = JobStatus.RUNNING, waiting_for=None) -> JobProgress:  # noqa: ANN001
    stages = [
        StageProgress(
            stage_id=stage,
            state=states.get(stage, "pending"),
            started_at=_T0 + timedelta(minutes=index) if states.get(stage) not in {None, "pending"} else None,
            completed_at=_T0 + timedelta(minutes=index + 1) if states.get(stage) == "succeeded" else None,
        )
        for index, stage in enumerate(_JOB_STAGES)
    ]
    current = next((stage.stage_id for stage in stages if stage.state in {"running", "waiting"}), _JOB_STAGES[-1])
    return JobProgress(
        job_id="job-a",
        status=status,
        current_stage=current,
        attempt=1,
        started_at=_T0,
        updated_at=_T0,
        stages=stages,
        preview_ready=False,
        waiting_for=waiting_for,
    )


def _done_until(last: StageId) -> dict[StageId, str]:
    return {stage: "succeeded" for stage in _JOB_STAGES[: _JOB_STAGES.index(last) + 1]}


def _ids(steps) -> list[str]:  # noqa: ANN001
    return [step.step_id.value for step in steps]


def test_video_job_steps_in_order(job) -> None:  # noqa: ANN001
    steps = compose_steps(_progress({StageId.INPUT_VALIDATE: "running"}), job, [], None, None)
    assert _ids(steps) == [stage.value for stage in _JOB_STAGES]


def test_metric_step_is_user_and_waiting(job) -> None:  # noqa: ANN001
    states = {**_done_until(StageId.VISUAL_RECON), StageId.METRIC_CANONICALIZE: "waiting"}
    steps = compose_steps(_progress(states, waiting_for="metric_confirmation"), job, [], None, None)
    metric = next(step for step in steps if step.step_id == StageId.METRIC_CANONICALIZE)
    assert (metric.actor, metric.state) == ("user", "waiting")


def test_resource_wait_is_queued_not_waiting(job) -> None:  # noqa: ANN001
    states = {**_done_until(StageId.FRAME_EXTRACT), StageId.CAMERA_POSE: "running"}
    steps = compose_steps(_progress(states, waiting_for="resources"), job, [], None, None)
    camera = next(step for step in steps if step.step_id == StageId.CAMERA_POSE)
    assert camera.state == "queued"


def test_recorded_marks_preferred_over_inferred(job) -> None:  # noqa: ANN001
    recorded = _T0 + timedelta(seconds=30)
    mark = StepMark(
        job_id="job-a",
        run_kind="pipeline",
        run_id="1",
        step_id="ST-INPUT-VALIDATE",
        started_at=recorded,
        completed_at=recorded + timedelta(seconds=5),
        outcome="succeeded",
    )
    steps = compose_steps(_progress(_done_until(StageId.INPUT_VALIDATE)), job, [mark], None, None)
    first = steps[0]
    assert (first.started_at, first.timing_source) == (recorded, "recorded")


def test_reused_stage_takes_mark_from_earlier_attempt(job) -> None:  # noqa: ANN001
    old = StepMark(
        job_id="job-a",
        run_kind="pipeline",
        run_id="1",
        step_id="ST-CAMERA-POSE",
        started_at=_T0,
        completed_at=_T0 + timedelta(minutes=3),
        outcome="succeeded",
    )
    progress = _progress(_done_until(StageId.CAMERA_POSE)).model_copy(update={"attempt": 2})
    camera = next(
        step for step in compose_steps(progress, job, [old], None, None) if step.step_id == StageId.CAMERA_POSE
    )
    assert camera.timing_source == "recorded" and camera.completed_at == _T0 + timedelta(minutes=3)


def test_retry_does_not_show_old_attempt_timing_on_steps_not_run_yet(job) -> None:  # noqa: ANN001
    """Review fix: after a retry, a step still pending must not carry the failed attempt's times."""
    failed = StepMark(
        job_id="job-a",
        run_kind="pipeline",
        run_id="1",
        step_id="ST-RGB-GEOMETRY",
        started_at=_T0,
        completed_at=_T0 + timedelta(minutes=42),
        outcome="failed",
    )
    progress = _progress(_done_until(StageId.METRIC_CANONICALIZE)).model_copy(update={"attempt": 2})
    geometry = next(
        step for step in compose_steps(progress, job, [failed], None, None) if step.step_id == StageId.RGB_GEOMETRY
    )
    assert geometry.state == "pending"
    assert (geometry.started_at, geometry.completed_at) == (None, None)


def test_legacy_job_without_marks_is_inferred(job) -> None:  # noqa: ANN001
    steps = compose_steps(_progress(_done_until(StageId.CAMERA_POSE)), job, [], None, None)
    assert {step.timing_source for step in steps if step.state == "succeeded"} == {"inferred"}
    assert {step.timing_source for step in steps if step.state == "pending"} == {"none"}


def test_anonymization_review_step_inserted_and_waiting(job) -> None:  # noqa: ANN001
    frames = StageArtifact(
        stage_id=StageId.FRAME_EXTRACT,
        status="SUCCEEDED",
        artifact_type="NormalizedRGBFrameSet",
        artifact_uri="artifact://jobs/x/rec02a/sanitized/frame_set.json",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        completed_at=_T0,
    )
    sanitized = job.model_copy(update={"stage_artifacts": [frames]})
    states = {**_done_until(StageId.FRAME_EXTRACT)}
    steps = compose_steps(_progress(states, waiting_for="anonymization_review"), sanitized, [], None, None)
    ids = _ids(steps)
    assert ids[ids.index("ST-FRAME-EXTRACT") + 1] == "ST-ANONYMIZATION-REVIEW"
    review = steps[ids.index("ST-ANONYMIZATION-REVIEW")]
    assert (review.actor, review.state) == ("user", "waiting")


def _objectify(**update: object) -> ObjectifyState:
    return ObjectifyState(scene_revision="rev-002", **update)


def test_awaiting_choice_marks_object_extract_failed(job) -> None:  # noqa: ANN001
    steps = compose_steps(
        _progress(_done_until(StageId.OBJECT_EXTRACT), status=JobStatus.SUCCEEDED),
        job,
        [],
        _objectify(awaiting_choice=True, retryable=True),
        None,
    )
    extract = steps[-1]
    assert extract.state == "failed" and extract.error is not None
    assert extract.error.error_code == "OBJECTIFY_AWAITING_CHOICE" and extract.error.retryable is True


def test_draft_adds_confirm_waiting_and_build_pending(job) -> None:  # noqa: ANN001
    steps = compose_steps(
        _progress(_done_until(StageId.OBJECT_EXTRACT), status=JobStatus.SUCCEEDED),
        job,
        [],
        _objectify(object_geometry="awaiting_review"),
        "awaiting_review",
    )
    assert _ids(steps)[-2:] == ["ST-OBJECT-CONFIRM", "ST-SCENE-DECOMPOSE"]
    assert (steps[-2].state, steps[-2].actor, steps[-1].state) == ("waiting", "user", "pending")


def test_geometry_running_shows_phase(job) -> None:  # noqa: ANN001
    state = _objectify(
        object_geometry="awaiting_review",
        status="running",
        mode="geometry",
        phase="collider",
        requested_at=_T0,
        started_at=_T0,
    )
    steps = compose_steps(
        _progress(_done_until(StageId.OBJECT_EXTRACT), status=JobStatus.SUCCEEDED), job, [], state, "awaiting_review"
    )
    assert (steps[-2].state, steps[-1].state, steps[-1].phase) == ("succeeded", "running", "collider")


def test_geometry_failed_on_current_revision(job) -> None:  # noqa: ANN001
    state = _objectify(
        object_geometry="awaiting_review",
        status="failed",
        mode="geometry",
        base_revision="rev-002",
        error="CoACD lỗi",
        retryable=True,
    )
    steps = compose_steps(
        _progress(_done_until(StageId.OBJECT_EXTRACT), status=JobStatus.SUCCEEDED), job, [], state, "awaiting_review"
    )
    build = steps[-1]
    assert (
        build.state == "failed" and build.error is not None and build.error.error_code == "OBJECT_GEOMETRY_BUILD_FAILED"
    )


def test_region_rebuild_keeps_build_succeeded(job) -> None:  # noqa: ANN001
    state = _objectify(object_geometry="ready", status="running", mode="region", phase="shell")
    steps = compose_steps(
        _progress(_done_until(StageId.OBJECT_EXTRACT), status=JobStatus.SUCCEEDED), job, [], state, "ready"
    )
    assert steps[-1].state == "succeeded"


def test_legacy_scene_without_geometry_key_has_no_review_steps(job) -> None:  # noqa: ANN001
    steps = compose_steps(
        _progress(_done_until(StageId.OBJECT_EXTRACT), status=JobStatus.SUCCEEDED), job, [], _objectify(), None
    )
    assert _ids(steps)[-1] == "ST-OBJECT-EXTRACT"


def test_current_step_and_usable(job) -> None:  # noqa: ANN001
    done = _progress(_done_until(StageId.OBJECT_EXTRACT), status=JobStatus.SUCCEEDED)
    draft = compose_steps(done, job, [], _objectify(object_geometry="awaiting_review"), "awaiting_review")
    assert current_step(draft) == StageId.OBJECT_CONFIRM
    assert is_usable(JobStatus.SUCCEEDED, "awaiting_review", False) is False
    assert is_usable(JobStatus.SUCCEEDED, "ready", False) is True
    assert is_usable(JobStatus.SUCCEEDED, None, False) is True
    assert is_usable(JobStatus.SUCCEEDED, None, True) is False


def test_lidar_odometry_stage_is_listed(job) -> None:  # noqa: ANN001
    odometry = StageArtifact(
        stage_id=StageId.LIDAR_ODOMETRY,
        status="SUCCEEDED",
        artifact_type="LidarOdometryEvidence",
        artifact_uri="artifact://jobs/x/odometry.json",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        completed_at=_T0,
    )
    assert StageId.LIDAR_ODOMETRY in studio_pipeline(job.model_copy(update={"stage_artifacts": [odometry]}))
