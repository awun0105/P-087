"""Unified input assembly uploads, immutable revisions and deterministic resolution."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api import schemas
from src.api.auth import (
    enforce_gpu_quota,
    guest_run_intent,
    idempotency_conflict_http,
    quota_exceeded_http,
    record_gpu_run,
    require_contributor,
)
from src.api.ownership import (
    authorize_input_assembly_access,
    authorize_staged_input_upload_mutation,
    authorize_upload_mutation,
)
from src.api.studio import deps
from src.api.studio.error_view import filter_manifest_errors
from src.models.contracts.artifacts import Checksum
from src.models.contracts.input_assembly import (
    CandidateState,
    DistanceUnit,
    EvidenceProvenance,
    GaussianViewCandidate,
    InputAssemblyDeclarations,
    InputAssemblySnapshot,
    InputBinding,
    InputResolutionReport,
    InputResolutionState,
    InputRole,
    InputWorkflowIntent,
    RecipeComponentVersion,
    RecipeGroup,
    RuntimeQualificationStatus,
    StagedInputFile,
    TrajectoryConvention,
    TrajectoryOrigin,
    VideoRecipeCandidate,
    seal_gaussian_view_intent,
    seal_input_recipe,
)
from src.models.contracts.manifests import InputFile, JobManifest
from src.services.orchestration.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactChecksumError,
    ArtifactTooLargeError,
    sha256_bytes,
)
from src.services.orchestration.auth import UserRecord, actor_of
from src.services.orchestration.auth.quota_ledger import (
    GuestQuotaExceededError,
    GuestQuotaIdempotencyConflictError,
)
from src.services.orchestration.inputs import (
    InputAssemblyConflictError,
    InputAssemblyNotFoundError,
    InputAssemblyRunCommit,
    InputAssemblyService,
    InputResolutionRecord,
    StoredInputAssembly,
)
from src.services.orchestration.inputs.assembly import InputAssemblyRuntimeConfigError
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.processing.config import build_job_config, config_bytes, is_presets_file, preset_values
from src.services.orchestration.processing.resources import evaluate
from src.services.orchestration.projects import (
    JobCreateInput,
    PrivacyGateBlockedError,
    ProjectNotFoundError,
)
from src.services.orchestration.projects.models import LidarAttachment, SourceRightsAttestation, UploadProjectInput
from src.services.orchestration.uploads import UploadError, UploadNotFoundError
from src.services.orchestration.uploads.assembly_models import StagedInputUploadRecord
from src.services.orchestration.uploads.scene_imports import ImportedScene, SceneImportError
from src.services.reconstruction.inputs.input_probe import InputProbe

router = APIRouter()


class AssemblyUploadResponse(BaseModel):
    """Content-probed upload result; no geometry, calibration, or QA pass is implied."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    source_file: InputFile
    staged_files: list[StagedInputFile]
    probes: list[InputProbe]
    received_at: datetime


class AssemblyWriteRequest(BaseModel):
    """User declarations/bindings are typed and remain distinct from observed bytes."""

    model_config = ConfigDict(extra="forbid")

    upload_ids: list[str] = Field(min_length=1, max_length=100)
    declarations: InputAssemblyDeclarations = Field(default_factory=InputAssemblyDeclarations)
    bindings: list[InputBinding] = Field(default_factory=list, max_length=100)
    requested_intent: InputWorkflowIntent | None = None


class AssemblyRevisionRequest(AssemblyWriteRequest):
    expected_revision: int = Field(ge=1)


class ResolveAssemblyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)


class ResolveAssemblyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: InputResolutionReport


class AssemblyRunRequest(BaseModel):
    """Exact ready recipe the user accepted for reconstruction."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    resolution_checksum: Checksum
    candidate_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    attestation: SourceRightsAttestation
    processing: dict[str, int | float | str] | None = None
    #: Tự động che khuôn mặt/biển số trên frame trước khi dựng 3D (AUD-18).
    anonymize: bool = False


class AssemblyRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: schemas.ProjectResponse
    job: JobManifest


class AssemblyImportRequest(BaseModel):
    """Exact Gaussian master selected for the existing durable view/import path."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    resolution_checksum: Checksum
    candidate_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)


class AssemblyImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imported_scene: ImportedScene
    intent_checksum: Checksum


def _service() -> InputAssemblyService:
    return deps.input_assemblies()


def _handle_assembly_error(error: Exception) -> HTTPException:
    if isinstance(error, InputAssemblyNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, (InputAssemblyConflictError, RuntimeStateConflictError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, InputAssemblyRuntimeConfigError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, ArtifactChecksumError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


def _request_fingerprint(operation: str, payload: dict[str, object]) -> str:
    raw = json.dumps(
        {"operation": operation, "payload": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _checked_resolution(
    service: InputAssemblyService,
    assembly_id: str,
    revision: int,
    expected_checksum: str,
    user: UserRecord | None,
) -> tuple[StoredInputAssembly, InputResolutionRecord]:
    stored = service.get_assembly(assembly_id, revision)
    authorize_input_assembly_access(user, assembly_id, stored.snapshot.owner_id)
    for upload_id in sorted({item.upload_id for item in stored.snapshot.files}):
        authorize_staged_input_upload_mutation(user, service.get_upload(upload_id), operation="chạy assembly")
    service.verify_upload_sources(stored)
    resolved = service.resolve(assembly_id, revision)
    if resolved.report.report_checksum != expected_checksum:
        raise InputAssemblyConflictError("resolution changed; review the latest report before accepting Run")
    return stored, resolved


def _response(record: StagedInputUploadRecord) -> AssemblyUploadResponse:
    return AssemblyUploadResponse(
        upload_id=record.upload_id,
        source_file=record.source_file,
        staged_files=record.staged_files,
        probes=record.probes,
        received_at=record.received_at,
    )


@router.post(
    "/input-assemblies/uploads",
    response_model=AssemblyUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_assembly_input(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    user: UserRecord | None = Depends(require_contributor),
) -> AssemblyUploadResponse:
    """Proxy upload fallback for generic sidecars; cloud deployments can use resumable direct upload."""
    service = deps.uploads()
    try:
        pending = await run_in_threadpool(service.begin_assembly, filename)
        async for chunk in request.stream():
            if chunk:
                await run_in_threadpool(pending.publication.write, chunk)
        record = await run_in_threadpool(service.finish_assembly, pending, actor_of(user))
        return _response(record)
    except ArtifactTooLargeError as error:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(error)) from error
    except (UploadError, ValueError, ArtifactAlreadyExistsError) as error:
        raise _handle_assembly_error(error) from error
    finally:
        if "pending" in locals():
            pending.publication.abort()


@router.get("/input-assemblies/uploads/{upload_id}", response_model=AssemblyUploadResponse)
def get_input_assembly_upload(
    upload_id: str,
    user: UserRecord | None = Depends(require_contributor),
) -> AssemblyUploadResponse:
    service = _service()
    try:
        record = service.get_upload(upload_id)
        authorize_staged_input_upload_mutation(user, record, operation="đọc staged input upload")
        return _response(record)
    except InputAssemblyNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/input-assemblies/uploads/{upload_id}/stage", response_model=AssemblyUploadResponse)
def stage_existing_input_upload(
    upload_id: str,
    user: UserRecord | None = Depends(require_contributor),
) -> AssemblyUploadResponse:
    """Attach a verified legacy upload to assembly inventory without copying its source bytes."""
    try:
        uploads = deps.uploads()
        legacy = uploads.get(upload_id)
        authorize_upload_mutation(user, legacy, operation="thêm upload hiện có vào assembly")
        return _response(uploads.stage_for_assembly(upload_id))
    except UploadNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (UploadError, RuntimeStateConflictError, ValueError) as error:
        raise _handle_assembly_error(error) from error


@router.post("/input-assemblies", response_model=InputAssemblySnapshot, status_code=status.HTTP_201_CREATED)
def create_input_assembly(
    request: AssemblyWriteRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> InputAssemblySnapshot:
    service = _service()
    try:
        for upload_id in request.upload_ids:
            authorize_staged_input_upload_mutation(
                user,
                service.get_upload(upload_id),
                operation="thêm file vào assembly",
            )
        owner_id = user.user_id if user is not None else "anonymous"
        return service.create(
            owner_id,
            request.upload_ids,
            request.declarations,
            request.bindings,
            request.requested_intent,
        ).snapshot
    except Exception as error:
        if isinstance(error, HTTPException):
            raise
        raise _handle_assembly_error(error) from error


@router.put("/input-assemblies/{assembly_id}", response_model=InputAssemblySnapshot)
def revise_input_assembly(
    assembly_id: str,
    request: AssemblyRevisionRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> InputAssemblySnapshot:
    service = _service()
    try:
        current = service.get_assembly(assembly_id)
        authorize_input_assembly_access(user, assembly_id, current.snapshot.owner_id, operation="sửa assembly")
        for upload_id in request.upload_ids:
            authorize_staged_input_upload_mutation(
                user,
                service.get_upload(upload_id),
                operation="thêm file vào assembly",
            )
        return service.revise(
            assembly_id,
            current.snapshot.owner_id,
            request.expected_revision,
            request.upload_ids,
            request.declarations,
            request.bindings,
            request.requested_intent,
        ).snapshot
    except Exception as error:
        if isinstance(error, HTTPException):
            raise
        raise _handle_assembly_error(error) from error


@router.get("/input-assemblies/{assembly_id}", response_model=InputAssemblySnapshot)
def get_input_assembly(
    assembly_id: str,
    revision: int | None = Query(default=None, ge=1),
    user: UserRecord | None = Depends(require_contributor),
) -> InputAssemblySnapshot:
    service = _service()
    try:
        stored = service.get_assembly(assembly_id, revision)
        authorize_input_assembly_access(user, assembly_id, stored.snapshot.owner_id)
        return stored.snapshot
    except HTTPException:
        raise
    except Exception as error:
        raise _handle_assembly_error(error) from error


@router.post("/input-assemblies/{assembly_id}/resolve", response_model=ResolveAssemblyResponse)
def resolve_input_assembly(
    assembly_id: str,
    request: ResolveAssemblyRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> ResolveAssemblyResponse:
    service = _service()
    try:
        stored = service.get_assembly(assembly_id, request.revision)
        authorize_input_assembly_access(user, assembly_id, stored.snapshot.owner_id)
        return ResolveAssemblyResponse(report=service.resolve(assembly_id, request.revision).report)
    except HTTPException:
        raise
    except Exception as error:
        raise _handle_assembly_error(error) from error


def _accepted_job_response(job: JobManifest, user: UserRecord | None) -> AssemblyRunResponse:
    project = deps.registry().get_project(job.project_id)
    return AssemblyRunResponse(project=schemas.project_response(project), job=filter_manifest_errors(job, user))


@router.post(
    "/input-assemblies/{assembly_id}/run",
    response_model=AssemblyRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def run_input_assembly(
    assembly_id: str,
    request: AssemblyRunRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128),
    user: UserRecord | None = Depends(require_contributor),
) -> AssemblyRunResponse:
    """Accept one compatible recipe into the existing durable reconstruction queue."""
    if idempotency_key is None or not idempotency_key.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run cần Idempotency-Key hợp lệ")
    registry = deps.registry()
    if registry.persistence is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Grouped input Run requires the shared persistent runtime database",
        )
    payload: dict[str, object] = {"assembly_id": assembly_id, "request": request.model_dump(mode="json")}
    fingerprint = _request_fingerprint("scene.create", payload)
    try:
        quota_intent = guest_run_intent(user, "scene.create", idempotency_key, payload)
        if quota_intent is not None:
            duplicate = registry.lookup_quota_job(quota_intent)
            if duplicate is not None:
                return _accepted_job_response(duplicate, user)
        duplicate_run = registry.lookup_input_run(user.user_id if user else "anonymous", idempotency_key, fingerprint)
        if duplicate_run is not None:
            return _accepted_job_response(registry.get_job(duplicate_run.job_id), user)
    except GuestQuotaIdempotencyConflictError as error:
        raise idempotency_conflict_http(error) from error
    except RuntimeStateConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    enforce_gpu_quota(user)
    settings = deps.settings()
    if settings.product_privacy_mode != "self_attested":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video upload cần QA xác nhận ẩn danh; đặt PRODUCT_PRIVACY_MODE=self_attested cho MVP",
        )
    if registry.execution_profile is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chưa cấu hình worker: cần PRODUCT_PROCESSING_CONFIG và PRODUCT_RUNTIME_MANIFEST",
        )
    processing = None
    if settings.product_processing_config is not None and is_presets_file(settings.product_processing_config):
        presets, presets_checksum = deps.presets()
        capability = deps.capability()
        params = request.processing or preset_values(presets, "minimum_quality")
        observed = deps.observed_resource_budget(
            registry,
            params,
            capability.gpu_name if capability is not None else None,
            colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False),
        )
        try:
            processing = build_job_config(
                presets,
                presets_checksum,
                params,
                capability,
                colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False),
                anonymize=deps.require_anonymize(request.anonymize),
            )
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
        if evaluate(presets, params, capability, observed=observed).blocking:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Thông số vượt cấu hình máy xử lý và có thể crash; giảm các ô được tô đỏ",
            )
    elif request.processing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Worker chưa dùng file thông số chung; không nhận thông số tùy chỉnh",
        )
    config_checksum = (
        sha256_bytes(config_bytes(processing)) if processing is not None else registry.execution_profile.config_checksum
    )

    service = _service()
    try:
        stored, resolution = _checked_resolution(
            service,
            assembly_id,
            request.revision,
            request.resolution_checksum,
            user,
        )
        report = resolution.report
        if report.state != InputResolutionState.READY or report.recommended_candidate_id != request.candidate_id:
            raise InputAssemblyConflictError("Only the one currently recommended ready candidate can be run")
        candidate = next((item for item in report.candidates if item.candidate_id == request.candidate_id), None)
        if not isinstance(candidate, VideoRecipeCandidate) or candidate.state != CandidateState.READY:
            raise InputAssemblyConflictError("Selected candidate is not a ready video reconstruction recipe")
        if candidate.runtime.status != RuntimeQualificationStatus.QUALIFIED:
            raise InputAssemblyConflictError("Selected worker capability is not qualified")
        if candidate.recipe_group not in {RecipeGroup.RGB_ONLY, RecipeGroup.SUPPLIED_TRAJECTORY}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Recipe {candidate.recipe_group.value} has no compatible dispatch adapter yet",
            )
        bindings = {binding.role: binding.file_ids for binding in candidate.bindings}
        video_ids = bindings.get(InputRole.RGB_VIDEO, [])
        if len(video_ids) != 1:
            raise InputAssemblyConflictError("Run requires exactly one explicitly selected RGB video")
        staged_by_id = {item.file_id: item for item in stored.snapshot.files}
        video_staged = staged_by_id[video_ids[0]]
        if video_staged.archive_member is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Video contained in an archive has no worker adapter; upload the source video directly",
            )
        uploads = deps.uploads()
        video_upload = uploads.get(video_staged.upload_id)
        authorize_upload_mutation(user, video_upload, operation="chạy video trong assembly")
        if (
            video_upload.input_kind != "rgb_video"
            or video_upload.checksum != video_staged.source_file.checksum
            or video_upload.size_bytes != video_staged.source_file.size_bytes
            or video_upload.artifact_uri != video_staged.source_file.artifact_uri
        ):
            raise ArtifactChecksumError("Selected RGB video differs from its legacy verified upload record")

        lidar_upload = None
        lidar_attachment = None
        selected_upload_ids = {video_upload.upload_id}
        if candidate.recipe_group == RecipeGroup.SUPPLIED_TRAJECTORY:
            lidar_roles = (
                InputRole.LIDAR_SCAN,
                InputRole.SENSOR_TRAJECTORY,
                InputRole.CAMERA_LIDAR_CALIBRATION,
                InputRole.RGB_FRAME_TIMES,
            )
            lidar_file_ids = [file_id for role in lidar_roles for file_id in bindings.get(role, [])]
            if not lidar_file_ids:
                raise InputAssemblyConflictError("R4 has no bound LiDAR source files")
            package_upload_ids = {staged_by_id[file_id].upload_id for file_id in lidar_file_ids}
            if len(package_upload_ids) != 1:
                raise InputAssemblyConflictError("R4 files must come from one verified LiDAR ZIP package")
            lidar_upload_id = next(iter(package_upload_ids))
            lidar_upload = uploads.get(lidar_upload_id)
            authorize_upload_mutation(user, lidar_upload, operation="chạy LiDAR trong assembly")
            if lidar_upload.input_kind != "lidar_scan_sequence":
                raise InputAssemblyConflictError("The R4 adapter requires a legacy-verified raw scan sequence ZIP")
            declarations = stored.snapshot.declarations
            if (
                declarations.same_scene is None
                or declarations.same_scene.value is not True
                or declarations.same_scene.provenance not in {EvidenceProvenance.DECLARED, EvidenceProvenance.VERIFIED}
                or declarations.coordinate_unit is None
                or declarations.coordinate_unit.value != DistanceUnit.METER
                or declarations.trajectory_convention is None
                or declarations.trajectory_convention.value != TrajectoryConvention.WORLD_FROM_SENSOR
                or candidate.trajectory_origin != TrajectoryOrigin.SUPPLIED
            ):
                raise InputAssemblyConflictError(
                    "R4 requires declared same-scene, meter units, and world_from_sensor poses"
                )
            lidar_attachment = LidarAttachment(
                upload_id=lidar_upload.upload_id,
                trajectory_origin="supplied",
                same_scene_confirmed=True,
            )
            selected_upload_ids.add(lidar_upload.upload_id)

        component_versions = [
            RecipeComponentVersion(
                component_id=f"runtime-{candidate.runtime.runtime_id}",
                version=candidate.runtime.runtime_version,
                config_checksum=candidate.runtime.qualification_evidence_checksum,
            ),
            RecipeComponentVersion(
                component_id="input-resolver",
                version=report.resolver_version,
                config_checksum=resolution.runtime_registry.registry_checksum,
            ),
        ]
        recipe = seal_input_recipe(
            {
                "schema_version": "1.0",
                "recipe_id": f"recipe-{uuid4().hex[:16]}",
                "assembly_id": stored.snapshot.assembly_id,
                "assembly_revision": stored.snapshot.revision,
                "assembly_checksum": stored.snapshot.assembly_checksum,
                "resolution_checksum": report.report_checksum,
                "candidate_id": candidate.candidate_id,
                "recipe_group": candidate.recipe_group,
                "selected_by": user.user_id if user else "anonymous",
                "accepted_at": datetime.now(UTC),
                "bindings": candidate.bindings,
                "excluded_file_ids": candidate.excluded_file_ids,
                "trajectory_origin": candidate.trajectory_origin,
                "component_versions": component_versions,
                "config_checksum": config_checksum,
                "recipe_checksum": "sha256:" + "0" * 64,
            }
        )
        project_request = UploadProjectInput(
            upload_id=video_upload.upload_id,
            name=request.name,
            attestation=request.attestation,
            processing=request.processing,
            anonymize=request.anonymize,
            lidar=lidar_attachment,
        )
        project = registry.create_project_from_input_assembly(
            video_upload,
            project_request,
            settings.product_privacy_mode,
            resolution,
            recipe,
            config_checksum,
            assembly=stored.snapshot,
            lidar=lidar_upload,
            created_by=actor_of(user),
            defer_persistence=True,
        )
        recipe_ref = project.input_recipe_ref
        if recipe_ref is None:
            raise AssertionError("accepted assembly project must publish its input recipe")
        commit = InputAssemblyRunCommit(
            requester_id=user.user_id if user else "anonymous",
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            assembly_id=stored.snapshot.assembly_id,
            assembly_revision=stored.snapshot.revision,
            assembly_checksum=stored.snapshot.assembly_checksum,
            resolution_checksum=report.report_checksum,
            candidate_id=candidate.candidate_id,
            recipe_checksum=recipe.recipe_checksum,
            recipe_ref=recipe_ref,
            staged_upload_ids=tuple(sorted({item.upload_id for item in stored.snapshot.files})),
        )
        job = registry.create_job(
            JobCreateInput(project_id=project.project_id),
            processing,
            requested_by=actor_of(user),
            owner_user_id=user.user_id if user else None,
            quota_intent=quota_intent,
            project_record=project,
            upload_ids_to_link=tuple(sorted(selected_upload_ids)),
            input_assembly_run=commit,
        )
        if job.project_id == project.project_id:
            record_gpu_run(user, job.job_id, {"kind": "scene.create", "project_id": project.project_id})
        return _accepted_job_response(job, user)
    except HTTPException:
        raise
    except GuestQuotaExceededError as error:
        raise quota_exceeded_http(error) from error
    except GuestQuotaIdempotencyConflictError as error:
        raise idempotency_conflict_http(error) from error
    except (InputAssemblyConflictError, RuntimeStateConflictError, PrivacyGateBlockedError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (InputAssemblyNotFoundError, ProjectNotFoundError, UploadNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise _handle_assembly_error(error) from error


@router.post(
    "/input-assemblies/{assembly_id}/import",
    response_model=AssemblyImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_input_assembly_gaussian(
    assembly_id: str,
    request: AssemblyImportRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128),
    user: UserRecord | None = Depends(require_contributor),
) -> AssemblyImportResponse:
    """Send an exact PLY/SOG selection through AUD-06's durable import command."""
    if idempotency_key is None or not idempotency_key.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Import cần Idempotency-Key hợp lệ")
    try:
        stored, resolution = _checked_resolution(
            _service(), assembly_id, request.revision, request.resolution_checksum, user
        )
        report = resolution.report
        if report.state != InputResolutionState.READY or report.recommended_candidate_id != request.candidate_id:
            raise InputAssemblyConflictError("Only the one currently ready Gaussian selection can be imported")
        candidate = next((item for item in report.candidates if item.candidate_id == request.candidate_id), None)
        if not isinstance(candidate, GaussianViewCandidate) or candidate.state != CandidateState.READY:
            raise InputAssemblyConflictError("Selected candidate is not a ready Gaussian view import")
        if candidate.runtime.status != RuntimeQualificationStatus.QUALIFIED:
            raise InputAssemblyConflictError("Gaussian view runtime is not qualified")
        staged = next((item for item in stored.snapshot.files if item.file_id == candidate.source_file_id), None)
        if staged is None:
            raise InputAssemblyConflictError("Gaussian master file is missing from the immutable assembly")
        upload = deps.uploads().get(staged.upload_id)
        authorize_upload_mutation(user, upload, operation="import scene từ assembly")
        if upload.input_kind != candidate.source_format.value or upload.checksum != staged.source_file.checksum:
            raise ArtifactChecksumError("Selected Gaussian master differs from the legacy verified upload")
        intent = seal_gaussian_view_intent(
            {
                "schema_version": "1.0",
                "intent_id": f"gaussian-view-{uuid4().hex[:16]}",
                "assembly_id": stored.snapshot.assembly_id,
                "assembly_revision": stored.snapshot.revision,
                "assembly_checksum": stored.snapshot.assembly_checksum,
                "resolution_checksum": report.report_checksum,
                "candidate_id": candidate.candidate_id,
                "source_file_id": candidate.source_file_id,
                "source_format": candidate.source_format,
                "source_checksum": staged.source_file.checksum,
                "selected_by": user.user_id if user else "anonymous",
                "selected_at": datetime.now(UTC),
                "intent_checksum": "sha256:" + "0" * 64,
            }
        )
        current = deps.settings()
        imported = deps.imports().create(
            upload,
            request.name,
            user.user_id if user else None,
            user.display_name if user else None,
            user.role if user else None,
            idempotency_key=idempotency_key,
            gpu_index=current.product_geometry_gpu_index,
            input_intent=intent,
        )
        stored_intent = imported.input_intent or intent
        return AssemblyImportResponse(imported_scene=imported, intent_checksum=stored_intent.intent_checksum)
    except HTTPException:
        raise
    except (InputAssemblyConflictError, RuntimeStateConflictError, SceneImportError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (InputAssemblyNotFoundError, UploadNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise _handle_assembly_error(error) from error
