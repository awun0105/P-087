"""Duyệt và phát hành trong Studio (PRODUCT-10/11).

Quyết định luôn cần **Reviewer đã đăng nhập**, kể cả khi `AUTH_REQUIRED=false` (chế độ local):
approval vô danh không phải quyết định của con người có quyền (PRD §3.4). reviewer_id lấy từ phiên,
không nhận từ payload.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from src.api import auth
from src.api.studio import deps
from src.models.contracts.release import ApprovalDecision
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.auth.service import has_role
from src.services.orchestration.projects import JobNotFoundError
from src.services.orchestration.review.workflow import ReviewError, ReviewState, decide, review_state, seal_release
from src.services.orchestration.scene.errors import SceneNotAvailableError

router = APIRouter()


class ReviewDecisionRequest(BaseModel):
    """Quyết định trên đúng gói + báo cáo đang hiển thị (checksum để phát hiện màn hình cũ)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "REJECT"]
    candidate_checksum: str
    validation_report_checksum: str
    accepted_warning_ids: list[str] = []
    reason: str | None = None


def _reviewer(request: Request) -> UserRecord:
    user = auth.current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Đăng nhập tài khoản Reviewer để duyệt")
    if not has_role(user, "reviewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chỉ Reviewer được duyệt và phát hành")
    return user


def _state(job_id: str) -> ReviewState:
    try:
        return review_state(deps.registry(), job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _review_error(error: ReviewError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if error.conflict else status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=str(error))


@router.get("/jobs/{job_id}/review-state", response_model=ReviewState)
def get_review_state(job_id: str) -> ReviewState:
    """Trạng thái duyệt của revision hiện tại, kèm gói/báo cáo/quyết định/bản phát hành làm căn cứ."""
    return _state(job_id)


@router.post("/jobs/{job_id}/review-decision", response_model=ReviewState)
def post_review_decision(job_id: str, body: ReviewDecisionRequest, request: Request) -> ReviewState:
    """Duyệt (rồi tự phát hành) hoặc từ chối kèm lý do; mỗi gói chỉ một quyết định."""
    reviewer = _reviewer(request)
    _state(job_id)
    try:
        result = decide(
            deps.registry(),
            job_id,
            reviewer.user_id,
            ApprovalDecision(body.decision),
            body.candidate_checksum,
            body.validation_report_checksum,
            body.accepted_warning_ids,
            body.reason,
        )
    except ReviewError as error:
        raise _review_error(error) from error
    auth.auth_service().audit(
        reviewer.user_id,
        f"review.{body.decision.lower()}",
        job_id,
        {"candidate_checksum": body.candidate_checksum, "scene_revision": result.record.scene_revision},
    )
    return result


@router.post("/jobs/{job_id}/release-seal", response_model=ReviewState)
def post_release_seal(job_id: str, request: Request) -> ReviewState:
    """Thử lại niêm phong phát hành cho gói đã duyệt (không tạo quyết định mới)."""
    reviewer = _reviewer(request)
    _state(job_id)
    try:
        result = seal_release(deps.registry(), job_id)
    except ReviewError as error:
        raise _review_error(error) from error
    auth.auth_service().audit(
        reviewer.user_id, "release.seal", job_id, {"scene_revision": result.record.scene_revision}
    )
    return result


@router.get("/jobs/{job_id}/release-download", response_class=FileResponse)
def get_release_download(job_id: str) -> FileResponse:
    """Gói phát hành (.zip: gói đã kiểm + release manifest + validation report + approval record)."""
    state = _state(job_id)
    if state.release is None or state.release_archive is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision hiện tại chưa được phát hành")
    path = deps.registry().runtime_resolver.require(state.release_archive)
    return FileResponse(
        path, media_type="application/zip", filename=f"{job_id}-{state.record.scene_revision}-release.zip"
    )
