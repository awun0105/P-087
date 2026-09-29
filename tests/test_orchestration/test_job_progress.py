"""Tiến trình theo stage: suy từ JobManifest + journal, không có phần trăm ước đoán."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.manifests import ExecutionError, JobStatus, StageArtifact, StageId
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import JobAttemptRecord, TransitionRequest
from src.services.orchestration.jobs.preview_cli import _Attempt, _StageProgress
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.progress import MVP_PIPELINE, job_progress
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry

_T0 = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


def _registry(root: Path) -> ProjectRegistry:
    probe = ProjectRegistry(runtime_root=root / "artifacts")
    registry = ProjectRegistry(
        runtime_root=root / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}"),
        execution_profile=ExecutionProfile(
            config_checksum=probe._fixture_config_checksum(),
            runtime_manifest_checksum=probe._fixture_runtime_checksum(),
            seed=7,
        ),
    )
    registry.seed_from_fixtures()
    return registry


def _event(attempt: int, status: JobStatus, stage: StageId, minutes: int, error: ExecutionError | None = None):  # noqa: ANN202
    return JobAttemptRecord(
        attempt=attempt, status=status, current_stage=stage, recorded_at=_T0 + timedelta(minutes=minutes), error=error
    )


def _succeeded(stage: StageId, minutes: int) -> StageArtifact:
    return StageArtifact(
        stage_id=stage,
        status="SUCCEEDED",
        artifact_type="X",
        artifact_uri=f"artifact://jobs/job-p/{stage.value.lower()}.json",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        completed_at=_T0 + timedelta(minutes=minutes),
    )


def _job(root: Path, **update: object):  # noqa: ANN202
    registry = _registry(root)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    return job.model_copy(update={"job_id": "job-p", "started_at": _T0, **update})


def test_running_job_marks_done_running_and_pending_stages(tmp_path: Path) -> None:
    job = _job(
        tmp_path,
        status=JobStatus.RUNNING,
        current_stage=StageId.CAMERA_POSE,
        stage_artifacts=[_succeeded(s, 2) for s in MVP_PIPELINE[:3]],
    )
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, 1),
        _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, 3),
    ]
    progress = job_progress(job, attempts, preview_ready=False)
    assert [stage.state for stage in progress.stages] == ["succeeded", "succeeded", "succeeded", "running", "pending"]
    camera = progress.stages[3]
    assert camera.started_at == _T0 + timedelta(minutes=3) and camera.completed_at is None
    assert progress.updated_at == _T0 + timedelta(minutes=3) and progress.error is None


def test_failed_stage_carries_error_and_retry_resets_to_new_attempt(tmp_path: Path) -> None:
    error = ExecutionError(error_code="COLMAP_FAILED", stage_id=StageId.CAMERA_POSE, human_message="x", retryable=True)
    job = _job(
        tmp_path,
        status=JobStatus.FAILED,
        current_stage=StageId.CAMERA_POSE,
        completed_at=_T0 + timedelta(minutes=9),
        stage_artifacts=[_succeeded(s, 2) for s in MVP_PIPELINE[:3]],
    )
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, 3),
        _event(1, JobStatus.FAILED, StageId.CAMERA_POSE, 9, error),
    ]
    failed = job_progress(job, attempts, preview_ready=False)
    assert failed.stages[3].state == "failed" and failed.stages[3].error == error
    assert failed.error == error
    retried = job.model_copy(update={"status": JobStatus.QUEUED, "completed_at": None})
    retry_events = [*attempts, _event(2, JobStatus.QUEUED, StageId.CAMERA_POSE, 10)]
    fresh = job_progress(retried, retry_events, preview_ready=False)
    assert fresh.attempt == 2 and fresh.error is None
    # Frame set của attempt 1 hoàn tất trước khi attempt 2 bắt đầu nên không tính lại.
    assert [stage.state for stage in fresh.stages] == ["pending"] * 5


def test_stage_progress_reader_advances_job_and_waits_for_complete_line(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    running = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.CAMERA_POSE)
    )
    attempt = _Attempt(registry, SimpleNamespace(), running, tmp_path)
    progress_file = tmp_path / "preview.progress.jsonl"
    reader = _StageProgress(attempt, progress_file)
    reader.poll()  # Chưa có file: không làm gì.
    started = StageArtifact(stage_id=StageId.VISUAL_RECON, status="RUNNING", started_at=_T0)
    line = started.model_dump_json()
    progress_file.write_text(line[:10])
    reader.poll()
    assert registry.get_job(job.job_id).current_stage == StageId.CAMERA_POSE
    progress_file.write_text(line + "\n")
    reader.poll()
    assert attempt.job.current_stage == StageId.VISUAL_RECON
    assert registry.get_job(job.job_id) == attempt.job
    # Cancel song song: revision mới → reducer từ chối, không ghi đè.
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.CANCELLED))
    with pytest.raises(RuntimeStateConflictError):
        registry.record_stage_progress(attempt.job, StageId.CAMERA_POSE)
