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
from src.api.studio.error_view import filter_job_progress_errors, filter_manifest_errors
from src.models.contracts.manifests import JobManifest, JobStatus, StageId, StageStatus
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.auth import Actor, UserRecord, actor_of, with_current_role
from src.services.orchestration.auth.quota_ledger import GuestQuotaExceededError, GuestQuotaIdempotencyConflictError
from src.services.orchestration.jobs.admission import job_reservation, resource_wait
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.lidar_overlay import lidar_overlay_file
from src.services.orchestration.jobs.progress import (
    JobProgress,
    awaiting_anonymization_review,
    awaiting_finalize,
    job_progress,
)
from src.services.orchestration.jobs.queue import job_requester_actors, job_requesters, queue_position
from src.services.orchestration.jobs.stage_views import StageViewList, stage_views
from src.services.orchestration.jobs.thumbnails import scene_thumbnail
from src.services.orchestration.jobs.worker_runtimes import has_live_runtime
from src.services.orchestration.processing import build_job_config, evaluate, is_presets_file, preset_values
from src.services.orchestration.processing.observed import load_usages, processing_seconds
from src.services.orchestration.projects import (
    JobCreateInput,
    JobNotFoundError,
    PrivacyGateBlockedError,
    ProjectNotFoundError,
)
from src.services.orchestration.projects.models import UploadProjectInput
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene import objectify_queue
from src.services.orchestration.scene.errors import SceneError
from src.services.orchestration.scene.objectify import AWAITING_CHOICE
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
    #: Job mới nhất đã che xong frame và đang chờ người upload xem bản đã che; danh sách cần biết để không gọi nó là
    #: "đang chạy" (cùng điều kiện với `waiting_for="anonymization_review"` của progress).
    awaiting_anonymization_review: bool = False
    #: Job đã xong nhưng tách theo vật lỗi hết số lần thử: scene chỉ có môi trường, chờ người dùng chọn chạy lại hoặc dùng
    #: hộp ứng viên (cùng điều kiện với `awaiting_choice` của `GET /jobs/{id}/scene/objectify`).
    awaiting_object_choice: bool = False
    #: Bước "Duyệt vật & Tạo mesh" của scene theo vật: chờ duyệt, đang dựng, hoặc Tạo mesh lỗi. None = không còn việc
    #: (scene Ready) hoặc scene cũ không có bước này. Cùng quy tắc với hàng tiến trình trong Studio (T-021).
    geometry_review: objectify_queue.GeometryReview | None = None
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

    # `qa_verified`: mọi video phải qua bộ che và được người upload chấp nhận; thiếu bộ che thì từ chối ngay.
    deps.require_anonymize(request.anonymize)
    if registry.job_profile() is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chưa có runtime cho job: cần PRODUCT_PROCESSING_CONFIG và PRODUCT_RUNTIME_MANIFEST, "
            "hoặc GPU worker đã công bố runtime (PRODUCT_RUNTIME_FROM_WORKERS=true)",
        )
    processing = None
    if settings.product_processing_config is not None and is_presets_file(settings.product_processing_config):
        presets, presets_checksum = deps.presets()
        capability = deps.capability()
        params = request.processing or preset_values(presets, "minimum_quality")
        anonymize = deps.require_anonymize(request.anonymize)
        try:
            observed = deps.observed_resource_budget(
                registry,
                params,
                capability.gpu_name if capability is not None else None,
                colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False),
            )
            evaluation = evaluate(presets, params, capability, observed=observed)
            processing = build_job_config(
                presets,
                presets_checksum,
                params,
                capability,
                colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False),
                anonymize=anonymize,
            )
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
        from src.services.orchestration.uploads.temporary import TemporaryUploadService

        TemporaryUploadService(uploads.database, uploads.resolver).reserve(
            [upload.upload_id, *([lidar.upload_id] if lidar is not None else [])]
        )
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
    return SceneFromUploadResponse(project=schemas.project_response(project), job=filter_manifest_errors(job, user))


#: Kết quả theo (job, revision scene hiện tại): đọc SceneIR chỉ khi revision đổi, không mỗi lần danh sách được poll.
_OBJECT_CHOICE_CACHE: dict[tuple[str, str], bool] = {}
_OBJECT_CHOICE_CACHE_MAX = 512


def _awaiting_object_choice(registry: ProjectRegistry, job: JobManifest) -> bool:
    """Scene của job có đang chờ người dùng chọn cách dựng tập vật (tách theo vật lỗi hết số lần thử) không."""
    done = any(
        stage.stage_id == StageId.OBJECT_EXTRACT and stage.status == StageStatus.SUCCEEDED
        for stage in job.stage_artifacts
    )
    if job.status != JobStatus.SUCCEEDED or not done:
        return False
    try:
        head = registry.scene.head_repository.get(job.job_id) if registry.scene.head_repository is not None else None
        key = (job.job_id, head.scene_revision) if head is not None else None
        if key is not None and key in _OBJECT_CHOICE_CACHE:
            waiting = _OBJECT_CHOICE_CACHE[key]
        else:
            waiting = registry.scene.current(job.job_id).scene.provenance.get("object_extraction") == AWAITING_CHOICE
            if key is not None:
                if len(_OBJECT_CHOICE_CACHE) >= _OBJECT_CHOICE_CACHE_MAX:
                    _OBJECT_CHOICE_CACHE.clear()
                _OBJECT_CHOICE_CACHE[key] = waiting
        # Đang chạy lại thì người dùng đã chọn rồi: không báo "chờ chọn" cho tới khi yêu cầu xong (kết quả không cache vì đổi nhanh).
        return waiting and not _objectify_request_pending(registry, job.job_id)
    except (SceneError, ArtifactStoreError, ValueError, OSError):
        return False  # scene chưa đọc được: danh sách không đoán, màn scene sẽ nói rõ


