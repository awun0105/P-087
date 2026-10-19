"""Timing snapshots separate worker stages, queueing, user wait, and partial attempts."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobStatus, StageArtifact, StageId
from src.services.orchestration.benchmark import (
    PipelineRuntimeBenchmark,
    StageTiming,
    _critical_path,
    _interval_union_seconds,
    build_benchmark,
)
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry

_T0 = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)


def _registry(root: Path) -> tuple[ProjectRegistry, str]:
    registry = ProjectRegistry(runtime_root=root / "artifacts")
    registry.seed_from_fixtures()
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    return registry, job.job_id


def _event(
    attempt: int,
    status: JobStatus,
    stage: StageId,
    at: datetime,
    *,
    actual_frame_count: int | None = None,
    preview_verified_at: datetime | None = None,
) -> JobAttemptRecord:
    return JobAttemptRecord(
        attempt=attempt,
        status=status,
        current_stage=stage,
        recorded_at=at,
        actual_frame_count=actual_frame_count,
        preview_verified_at=preview_verified_at,
    )


def _stage(stage: StageId, started: datetime, completed: datetime) -> StageArtifact:
    return StageArtifact(
        stage_id=stage,
        status="SUCCEEDED",
        artifact_type="FixtureStage",
        artifact_uri=f"artifact://jobs/job-timing/{stage.value.lower()}.json",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        started_at=started,
        completed_at=completed,
    )


def _replace_job(registry: ProjectRegistry, job_id: str, **update: object) -> None:
    current = registry.get_job(job_id)
    registry._jobs[job_id] = current.model_copy(update=update)


def test_running_attempt_has_no_full_job_total_and_uses_actual_frames(tmp_path: Path) -> None:
    registry, job_id = _registry(tmp_path)
    _replace_job(
        registry,
        job_id,
        status=JobStatus.RUNNING,
        current_stage=StageId.VISUAL_RECON,
        started_at=_T0,
        completed_at=None,
        stage_artifacts=[_stage(StageId.FRAME_EXTRACT, _T0 + timedelta(seconds=10), _T0 + timedelta(seconds=20))],
    )
    registry._attempts[job_id] = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, _T0),
        _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, _T0 + timedelta(seconds=5), actual_frame_count=50),
        _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, _T0 + timedelta(seconds=25)),
        _event(1, JobStatus.RUNNING, StageId.VISUAL_RECON, _T0 + timedelta(seconds=40)),
    ]

    benchmark = build_benchmark(registry, job_id, observed_at=_T0 + timedelta(seconds=90))

    assert benchmark.snapshot_phase == "partial"
    assert benchmark.total_seconds is None
    assert benchmark.attempt_wall_seconds is None
    assert benchmark.queue_seconds == 5
    assert benchmark.actual_frame_count == 50
    assert benchmark.estimated_gpu_cost_usd is None
    assert benchmark.first_preview_ready_at is None
    assert benchmark.worker_process_seconds is None


def test_waiting_for_metric_is_separate_from_worker_stage_time(tmp_path: Path) -> None:
    registry, job_id = _registry(tmp_path)
    _replace_job(
        registry,
        job_id,
        status=JobStatus.RUNNING,
        current_stage=StageId.METRIC_CANONICALIZE,
        started_at=_T0,
        completed_at=None,
        stage_artifacts=[_stage(StageId.VISUAL_RECON, _T0 + timedelta(seconds=10), _T0 + timedelta(seconds=40))],
    )
    registry._attempts[job_id] = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, _T0),
        _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, _T0 + timedelta(seconds=5)),
        _event(1, JobStatus.RUNNING, StageId.VISUAL_RECON, _T0 + timedelta(seconds=10)),
        _event(1, JobStatus.RUNNING, StageId.METRIC_CANONICALIZE, _T0 + timedelta(seconds=40)),
    ]
    registry.get_preview = lambda _: SimpleNamespace(  # type: ignore[method-assign]
        delivery_ref=ProductArtifactRef(
            artifact_type="GaussianSOG",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/preview.sog",
            artifact_checksum="sha256:" + "b" * 64,
            data_class="derived",
            producer_stage=StageId.VISUAL_RECON,
            job_id=job_id,
        )
    )

    benchmark = build_benchmark(registry, job_id, observed_at=_T0 + timedelta(seconds=100))
    metric = next(stage for stage in benchmark.stages if stage.stage_id == StageId.METRIC_CANONICALIZE.value)

    assert benchmark.user_wait_seconds == 60
    assert metric.state == "waiting"
    assert metric.seconds is None
    assert metric.waiting_seconds == 60


def test_first_preview_latency_uses_consumer_verified_timestamp(tmp_path: Path) -> None:
    registry, job_id = _registry(tmp_path)
    preview_verified_at = _T0 + timedelta(seconds=55)
    _replace_job(
        registry,
        job_id,
        status=JobStatus.RUNNING,
        current_stage=StageId.METRIC_CANONICALIZE,
        started_at=_T0,
        completed_at=None,
        stage_artifacts=[_stage(StageId.VISUAL_RECON, _T0 + timedelta(seconds=10), preview_verified_at)],
    )
    registry._attempts[job_id] = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, _T0),
        _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, _T0 + timedelta(seconds=5)),
        _event(
            1,
            JobStatus.RUNNING,
            StageId.VISUAL_RECON,
            _T0 + timedelta(seconds=10),
            preview_verified_at=preview_verified_at,
        ),
    ]
    registry.get_preview = lambda _: SimpleNamespace(  # type: ignore[method-assign]
        delivery_ref=ProductArtifactRef(
            artifact_type="GaussianSOG",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/preview.sog",
            artifact_checksum="sha256:" + "b" * 64,
            data_class="derived",
            producer_stage=StageId.VISUAL_RECON,
            job_id=job_id,
        )
    )

    benchmark = build_benchmark(registry, job_id)

    assert benchmark.first_preview_ready_at == preview_verified_at
    assert benchmark.first_preview_time_source == "verified"
    assert benchmark.time_to_first_preview_seconds == 55


@pytest.mark.parametrize("status", [JobStatus.FAILED, JobStatus.CANCELLED])
def test_terminal_failure_or_cancel_records_elapsed_stage_without_success(tmp_path: Path, status: JobStatus) -> None:
    registry, job_id = _registry(tmp_path)
    terminal_at = _T0 + timedelta(seconds=60)
    _replace_job(
        registry,
        job_id,
        status=status,
        current_stage=StageId.CAMERA_POSE,
        started_at=_T0,
        completed_at=terminal_at,
    )
    registry._attempts[job_id] = [
        _event(1, JobStatus.QUEUED, StageId.CAMERA_POSE, _T0),
        _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, _T0 + timedelta(seconds=5)),
        _event(1, status, StageId.CAMERA_POSE, terminal_at),
    ]

    benchmark = build_benchmark(registry, job_id, observed_at=terminal_at)
    camera = next(stage for stage in benchmark.stages if stage.stage_id == StageId.CAMERA_POSE.value)

    assert benchmark.snapshot_phase == "terminal"
    assert benchmark.total_seconds == 60
    assert benchmark.attempt_wall_seconds == 55
    assert camera.state == status.value.lower()
    assert camera.seconds == 55
    assert benchmark.critical_path_seconds == 55


def test_successful_terminal_snapshot_separates_job_wall_from_worker_critical_path(tmp_path: Path) -> None:
    registry, job_id = _registry(tmp_path)
    stage_intervals = {
        StageId.INPUT_VALIDATE: (5, 10),
        StageId.PRIVACY_GATE: (10, 15),
        StageId.FRAME_EXTRACT: (15, 20),
        StageId.CAMERA_POSE: (20, 40),
        StageId.VISUAL_RECON: (40, 80),
        StageId.METRIC_CANONICALIZE: (80, 85),
        StageId.RGB_GEOMETRY: (85, 92),
        StageId.OBJECT_EXTRACT: (92, 100),
    }
    artifacts = [
        _stage(stage, _T0 + timedelta(seconds=start), _T0 + timedelta(seconds=end))
        for stage, (start, end) in stage_intervals.items()
    ]
    _replace_job(
        registry,
        job_id,
        status=JobStatus.SUCCEEDED,
        current_stage=StageId.OBJECT_EXTRACT,
        started_at=_T0,
        completed_at=_T0 + timedelta(seconds=100),
        stage_artifacts=artifacts,
    )
    registry._attempts[job_id] = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, _T0),
        *[
            _event(1, JobStatus.RUNNING, stage, _T0 + timedelta(seconds=start))
            for stage, (start, _) in stage_intervals.items()
        ],
        _event(1, JobStatus.SUCCEEDED, StageId.OBJECT_EXTRACT, _T0 + timedelta(seconds=100)),
    ]

    benchmark = build_benchmark(registry, job_id)

    assert benchmark.snapshot_phase == "terminal"
    assert benchmark.total_seconds == 100
    assert benchmark.attempt_wall_seconds == 95
    assert benchmark.critical_path_seconds == 90  # metric confirmation is user time, not worker compute
    assert benchmark.timing_coverage is not None
    assert benchmark.timing_coverage.worker_stage_count == 7
    assert benchmark.timing_coverage.measured_worker_stage_count == 7


def test_retry_marks_prior_preparation_as_reused(tmp_path: Path) -> None:
    registry, job_id = _registry(tmp_path)
    _replace_job(
        registry,
        job_id,
        status=JobStatus.RUNNING,
        current_stage=StageId.CAMERA_POSE,
        started_at=_T0,
        completed_at=None,
        stage_artifacts=[_stage(StageId.FRAME_EXTRACT, _T0 + timedelta(seconds=10), _T0 + timedelta(seconds=20))],
    )
    registry._attempts[job_id] = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, _T0),
        _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, _T0 + timedelta(seconds=5), actual_frame_count=50),
        _event(1, JobStatus.FAILED, StageId.VISUAL_RECON, _T0 + timedelta(seconds=30)),
        _event(2, JobStatus.QUEUED, StageId.CAMERA_POSE, _T0 + timedelta(seconds=60)),
        _event(2, JobStatus.RUNNING, StageId.CAMERA_POSE, _T0 + timedelta(seconds=70)),
    ]

    benchmark = build_benchmark(registry, job_id, observed_at=_T0 + timedelta(seconds=80))
    frame = next(stage for stage in benchmark.stages if stage.stage_id == StageId.FRAME_EXTRACT.value)

    assert benchmark.attempt == 2
    assert benchmark.actual_frame_count == 50
    assert benchmark.queue_seconds == 10
    assert frame.scope == "reused"
    assert frame.seconds is None


def test_overlapping_tool_intervals_count_wall_once_and_invalidate_serial_critical_path() -> None:
    first = _T0 + timedelta(seconds=10)
    second = _T0 + timedelta(seconds=25)
    end_first = _T0 + timedelta(seconds=30)
    end_second = _T0 + timedelta(seconds=40)

    assert _interval_union_seconds([(first, end_first), (second, end_second)]) == 30
    critical_path, issues = _critical_path(
        [
            StageTiming(
                stage_id=StageId.CAMERA_POSE.value,
                state="succeeded",
                seconds=20,
                scope="attempt",
                started_at=first,
                completed_at=end_first,
            ),
            StageTiming(
                stage_id=StageId.VISUAL_RECON.value,
                state="succeeded",
                seconds=15,
                scope="attempt",
                started_at=second,
                completed_at=end_second,
            ),
        ],
        terminal=True,
    )
    assert critical_path is None
    assert issues == ["overlapping_serial_stage_intervals"]


def test_serial_critical_path_includes_observed_gaps_between_worker_stages() -> None:
    first = _T0 + timedelta(seconds=10)
    first_end = _T0 + timedelta(seconds=20)
    second = _T0 + timedelta(seconds=40)
    second_end = _T0 + timedelta(seconds=50)

    critical_path, issues = _critical_path(
        [
            StageTiming(
                stage_id=StageId.CAMERA_POSE.value,
                state="succeeded",
                seconds=10,
                scope="attempt",
                started_at=first,
                completed_at=first_end,
            ),
            StageTiming(
                stage_id=StageId.VISUAL_RECON.value,
                state="succeeded",
                seconds=10,
                scope="attempt",
                started_at=second,
                completed_at=second_end,
            ),
        ],
        terminal=True,
    )

    assert critical_path == 40
    assert issues == []


def test_schema_10_records_remain_readable() -> None:
    payload = {
        "schema_version": "1.0",
        "benchmark_kind": "pipeline_runtime",
        "job_id": "job-old",
        "project_id": "project-old",
        "attempt": 1,
        "recorded_at": _T0.isoformat(),
        "status": "RUNNING",
        "stages": [{"stage_id": StageId.CAMERA_POSE.value, "state": "running", "seconds": None}],
        "total_seconds": 12.0,
        "config_checksum": "sha256:" + "c" * 64,
    }

    legacy = PipelineRuntimeBenchmark.model_validate(payload)

    assert legacy.schema_version == "1.0"
    assert legacy.actual_frame_count is None
    assert legacy.snapshot_phase is None
    assert PipelineRuntimeBenchmark.model_validate_json(legacy.model_dump_json()) == legacy
