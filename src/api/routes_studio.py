"""Endpoint Studio MVP: upload video, chọn video để dựng scene, theo dõi tiến trình.

Upload nhận raw body (không multipart) để stream file lớn thẳng vào artifact store
mà không cần thêm dependency; file I/O đồng bộ chạy qua threadpool để không chặn
event loop. Các endpoint còn lại là `def` đồng bộ như `routes_product`.
"""

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from src.api import schemas
from src.config import get_settings
from src.models.contracts.manifests import JobManifest
from src.services.orchestration.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactResolver,
    ArtifactStoreError,
    ArtifactTooLargeError,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.progress import JobProgress, job_progress
from src.services.orchestration.projects import (
    JobCreateInput,
    JobNotFoundError,
    PrivacyGateBlockedError,
    get_project_registry,
)
from src.services.orchestration.projects.models import UploadProjectInput
from src.services.orchestration.uploads import (
    UploadError,
    UploadNotFoundError,
    UploadRecord,
    VideoUploadService,
)

router = APIRouter(tags=["studio"])


class UploadListResponse(BaseModel):
    """Video đã upload, mới nhất trước."""

    model_config = ConfigDict(extra="forbid")

    uploads: list[UploadRecord]


class SceneFromUploadResponse(BaseModel):
    """Project (scene) tạo từ upload và job xử lý đầu tiên của nó."""

    model_config = ConfigDict(extra="forbid")

    project: schemas.ProjectResponse
    job: JobManifest


def _uploads() -> VideoUploadService:
    settings = get_settings()
    return VideoUploadService(
        RuntimeDatabase(settings.database_url),
        ArtifactResolver(settings.artifact_root),
        settings.product_upload_max_bytes,
    )


@router.post("/uploads", response_model=UploadRecord, status_code=status.HTTP_201_CREATED)
async def upload_video(request: Request, filename: str = Query(..., min_length=1, max_length=255)) -> UploadRecord:
    """Nhận bytes video trong body; bytes gốc được giữ nguyên, checksum tính khi ghi."""
    service = _uploads()
    try:
        pending = await run_in_threadpool(service.begin, filename)
    except UploadError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    try:
        async for chunk in request.stream():
            if chunk:
                await run_in_threadpool(pending.publication.write, chunk)
        return await run_in_threadpool(service.finish, pending)
    except ArtifactTooLargeError as error:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except ArtifactAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    finally:
        # Client ngắt giữa chừng hoặc lỗi bất kỳ: không để lại file tạm.
        pending.publication.abort()


@router.get("/uploads", response_model=UploadListResponse)
def list_uploads() -> UploadListResponse:
    """Danh sách video đã upload để người dùng chọn."""
    return UploadListResponse(uploads=_uploads().list())


@router.post(
    "/scenes/from-upload",
    response_model=SceneFromUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": schemas.ApiErrorResponse}},
)
def create_scene_from_upload(request: UploadProjectInput) -> SceneFromUploadResponse:
    """Tạo scene từ video đã upload và xếp hàng job xử lý (worker chạy ngoài API).

    Kiểm execution profile trước khi tạo project để không sinh scene mồ côi khi
    deployment chưa cấu hình worker.
    """
    settings = get_settings()
    if settings.product_privacy_mode != "self_attested":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video upload cần QA xác nhận ẩn danh; đặt PRODUCT_PRIVACY_MODE=self_attested cho MVP",
        )
    registry = get_project_registry()
    if registry.execution_profile is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chưa cấu hình worker: cần PRODUCT_PROCESSING_CONFIG và PRODUCT_RUNTIME_MANIFEST",
        )
    uploads = _uploads()
    try:
        upload = uploads.get(request.upload_id)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    project = registry.create_project_from_upload(upload, request, settings.product_privacy_mode)
    uploads.link_project(upload.upload_id, project.project_id)
    try:
        job = registry.create_job(JobCreateInput(project_id=project.project_id))
    except (PrivacyGateBlockedError, RuntimeStateConflictError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return SceneFromUploadResponse(project=schemas.project_response(project), job=job)


@router.get("/jobs/{job_id}/progress", response_model=JobProgress)
def get_job_progress(job_id: str) -> JobProgress:
    """Tiến trình từng stage của attempt hiện tại; UI poll endpoint này."""
    registry = get_project_registry()
    try:
        job = registry.get_job(job_id)
        attempts = registry.list_job_attempts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    try:
        registry.get_preview(job_id)
        preview_ready = True
    except (ArtifactStoreError, ValueError):
        preview_ready = False
    return job_progress(job, attempts, preview_ready)
