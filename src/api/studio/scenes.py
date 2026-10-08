"""Scene Studio: tạo scene từ video đã upload, liệt kê scene, tiến trình job."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from src.api import schemas
from src.api.auth import (
    auth_service,
    enforce_gpu_quota,
    guest_run_intent,
    idempotency_conflict_http,
    quota_exceeded_http,
    record_gpu_run,
    require_contributor,
)
from src.api.ownership import authorize_upload_mutation, owner_mutation_allowed
from src.api.studio import deps
from src.models.contracts.manifests import JobManifest, JobStatus
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.auth import Actor, UserRecord, actor_of
from src.services.orchestration.auth.quota_ledger import GuestQuotaExceededError, GuestQuotaIdempotencyConflictError
from src.services.orchestration.jobs.admission import job_reservation, resource_wait
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.lidar_overlay import lidar_overlay_file
from src.services.orchestration.jobs.progress import JobProgress, awaiting_finalize, job_progress
from src.services.orchestration.jobs.queue import job_requester_actors, job_requesters, queue_position
from src.services.orchestration.jobs.stage_views import StageViewList, stage_views
from src.services.orchestration.jobs.thumbnails import scene_thumbnail
from src.services.orchestration.processing import build_job_config, evaluate, is_presets_file, preset_values
from src.services.orchestration.processing.observed import load_usages, processing_seconds
from src.services.orchestration.projects import (
    JobCreateInput,
    JobNotFoundError,
    PrivacyGateBlockedError,
    ProjectNotFoundError,
)
from src.services.orchestration.projects.models import UploadProjectInput
from src.services.orchestration.uploads import UploadNotFoundError

router = APIRouter()


class SceneCapabilities(BaseModel):
    """Caller-specific authorization hints for actions on this scene card."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    can_delete_project: bool


class JobMutationCapabilities(BaseModel):
    """Caller-specific permissions on a job; quota remains a separate run policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    can_mutate: bool
    can_cancel: bool
    can_retry: bool


class SceneSummary(BaseModel):
    """Một scene trên màn hình Scenes: project upload + job mới nhất."""

    model_config = ConfigDict(extra="forbid")

    project: schemas.ProjectResponse
    latest_job: JobManifest | None = None
    preview_ready: bool = False
    #: Thời gian máy đã xử lý của job mới nhất (tổng các bước đã chạy xong); không gồm lúc xếp hàng và lúc chờ người
    #: dùng. None = job chưa có bước nào được đo.
    processing_seconds: float | None = None
    #: Người bấm chạy job mới nhất (tạo scene hoặc thử lại), theo nhật ký lượt xử lý; None khi không bật đăng nhập.
    requested_by: Actor | None = None
    capabilities: SceneCapabilities


class JobProgressResponse(JobProgress):
    """Job progress plus current actor's resource capabilities."""

    capabilities: JobMutationCapabilities


class SceneListResponse(BaseModel):
    """Scene tạo từ video upload, mới nhất trước."""

    model_config = ConfigDict(extra="forbid")

    scenes: list[SceneSummary]


class SceneFromUploadResponse(BaseModel):
    """Project (scene) tạo từ upload và job xử lý đầu tiên của nó."""

    model_config = ConfigDict(extra="forbid")

    project: schemas.ProjectResponse
    job: JobManifest


