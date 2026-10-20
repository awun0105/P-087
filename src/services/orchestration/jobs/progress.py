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
from src.models.contracts.retryability import is_execution_error_retryable
from src.services.orchestration.jobs.admission import ResourceWait
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.queue import QueuePosition

#: 5 stage tới preview 3DGS (video mẫu, export bundle dùng danh sách này).
MVP_PIPELINE: tuple[StageId, ...] = (
    StageId.INPUT_VALIDATE,
    StageId.PRIVACY_GATE,
    StageId.FRAME_EXTRACT,
    StageId.CAMERA_POSE,
    StageId.VISUAL_RECON,
)
#: Tiến trình job Studio: preview + bước xác nhận tỉ lệ mét (REC-06) chờ người dùng.
#: Studio: sau preview là xác nhận tỉ lệ (người dùng), hình học/collision + bundle (REC-05/10),
#: rồi tách vật thể ứng viên (SAMPro3D/SAM2, ADR 0006).
STUDIO_PIPELINE: tuple[StageId, ...] = (
    *MVP_PIPELINE,
    StageId.METRIC_CANONICALIZE,
    StageId.RGB_GEOMETRY,
    StageId.OBJECT_EXTRACT,
)


def studio_pipeline(job: JobManifest) -> tuple[StageId, ...]:
    """Job LiDAR thêm ingest và, với job mới, QA calibration sau bước tách frame.

    Job cũ có artifact ingest nhưng chưa có report QA vẫn giữ nguyên timeline; job đang hoặc đã chạy QA hiển thị cả hai.
    """
    has_ingest = any(stage.stage_id == StageId.LIDAR_INGEST for stage in job.stage_artifacts)
    has_qa = job.current_stage == StageId.LIDAR_CALIBRATION_QA or any(
        stage.stage_id == StageId.LIDAR_CALIBRATION_QA for stage in job.stage_artifacts
    )
    if job.current_stage == StageId.LIDAR_INGEST:
        has_ingest = True
    if not has_ingest and not has_qa:
        return STUDIO_PIPELINE
    index = STUDIO_PIPELINE.index(StageId.FRAME_EXTRACT) + 1
    lidar_stages = (StageId.LIDAR_INGEST, StageId.LIDAR_CALIBRATION_QA) if has_qa else (StageId.LIDAR_INGEST,)
    return (*STUDIO_PIPELINE[:index], *lidar_stages, *STUDIO_PIPELINE[index:])


StageState = Literal["pending", "running", "waiting", "succeeded", "failed", "cancelled"]
#: Lý do pipeline chờ: người xác nhận, worker chưa đủ tài nguyên, hoặc chưa có GPU đúng runtime của job (T-040).
WaitingFor = Literal["metric_confirmation", "anonymization_review", "runtime", "resources"]


class StageProgress(BaseModel):
    """Trạng thái một stage trong attempt hiện tại."""

    model_config = ConfigDict(extra="forbid")

    stage_id: StageId
    state: StageState
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: ExecutionError | None = None
    note: str | None = None


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
    resource_wait: ResourceWait | None = None
    #: Vị trí trong hàng đợi khi job đang chờ worker; None khi job đang chạy, đã xong hoặc chờ người dùng.
    queue: QueuePosition | None = None
    error: ExecutionError | None = None


#: Loại artifact ghi nhận người dùng đã xem và chấp nhận bản frame đã che (AUD-18).
ANONYMIZATION_ACCEPTANCE_TYPE = "SanitizationAcceptance"
_SANITIZED_FRAME_SET_SUFFIX = "/rec02a/sanitized/frame_set.json"


def sanitized_frame_stage(job: JobManifest) -> StageArtifact | None:
    """Stage tách frame của job khi frame set là bản đã che khuôn mặt/biển số; None nếu job không chọn che."""
    return next(
        (
            stage
            for stage in reversed(job.stage_artifacts)
            if stage.stage_id == StageId.FRAME_EXTRACT
            and stage.status == StageStatus.SUCCEEDED
            and stage.artifact_type == "NormalizedRGBFrameSet"
            and (stage.artifact_uri or "").endswith(_SANITIZED_FRAME_SET_SUFFIX)
        ),
        None,
    )


def anonymization_acceptance_stage(job: JobManifest) -> StageArtifact | None:
    """Bản ghi người dùng đã chấp nhận bản đã che, nếu có."""
    return next(
        (
            stage
            for stage in job.stage_artifacts
            if stage.stage_id == StageId.PRIVACY_GATE
            and stage.status == StageStatus.SUCCEEDED
            and stage.artifact_type == ANONYMIZATION_ACCEPTANCE_TYPE
        ),
        None,
    )


def awaiting_anonymization_review(job: JobManifest) -> bool:
    """Frame đã che xong, job dừng trước COLMAP chờ người dùng xem và chấp nhận bản đã che.

    QUEUED cũng tính (job được retry trước khi có chấp nhận): worker không được dựng 3D từ bản chưa ai xem.
    """
    if sanitized_frame_stage(job) is None or anonymization_acceptance_stage(job) is not None:
        return False
    return job.status == JobStatus.QUEUED or (
        job.status == JobStatus.RUNNING and job.current_stage == StageId.FRAME_EXTRACT
    )


