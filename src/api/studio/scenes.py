"""Scene Studio: tạo scene từ video đã upload, liệt kê scene, tiến trình job."""

import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
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
from src.api.product.http_cache import checksum_etag, not_modified
from src.api.studio import deps
from src.api.studio.error_view import filter_job_progress_errors, filter_manifest_errors
from src.api.studio.gpu import deployment_id
from src.models.contracts.manifests import JobManifest, JobStatus, StageId, StageStatus
from src.models.contracts.retryability import is_execution_error_retryable
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import RuleResult
from src.services.orchestration.artifacts import ArtifactStoreError, sha256_file
from src.services.orchestration.auth import Actor, UserRecord, actor_of, with_current_role
from src.services.orchestration.auth.quota_ledger import GuestQuotaExceededError, GuestQuotaIdempotencyConflictError
from src.services.orchestration.gpu.status import GpuCapacity, gpu_capacity
from src.services.orchestration.jobs.admission import job_reservation, resource_wait
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.lidar_overlay import lidar_overlay_file
from src.services.orchestration.jobs.progress import (
    JobProgress,
    awaiting_anonymization_review,
    awaiting_finalize,
    awaiting_metric_confirmation,
    job_progress,
)
from src.services.orchestration.jobs.queue import job_requester_actors, job_requesters, queue_position
from src.services.orchestration.jobs.stage_results import stage_notes
from src.services.orchestration.jobs.stage_views import StageViewList, stage_views
from src.services.orchestration.jobs.step_marks import list_marks
from src.services.orchestration.jobs.thumbnails import scene_thumbnail
from src.services.orchestration.jobs.worker_runtimes import has_live_runtime
from src.services.orchestration.pipeline.models import PipelineView, PipelineWait
from src.services.orchestration.pipeline.next_action import (
    NextActionFacts,
    NextActionKind,
    PackageFacts,
    SceneOperationFacts,
    next_action,
    pending_candidates,
)
from src.services.orchestration.pipeline.view import compose_steps, current_step, is_usable, scene_operation_wait
from src.services.orchestration.processing import build_job_config, evaluate, is_presets_file, preset_values
from src.services.orchestration.processing.observed import load_usages, processing_seconds
from src.services.orchestration.projects import (
    JobCreateInput,
    JobNotFoundError,
    PrivacyGateBlockedError,
)
from src.services.orchestration.projects.errors import ProjectNotFoundError
from src.services.orchestration.projects.models import UploadProjectInput
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.review.simulation_package import current_package
from src.services.orchestration.review.workflow import review_state
from src.services.orchestration.scene import objectify_queue
from src.services.orchestration.scene.errors import SceneError
from src.services.orchestration.scene.objectify import AWAITING_CHOICE
from src.services.orchestration.uploads import UploadNotFoundError
from src.services.scene.geometry_state import object_geometry_view

router = APIRouter()


@router.get("/projects/{project_id}/display-video", response_class=FileResponse)
def get_project_display_video(project_id: str) -> FileResponse:
    """Serve the optional replay-only MP4 without adding it to the pipeline InputManifest."""
    registry = deps.registry()
    try:
        project = registry.get_project(project_id)
        reference = project.display_video_ref
        if reference is None:
            raise HTTPException(status_code=404, detail="Project không có video xem lại")
        path = registry.runtime_resolver.require(reference)
        if sha256_file(path) != reference.artifact_checksum:
            raise HTTPException(status_code=409, detail="Video xem lại sai checksum")
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=404, detail="Không tìm thấy project") from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=404, detail="Không tìm thấy video xem lại") from error
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, no-cache"})


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
    #: Việc tiếp theo, cùng hàm với trang scene (T-059); API cũ không gửi trường này.
    next_action: NextActionKind | None = None
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
    found = _scene_geometry(registry, job)
    if found is None or found[0] is None:
        return None  # scene cũ không có bước này (hoặc chưa đọc được): không đọc hàng đợi
    # Trạng thái hàng đợi đổi nhanh nên không cache.
    return _geometry_queue_state(job.job_id, found[0], found[1])


def _scene_geometry(
    registry: ProjectRegistry, job: JobManifest
) -> tuple[objectify_queue.ObjectGeometry | None, str] | None:
    """Trạng thái hình học + revision của scene hiện tại, đệm theo revision head; None khi scene chưa đọc được."""
    try:
        head = registry.scene.head_repository.get(job.job_id) if registry.scene.head_repository is not None else None
        key = (job.job_id, head.scene_revision) if head is not None else None
        if key is not None and key in _GEOMETRY_CACHE:
            return _GEOMETRY_CACHE[key], head.scene_revision
        scene = registry.scene.current(job.job_id).scene
        geometry = object_geometry_view(scene)
        revision = head.scene_revision if head is not None else scene.scene_revision
        if key is not None:
            if len(_GEOMETRY_CACHE) >= _GEOMETRY_CACHE_MAX:
                _GEOMETRY_CACHE.clear()
            _GEOMETRY_CACHE[key] = geometry
        return geometry, revision
    except (SceneError, ArtifactStoreError, ValueError, OSError):
        return None  # scene chưa đọc được: danh sách không đoán, màn scene sẽ nói rõ