@router.post(
    "/scenes/from-upload",
    response_model=SceneFromUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": schemas.ApiErrorResponse}},
)
def create_scene_from_upload(
    request: UploadProjectInput,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: UserRecord | None = Depends(require_contributor),
) -> SceneFromUploadResponse:
    """Tạo scene từ video đã upload và xếp hàng job xử lý (worker chạy ngoài API).

    Kiểm input và execution profile trước khi chấp nhận intent. Guest dùng quota
    calendar-day atomic; Editor giữ rolling-24-hour quota, Reviewer không giới hạn.
    """
    enforce_gpu_quota(user)
    settings = deps.settings()
    registry = deps.registry()
    uploads = deps.uploads()
    try:
        upload = uploads.get(request.upload_id)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    authorize_upload_mutation(user, upload, operation="tạo scene từ")
    if upload.input_kind != "rgb_video":
        # Luồng import 3DGS (ADR 0004 §3) chưa có worker; không tạo job video từ file PLY/ZIP.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Đã nhận file 3DGS nhưng luồng dựng scene từ PLY/ZIP chưa được bật trên máy chủ",
        )
    lidar = None
    if request.lidar is not None:
        try:
            lidar = uploads.get(request.lidar.upload_id)
        except UploadNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        authorize_upload_mutation(user, lidar, operation="đính kèm LiDAR vào scene từ")
        if lidar.input_kind not in {"registered_lidar", "lidar_scan_sequence"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="File đính kèm không phải gói LiDAR (.zip gồm đám mây hoặc scan, quỹ đạo, calibration, thời điểm frame)",
            )
    quota_intent = guest_run_intent(user, "scene.create", idempotency_key, request.model_dump(mode="json"))
    if quota_intent is not None:
        if registry.persistence is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Guest quota requires the shared persistent runtime database",
            )
        try:
            duplicate = registry.lookup_quota_job(quota_intent)
        except GuestQuotaIdempotencyConflictError as error:
            raise idempotency_conflict_http(error) from error
        if duplicate is not None:
            try:
                project = registry.get_project(duplicate.project_id)
            except ProjectNotFoundError as error:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
            return SceneFromUploadResponse(project=schemas.project_response(project), job=duplicate)

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
        try:
            evaluation = evaluate(presets, params, capability)
            processing = build_job_config(presets, presets_checksum, params, capability)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
        if evaluation.blocking:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Thông số vượt cấu hình máy xử lý và có thể crash; giảm các ô được tô đỏ",
            )
    elif request.processing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Worker chưa dùng file thông số chung; không nhận thông số tùy chỉnh",
        )
    try:
        project = registry.create_project_from_upload(
            upload,
            request,
            settings.product_privacy_mode,
            lidar,
            actor_of(user),
            defer_persistence=registry.persistence is not None,
        )
        if registry.persistence is None:
            if quota_intent is not None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Guest quota requires the shared persistent runtime database",
                )
            uploads.link_project(upload.upload_id, project.project_id)
            if lidar is not None:
                uploads.link_project(lidar.upload_id, project.project_id)
        job = registry.create_job(
            JobCreateInput(project_id=project.project_id),
            processing,
            requested_by=actor_of(user),
            owner_user_id=user.user_id if user is not None else None,
            quota_intent=quota_intent,
            project_record=project if registry.persistence is not None else None,
            upload_ids_to_link=tuple(
                upload_id
                for upload_id in (upload.upload_id, lidar.upload_id if lidar is not None else None)
                if upload_id
            )
            if registry.persistence is not None
            else (),
        )
    except GuestQuotaExceededError as error:
        raise quota_exceeded_http(error) from error
    except GuestQuotaIdempotencyConflictError as error:
        raise idempotency_conflict_http(error) from error
    except (PrivacyGateBlockedError, RuntimeStateConflictError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    record_gpu_run(user, job.job_id, {"kind": "scene.create", "project_id": project.project_id})
    return SceneFromUploadResponse(project=schemas.project_response(project), job=job)


@router.get("/scenes", response_model=SceneListResponse)
def list_scenes(user: UserRecord | None = Depends(require_contributor)) -> SceneListResponse:
    """Scene của Studio (project tạo từ upload); project fixture/dataset không hiện ở đây."""
    registry = deps.registry()
    scenes: list[SceneSummary] = []
    measured = (
        processing_seconds(load_usages(registry.persistence.database)) if registry.persistence is not None else {}
    )
    requesters = job_requesters(registry.persistence.database) if registry.persistence is not None else {}
    actors = auth_service().actors() if requesters else {}
    requester_actors = (
        job_requester_actors(registry.persistence.database, actors) if requesters and registry.persistence else {}
    )
    for project in registry.list_projects():
        if project.input_manifest_ref is None:
            continue
        jobs = registry.list_jobs(project.project_id)
        latest = max(jobs, key=lambda job: job.started_at) if jobs else None
        project_owner_id = project.created_by.user_id if project.created_by is not None else None
        can_delete_project = owner_mutation_allowed(user, project_owner_id)
        if can_delete_project and user is not None and user.role == "guest":
            # Project deletion cascades to every job; show the control only if each
            # affected job has the same known owner. Upload creation already guards
            # ownership, and upload owner IDs are immutable after creation.
            can_delete_project = all(
                owner_mutation_allowed(user, registry.get_job_owner_user_id(job.job_id)) for job in jobs
            )
        scenes.append(
            SceneSummary(
                project=schemas.project_response(project),
                latest_job=latest,
                preview_ready=latest is not None and deps.preview_ready(registry, latest.job_id),
                processing_seconds=None if latest is None else measured.get(latest.job_id),
                requested_by=None if latest is None else requester_actors.get(latest.job_id),
                capabilities=SceneCapabilities(can_delete_project=can_delete_project),
            )
        )
    # Project upload luôn có created_at; mốc 0 chỉ là phòng hờ cho record cũ.
    scenes.sort(key=lambda scene: scene.project.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return SceneListResponse(scenes=scenes)


@router.get("/jobs/{job_id}/progress", response_model=JobProgressResponse)
def get_job_progress(job_id: str, user: UserRecord | None = Depends(require_contributor)) -> JobProgressResponse:
    """Tiến trình từng stage của attempt hiện tại; UI poll endpoint này."""
    registry = deps.registry()
    try:
        job = registry.get_job(job_id)
        attempts = registry.list_job_attempts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    observation = resource_wait(registry.persistence.database, job) if registry.persistence is not None else None
    reservation = job_reservation(registry.persistence.database, job_id) if registry.persistence is not None else None
    heartbeat_at = reservation.heartbeat_at if reservation is not None else None
    # Vị trí hàng đợi chỉ tính cho job đang chờ worker (đọc journal của mọi job): job đang chạy không cần.
    position = queue_position(registry, job_id) if job.status == JobStatus.QUEUED or awaiting_finalize(job) else None
    progress = job_progress(
        job,
        attempts,
        deps.preview_ready(registry, job_id),
        observation,
        position,
        heartbeat_at=heartbeat_at,
    )
    allowed = owner_mutation_allowed(
        user,
        registry.get_job_owner_user_id(job_id) if user is not None and user.role == "guest" else None,
    )
    return JobProgressResponse(
        **progress.model_dump(),
        capabilities=JobMutationCapabilities(
            can_mutate=allowed,
            can_cancel=allowed
            and progress.status in {JobStatus.QUEUED, JobStatus.RUNNING}
            and progress.waiting_for != "metric_confirmation",
            can_retry=allowed
            and progress.status == JobStatus.FAILED
            and progress.error is not None
            and progress.error.retryable,
        ),
    )


@router.get("/jobs/{job_id}/stage-views", response_model=StageViewList)
def get_stage_views(job_id: str) -> StageViewList:
    """Kết quả xem được của từng bước (ADR 0005); UI chọn một lớp để nạp."""
    try:
        return stage_views(deps.registry(), job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/jobs/{job_id}/lidar-overlay", response_class=FileResponse)
def get_lidar_overlay(job_id: str) -> FileResponse:
    """Đám mây LiDAR đã căn chỉnh của scene, thu gọn để vẽ chồng lên 3DGS: float32 little-endian `x y z` (mét, Z-up)."""
    registry = deps.registry()
    cache = deps.settings().artifact_root.expanduser().resolve().parent / "lidar_overlay_cache"
    try:
        path = lidar_overlay_file(registry, job_id, cache)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (ArtifactStoreError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Không đọc được dữ liệu LiDAR của scene này"
        ) from error
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scene này không có LiDAR đã căn chỉnh")
    # Tên file khoá theo checksum bản ghi căn chỉnh (bất biến) → cache trình duyệt dài hạn an toàn.
    return FileResponse(
        path, media_type="application/octet-stream", headers={"Cache-Control": "private, max-age=86400"}
    )


@router.get("/jobs/{job_id}/thumbnail.jpg", response_class=FileResponse)
def get_job_thumbnail(job_id: str) -> FileResponse:
    """Ảnh nhỏ của frame đầu cho thẻ scene; 404 khi job chưa trích frame."""
    registry = deps.registry()
    # Cache dẫn xuất cạnh kho artifact, không nằm trong kho (không phải artifact).
    cache = deps.settings().artifact_root.expanduser().resolve().parent / "thumbnail_cache"
    try:
        path = scene_thumbnail(registry, job_id, cache)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job chưa có frame để làm ảnh xem trước")
    # Tên file khoá theo checksum frame bất biến → cache trình duyệt dài hạn an toàn.
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