def awaiting_reviewed_preview(job: JobManifest) -> bool:
    """Người dùng đã chấp nhận bản đã che; job RUNNING đang chờ worker nhận để dựng preview."""
    return (
        job.status == JobStatus.RUNNING
        and job.current_stage == StageId.FRAME_EXTRACT
        and sanitized_frame_stage(job) is not None
        and anonymization_acceptance_stage(job) is not None
    )


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


def job_progress(
    job: JobManifest,
    attempts: list[JobAttemptRecord],
    preview_ready: bool,
    resource_wait: ResourceWait | None = None,
    queue: QueuePosition | None = None,
    heartbeat_at: datetime | None = None,
    runtime_wait: bool = False,
    notes: dict[StageId, str] | None = None,
) -> JobProgress:
    """Chiếu JobManifest + journal thành tiến trình từng stage của attempt hiện tại.

    `runtime_wait`: không worker nào đang sống chạy được runtime của job (người gọi tính từ `r2s_worker_runtimes`).
    """
    events = _current_attempt(attempts)
    pipeline = studio_pipeline(job)
    attempt_start = next((event.recorded_at for event in events if event.status == JobStatus.QUEUED), None)
    # Retry bước hoàn tất bắt đầu thẳng ở hình học: các stage trước đó không chạy lại
    # trong attempt này, kết quả của chúng (preview, xác nhận) là artifact attempt trước.
    first_running = next((event.current_stage for event in events if event.status == JobStatus.RUNNING), None)
    carried = set(pipeline[: pipeline.index(first_running)]) if first_running in pipeline else set()
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
            if event.stage_started_at is not None:
                stage_starts[event.current_stage] = event.stage_started_at
            else:
                stage_starts.setdefault(event.current_stage, event.recorded_at)
    failure = next((event.error for event in reversed(events) if event.error is not None), None)
    terminal_at = next(
        (
            event.recorded_at
            for event in reversed(events)
            if event.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
        ),
        job.completed_at,
    )
    if failure is not None and failure.retryable != is_execution_error_retryable(failure):
        # Retry flags follow today's policy in both directions (lower and raise) so the UI agrees with POST /retry.
        failure = failure.model_copy(update={"retryable": not failure.retryable})
    # Pipeline chạy tuần tự: journal cho thấy đã sang stage sau → stage trước đã xong,
    # dù StageArtifact của nó chỉ được commit cùng receipt ở cuối attempt.
    advanced = {
        stage_id: stage_starts[later]
        for index, stage_id in enumerate(pipeline)
        if stage_id in stage_starts
        for later in pipeline[index + 1 :]
        if later in stage_starts
    }
    waiting = awaiting_metric_confirmation(job, preview_ready)
    reviewing = awaiting_anonymization_review(job)
    resources = (
        resource_wait
        if resource_wait is not None
        and resource_wait.job_manifest_checksum == job.job_manifest_checksum
        and not reviewing
        and (job.status == JobStatus.QUEUED or awaiting_finalize(job) or awaiting_reviewed_preview(job))
        else None
    )
    # Snapshot chờ tài nguyên chỉ do worker đang sống ghi, nên job đó đã có máy xét và không thiếu runtime.
    runtime_pending = (
        runtime_wait
        and resources is None
        and not waiting
        and not reviewing
        and (job.status == JobStatus.QUEUED or awaiting_finalize(job) or awaiting_reviewed_preview(job))
    )
    stages: list[StageProgress] = []
    for stage_id in pipeline:
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
            elif resources is not None and state == "running":
                state = "pending"
        if reviewing and stage_id == StageId.FRAME_EXTRACT:
            # Frame đã tách và che xong nhưng bước này chưa khép lại: đang chờ người dùng xem bản đã che.
            state = "waiting"
        if stage_id == job.current_stage and state in {"failed", "cancelled"} and completed_at is None:
            completed_at = terminal_at
        stages.append(
            StageProgress(
                stage_id=stage_id,
                state=state,
                started_at=(record.started_at if record is not None else None) or stage_starts.get(stage_id),
                completed_at=completed_at,
                error=error,
                note=(notes or {}).get(stage_id),
            )
        )
    base_updated = resources.checked_at if resources else (events[-1].recorded_at if events else job.started_at)
    if heartbeat_at is not None and job.status == JobStatus.RUNNING:
        updated_at = max(base_updated, heartbeat_at)
    else:
        updated_at = base_updated

    return JobProgress(
        job_id=job.job_id,
        status=job.status,
        current_stage=job.current_stage,
        attempt=events[-1].attempt if events else 1,
        started_at=job.started_at,
        updated_at=updated_at,
        completed_at=job.completed_at,
        stages=stages,
        preview_ready=preview_ready,
        waiting_for=(
            "metric_confirmation"
            if waiting
            else (
                "anonymization_review"
                if reviewing
                else ("runtime" if runtime_pending else ("resources" if resources else None))
            )
        ),
        resource_wait=resources,
        queue=(
            queue
            if not reviewing
            and (job.status == JobStatus.QUEUED or awaiting_finalize(job) or awaiting_reviewed_preview(job))
            else None
        ),
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