#: Trạng thái hình học theo (job, revision scene hiện tại); chỉ đọc SceneIR khi revision đổi, như `_OBJECT_CHOICE_CACHE`.
_GEOMETRY_CACHE: dict[tuple[str, str], objectify_queue.ObjectGeometry | None] = {}
_GEOMETRY_CACHE_MAX = 512


def _geometry_review(registry: ProjectRegistry, job: JobManifest) -> objectify_queue.GeometryReview | None:
    """Scene của job còn việc ở bước "Duyệt vật & Tạo mesh" không (Draft chờ duyệt, đang dựng, Tạo mesh lỗi)."""
    done = any(
        stage.stage_id == StageId.OBJECT_EXTRACT and stage.status == StageStatus.SUCCEEDED
        for stage in job.stage_artifacts
    )
    if job.status != JobStatus.SUCCEEDED or not done:
        return None
    try:
        head = registry.scene.head_repository.get(job.job_id) if registry.scene.head_repository is not None else None
        key = (job.job_id, head.scene_revision) if head is not None else None
        if key is not None and key in _GEOMETRY_CACHE:
            geometry = _GEOMETRY_CACHE[key]
            revision = head.scene_revision
        else:
            scene = registry.scene.current(job.job_id).scene
            geometry = objectify_queue.object_geometry_status(scene.provenance)
            revision = head.scene_revision if head is not None else scene.scene_revision
            if key is not None:
                if len(_GEOMETRY_CACHE) >= _GEOMETRY_CACHE_MAX:
                    _GEOMETRY_CACHE.clear()
                _GEOMETRY_CACHE[key] = geometry
        if geometry is None:
            return None  # scene cũ không có bước này: không đọc hàng đợi
        # Trạng thái hàng đợi đổi nhanh nên không cache.
        return _geometry_queue_state(job.job_id, geometry, revision)
    except (SceneError, ArtifactStoreError, ValueError, OSError):
        return None  # scene chưa đọc được: danh sách không đoán, màn scene sẽ nói rõ


def _geometry_queue_state(
    job_id: str, geometry: objectify_queue.ObjectGeometry, revision: str
) -> objectify_queue.GeometryReview | None:
    return objectify_queue.geometry_review(deps.settings(), job_id, geometry, revision)


def _objectify_request_pending(registry: ProjectRegistry, job_id: str) -> bool:
    """Có yêu cầu dựng lại tập vật đang xếp hàng hoặc chạy của job không (chỉ gọi cho scene đang chờ chọn)."""
    return objectify_queue.state(registry, deps.settings(), job_id).status in {"queued", "running"}


@router.get("/scenes", response_model=SceneListResponse)
def list_scenes(user: UserRecord | None = Depends(require_contributor)) -> SceneListResponse:
    """Scene của Studio (project tạo từ upload); project fixture/dataset không hiện ở đây."""
    registry = deps.registry()
    scenes: list[SceneSummary] = []
    measured = (
        processing_seconds(load_usages(registry.persistence.database)) if registry.persistence is not None else {}
    )
    requesters = job_requesters(registry.persistence.database) if registry.persistence is not None else {}
    projects = registry.list_projects()
    # Tra tài khoản chỉ khi có bản ghi cần điền role hiện tại (snapshot cũ không có role) hoặc người yêu cầu cũ.
    needs_directory = bool(requesters) or any(
        project.created_by is not None and project.created_by.role is None for project in projects
    )
    actors = auth_service().actors() if needs_directory else {}
    requester_actors = (
        job_requester_actors(registry.persistence.database, actors) if requesters and registry.persistence else {}
    )
    for project in projects:
        if project.input_manifest_ref is None:
            continue
        jobs = registry.list_jobs(project.project_id)
        latest = max(jobs, key=lambda job: job.started_at) if jobs else None
        if latest is not None:
            latest = filter_manifest_errors(latest, user)
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
                project=schemas.project_response(project).model_copy(
                    update={"created_by": with_current_role(project.created_by, actors)}
                ),
                latest_job=latest,
                preview_ready=latest is not None and deps.preview_ready(registry, latest.job_id),
                awaiting_anonymization_review=latest is not None and awaiting_anonymization_review(latest),
                awaiting_object_choice=latest is not None and _awaiting_object_choice(registry, latest),
                geometry_review=None if latest is None else _geometry_review(registry, latest),
                processing_seconds=None if latest is None else measured.get(latest.job_id),
                requested_by=None if latest is None else with_current_role(requester_actors.get(latest.job_id), actors),
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
    # T-040: không worker nào đang sống chạy được runtime của job thì UI báo "đang chờ GPU" thay vì im lặng.
    runtime_wait = registry.persistence is not None and not has_live_runtime(
        registry.persistence.database, job.runtime_manifest_checksum
    )
    progress = job_progress(
        job,
        attempts,
        deps.preview_ready(registry, job_id),
        observation,
        position,
        heartbeat_at=heartbeat_at,
        runtime_wait=runtime_wait,
    )
    progress = filter_job_progress_errors(progress, user)
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
