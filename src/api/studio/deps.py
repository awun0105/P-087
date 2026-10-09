"""Dependency dùng chung của các route Studio.

Route gọi hàm trong module này (không import thẳng `get_settings`) nên test patch
`deps.get_settings` / `deps.get_project_registry` là đủ cho mọi route.
"""

from typing import Literal

from fastapi import HTTPException, status

from src.config import Settings, get_settings
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.inputs import InputAssemblyService
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing import (
    MachineCapability,
    ProcessingConfigError,
    ProcessingPresets,
    is_presets_file,
    load_presets,
)
from src.services.orchestration.processing.capability import latest as latest_capability
from src.services.orchestration.processing.models import ParamValue
from src.services.orchestration.processing.observed import load_usages, observed_for_config
from src.services.orchestration.projects import ProjectRegistry, get_project_registry
from src.services.orchestration.samples import DemoLibrary
from src.services.orchestration.storage import runtime_resolver
from src.services.orchestration.uploads import DirectUploadService, VideoUploadService
from src.services.orchestration.uploads.scene_imports import ImportService


def settings() -> Settings:
    """Settings hiện hành (patch được trong test)."""
    return get_settings()


def registry() -> ProjectRegistry:
    """Registry project/job dùng chung của API."""
    return get_project_registry()


def uploads() -> VideoUploadService:
    """Service upload video trên DB runtime và artifact store đang cấu hình."""
    current = settings()
    return VideoUploadService(
        RuntimeDatabase(current.database_url),
        runtime_resolver(current),
        current.product_upload_max_bytes,
    )


def input_assemblies() -> InputAssemblyService:
    """Shared durable assembly store and its optional deployment qualification registry."""
    current = settings()
    return InputAssemblyService(
        RuntimeDatabase(current.database_url),
        str(current.product_input_runtime_registry) if current.product_input_runtime_registry is not None else None,
        runtime_resolver(current),
    )


def imports() -> ImportService:
    """Durable PLY/SOG import command used by both standalone and unified upload routes."""
    current = settings()
    return ImportService(
        RuntimeDatabase(current.database_url),
        runtime_resolver(current),
        current.product_worker_root.expanduser().resolve() / "imports",
        max_uncompressed_bytes=current.product_upload_max_bytes * 2,
    )


def direct_uploads() -> DirectUploadService:
    """Service upload thẳng lên kho file; deployment chưa có kho file → 409."""
    current = settings()
    resolver = runtime_resolver(current)
    if resolver.remote is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deployment chưa cấu hình kho file (ARTIFACT_S3_*); dùng upload qua API",
        )
    return DirectUploadService(RuntimeDatabase(current.database_url), resolver, current.product_upload_max_bytes)


def sample_library() -> DemoLibrary:
    """Thư viện video mẫu tại PRODUCT_DEMO_DIR."""
    return DemoLibrary(settings().product_demo_dir)


def presets() -> tuple[ProcessingPresets, str]:
    """File cấu hình chung đang dùng (PRODUCT_PROCESSING_CONFIG) và checksum của nó."""
    path = settings().product_processing_config
    if path is None or not is_presets_file(path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chưa cấu hình file thông số chung: đặt PRODUCT_PROCESSING_CONFIG=configs/product/processing_presets_v1.json",
        )
    try:
        return load_presets(path)
    except ProcessingConfigError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


def capability() -> MachineCapability | None:
    """Lần đo máy worker gần nhất còn hạn (None nếu worker chưa báo)."""
    return latest_capability(RuntimeDatabase(settings().database_url))


def observed_resource_budget(
    project_registry: ProjectRegistry,
    params: dict[str, ParamValue],
    gpu_name: str | None,
    *,
    colmap_use_gpu: bool = False,
) -> dict[Literal["vram", "ram"], float] | None:
    """Số đo job cùng GPU/runtime; checksum lấy từ profile mà create_job sẽ gắn."""
    profile = project_registry.execution_profile
    if profile is None:
        return None
    database = (
        project_registry.persistence.database
        if project_registry.persistence is not None
        else RuntimeDatabase(settings().database_url)
    )
    return observed_for_config(
        load_usages(database),
        params=params,
        gpu_name=gpu_name,
        runtime_manifest_checksum=profile.runtime_manifest_checksum,
        colmap_use_gpu=colmap_use_gpu,
    )


def anonymizer_available() -> bool:
    """Deployment đã cấu hình bộ che khuôn mặt/biển số (AUD-18). API và worker phải đặt cùng giá trị."""
    current = settings()
    # Settings giả trong test có thể thiếu trường mới: coi như chưa cấu hình.
    return (
        getattr(current, "product_scene_runtime_python", None) is not None
        and getattr(current, "product_egoblur_weights", None) is not None
    )


def require_anonymize(requested: bool) -> bool:
    """Giá trị `anonymize` ghi vào cấu hình job; yêu cầu che trên deployment không có anonymizer bị từ chối."""
    if requested and not anonymizer_available():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Máy xử lý chưa cấu hình bộ che khuôn mặt/biển số; bỏ chọn tự động che hoặc báo quản trị viên",
        )
    return requested or (anonymizer_available() and getattr(settings(), "product_anonymize_input", False))


def preview_ready(project_registry: ProjectRegistry, job_id: str) -> bool:
    """Preview 3DGS đã commit và verify được (không dùng file lẻ trên đĩa)."""
    try:
        project_registry.get_preview(job_id)
    except (ArtifactStoreError, ValueError):
        return False
    return True
