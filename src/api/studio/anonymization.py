"""Xem các frame đã che khuôn mặt/biển số và chấp nhận trước khi job dựng 3D (AUD-18).

Từ chối không có route riêng: người dùng hủy job bằng `POST /jobs/{id}/transitions` như mọi job khác.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict

from src.api import schemas
from src.api.auth import require_contributor
from src.api.ownership import authorize_job_mutation
from src.api.studio import deps
from src.models.contracts.artifacts import ProductArtifactRef
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.jobs.anonymization_review import (
    AnonymizationReview,
    AnonymizationReviewError,
    accept,
    redacted_frame,
    review,
)
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.projects import JobNotFoundError

router = APIRouter()
_ERRORS = {404: {"model": schemas.ApiErrorResponse}, 409: {"model": schemas.ApiErrorResponse}}
_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


class AnonymizationAcceptRequest(BaseModel):
    """Checksum của bộ frame người dùng vừa xem (lấy từ GET)."""

    model_config = ConfigDict(extra="forbid")

    frame_set_checksum: str


class AnonymizationAcceptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acceptance: ProductArtifactRef


def _http(error: Exception) -> HTTPException:
    if isinstance(error, JobNotFoundError | AnonymizationReviewError | ArtifactStoreError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


_HANDLED = (JobNotFoundError, AnonymizationReviewError, ArtifactStoreError, RuntimeStateConflictError, ValueError)


@router.get("/jobs/{job_id}/anonymization", response_model=AnonymizationReview, responses=_ERRORS)
def get_anonymization_review(
    job_id: str, user: UserRecord | None = Depends(require_contributor)
) -> AnonymizationReview:
    """Danh sách frame có vùng bị che và trạng thái chờ xác nhận; 404 khi job không dùng bộ che."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="xem bản đã che của")
    try:
        return review(registry, job_id)
    except _HANDLED as error:
        raise _http(error) from error


@router.get("/jobs/{job_id}/anonymization/frames/{frame_name}", responses=_ERRORS)
def get_redacted_frame(
    job_id: str, frame_name: str, user: UserRecord | None = Depends(require_contributor)
) -> Response:
    """Ảnh của một frame đã che. Chỉ trả frame thuộc bộ frame đã che của chính job."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="xem bản đã che của")
    try:
        reference = redacted_frame(registry, job_id, frame_name)
        resolver = registry.runtime_resolver
        if resolver.remote is not None:
            key = resolver.relative_key(reference.artifact_uri)
            if resolver.remote.store.head(resolver.remote.key(key)) is not None:
                link = resolver.remote.presign(key, deps.settings().artifact_presign_seconds)
                return RedirectResponse(link, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        path = resolver.require(reference)
    except _HANDLED as error:
        raise _http(error) from error
    return FileResponse(
        path,
        media_type=_MEDIA.get(frame_name.rsplit(".", 1)[-1].lower(), "application/octet-stream"),
        headers={"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/jobs/{job_id}/anonymization/accept", response_model=AnonymizationAcceptResponse, responses=_ERRORS)
def accept_anonymization(
    job_id: str, request: AnonymizationAcceptRequest, user: UserRecord | None = Depends(require_contributor)
) -> AnonymizationAcceptResponse:
    """Người upload xác nhận bản đã che đủ dùng; worker tiếp tục dựng 3D từ đúng bộ frame đó."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="xác nhận bản đã che của")
    try:
        reference = accept(registry, job_id, request.frame_set_checksum, user.user_id if user is not None else None)
    except _HANDLED as error:
        raise _http(error) from error
    return AnonymizationAcceptResponse(acceptance=reference)
