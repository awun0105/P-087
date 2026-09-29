"""Xác nhận tỉ lệ mét của scene (REC-06): xem trước rồi xác nhận, sau khi xem 3DGS.

Điểm chọn nằm trong hệ tọa độ gốc của file 3DGS (SfM) như viewer trả về. Người xác
nhận lấy từ phiên đăng nhập, không nhận từ body.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from src.api import schemas
from src.api.auth import require_editor
from src.api.studio import deps
from src.models.contracts.artifacts import ProductArtifactRef
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.metric import (
    MetricConfirmationError,
    MetricConfirmationService,
    MetricPreviewView,
)
from src.services.orchestration.projects import JobNotFoundError
from src.services.reconstruction import UserMetricInput

router = APIRouter()
_ERRORS = {404: {"model": schemas.ApiErrorResponse}, 409: {"model": schemas.ApiErrorResponse}}


class MetricConfirmRequest(BaseModel):
    """Đúng các điểm đã xem trước + checksum của bản xem trước đó."""

    model_config = ConfigDict(extra="forbid")

    input: UserMetricInput
    preview_checksum: str


class MetricConfirmResponse(BaseModel):
    """Bản xác nhận REC-06 bất biến đã ghi vào job."""

    model_config = ConfigDict(extra="forbid")

    confirmation: ProductArtifactRef


def _service(job_id: str) -> MetricConfirmationService:
    registry = deps.registry()
    try:
        registry.get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return MetricConfirmationService(registry)


@router.post("/jobs/{job_id}/metric/preview", response_model=MetricPreviewView, responses=_ERRORS)
def preview_metric(job_id: str, request: UserMetricInput) -> MetricPreviewView:
    """Tính scale/khung sàn từ điểm chọn; chưa ghi xác nhận."""
    try:
        return _service(job_id).preview(job_id, request)
    except MetricConfirmationError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/jobs/{job_id}/metric/confirm", response_model=MetricConfirmResponse, responses=_ERRORS)
def confirm_metric(
    job_id: str, request: MetricConfirmRequest, user: UserRecord | None = Depends(require_editor)
) -> MetricConfirmResponse:
    """Xác nhận đúng bản xem trước; job tiếp tục sang dựng hình học ở worker."""
    role: Literal["editor", "reviewer"] | None = user.role if user is not None else None
    try:
        reference = _service(job_id).confirm(
            job_id,
            request.input,
            request.preview_checksum,
            user.user_id if user is not None else None,
            role,
            deps.settings().auth_required,
        )
    except (MetricConfirmationError, RuntimeStateConflictError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return MetricConfirmResponse(confirmation=reference)
