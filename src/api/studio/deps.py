"""Dependency dùng chung của các route Studio.

Route gọi hàm trong module này (không import thẳng `get_settings`) nên test patch
`deps.get_settings` / `deps.get_project_registry` là đủ cho mọi route.
"""

from fastapi import HTTPException, status

from src.config import Settings, get_settings
from src.services.orchestration.artifacts import ArtifactResolver, ArtifactStoreError
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing import (
    MachineCapability,
    ProcessingConfigError,
    ProcessingPresets,
    is_presets_file,
    load_presets,
)
from src.services.orchestration.processing.capability import latest as latest_capability
from src.services.orchestration.projects import ProjectRegistry, get_project_registry
from src.services.orchestration.samples import DemoLibrary
from src.services.orchestration.uploads import VideoUploadService


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
        ArtifactResolver(current.artifact_root),
        current.product_upload_max_bytes,
    )


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


def preview_ready(project_registry: ProjectRegistry, job_id: str) -> bool:
    """Preview 3DGS đã commit và verify được (không dùng file lẻ trên đĩa)."""
    try:
        project_registry.get_preview(job_id)
    except (ArtifactStoreError, ValueError):
        return False
    return True