def _list_next_action(
    registry: ProjectRegistry, job: JobManifest, preview_ready: bool, awaiting_review: bool, awaiting_choice: bool
) -> NextActionKind:
    """Cùng hàm `next_action` với trang scene; danh sách không đọc gói / vật chờ nên scene xong là `scene_ready`."""
    waiting = (
        "anonymization_review"
        if awaiting_review
        else "metric_confirmation"
        if awaiting_metric_confirmation(job, preview_ready)
        else None
    )
    retryable: bool | None = None
    if job.status == JobStatus.FAILED:
        attempts = registry.list_job_attempts(job.job_id)
        failure = next((event.error for event in reversed(attempts) if event.error is not None), None)
        retryable = failure is not None and is_execution_error_retryable(failure)
    geometry = None
    operation = None
    if job.status == JobStatus.SUCCEEDED:
        found = _scene_geometry(registry, job)
        geometry = found[0] if found is not None else None
        record = (
            objectify_queue.latest_request(registry.persistence.database, job.job_id)
            if registry.persistence is not None and found is not None
            else None
        )
        if record is not None and found is not None:
            operation = SceneOperationFacts(
                status=record.status, mode=record.mode, on_current_revision=record.base_revision == found[1]
            )
    return next_action(
        NextActionFacts(
            job_status=job.status,
            waiting_for=waiting,
            failure_retryable=retryable,
            awaiting_object_choice=awaiting_choice,
            object_geometry=geometry,
            scene_operation=operation,
            pending_candidates=None,
            package=None,
            review_status=None,
        )
    ).kind


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
    listed = []
    for project in projects:
        if project.input_manifest_ref is None:
            continue
        jobs = registry.list_jobs(project.project_id)
        listed.append((project, jobs, max(jobs, key=lambda job: job.started_at) if jobs else None))
    # T-054: chỉ đọc số đo của các job đang hiển thị (index theo job), không quét cả bảng mỗi lần danh sách được poll.
    shown = [latest.job_id for _, _, latest in listed if latest is not None]
    measured = (
        processing_seconds(load_usages(registry.persistence.database, job_ids=shown))
        if registry.persistence is not None
        else {}
    )
    for project, jobs, latest in listed:
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
        # Mỗi cờ đọc một lần cho scene (mỗi lần đọc preview/lựa chọn vật chạm DB và file).
        preview_ready = latest is not None and deps.preview_ready(registry, latest.job_id)
        awaiting_review = latest is not None and awaiting_anonymization_review(latest)
        awaiting_choice = latest is not None and _awaiting_object_choice(registry, latest)
        scenes.append(
            SceneSummary(
                project=schemas.project_response(project).model_copy(
                    update={"created_by": with_current_role(project.created_by, actors)}
                ),
                latest_job=latest,
                preview_ready=preview_ready,
                awaiting_anonymization_review=awaiting_review,
                awaiting_object_choice=awaiting_choice,
                geometry_review=None if latest is None else _geometry_review(registry, latest),
                next_action=None
                if latest is None
                else _list_next_action(registry, latest, preview_ready, awaiting_review, awaiting_choice),
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
    return _job_progress_response(deps.registry(), job_id, user)[1]


def _job_progress_response(
    registry: ProjectRegistry, job_id: str, user: UserRecord | None
) -> tuple[JobManifest, JobProgressResponse]:
    """Thân của `/progress`, dùng chung với `/pipeline` (T-059)."""
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
        notes=stage_notes(registry, job),
    )
    progress = filter_job_progress_errors(progress, user)
    allowed = owner_mutation_allowed(
        user,
        registry.get_job_owner_user_id(job_id) if user is not None and user.role == "guest" else None,
    )
    return job, JobProgressResponse(
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


class PipelineViewResponse(PipelineView):
    """Một lần gọi đủ cho trang scene: bước, chờ gì, việc tiếp theo, kèm tiến trình và hàng đợi tách vật (T-059)."""

    progress: JobProgressResponse
    objectify: objectify_queue.ObjectifyState | None = None
    gpu: GpuCapacity | None = None


def _pipeline_wait(progress: JobProgressResponse) -> PipelineWait | None:
    if progress.waiting_for in {"anonymization_review", "metric_confirmation"}:
        step = (
            StageId.ANONYMIZATION_REVIEW
            if progress.waiting_for == "anonymization_review"
            else StageId.METRIC_CANONICALIZE
        )
        return PipelineWait(kind="user", step_id=step)
    if progress.waiting_for in {"resources", "runtime"}:
        return PipelineWait(kind=progress.waiting_for, step_id=progress.current_stage)
    if progress.status == JobStatus.QUEUED:
        return PipelineWait(kind="queue", step_id=progress.current_stage)
    return None


def _ready_facts(
    registry: ProjectRegistry, job_id: str, scene: SceneIR
) -> tuple[int | None, PackageFacts | None, str | None]:
    """Vật chờ xác nhận, gói và trạng thái duyệt của revision hiện tại; đọc lỗi thì để None (không làm hỏng cả view)."""
    try:
        package = current_package(registry, job_id)
        review = review_state(registry, job_id)
    except (SceneError, ArtifactStoreError, ValueError, OSError):
        return pending_candidates(scene), None, None
    facts = PackageFacts(
        exists_for_revision=package is not None
        and package.scene_revision == scene.scene_revision
        and package.package_ref is not None,
        preflight_failed=package is not None and package.preflight.blocking_result == RuleResult.FAIL,
    )
    status_value = review.record.status.value if review.record.scene_revision == scene.scene_revision else None
    return pending_candidates(scene), facts, status_value


@router.get("/jobs/{job_id}/pipeline", response_model=PipelineViewResponse)
def get_job_pipeline(
    job_id: str,
    response: Response,
    user: UserRecord | None = Depends(require_contributor),
    if_none_match: Annotated[str | None, Header()] = None,
) -> PipelineViewResponse | Response:
    """Tiến trình hợp nhất: danh sách bước thật tới khi scene dùng được, ai đang làm gì, việc tiếp theo (T-059).

    ETag theo nội dung: không có gì đổi thì trả 304, trình duyệt không phải tải và vẽ lại.
    """
    registry = deps.registry()
    job, progress = _job_progress_response(registry, job_id, user)
    database = registry.persistence.database if registry.persistence is not None else None
    scene: SceneIR | None = None
    try:
        scene = registry.scene.current(job_id).scene
    except (SceneError, ArtifactStoreError, ValueError, OSError):
        scene = None
    geometry = object_geometry_view(scene) if scene is not None else None
    objectify = objectify_queue.state(registry, deps.settings(), job_id) if scene is not None and database else None
    marks = list_marks(database, job_id) if database is not None else []
    steps = compose_steps(progress, job, marks, objectify, geometry)
    awaiting_choice = (
        objectify is not None and objectify.awaiting_choice and objectify.status not in {"queued", "running"}
    )
    operation = (
        SceneOperationFacts(
            status=objectify.status,
            mode=objectify.mode,
            on_current_revision=objectify.base_revision == objectify.scene_revision,
        )
        if objectify is not None and objectify.mode is not None
        else None
    )
    pending: int | None = None
    package: PackageFacts | None = None
    review_status: str | None = None
    if scene is not None and progress.status == JobStatus.SUCCEEDED and geometry in {None, "ready"}:
        pending, package, review_status = _ready_facts(registry, job_id, scene)
    elif scene is not None:
        pending = pending_candidates(scene)
    action = next_action(
        NextActionFacts(
            job_status=progress.status,
            waiting_for=progress.waiting_for,
            failure_retryable=progress.error.retryable if progress.error is not None else None,
            awaiting_object_choice=awaiting_choice,
            object_geometry=geometry,
            scene_operation=operation,
            pending_candidates=pending,
            package=package,
            review_status=review_status,
        )
    )
    waiting_for_machine = progress.status == JobStatus.QUEUED or progress.waiting_for in {"resources", "runtime"}
    gpu = gpu_capacity(database, deployment_id()) if waiting_for_machine and database is not None else None
    view = PipelineViewResponse(
        job_id=job_id,
        scene_revision=scene.scene_revision if scene is not None else None,
        usable=is_usable(progress.status, geometry, awaiting_choice),
        steps=steps,
        current_step=current_step(steps),
        wait=_pipeline_wait(progress) or scene_operation_wait(objectify, geometry),
        next_action=action,
        version="",
        progress=progress,
        objectify=objectify,
        gpu=gpu.model_copy(update={"elapsed_seconds": None, "remaining_seconds": None}) if gpu is not None else None,
    )
    version = hashlib.sha256(view.model_dump_json(exclude={"version"}).encode("utf-8")).hexdigest()[:32]
    etag = f'"{version}"'
    if not_modified(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    return view.model_copy(update={"version": version})


@router.get("/jobs/{job_id}/stage-views", response_model=StageViewList)
def get_stage_views(
    job_id: str,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> StageViewList | Response:
    """Kết quả xem được của từng bước (ADR 0005); UI chọn một lớp để nạp. ETag theo revision manifest (T-054)."""
    try:
        registry = deps.registry()
        etag = checksum_etag(registry.get_job(job_id).job_manifest_checksum)
        if not_modified(if_none_match, etag):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "private, no-cache"
        return stage_views(registry, job_id)
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
