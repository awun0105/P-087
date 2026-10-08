"""Scene import từ 3DGS PLY/SOG/ZIP: chỉ xem/chỉnh sửa; xử lý qua durable worker (ADR 0004 §3)."""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_contributor
from src.api.ownership import authorize_upload_mutation, owner_mutation_allowed
from src.api.studio import deps
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.storage import runtime_resolver
from src.services.orchestration.uploads import UploadNotFoundError
from src.services.orchestration.uploads.scene_imports import (
    ImportedScene,
    ImportNotFoundError,
    ImportService,
    SceneImportError,
)

router = APIRouter()


class ImportRequest(BaseModel):
    """Upload 3DGS đã nhận diện + tên scene."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    name: str = Field(min_length=1, max_length=200)


class ImportCapabilities(BaseModel):
    """Caller-specific actions available for an imported scene."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    can_delete: bool
    can_retry: bool
    can_cancel: bool


class ImportedSceneResponse(ImportedScene):
    """Imported scene plus a non-authoritative UI permission hint."""

    capabilities: ImportCapabilities


class ImportListResponse(BaseModel):
    """Scene import, mới nhất trước."""

    model_config = ConfigDict(extra="forbid")

    imports: list[ImportedSceneResponse]


def _view(record: ImportedScene, user: UserRecord | None) -> ImportedSceneResponse:
    owner_mutation = owner_mutation_allowed(user, record.created_by)
    operation = record.operation
    retryable_codes = {"runtime_failure", "publication_failure", "source_unavailable", "worker_interrupted"}
    return ImportedSceneResponse(
        **record.model_dump(),
        capabilities=ImportCapabilities(
            can_delete=owner_mutation,
            can_retry=bool(
                owner_mutation
                and operation is not None
                and operation.status == "FAILED"
                and operation.retryable is True
                and operation.failure_code in retryable_codes
            ),
            can_cancel=bool(
                owner_mutation
                and operation is not None
                and operation.status in {"QUEUED", "WAITING", "RUNNING"}
                and not operation.cancel_requested
            ),
        ),
    )


def _service() -> ImportService:
    current = deps.settings()
    return ImportService(
        RuntimeDatabase(current.database_url),
        runtime_resolver(current),
        current.product_worker_root.expanduser().resolve() / "imports",
        max_uncompressed_bytes=current.product_upload_max_bytes * 2,
    )


@router.post("/imports", response_model=ImportedSceneResponse, status_code=status.HTTP_201_CREATED)
def create_import(
    request: ImportRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128),
    user: UserRecord | None = Depends(require_contributor),
) -> ImportedSceneResponse:
    """Tạo scene cùng durable operation; standalone worker xử lý tới READY/FAILED."""
    try:
        upload = deps.uploads().get(request.upload_id)
        authorize_upload_mutation(user, upload, operation="tạo scene import từ")
        settings = deps.settings()
        record = _service().create(
            upload,
            request.name,
            user.user_id if user else None,
            user.display_name if user else None,
            user.role if user else None,
            idempotency_key=idempotency_key,
            gpu_index=settings.product_geometry_gpu_index,
        )
    except UploadNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneImportError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _view(record, user)


@router.get("/imports", response_model=ImportListResponse)
def list_imports(user: UserRecord | None = Depends(require_contributor)) -> ImportListResponse:
    """Danh sách scene import."""
    return ImportListResponse(imports=[_view(record, user) for record in _service().list()])


@router.get("/imports/{import_id}", response_model=ImportedSceneResponse)
def get_import(import_id: str, user: UserRecord | None = Depends(require_contributor)) -> ImportedSceneResponse:
    """Trạng thái một scene import."""
    try:
        return _view(_service().get(import_id), user)
    except ImportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/imports/{import_id}/retry", response_model=ImportedSceneResponse)
def retry_import(import_id: str, user: UserRecord | None = Depends(require_contributor)) -> ImportedSceneResponse:
    """Retry only a stored transient failure, preserving the same source/config identity."""
    service = _service()
    try:
        record = service.get(import_id)
        if not owner_mutation_allowed(user, record.created_by):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền retry scene import này")
        return _view(service.retry(import_id), user)
    except ImportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneImportError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/imports/{import_id}/cancel", response_model=ImportedSceneResponse)
def cancel_import(import_id: str, user: UserRecord | None = Depends(require_contributor)) -> ImportedSceneResponse:
    """Cancel a queued request or ask its live worker to reap the current child before finishing."""
    service = _service()
    try:
        record = service.get(import_id)
        if not owner_mutation_allowed(user, record.created_by):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền hủy scene import này")
        return _view(service.cancel(import_id), user)
    except ImportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneImportError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


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
