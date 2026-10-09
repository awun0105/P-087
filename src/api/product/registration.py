"""Durable RGB–LiDAR registration command and operation status routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import Field

from src.api.auth import require_contributor
from src.api.ownership import authorize_job_mutation
from src.api.product import deps
from src.api.schemas import ApiModel
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import JobManifest, StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationInputMode,
    RegistrationOperationState,
    RegistrationPreflight,
    RegistrationPreflightState,
    RegistrationProposal,
    RegistrationQAReport,
    RegistrationRequest,
    registration_preflight,
    validate_registration_proposal_binding,
    validate_registration_qa_binding,
)
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.auth.models import UserRecord
from src.services.orchestration.inputs.assembly import InputAssemblyService
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.registration_operations import (
    RegistrationOperationNotFoundError,
    RegistrationOperationRecord,
    RegistrationOperationStore,
)
from src.services.orchestration.jobs.registration_preparation import (
    RegistrationRequestPreparationError,
    RegistrationRequestPreparer,
    RegistrationSceneRevisionConflictError,
)
from src.services.orchestration.jobs.registration_sources import RegistrationSourceResolutionError
from src.services.orchestration.jobs.registration_targets import RegistrationTargetResolutionError
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


class RegistrationOperationInspectionResponse(ApiModel):
    """Verified read-only proposal and QA payloads bound to one operation."""

    operation_id: str
    job_id: str
    expected_scene_revision: str
    current_scene_revision: str | None
    proposal: RegistrationProposal | None
    qa_report: RegistrationQAReport | None


class RegistrationPreparationRequest(ApiModel):
    expected_scene_revision: str = Field(min_length=1, max_length=128)


class RegistrationPreparationResponse(ApiModel):
    request: RegistrationRequest
    preflight: RegistrationPreflight


def _operation_store(registry: ProjectRegistry) -> RegistrationOperationStore:
    if registry.persistence is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RGB–LiDAR registration requires the shared persistent runtime database",
        )
    return RegistrationOperationStore(registry.persistence.database)


def _request_preparer(registry: ProjectRegistry) -> RegistrationRequestPreparer:
    if registry.persistence is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RGB–LiDAR registration preparation requires the shared persistent runtime database",
        )
    settings = deps.settings()
    assemblies = InputAssemblyService(
        registry.persistence.database,
        str(settings.product_input_runtime_registry) if settings.product_input_runtime_registry is not None else None,
        registry.runtime_resolver,
    )
    return RegistrationRequestPreparer(
        registry,
        assemblies,
        max_collision_glb_bytes=min((1 << 32) - 1, settings.product_upload_max_bytes * 2),
    )


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
    "/jobs/{job_id}/rgb-lidar-registration/prepare",
    response_model=RegistrationPreparationResponse,
    responses={
        401: {"description": "An authenticated requester is required"},
        403: {"description": "The caller cannot mutate this job"},
        404: {"description": "Job not found"},
        409: {"description": "The target scene or accepted input lineage is stale"},
        422: {"description": "The accepted recipe or geometry evidence is unsupported"},
        503: {"description": "Durable runtime persistence is unavailable"},
    },
)
def prepare_registration_request(
    job_id: str,
    body: RegistrationPreparationRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> RegistrationPreparationResponse:
    """Derive a sealed map request from the job's accepted recipe and current scene."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="chuẩn bị RGB–LiDAR registration cho")
    job = _job_or_404(registry, job_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An authenticated account is required to prepare a durable registration request",
        )
    try:
        prepared = _request_preparer(registry).prepare(
            job,
            requested_by=user.user_id,
            expected_scene_revision=body.expected_scene_revision,
        )
    except RegistrationSceneRevisionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except SceneNotAvailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The target job has no current scene"
        ) from error
    except (RegistrationSourceResolutionError, RegistrationTargetResolutionError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except RegistrationRequestPreparationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Registration evidence is stale or unavailable"
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return RegistrationPreparationResponse(request=prepared.request, preflight=prepared.preflight)


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


@router.get(
    "/jobs/{job_id}/rgb-lidar-registration/operations/{operation_id}/inspection",
    response_model=RegistrationOperationInspectionResponse,
    responses={
        401: {"description": "An authenticated contributor is required"},
        404: {"description": "Job or operation not found"},
        409: {"description": "Registration outputs are stale, missing or invalid"},
        503: {"description": "Durable runtime unavailable"},
    },
)
def inspect_registration_operation(
    job_id: str,
    operation_id: str,
    user: UserRecord | None = Depends(require_contributor),
) -> RegistrationOperationInspectionResponse:
    """Load exact operation outputs for inspection without applying their transform."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An authenticated account is required to inspect registration outputs",
        )
    registry = deps.registry()
    _job_or_404(registry, job_id)
    record = _operation_or_404(_operation_store(registry), operation_id)
    if record.target_job_id != job_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="registration operation not found")

    proposal: RegistrationProposal | None = None
    qa_report: RegistrationQAReport | None = None
    try:
        resolver = registry.runtime_resolver
        if record.qa_report_ref is not None:
            qa_report = resolver.load_model(record.qa_report_ref, RegistrationQAReport)
            _validate_inspection_reference(record, record.qa_report_ref, "RegistrationQAReport")

        proposal_ref = record.proposal_ref or (qa_report.proposal_ref if qa_report is not None else None)
        if record.proposal_ref is not None and qa_report is not None and qa_report.proposal_ref != record.proposal_ref:
            raise ValueError("QA proposal reference differs from the operation output")
        if proposal_ref is not None:
            _validate_inspection_reference(record, proposal_ref, "RegistrationProposalArtifact")
            proposal = resolver.load_model(proposal_ref, RegistrationProposal)
            validate_registration_proposal_binding(record.request, proposal)
        if qa_report is not None:
            if proposal is None:
                raise ValueError("QA report has no resolvable proposal")
            validate_registration_qa_binding(record.request, proposal, qa_report)
    except (ArtifactStoreError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration outputs are missing, corrupt, or bound to different evidence",
        ) from error

    try:
        current_scene_revision = registry.scene.current(job_id).scene.scene_revision
    except SceneNotAvailableError:
        current_scene_revision = None
    return RegistrationOperationInspectionResponse(
        operation_id=record.operation_id,
        job_id=job_id,
        expected_scene_revision=record.request.expected_scene_revision,
        current_scene_revision=current_scene_revision,
        proposal=proposal,
        qa_report=qa_report,
    )


def _validate_inspection_reference(
    record: RegistrationOperationRecord,
    reference: ProductArtifactRef,
    artifact_type: str,
) -> None:
    provenance = reference.source_provenance or {}
    if (
        reference.artifact_type != artifact_type
        or reference.job_id != record.target_job_id
        or not reference.artifact_uri.startswith(f"artifact://jobs/{record.target_job_id}/")
        or reference.producer_stage != StageId.RGB_LIDAR_ALIGN
        or reference.data_class != ArtifactDataClass.DERIVED
        or provenance.get("operation_id") != record.operation_id
        or provenance.get("registration_request_checksum") != record.request_checksum
    ):
        raise ValueError("registration artifact reference is not bound to this operation")


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
