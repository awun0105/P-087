"""Scene import từ 3DGS PLY/SOG/ZIP: chỉ xem/chỉnh sửa; xử lý qua durable worker (ADR 0004 §3)."""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.api.auth import auth_service, require_contributor
from src.api.ownership import authorize_upload_mutation, owner_mutation_allowed
from src.api.studio import deps
from src.services.orchestration.auth import Actor, UserRecord
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.uploads import UploadNotFoundError
from src.services.orchestration.uploads.scene_imports import (
    CameraPoseRecord,
    ImportedScene,
    ImportNotFoundError,
    ImportService,
    SceneImportError,
)

router = APIRouter()


class UpdateCameraRequest(BaseModel):
    """Cập nhật góc nhìn mở đầu mặc định của scene import (hoặc gỡ nếu None)."""

    model_config = ConfigDict(extra="forbid")

    position: list[float] | None = None
    target: list[float] | None = None
    fov: float | None = Field(default=None, ge=10.0, le=120.0)

    @model_validator(mode="after")
    def validate_pose(self) -> "UpdateCameraRequest":
        if (self.position is None) ^ (self.target is None):
            raise ValueError("position và target phải cùng được cung cấp hoặc cùng là None")
        if self.position is not None and len(self.position) != 3:
            raise ValueError("position phải có đúng 3 tọa độ [x, y, z]")
        if self.target is not None and len(self.target) != 3:
            raise ValueError("target phải có đúng 3 tọa độ [x, y, z]")
        return self


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


def _legacy_creator_names(records: list[ImportedScene]) -> dict[str, Actor]:
    """Batch-resolve current name and role for rows whose stored snapshot lacks them (response only, never stored)."""
    user_ids = {
        record.created_by
        for record in records
        if record.created_by is not None and (record.created_by_name is None or record.created_by_role is None)
    }
    if not user_ids:
        return {}
    actors = auth_service().actors()
    return {user_id: actors[user_id] for user_id in user_ids if user_id in actors}


def _with_legacy_creator_name(record: ImportedScene, actors: dict[str, Actor]) -> ImportedScene:
    if record.created_by is None or (record.created_by_name is not None and record.created_by_role is not None):
        return record
    actor = actors.get(record.created_by)
    if actor is None:
        return record
    payload = record.model_dump(mode="python")
    # Snapshot đã lưu thắng; chỉ điền phần còn thiếu từ tài khoản hiện tại.
    if record.created_by_name is None:
        payload["created_by_name"] = actor.display_name
    if record.created_by_role is None and actor.role is not None:
        payload["created_by_role"] = actor.role
    return ImportedScene.model_validate(payload)


def _view(
    record: ImportedScene,
    user: UserRecord | None,
    legacy_actors: dict[str, Actor] | None = None,
) -> ImportedSceneResponse:
    if legacy_actors is not None:
        record = _with_legacy_creator_name(record, legacy_actors)
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
    return deps.imports()


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
        from src.services.orchestration.uploads.temporary import TemporaryUploadService

        uploads = deps.uploads()
        TemporaryUploadService(uploads.database, uploads.resolver).reserve([upload.upload_id])
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
    except (SceneImportError, RuntimeStateConflictError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _view(record, user, _legacy_creator_names([record]))


@router.get("/imports", response_model=ImportListResponse)
def list_imports(user: UserRecord | None = Depends(require_contributor)) -> ImportListResponse:
    """Danh sách scene import."""
    records = _service().list()
    legacy_actors = _legacy_creator_names(records)
    return ImportListResponse(imports=[_view(record, user, legacy_actors) for record in records])


@router.get("/imports/{import_id}", response_model=ImportedSceneResponse)
def get_import(import_id: str, user: UserRecord | None = Depends(require_contributor)) -> ImportedSceneResponse:
    """Trạng thái một scene import."""
    try:
        record = _service().get(import_id)
        return _view(record, user, _legacy_creator_names([record]))
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
        updated = service.retry(import_id)
        return _view(updated, user, _legacy_creator_names([updated]))
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
        updated = service.cancel(import_id)
        return _view(updated, user, _legacy_creator_names([updated]))
    except ImportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneImportError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.patch("/imports/{import_id}/camera", response_model=ImportedSceneResponse)
def update_import_camera(
    import_id: str,
    request: UpdateCameraRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> ImportedSceneResponse:
    """Lưu hoặc gỡ góc nhìn bookmark mở đầu mặc định của scene import."""
    service = _service()
    try:
        record = service.get(import_id)
        if not owner_mutation_allowed(user, record.created_by):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Không có quyền cập nhật góc nhìn cho scene import này",
            )
        camera: CameraPoseRecord | None = None
        if request.position is not None and request.target is not None:
            camera = CameraPoseRecord(
                position=request.position,
                target=request.target,
                fov=request.fov if request.fov is not None else 60.0,
            )
        updated = service.update_default_camera(import_id, camera)
        return _view(updated, user, _legacy_creator_names([updated]))
    except ImportNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneImportError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete("/imports/{import_id}/camera", response_model=ImportedSceneResponse)
def delete_import_camera(
    import_id: str,
    user: UserRecord | None = Depends(require_contributor),
) -> ImportedSceneResponse:
    """Gỡ bookmark góc nhìn mặc định của scene import, quay lại góc nhìn ban đầu tính toán tự động."""
    service = _service()
    try:
        record = service.get(import_id)
        if not owner_mutation_allowed(user, record.created_by):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Không có quyền gỡ góc nhìn cho scene import này",
            )
        updated = service.update_default_camera(import_id, None)
        return _view(updated, user, _legacy_creator_names([updated]))
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
