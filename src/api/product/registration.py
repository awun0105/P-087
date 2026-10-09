"""Durable RGB–LiDAR registration command and operation status routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status

from src.api.auth import require_contributor
from src.api.ownership import authorize_job_mutation
from src.api.product import deps
from src.api.schemas import ApiModel
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobManifest
from src.models.contracts.rgb_lidar_registration import (
    RegistrationInputMode,
    RegistrationOperationState,
    RegistrationPreflightState,
    RegistrationRequest,
    registration_preflight,
)
from src.services.orchestration.auth.models import UserRecord
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.registration_operations import (
    RegistrationOperationNotFoundError,
    RegistrationOperationRecord,
    RegistrationOperationStore,
)
from src.services.orchestration.projects import JobNotFoundError, ProjectRegistry
from src.services.orchestration.scene.errors import SceneNotAvailableError

router = APIRouter()


class RegistrationOperationResponse(ApiModel):
    """Public operation state; never expose the sealed request, idempotency key or worker lease."""

    operation_id: str
    job_id: str
    state: RegistrationOperationState
    attempt: int
    created_at: datetime
    updated_at: datetime
    proposal_ref: ProductArtifactRef | None = None
    qa_report_ref: ProductArtifactRef | None = None
    cancellation_requested: bool = False


def _operation_store(registry: ProjectRegistry) -> RegistrationOperationStore:
    if registry.persistence is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RGB–LiDAR registration requires the shared persistent runtime database",
        )
    return RegistrationOperationStore(registry.persistence.database)


def _public_operation(record: RegistrationOperationRecord) -> RegistrationOperationResponse:
    return RegistrationOperationResponse(
        operation_id=record.operation_id,
        job_id=record.target_job_id,
        state=record.state,
        attempt=record.attempt,
        created_at=record.created_at,
        updated_at=record.updated_at,
        proposal_ref=record.proposal_ref,
        qa_report_ref=record.qa_report_ref,
        cancellation_requested=record.cancellation_requested,
    )


def _job_or_404(registry: ProjectRegistry, job_id: str) -> JobManifest:
    try:
        return registry.get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _operation_or_404(store: RegistrationOperationStore, operation_id: str) -> RegistrationOperationRecord:
    try:
        return store.get(operation_id)
    except RegistrationOperationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="registration operation not found") from error
    except RuntimeStateConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/jobs/{job_id}/rgb-lidar-registration/operations",
    response_model=RegistrationOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"description": "An authenticated requester is required"},
        403: {"description": "The caller cannot mutate this job"},
        404: {"description": "Job not found"},
        409: {"description": "The bound project, scene revision or idempotency key is stale"},
        422: {"description": "The request is invalid or preflight is insufficient"},
        503: {"description": "Durable runtime persistence is unavailable"},
    },
)
def enqueue_registration(
    job_id: str,
    request: RegistrationRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    user: UserRecord | None = Depends(require_contributor),
) -> RegistrationOperationResponse:
    """Accept one sealed map-registration request into the durable worker queue."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="tạo yêu cầu RGB–LiDAR registration cho")
    job = _job_or_404(registry, job_id)

    if request.target_job_id != job_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Request target differs from job path"
        )
    if request.target_project_id != job.project_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registration project binding is stale")
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An authenticated account is required to create a durable registration operation",
        )
    if request.requested_by != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Registration requester must match the session"
        )
    if not idempotency_key.strip() or idempotency_key != idempotency_key.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Idempotency-Key is invalid")
    if request.source.mode not in {RegistrationInputMode.REGISTERED_MAP, RegistrationInputMode.STATIC_CLOUD}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This registration worker accepts registered maps or one static point cloud",
        )

    store = _operation_store(registry)
    try:
        preflight = registration_preflight(request)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    if preflight.state != RegistrationPreflightState.READY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "registration_preflight_insufficient",
                "findings": [finding.value for finding in preflight.findings],
            },
        )

    try:
        current_revision = registry.scene.current(job_id).scene.scene_revision
    except SceneNotAvailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The target job has no committed scene revision"
        ) from error
    if current_revision != request.expected_scene_revision:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registration target scene revision is stale")

    try:
        record = store.enqueue(request, idempotency_key)
    except RuntimeStateConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return _public_operation(record)


@router.get(
    "/jobs/{job_id}/rgb-lidar-registration/operations/{operation_id}",
    response_model=RegistrationOperationResponse,
    responses={404: {"description": "Job or operation not found"}, 503: {"description": "Durable runtime unavailable"}},
)
def get_registration_operation(job_id: str, operation_id: str) -> RegistrationOperationResponse:
    """Read status only when the operation is bound to the requested job."""
    registry = deps.registry()
    _job_or_404(registry, job_id)
    store = _operation_store(registry)
    record = _operation_or_404(store, operation_id)
    if record.target_job_id != job_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="registration operation not found")
    return _public_operation(record)


@router.post(
    "/jobs/{job_id}/rgb-lidar-registration/operations/{operation_id}/cancel",
    response_model=RegistrationOperationResponse,
    responses={
        403: {"description": "The caller cannot mutate this job"},
        404: {"description": "Job or operation not found"},
        503: {"description": "Durable runtime unavailable"},
    },
)
def cancel_registration_operation(
    job_id: str,
    operation_id: str,
    user: UserRecord | None = Depends(require_contributor),
) -> RegistrationOperationResponse:
    """Cancel queued work or persist a cooperative cancellation request for a worker."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="hủy yêu cầu RGB–LiDAR registration của")
    _job_or_404(registry, job_id)
    store = _operation_store(registry)
    record = _operation_or_404(store, operation_id)
    if record.target_job_id != job_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="registration operation not found")
    try:
        return _public_operation(store.cancel(operation_id))
    except RegistrationOperationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="registration operation not found") from error
    except RuntimeStateConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
