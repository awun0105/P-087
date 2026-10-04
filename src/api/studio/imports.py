"""Scene import từ file 3DGS (.ply / .zip PLY + COLMAP): chỉ xem/chỉnh sửa (ADR 0004 §3)."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_editor
from src.api.studio import deps
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.storage import runtime_resolver
from src.services.orchestration.uploads import UploadNotFoundError
from src.services.orchestration.uploads.scene_imports import (
    ImportedScene,
    ImportNotFoundError,
    ImportService,
    SceneImportError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ImportRequest(BaseModel):
    """Upload 3DGS đã nhận diện + tên scene."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    name: str = Field(min_length=1, max_length=200)


class ImportListResponse(BaseModel):
    """Scene import, mới nhất trước."""

    model_config = ConfigDict(extra="forbid")

    imports: list[ImportedScene]


def _service() -> ImportService:
    current = deps.settings()
    return ImportService(
        RuntimeDatabase(current.database_url),
        runtime_resolver(current),
        current.product_worker_root.expanduser().resolve() / "imports",
    )


def _package_in_background(import_id: str, upload_id: str) -> None:
    """Process boundary của tác vụ nền: lỗi bất ngờ → FAILED, có log kèm cause."""
    service = _service()
    try:
        upload = deps.uploads().get(upload_id)
        service.package(import_id, upload, deps.settings().product_geometry_gpu_index)
    except Exception:
        logger.exception("Import %s thất bại", import_id)
        try:
            record = service.get(import_id)
            if record.status == "PACKAGING":
                service._update(record, status="FAILED", error="Không nén được scene 3DGS; thử lại sau")
        except (ImportNotFoundError, RuntimeStateConflictError):
            logger.info("Import %s đã đổi trạng thái trước khi ghi lỗi", import_id)


@router.post("/imports", response_model=ImportedScene, status_code=status.HTTP_201_CREATED)
def create_import(
    request: ImportRequest, background: BackgroundTasks, user: UserRecord | None = Depends(require_editor)
) -> ImportedScene:
    """Tạo scene import và nén PLY → SOG trong nền; client poll tới READY/FAILED."""
    try:
        upload = deps.uploads().get(request.upload_id)
        record = _service().create(
            upload, request.name, user.user_id if user else None, user.display_name if user else None
        )
    except UploadNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneImportError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    background.add_task(_package_in_background, record.import_id, upload.upload_id)
    return record


@router.get("/imports", response_model=ImportListResponse)
def list_imports() -> ImportListResponse:
    """Danh sách scene import."""
    return ImportListResponse(imports=_service().list())


@router.get("/imports/{import_id}", response_model=ImportedScene)
def get_import(import_id: str) -> ImportedScene:
    """Trạng thái một scene import."""
    try:
        return _service().get(import_id)
    except ImportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/imports/{import_id}/content/{filename}")
def get_import_content(import_id: str, filename: str) -> FileResponse:
    """SOG đã nén (checksum đã kiểm); `filename` chỉ để viewer chọn parser theo đuôi."""
    try:
        path = _service().content_path(import_id)
    except ImportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneImportError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return FileResponse(path, media_type="application/octet-stream", filename="scene.sog")
