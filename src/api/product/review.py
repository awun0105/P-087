"""Validation, review và release theo hợp đồng UI P0 (PRODUCT-05/10/11).

Hai lệnh ghi (`review/{action}`, `release`) cố ý fail closed bằng 501: luồng duyệt và phát hành thật nằm ở
`src/api/studio/review.py`.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from src.api import schemas
from src.api.auth import require_reviewer
from src.api.product import deps
from src.services.orchestration.artifacts import ArtifactStoreError

router = APIRouter()


@router.get("/jobs/{job_id}/validation", response_model=schemas.ValidationStateResponse)
def get_job_validation(job_id: str) -> schemas.ValidationStateResponse:
    """Báo cáo validation của job, kèm cờ nói rõ Isaac đã chạy thật hay chưa."""
    deps.job_or_404(job_id)
    try:
        return schemas.validation_state(job_id, deps.registry().get_validation_report(job_id))
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/jobs/{job_id}/review", response_model=schemas.ReviewStateResponse)
def get_job_review(job_id: str) -> schemas.ReviewStateResponse:
    """Trạng thái review của job. Approval ở đây là bản synthetic của fixture."""
    deps.job_or_404(job_id)
    try:
        return schemas.review_state(job_id, deps.registry().get_approval_record(job_id))
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/jobs/{job_id}/review/{action}",
    response_model=schemas.ReviewStateResponse,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
    dependencies=[Depends(require_reviewer)],
)
def review_action(
    job_id: str,
    action: str,
    request: schemas.ReviewActionRequest,
) -> schemas.ReviewStateResponse:
    """Không dùng fixture approval làm authorization hoặc kết quả submit thật."""
    deps.job_or_404(job_id)
    if action not in {"submit", "approve", "reject"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"action review {action} không được hỗ trợ",
        )
    if action == "reject" and not request.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="lý do từ chối không được để trống",
        )
    raise HTTPException(
        status_code=501, detail="Review authorization/persistence chưa triển khai; không tạo approval giả"
    )


@router.post(
    "/jobs/{job_id}/release",
    response_model=schemas.ReleaseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
    dependencies=[Depends(require_reviewer)],
)
def release_candidate(
    job_id: str,
    request: schemas.ReleaseRequest,
) -> schemas.ReleaseResponse:
    """Fail closed tới khi có producer ReleaseManifest và authorization thật."""
    deps.job_or_404(job_id)
    raise HTTPException(
        status_code=501, detail="Release sealing chưa triển khai; không phát hành manifest/checksum giả"
    )
