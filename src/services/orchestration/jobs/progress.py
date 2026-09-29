"""Tiến trình theo stage của pipeline MVP (video → 3DGS preview), suy từ state bền vững.

PRODUCT-09: không có phần trăm ước đoán. Mỗi stage chỉ có trạng thái quan sát được
(pending/running/waiting/succeeded/failed/cancelled) cùng thời điểm lấy từ journal
attempt và StageArtifact đã publish.

Sau preview 3DGS, job ở `RUNNING` tại `ST-METRIC-CANONICALIZE` là **chủ đích**: pipeline
chờ người xác nhận tỉ lệ mét (REC-06) rồi mới đi tiếp. `JobStatus` là shared contract nên
không thêm trạng thái; tiến trình báo `waiting_for="metric_confirmation"` để UI hiển
thị "chờ bạn" thay vì "đang chạy".
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.manifests import (
    ExecutionError,
    JobManifest,
    JobStatus,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.services.orchestration.jobs.models import JobAttemptRecord

#: 5 stage tới preview 3DGS (video mẫu, export bundle dùng danh sách này).
MVP_PIPELINE: tuple[StageId, ...] = (
    StageId.INPUT_VALIDATE,
    StageId.PRIVACY_GATE,
    StageId.FRAME_EXTRACT,
    StageId.CAMERA_POSE,
    StageId.VISUAL_RECON,
)
#: Tiến trình job Studio: preview + bước xác nhận tỉ lệ mét (REC-06) chờ người dùng.
#: Studio: sau preview là xác nhận tỉ lệ (người dùng), rồi hình học/collision + bundle (REC-05/10).
STUDIO_PIPELINE: tuple[StageId, ...] = (*MVP_PIPELINE, StageId.METRIC_CANONICALIZE, StageId.RGB_GEOMETRY)

StageState = Literal["pending", "running", "waiting", "succeeded", "failed", "cancelled"]
#: Việc pipeline đang chờ con người làm (không phải worker).
WaitingFor = Literal["metric_confirmation"]


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
    waiting_for: WaitingFor | None = None
    error: ExecutionError | None = None


def awaiting_metric_confirmation(job: JobManifest, preview_ready: bool) -> bool:
    """Preview xong, job dừng ở REC-06 chờ người chọn A/B và nhập khoảng cách thật."""
    metric_done = any(stage.stage_id == StageId.METRIC_CANONICALIZE for stage in job.stage_artifacts)
    return (
        preview_ready
        and job.status == JobStatus.RUNNING
        and job.current_stage == StageId.METRIC_CANONICALIZE
        and not metric_done
    )


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
    # Retry bước hoàn tất bắt đầu thẳng ở hình học: các stage trước đó không chạy lại
    # trong attempt này, kết quả của chúng (preview, xác nhận) là artifact attempt trước.
    first_running = next((event.current_stage for event in events if event.status == JobStatus.RUNNING), None)
    carried = (
        set(STUDIO_PIPELINE[: STUDIO_PIPELINE.index(first_running)]) if first_running in STUDIO_PIPELINE else set()
    )
    records = {
        stage.stage_id: stage
        for stage in job.stage_artifacts
        # Chỉ tính record của attempt hiện tại khi có mốc thời gian để so.
        if stage.stage_id in carried
        or attempt_start is None
        or stage.completed_at is None
        or stage.completed_at >= attempt_start
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
        for index, stage_id in enumerate(STUDIO_PIPELINE)
        if stage_id in stage_starts
        for later in STUDIO_PIPELINE[index + 1 :]
        if later in stage_starts
    }
    waiting = awaiting_metric_confirmation(job, preview_ready)
    stages: list[StageProgress] = []
    for stage_id in STUDIO_PIPELINE:
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
            if waiting:
                state = "waiting"
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
        waiting_for="metric_confirmation" if waiting else None,
        error=failure if job.status == JobStatus.FAILED else None,
    )


def metric_confirmation_stage(job: JobManifest) -> StageArtifact | None:
    """StageArtifact xác nhận tỉ lệ (REC-06) của job, nếu người dùng đã xác nhận."""
    return next(
        (
            stage
            for stage in job.stage_artifacts
            if stage.stage_id == StageId.METRIC_CANONICALIZE
            and stage.status == StageStatus.SUCCEEDED
            and stage.artifact_type == "RGBMetricConfirmation"
        ),
        None,
    )


def _has_bundle(job: JobManifest) -> bool:
    return any(stage.artifact_type == "ReconstructionBundle" for stage in job.stage_artifacts)


def awaiting_finalize(job: JobManifest) -> bool:
    """Việc cho queue ở bước hoàn tất EX-REC.

    - RUNNING ở stage xác nhận, đã có bản xác nhận: lần chạy đầu sau khi người dùng xác nhận.
    - QUEUED (retry sau khi bước hoàn tất lỗi), đã có bản xác nhận, chưa có bundle: chỉ
      chạy lại bước hoàn tất; preview và xác nhận là artifact bất biến của attempt trước.
    """
    if metric_confirmation_stage(job) is None or _has_bundle(job):
        return False
    return job.status == JobStatus.QUEUED or (
        job.status == JobStatus.RUNNING and job.current_stage == StageId.METRIC_CANONICALIZE
    )
