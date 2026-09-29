"""Scene Studio: tạo scene từ video đã upload, liệt kê scene, tiến trình job."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from src.api import schemas
from src.api.auth import enforce_gpu_quota, record_gpu_run, require_editor
from src.api.studio import deps
from src.models.contracts.manifests import JobManifest
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.progress import JobProgress, job_progress
from src.services.orchestration.processing import build_job_config, evaluate, is_presets_file, preset_values
from src.services.orchestration.projects import JobCreateInput, JobNotFoundError, PrivacyGateBlockedError
from src.services.orchestration.projects.models import UploadProjectInput
from src.services.orchestration.stage_views import StageViewList, stage_views
from src.services.orchestration.uploads import UploadNotFoundError

router = APIRouter()


class SceneSummary(BaseModel):
    """Một scene trên màn hình Scenes: project upload + job mới nhất."""

    model_config = ConfigDict(extra="forbid")

    project: schemas.ProjectResponse
    latest_job: JobManifest | None = None
    preview_ready: bool = False


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
    request: UploadProjectInput, user: UserRecord | None = Depends(require_editor)
) -> SceneFromUploadResponse:
    """Tạo scene từ video đã upload và xếp hàng job xử lý (worker chạy ngoài API).

    Kiểm execution profile trước khi tạo project để không sinh scene mồ côi khi
    deployment chưa cấu hình worker. Khi bật đăng nhập: kiểm hạn mức scene/24 giờ của
    Editor (Reviewer không giới hạn) theo số lần xử lý GPU/24 giờ và ghi nhật ký.
    """
    enforce_gpu_quota(user)
    settings = deps.settings()
    if settings.product_privacy_mode != "self_attested":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video upload cần QA xác nhận ẩn danh; đặt PRODUCT_PRIVACY_MODE=self_attested cho MVP",
        )
    registry = deps.registry()
    if registry.execution_profile is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chưa cấu hình worker: cần PRODUCT_PROCESSING_CONFIG và PRODUCT_RUNTIME_MANIFEST",
        )
    uploads = deps.uploads()
    try:
        upload = uploads.get(request.upload_id)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if upload.input_kind != "rgb_video":
        # Luồng import 3DGS (ADR 0004 §3) chưa có worker; không tạo job video từ file PLY/ZIP.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Đã nhận file 3DGS nhưng luồng dựng scene từ PLY/ZIP chưa được bật trên máy chủ",
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
    project = registry.create_project_from_upload(upload, request, settings.product_privacy_mode)
    uploads.link_project(upload.upload_id, project.project_id)
    try:
        job = registry.create_job(JobCreateInput(project_id=project.project_id), processing)
    except (PrivacyGateBlockedError, RuntimeStateConflictError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    record_gpu_run(user, job.job_id, {"kind": "scene.create", "project_id": project.project_id})
    return SceneFromUploadResponse(project=schemas.project_response(project), job=job)


@router.get("/scenes", response_model=SceneListResponse)
def list_scenes() -> SceneListResponse:
    """Scene của Studio (project tạo từ upload); project fixture/dataset không hiện ở đây."""
    registry = deps.registry()
    scenes: list[SceneSummary] = []
    for project in registry.list_projects():
        if project.input_manifest_ref is None:
            continue
        jobs = registry.list_jobs(project.project_id)
        latest = max(jobs, key=lambda job: job.started_at) if jobs else None
        scenes.append(
            SceneSummary(
                project=schemas.project_response(project),
                latest_job=latest,
                preview_ready=latest is not None and deps.preview_ready(registry, latest.job_id),
            )
        )
    # Project upload luôn có created_at; mốc 0 chỉ là phòng hờ cho record cũ.
    scenes.sort(key=lambda scene: scene.project.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return SceneListResponse(scenes=scenes)


@router.get("/jobs/{job_id}/progress", response_model=JobProgress)
def get_job_progress(job_id: str) -> JobProgress:
    """Tiến trình từng stage của attempt hiện tại; UI poll endpoint này."""
    registry = deps.registry()
    try:
        job = registry.get_job(job_id)
        attempts = registry.list_job_attempts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return job_progress(job, attempts, deps.preview_ready(registry, job_id))


@router.get("/jobs/{job_id}/stage-views", response_model=StageViewList)
def get_stage_views(job_id: str) -> StageViewList:
    """Kết quả xem được của từng bước (ADR 0005); UI chọn một lớp để nạp."""
    try:
        return stage_views(deps.registry(), job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
