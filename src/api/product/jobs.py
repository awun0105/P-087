"""Vòng đời job (PRODUCT-02): manifest, chuyển trạng thái, chạy lại, lịch sử attempt."""

from fastapi import APIRouter, Depends, HTTPException, status

from src.api import schemas
from src.api.auth import enforce_gpu_quota, record_gpu_run, require_contributor, require_editor
from src.api.ownership import authorize_job_mutation
from src.api.product import deps
from src.models.contracts.manifests import JobManifest, JobStatus
from src.models.contracts.retryability import is_execution_error_retryable
from src.services.orchestration.auth import UserRecord, actor_of
from src.services.orchestration.jobs import (
    InvalidTransitionError,
    JobLifecycleError,
    JobNotResolvableError,
    TransitionRequest,
)
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.projects import JobNotFoundError, PrivacyGateBlockedError

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobManifest)
def get_job(job_id: str) -> JobManifest:
    """JobManifest đầy đủ: status, stage và artifact đã publish."""
    try:
        return deps.registry().get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post(
    "/jobs/{job_id}/transitions",
    response_model=JobManifest,
    responses={409: {"model": schemas.ApiErrorResponse}, 422: {"model": schemas.ApiErrorResponse}},
)
def transition_job(
    job_id: str, request: TransitionRequest, user: UserRecord | None = Depends(require_contributor)
) -> JobManifest:
    """Chuyển trạng thái job theo bảng chuyển hợp lệ (PRODUCT-02).

    Runtime HTTP chỉ nhận cancel; progress do worker ghi qua durable registry.
    Constructor registry không DB là test seam cũ, không phải runtime API mode.
    """
    try:
        registry = deps.registry()
        authorize_job_mutation(user, registry, job_id, operation="hủy job")
        if registry.persistence is not None and (
            request.target_status != JobStatus.CANCELLED
            or request.current_stage is not None
            or request.error is not None
        ):
            raise HTTPException(
                status_code=409, detail="Runtime progress do worker sở hữu; dùng cancel/retry, không tự báo SUCCESS"
            )
        return registry.transition_job(job_id, request)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidTransitionError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except (JobNotResolvableError, RuntimeStateConflictError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/jobs/{job_id}/retry", response_model=JobManifest)
def retry_job(job_id: str, user: UserRecord | None = Depends(require_editor)) -> JobManifest:
    """Chạy lại một job FAILED có structured error được policy cho phép.

    Attempt mới được nối thêm, không ghi đè attempt cũ. Mỗi retry tính vào hạn mức GPU của Editor.
    """
    registry = deps.registry()
    try:
        authorize_job_mutation(user, registry, job_id, operation="thử lại job")
        job = registry.get_job(job_id)
        if job.status != JobStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Chỉ job FAILED mới có thể thử lại",
            )
        attempts = registry.list_job_attempts(job_id)
        latest_attempt = max((event.attempt for event in attempts), default=None)
        failure = next(
            (
                event.error
                for event in reversed(attempts)
                if event.attempt == latest_attempt and event.error is not None
            ),
            None,
        )
        if failure is None or not is_execution_error_retryable(failure):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Lỗi của lần chạy hiện tại chưa được phân loại là có thể thử lại",
            )
        enforce_gpu_quota(user)
        job = registry.transition_job(
            job_id,
            TransitionRequest(target_status=JobStatus.QUEUED),
            expected_checksum=job.job_manifest_checksum,
            requested_by=actor_of(user),
        )
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except JobLifecycleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except (RuntimeStateConflictError, PrivacyGateBlockedError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    record_gpu_run(user, job_id, {"kind": "job.retry"})
    return job


@router.get("/jobs/{job_id}/attempts", response_model=schemas.JobAttemptListResponse)
def list_job_attempts(job_id: str) -> schemas.JobAttemptListResponse:
    """Lịch sử attempt của job, cũ nhất trước."""
    try:
        attempts = deps.registry().list_job_attempts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return schemas.JobAttemptListResponse(job_id=job_id, attempts=attempts)
