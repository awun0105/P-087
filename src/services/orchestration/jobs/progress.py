"""Tiến trình theo stage của pipeline MVP (video → 3DGS preview), suy từ state bền vững.

PRODUCT-09: không có phần trăm ước đoán. Mỗi stage chỉ có trạng thái quan sát được
(pending/running/succeeded/failed/cancelled) cùng thời điểm lấy từ journal attempt
và StageArtifact đã publish.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.manifests import ExecutionError, JobManifest, JobStatus, StageId, StageStatus
from src.services.orchestration.jobs.models import JobAttemptRecord

#: Thứ tự stage của lát cắt MVP; stage sau metric/SceneIR chưa thuộc Studio MVP.
MVP_PIPELINE: tuple[StageId, ...] = (
    StageId.INPUT_VALIDATE,
    StageId.PRIVACY_GATE,
    StageId.FRAME_EXTRACT,
    StageId.CAMERA_POSE,
    StageId.VISUAL_RECON,
)

StageState = Literal["pending", "running", "succeeded", "failed", "cancelled"]


class StageProgress(BaseModel):
    """Trạng thái một stage trong attempt hiện tại."""

    model_config = ConfigDict(extra="forbid")

    stage_id: StageId
    state: StageState
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: ExecutionError | None = None


class JobProgress(BaseModel):
    """Tiến trình job cho UI; `preview_ready` khi 3DGS preview đã được commit."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus
    current_stage: StageId
    attempt: int
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    stages: list[StageProgress]
    preview_ready: bool
    error: ExecutionError | None = None


def _current_attempt(attempts: list[JobAttemptRecord]) -> list[JobAttemptRecord]:
    """Event của attempt mới nhất (retry mở attempt mới, không sửa attempt cũ)."""
    if not attempts:
        return []
    latest = attempts[-1].attempt
    return [event for event in attempts if event.attempt == latest]


def job_progress(job: JobManifest, attempts: list[JobAttemptRecord], preview_ready: bool) -> JobProgress:
    """Chiếu JobManifest + journal thành tiến trình từng stage của attempt hiện tại."""
    events = _current_attempt(attempts)
    attempt_start = next((event.recorded_at for event in events if event.status == JobStatus.QUEUED), None)
    records = {
        stage.stage_id: stage
        for stage in job.stage_artifacts
        # Chỉ tính record của attempt hiện tại khi có mốc thời gian để so.
        if attempt_start is None or stage.completed_at is None or stage.completed_at >= attempt_start
    }
    stage_starts: dict[StageId, datetime] = {}
    for event in events:
        if event.status == JobStatus.RUNNING:
            stage_starts.setdefault(event.current_stage, event.recorded_at)
    failure = next((event.error for event in reversed(events) if event.error is not None), None)
    # Pipeline chạy tuần tự: journal cho thấy đã sang stage sau → stage trước đã xong,
    # dù StageArtifact của nó chỉ được commit cùng receipt ở cuối attempt.
    advanced = {
        stage_id: stage_starts[later]
        for index, stage_id in enumerate(MVP_PIPELINE)
        if stage_id in stage_starts
        for later in MVP_PIPELINE[index + 1 :]
        if later in stage_starts
    }
    stages: list[StageProgress] = []
    for stage_id in MVP_PIPELINE:
        record = records.get(stage_id)
        state: StageState = "pending"
        error = None
        completed_at = record.completed_at if record is not None else None
        if record is not None and record.status == StageStatus.SUCCEEDED:
            state = "succeeded"
        elif record is None and stage_id in advanced and job.current_stage != stage_id:
            state, completed_at = "succeeded", advanced[stage_id]
        elif record is not None and record.status == StageStatus.FAILED:
            state, error = "failed", record.error
        elif job.current_stage == stage_id:
            state = {
                JobStatus.RUNNING: "running",
                JobStatus.FAILED: "failed",
                JobStatus.CANCELLED: "cancelled",
            }.get(job.status, "pending")
            if state == "failed":
                error = failure
        stages.append(
            StageProgress(
                stage_id=stage_id,
                state=state,
                started_at=stage_starts.get(stage_id),
                completed_at=completed_at,
                error=error,
            )
        )
    return JobProgress(
        job_id=job.job_id,
        status=job.status,
        current_stage=job.current_stage,
        attempt=events[-1].attempt if events else 1,
        started_at=job.started_at,
        updated_at=events[-1].recorded_at if events else job.started_at,
        completed_at=job.completed_at,
        stages=stages,
        preview_ready=preview_ready,
        error=failure if job.status == JobStatus.FAILED else None,
    )
