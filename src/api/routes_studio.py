"""Endpoint Studio MVP: upload video, chọn video để dựng scene, theo dõi tiến trình.

Upload nhận raw body (không multipart) để stream file lớn thẳng vào artifact store
mà không cần thêm dependency; file I/O đồng bộ chạy qua threadpool để không chặn
event loop. Các endpoint còn lại là `def` đồng bộ như `routes_product`.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
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
from src.services.orchestration.processing import (
    Evaluation,
    MachineCapability,
    ParameterSpec,
    ProcessingConfigError,
    ProcessingPresets,
    build_job_config,
    evaluate,
    is_presets_file,
    load_presets,
    maximum_for_machine,
    preset_values,
)
from src.services.orchestration.processing.capability import latest as latest_capability
from src.services.orchestration.projects import (
    JobCreateInput,
    JobNotFoundError,
    PrivacyGateBlockedError,
    ProjectRegistry,
    get_project_registry,
)
from src.services.orchestration.projects.models import UploadProjectInput
from src.services.orchestration.samples import DemoLibrary, DemoManifest, DemoUnavailableError, SampleSummary
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


class ProcessingOptions(BaseModel):
    """Mọi thứ UI cần để vẽ bảng thông số: spec, preset, máy worker và ước lượng mặc định."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    parameters: list[ParameterSpec]
    presets: dict[str, dict[str, int | float | str]]
    capability: MachineCapability | None
    default_evaluation: Evaluation
    resource_note: str


class EvaluateRequest(BaseModel):
    """Bộ thông số cần kiểm (đủ mọi key của file cấu hình chung)."""

    model_config = ConfigDict(extra="forbid")

    params: dict[str, int | float | str]


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
    processing = None
    if settings.product_processing_config is not None and is_presets_file(settings.product_processing_config):
        presets, presets_checksum = _presets()
        capability = _capability()
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
    return job_progress(job, attempts, _preview_ready(registry, job_id))


class SampleListResponse(BaseModel):
    """Video mẫu đã xử lý sẵn, hiển thị cạnh ô tải video lên."""

    model_config = ConfigDict(extra="forbid")

    samples: list[SampleSummary]


def _samples() -> DemoLibrary:
    return DemoLibrary(get_settings().product_demo_dir)


@router.get("/samples", response_model=SampleListResponse)
def list_samples() -> SampleListResponse:
    """Mọi video mẫu hợp lệ trong thư viện; rỗng khi deployment chưa có bundle nào."""
    return SampleListResponse(samples=_samples().summaries())


@router.get("/samples/{sample_id}", response_model=DemoManifest)
def get_sample(sample_id: str) -> DemoManifest:
    """Manifest của một video mẫu: stage, thời lượng thật, thông số, file."""
    try:
        return _samples().bundle(sample_id).manifest()
    except DemoUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/samples/{sample_id}/files/{name}")
def get_sample_file(sample_id: str, name: str) -> FileResponse:
    """Một file của video mẫu; chỉ tên trong allow-list và đúng checksum mới được trả."""
    try:
        entry, path = _samples().bundle(sample_id).file(name)
    except DemoUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return FileResponse(
        path,
        media_type=entry.media_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


def _preview_ready(registry: ProjectRegistry, job_id: str) -> bool:
    """Preview 3DGS đã commit và verify được (không dùng file lẻ trên đĩa)."""
    try:
        registry.get_preview(job_id)
    except (ArtifactStoreError, ValueError):
        return False
    return True


@router.get("/scenes", response_model=SceneListResponse)
def list_scenes() -> SceneListResponse:
    """Scene của Studio (project tạo từ upload); project fixture/dataset không hiện ở đây."""
    registry = get_project_registry()
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
                preview_ready=latest is not None and _preview_ready(registry, latest.job_id),
            )
        )
    # Project upload luôn có created_at; mốc 0 chỉ là phòng hờ cho record cũ.
    scenes.sort(key=lambda scene: scene.project.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return SceneListResponse(scenes=scenes)


def _presets() -> tuple[ProcessingPresets, str]:
    """File cấu hình chung đang dùng (PRODUCT_PROCESSING_CONFIG)."""
    path = get_settings().product_processing_config
    if path is None or not is_presets_file(path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chưa cấu hình file thông số chung: đặt PRODUCT_PROCESSING_CONFIG=configs/product/processing_presets_v1.json",
        )
    try:
        return load_presets(path)
    except ProcessingConfigError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


def _capability() -> MachineCapability | None:
    return latest_capability(RuntimeDatabase(get_settings().database_url))


@router.get("/processing/options", response_model=ProcessingOptions)
def get_processing_options() -> ProcessingOptions:
    """Thông số chỉnh được + preset tối thiểu/tối đa/tối đa cho máy worker hiện tại."""
    presets, _ = _presets()
    capability = _capability()
    minimum = preset_values(presets, "minimum_quality")
    return ProcessingOptions(
        profile_id=presets.profile_id,
        parameters=presets.parameters,
        presets={
            "minimum_quality": minimum,
            "maximum": preset_values(presets, "maximum"),
            "machine_maximum": maximum_for_machine(presets, capability),
        },
        capability=capability,
        default_evaluation=evaluate(presets, minimum, capability),
        resource_note=presets.resource_model.note,
    )


@router.post("/processing/evaluate", response_model=Evaluation)
def evaluate_processing(request: EvaluateRequest) -> Evaluation:
    """Ước lượng tài nguyên của bộ thông số so với máy worker (đỏ = có thể crash)."""
    presets, _ = _presets()
    try:
        return evaluate(presets, request.params, _capability())
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
