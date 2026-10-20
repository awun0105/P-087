"""Tiến trình theo stage: suy từ JobManifest + journal, không có phần trăm ước đoán."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.services.orchestration.projects.registry as registry_module
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import ExecutionError, JobStatus, StageArtifact, StageId
from src.models.contracts.preview import PreviewWorkerReceipt
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import JobAttemptRecord, TransitionRequest
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.progress import MVP_PIPELINE, job_progress
from src.services.orchestration.jobs.runner import _Attempt, _StageProgress
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


def _event(
    attempt: int,
    status: JobStatus,
    stage: StageId,
    minutes: int,
    error: ExecutionError | None = None,
    *,
    stage_started_at: datetime | None = None,
):  # noqa: ANN202
    return JobAttemptRecord(
        attempt=attempt,
        status=status,
        current_stage=stage,
        recorded_at=_T0 + timedelta(minutes=minutes),
        error=error,
        stage_started_at=stage_started_at,
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
        _event(
            1,
            JobStatus.RUNNING,
            StageId.CAMERA_POSE,
            3,
            stage_started_at=_T0 + timedelta(minutes=2, seconds=30),
        ),
    ]
    progress = job_progress(job, attempts, preview_ready=False)
    assert [stage.state for stage in progress.stages] == [
        "succeeded", "succeeded", "succeeded", "running", "pending", "pending", "pending", "pending"
    ]  # fmt: skip
    camera = progress.stages[3]
    assert camera.started_at == _T0 + timedelta(minutes=2, seconds=30) and camera.completed_at is None
    assert progress.updated_at == _T0 + timedelta(minutes=3) and progress.error is None


def test_completed_stage_prefers_worker_artifact_start_over_claim_time(tmp_path: Path) -> None:
    job = _job(
        tmp_path,
        status=JobStatus.RUNNING,
        current_stage=StageId.CAMERA_POSE,
        stage_artifacts=[
            StageArtifact(
                stage_id=StageId.INPUT_VALIDATE,
                status="SUCCEEDED",
                artifact_type="InputValidation",
                artifact_uri="artifact://jobs/job-p/input/validation.json",
                artifact_checksum="sha256:" + "a" * 64,
                data_class="derived",
                started_at=_T0 + timedelta(seconds=10),
                completed_at=_T0 + timedelta(seconds=30),
            )
        ],
    )
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, 1),
    ]

    progress = job_progress(job, attempts, preview_ready=False)

    assert progress.stages[0].started_at == _T0 + timedelta(seconds=10)


def test_failed_stage_carries_error_and_retry_resets_to_new_attempt(tmp_path: Path) -> None:
    error = ExecutionError(error_code="COLMAP_TIMEOUT", stage_id=StageId.CAMERA_POSE, human_message="x", retryable=True)
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
    assert [stage.state for stage in fresh.stages] == ["pending"] * 8


def test_progress_hides_legacy_retry_flag_for_input_error(tmp_path: Path) -> None:
    error = ExecutionError(
        error_code="FRAME_QUALITY_MISMATCH",
        stage_id=StageId.CAMERA_POSE,
        human_message="source identity mismatch",
        retryable=True,
    )
    job = _job(
        tmp_path,
        status=JobStatus.FAILED,
        current_stage=StageId.CAMERA_POSE,
        completed_at=_T0 + timedelta(minutes=9),
        stage_artifacts=[_succeeded(stage, 2) for stage in MVP_PIPELINE[:3]],
    )
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, 3),
        _event(1, JobStatus.FAILED, StageId.CAMERA_POSE, 9, error),
    ]

    failed = job_progress(job, attempts, preview_ready=False)

    assert failed.error is not None and failed.error.retryable is False
    assert failed.stages[3].error is not None and failed.stages[3].error.retryable is False


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
    started_at = datetime.now(UTC)
    started = StageArtifact(stage_id=StageId.VISUAL_RECON, status="RUNNING", started_at=started_at)
    line = started.model_dump_json()
    progress_file.write_text(line[:10])
    reader.poll()
    assert registry.get_job(job.job_id).current_stage == StageId.CAMERA_POSE
    progress_file.write_text(line + "\n")
    reader.poll()
    assert attempt.job.current_stage == StageId.VISUAL_RECON
    assert registry.get_job(job.job_id) == attempt.job
    visual_start = registry.list_job_attempts(job.job_id)[-1]
    assert visual_start.stage_started_at == started_at
    assert visual_start.recorded_at >= started_at
    # Cancel song song: revision mới → reducer từ chối, không ghi đè.
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.CANCELLED))
    with pytest.raises(RuntimeStateConflictError):
        registry.record_stage_progress(attempt.job, StageId.CAMERA_POSE)


def test_stage_progress_records_precise_start_when_stage_was_already_claimed(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    running = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.CAMERA_POSE)
    )
    started_at = datetime.now(UTC)

    updated = registry.record_stage_progress(running, StageId.CAMERA_POSE, started_at=started_at)

    event = registry.list_job_attempts(job.job_id)[-1]
    assert updated.current_stage == StageId.CAMERA_POSE
    assert event.stage_started_at == started_at
    assert event.recorded_at >= started_at


def test_preview_commit_persists_consumer_verified_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _registry(tmp_path)
    queued = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    running = registry.transition_job(
        queued.job_id, TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.VISUAL_RECON)
    )
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(name: str, artifact_type: str) -> ProductArtifactRef:
        payload = name.encode()
        reference = ProductArtifactRef(
            artifact_type=artifact_type,
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{queued.job_id}/attempts/preview-1/{name}.json",
            artifact_checksum=sha256_bytes(payload),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.VISUAL_RECON,
            job_id=queued.job_id,
        )
        store.publish(reference, payload)
        return reference

    result_ref = publish("result", "PreparedPreviewResult")
    preview_ref = publish("preview", "ReconstructionPreview")
    receipt = PreviewWorkerReceipt(
        job_id=queued.job_id,
        attempt_id="preview-1",
        source_input_checksum=running.input_manifest_checksum,
        result_ref=result_ref,
        stage_artifacts=[],
        preview_ref=preview_ref,
    )
    monkeypatch.setattr(registry_module, "load_job_preview", lambda *_: None)
    verified_at = datetime.now(UTC)

    registry.record_preview(running, receipt, verified_at=verified_at)

    event = registry.list_job_attempts(queued.job_id)[-1]
    visual = next(
        stage
        for stage in registry.get_job(queued.job_id).stage_artifacts
        if stage.artifact_type == "ReconstructionPreview"
    )
    assert event.preview_verified_at == verified_at
    assert visual.completed_at == verified_at


def test_stage_left_behind_in_journal_counts_as_done_before_receipt(tmp_path: Path) -> None:
    """COLMAP xong (journal đã sang VISUAL_RECON) nhưng receipt chưa commit StageArtifact."""
    job = _job(
        tmp_path,
        status=JobStatus.RUNNING,
        current_stage=StageId.VISUAL_RECON,
        stage_artifacts=[_succeeded(s, 2) for s in MVP_PIPELINE[:3]],
    )
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, 1),
        _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, 3),
        _event(1, JobStatus.RUNNING, StageId.VISUAL_RECON, 8),
    ]
    progress = job_progress(job, attempts, preview_ready=False)
    assert [stage.state for stage in progress.stages] == ["succeeded"] * 4 + [
        "running",
        "pending",
        "pending",
        "pending",
    ]
    camera = progress.stages[3]
    assert camera.started_at == _T0 + timedelta(minutes=3)
    assert camera.completed_at == _T0 + timedelta(minutes=8)


def test_preview_ready_job_waits_for_metric_confirmation(tmp_path: Path) -> None:
    """Sau preview, job RUNNING ở REC-06 là chờ người xác nhận tỉ lệ, không phải đang chạy."""
    job = _job(
        tmp_path,
        status=JobStatus.RUNNING,
        current_stage=StageId.METRIC_CANONICALIZE,
        stage_artifacts=[_succeeded(s, 2) for s in MVP_PIPELINE],
    )
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, 1),
        _event(1, JobStatus.RUNNING, StageId.METRIC_CANONICALIZE, 9),
    ]
    waiting = job_progress(job, attempts, preview_ready=True)
    assert waiting.waiting_for == "metric_confirmation"
    assert [stage.state for stage in waiting.stages] == ["succeeded"] * 5 + ["waiting", "pending", "pending"]

    # Chưa có preview (vd đang dựng) → không báo chờ người.
    not_ready = job_progress(job, attempts, preview_ready=False)
    assert not_ready.waiting_for is None and not_ready.stages[-3].state == "running"


def test_running_job_advances_updated_at_from_heartbeat(tmp_path: Path) -> None:
    """Worker heartbeat giữ updated_at tươi mới trong suốt thời gian job đang chạy."""
    job = _job(tmp_path, status=JobStatus.RUNNING, current_stage=StageId.VISUAL_RECON)
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.VISUAL_RECON, 2),
    ]
    # Khi không có heartbeat, updated_at lấy từ event gần nhất (phút 2)
    progress_no_hb = job_progress(job, attempts, preview_ready=False)
    assert progress_no_hb.updated_at == _T0 + timedelta(minutes=2)

    # Khi có heartbeat (ví dụ phút 15), updated_at phải lấy theo heartbeat mới nhất
    hb_time = _T0 + timedelta(minutes=15)
    progress_with_hb = job_progress(job, attempts, preview_ready=False, heartbeat_at=hb_time)
    assert progress_with_hb.updated_at == hb_time


def test_progress_upgrades_legacy_shutdown_failure(tmp_path: Path) -> None:
    """A job stopped by a worker SIGTERM before T-047 shows Retry, matching POST /retry."""
    error = ExecutionError(
        error_code="PREVIEW_RUNNER_FAILED",
        stage_id=StageId.CAMERA_POSE,
        human_message="Worker dừng trước checkpoint hợp lệ",
        retryable=False,
        details={"exception_type": "KeyboardInterrupt"},
    )
    job = _job(
        tmp_path,
        status=JobStatus.FAILED,
        current_stage=StageId.CAMERA_POSE,
        completed_at=_T0 + timedelta(minutes=9),
        stage_artifacts=[_succeeded(stage, 2) for stage in MVP_PIPELINE[:3]],
    )
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, 3),
        _event(1, JobStatus.FAILED, StageId.CAMERA_POSE, 9, error),
    ]

    failed = job_progress(job, attempts, preview_ready=False)

    assert failed.error is not None and failed.error.retryable is True
