"""Duyệt và phát hành trong Studio (PRODUCT-10/11).

Quyết định luôn cần **Reviewer đã đăng nhập**, kể cả khi `AUTH_REQUIRED=false` (chế độ local):
approval vô danh không phải quyết định của con người có quyền (PRD §3.4). reviewer_id lấy từ phiên,
không nhận từ payload.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from src.api import auth
from src.api.auth import require_contributor
from src.api.ownership import authorize_job_mutation, owner_mutation_allowed
from src.api.studio import deps
from src.models.contracts.artifacts import Checksum
from src.models.contracts.identity import verify_candidate_inventory, verify_content_checksum
from src.models.contracts.release import ApprovalDecision
from src.models.contracts.validation_run import IsaacValidationRuntimeProfile, ValidationConfig
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.auth.service import has_role
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.projects import JobNotFoundError, ProjectRegistry
from src.services.orchestration.review.simulation_package import SimulationPackage, current_package
from src.services.orchestration.review.validation_queue import (
    ValidationCandidateSnapshot,
    ValidationQueue,
    ValidationQueueError,
    ValidationQueueNotFoundError,
    ValidationRunView,
)
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


class ValidationRunRequest(BaseModel):
    """Ask to validate the exact candidate currently shown in the Studio."""

    model_config = ConfigDict(extra="forbid")

    candidate_checksum: Checksum


def _reviewer(request: Request) -> UserRecord:
    user = auth.current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Đăng nhập tài khoản Reviewer để duyệt")
    if not has_role(user, "reviewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chỉ Reviewer được duyệt và phát hành")
    return user


def _named(state: ReviewState) -> ReviewState:
    """Điền tên người duyệt để UI hiện ai đã quyết định (không gian chung của nhóm, ADR 0003)."""
    if state.approval is None:
        return state
    user = auth.auth_service().get_user(state.approval.reviewer_id)
    return state.model_copy(update={"reviewer_name": user.display_name if user else None})


def _state(job_id: str) -> ReviewState:
    try:
        return _named(review_state(deps.registry(), job_id))
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _review_error(error: ReviewError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if error.conflict else status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=str(error))


def _validation_queue(registry: ProjectRegistry) -> ValidationQueue:
    persistence = registry.persistence
    if persistence is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Isaac validation cần RuntimeDatabase dùng chung để lưu queue bền vững",
        )
    return ValidationQueue(persistence.database, registry.runtime_resolver)


def _validation_policy() -> tuple[ValidationConfig, IsaacValidationRuntimeProfile]:
    settings = deps.settings()
    config_path = settings.product_isaac_validation_config
    profile_path = settings.product_isaac_validation_profile
    if config_path is None or profile_path is None or not config_path.is_file() or not profile_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Isaac validation chưa được cấu hình: cần PRODUCT_ISAAC_VALIDATION_CONFIG và "
                "PRODUCT_ISAAC_VALIDATION_PROFILE cùng các artifact RuntimeManifest/robot đã xác minh"
            ),
        )
    try:
        config = ValidationConfig.model_validate_json(config_path.read_bytes())
        profile = IsaacValidationRuntimeProfile.model_validate_json(profile_path.read_bytes())
        verify_content_checksum(config, "config_checksum")
        verify_content_checksum(profile, "profile_checksum")
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cấu hình Isaac validation không hợp lệ: {error}",
        ) from error
    if config.runtime_profile_ref is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PRODUCT_ISAAC_VALIDATION_CONFIG là policy template; profile được bind riêng từ server setting",
        )
    return config, profile


def _validation_job_access(job_id: str, user: UserRecord | None, *, mutation: bool) -> ProjectRegistry:
    registry = deps.registry()
    try:
        registry.get_job(job_id)
        if mutation:
            authorize_job_mutation(user, registry, job_id, operation="quản lý Isaac validation của")
        elif user is not None and not owner_mutation_allowed(user, registry.get_job_owner_user_id(job_id)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guest chỉ được xem job do mình tạo")
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return registry


def _current_validation_candidate(
    job_id: str, registry: ProjectRegistry
) -> tuple[SimulationPackage, ValidationCandidateSnapshot]:
    try:
        package = current_package(registry, job_id)
    except (ArtifactStoreError, SceneNotAvailableError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if package is None or package.candidate is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cần tạo SimulationPackage hợp lệ cho scene revision hiện tại trước khi chạy Isaac validation",
        )
    candidate = package.candidate
    try:
        verify_candidate_inventory(candidate)
        verify_content_checksum(candidate, "candidate_checksum")
        references = [candidate.entrypoint_usd, *candidate.assets, *candidate.geometry, *candidate.colliders]
        for reference in references:
            if reference.job_id != job_id:
                raise ValueError("Candidate ref belongs to a different job")
            registry.runtime_resolver.require(reference)
    except (ArtifactStoreError, ValueError, OSError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Candidate không hợp lệ: {error}") from error
    manifest = candidate.candidate_manifest
    if (
        manifest.scene_revision != package.scene_revision
        or manifest.scene_ir_checksum != package.scene_ir_checksum
        or package.job_id != job_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Candidate không khớp SimulationPackage hiện tại"
        )
    return package, ValidationCandidateSnapshot(
        job_id=job_id,
        scene_revision=package.scene_revision,
        scene_ir_checksum=package.scene_ir_checksum,
        candidate_checksum=candidate.candidate_checksum,
    )


def _validation_error(error: Exception) -> HTTPException:
    if isinstance(error, ValidationQueueNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, (ArtifactStoreError, RuntimeStateConflictError, ValidationQueueError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


@router.post(
    "/jobs/{job_id}/validation-runs",
    response_model=ValidationRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_validation_run(
    job_id: str,
    body: ValidationRunRequest,
    user: UserRecord | None = Depends(require_contributor),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
) -> ValidationRunView:
    """Queue a worker validation attempt for one exact, immutable SimulationPackage candidate."""
    registry = _validation_job_access(job_id, user, mutation=True)
    queue = _validation_queue(registry)
    policy, profile = _validation_policy()
    try:
        bound_config = queue.bind_profile(job_id, policy, profile)
        requester_id = user.user_id if user is not None else "__anonymous__"
        replayed = queue.replay(
            job_id=job_id,
            candidate_checksum=body.candidate_checksum,
            config_checksum=bound_config.config_checksum,
            requester_id=requester_id,
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            return replayed
        _, snapshot = _current_validation_candidate(job_id, registry)
        if body.candidate_checksum != snapshot.candidate_checksum:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate đã thay đổi; tải lại SimulationPackage trước khi chạy validation",
            )
        return queue.submit(
            snapshot,
            policy,
            profile=profile,
            requester_id=requester_id,
            idempotency_key=idempotency_key,
        )
    except HTTPException:
        raise
    except (ArtifactStoreError, RuntimeStateConflictError, ValidationQueueError, ValueError, OSError) as error:
        raise _validation_error(error) from error


@router.get("/jobs/{job_id}/validation-runs", response_model=list[ValidationRunView])
def list_validation_runs(
    job_id: str,
    user: UserRecord | None = Depends(require_contributor),
    limit: int = 100,
) -> list[ValidationRunView]:
    registry = _validation_job_access(job_id, user, mutation=False)
    try:
        return _validation_queue(registry).list_for_job(job_id, limit=limit)
    except (ArtifactStoreError, RuntimeStateConflictError, ValidationQueueError, ValueError, OSError) as error:
        raise _validation_error(error) from error


@router.get("/jobs/{job_id}/validation-runs/{run_id}", response_model=ValidationRunView)
def get_validation_run(
    job_id: str,
    run_id: str,
    user: UserRecord | None = Depends(require_contributor),
) -> ValidationRunView:
    registry = _validation_job_access(job_id, user, mutation=False)
    try:
        return _validation_queue(registry).get(job_id, run_id)
    except (ArtifactStoreError, RuntimeStateConflictError, ValidationQueueError, ValueError, OSError) as error:
        raise _validation_error(error) from error


@router.post("/jobs/{job_id}/validation-runs/{run_id}/cancel", response_model=ValidationRunView)
def cancel_validation_run(
    job_id: str,
    run_id: str,
    user: UserRecord | None = Depends(require_contributor),
) -> ValidationRunView:
    registry = _validation_job_access(job_id, user, mutation=True)
    try:
        return _validation_queue(registry).cancel(job_id, run_id)
    except (ArtifactStoreError, RuntimeStateConflictError, ValidationQueueError, ValueError, OSError) as error:
        raise _validation_error(error) from error


@router.post(
    "/jobs/{job_id}/validation-runs/{run_id}/retry",
    response_model=ValidationRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_validation_run(
    job_id: str,
    run_id: str,
    user: UserRecord | None = Depends(require_contributor),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
) -> ValidationRunView:
    registry = _validation_job_access(job_id, user, mutation=True)
    _, snapshot = _current_validation_candidate(job_id, registry)
    try:
        return _validation_queue(registry).retry(
            job_id,
            run_id,
            requester_id=user.user_id if user is not None else "__anonymous__",
            idempotency_key=idempotency_key,
            current_candidate_checksum=snapshot.candidate_checksum,
        )
    except (ArtifactStoreError, RuntimeStateConflictError, ValidationQueueError, ValueError, OSError) as error:
        raise _validation_error(error) from error


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
    return _named(result)


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
    return _named(result)


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
