"""Dependency dùng chung của các route Studio.

Route gọi hàm trong module này (không import thẳng `get_settings`) nên test patch
`deps.get_settings` / `deps.get_project_registry` là đủ cho mọi route.
"""

import logging
import os
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
from src.services.orchestration.samples.catalog import DemoCatalog
from src.services.orchestration.samples.session_context import demo_runtime
from src.services.orchestration.storage import runtime_resolver
from src.services.orchestration.uploads import DirectUploadService, VideoUploadService
from src.services.orchestration.uploads.scene_imports import ImportService

_LOGGER = logging.getLogger(__name__)


def settings() -> Settings:
    """Settings hiện hành (patch được trong test)."""
    scoped = demo_runtime.get()
    return scoped.settings if scoped is not None else get_settings()


def registry() -> ProjectRegistry:
    """Registry project/job dùng chung của API."""
    scoped = demo_runtime.get()
    return scoped.registry if scoped is not None else get_project_registry()


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
        _LOGGER.warning("Deployment chưa cấu hình kho file (ARTIFACT_S3_*); dùng upload qua API")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Máy chủ chưa bật tải lên trực tiếp. Báo quản trị viên.",
        )
    return DirectUploadService(RuntimeDatabase(current.database_url), resolver, current.product_upload_max_bytes)


def sample_catalog() -> DemoCatalog:
    """Catalog mẫu demo trong DB của deployment (nguồn sự thật về mẫu nào đang công khai)."""
    return DemoCatalog(RuntimeDatabase(settings().database_url))


def sample_library() -> DemoLibrary:
    """Thư viện video mẫu tại PRODUCT_DEMO_DIR, chỉ liệt kê mẫu catalog ghi là đang công khai."""
    return DemoLibrary(settings().product_demo_dir, catalog=sample_catalog())


def presets() -> tuple[ProcessingPresets, str]:
    """File cấu hình chung đang dùng (PRODUCT_PROCESSING_CONFIG) và checksum của nó."""
    path = settings().product_processing_config
    if path is None or not is_presets_file(path):
        _LOGGER.warning(
            "Chưa cấu hình file thông số chung: đặt PRODUCT_PROCESSING_CONFIG=configs/product/processing_presets_v1.json"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Máy chủ chưa có bộ thông số xử lý. Báo quản trị viên.",
        )
    try:
        return load_presets(path)
    except ProcessingConfigError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


def capability() -> MachineCapability | None:
    """Lần đo máy worker gần nhất còn hạn (None nếu worker chưa báo).

    Deployment tự thuê GPU: chưa có pod nào chạy thì dùng lần đo gần nhất của pod đã thuê (xem `latest`).
    """
    database = RuntimeDatabase(settings().database_url)
    fresh = latest_capability(database)
    if fresh is None and os.environ.get("GPU_AUTOPROVISION_ENABLED", "").strip().lower() in {"1", "true", "yes"}:
        return latest_capability(database, allow_stale=True)
    return fresh


def observed_resource_budget(
    project_registry: ProjectRegistry,
    params: dict[str, ParamValue],
    gpu_name: str | None,
    *,
    colmap_use_gpu: bool = False,
) -> dict[Literal["vram", "ram"], float] | None:
    """Số đo job cùng GPU/runtime; checksum lấy từ profile mà create_job sẽ gắn."""
    profile = project_registry.job_profile()
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
        runtime_manifest_checksum=profile.job_runtime_checksum,
        colmap_use_gpu=colmap_use_gpu,
    )


def anonymizer_available() -> bool:
    """Deployment đã cấu hình bộ che khuôn mặt/biển số (AUD-18). API và worker phải đặt cùng giá trị."""
    current = settings()
    # Settings giả trong test có thể thiếu trường mới: coi như chưa cấu hình.
    if getattr(current, "product_anonymize_remote_worker", False):
        # Production tách API và GPU worker: API không có scene runtime, người vận hành khai rằng worker có.
        return True
    return (
        getattr(current, "product_scene_runtime_python", None) is not None
        and getattr(current, "product_egoblur_weights", None) is not None
    )


def anonymize_enforced() -> bool:
    """Deployment bắt buộc che cho mọi video: chế độ `qa_verified`, hoặc PRODUCT_ANONYMIZE_INPUT khi có bộ che."""
    current = settings()
    if getattr(current, "product_privacy_mode", None) == "qa_verified":
        return True
    return anonymizer_available() and getattr(current, "product_anonymize_input", False)


def require_anonymize(requested: bool) -> bool:
    """Giá trị `anonymize` ghi vào cấu hình job; yêu cầu che trên deployment không có anonymizer bị từ chối."""
    if anonymizer_available():
        return requested or anonymize_enforced()
    if getattr(settings(), "product_privacy_mode", None) == "qa_verified":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hệ thống yêu cầu che khuôn mặt/biển số cho mọi video nhưng máy xử lý chưa có bộ che; báo quản trị viên",
        )
    if requested:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Máy xử lý chưa cấu hình bộ che khuôn mặt/biển số; bỏ chọn tự động che hoặc báo quản trị viên",
        )
    return False


def preview_ready(project_registry: ProjectRegistry, job_id: str) -> bool:
    """Preview 3DGS đã commit và verify được (không dùng file lẻ trên đĩa)."""
    try:
        project_registry.get_preview(job_id)
    except (ArtifactStoreError, ValueError):
        return False
    return True
