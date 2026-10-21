"""Upload video.

Hai đường: (1) upload thẳng từ trình duyệt lên kho file bằng link multipart có hạn
(deployment cloud, ADR 0003) — API không cõng bytes; (2) raw body stream vào artifact
store qua API (local/không có kho file). File I/O đồng bộ chạy qua threadpool.
"""

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_contributor
from src.api.ownership import authorize_upload_mutation, authorize_upload_session_mutation
from src.api.studio import deps
from src.models.contracts.video_preparation import (
    ClientVideoPreparationManifest,
    ServerVideoPreparationVerification,
    default_video_normalization_profile,
)
from src.services.orchestration.artifacts import ArtifactAlreadyExistsError, ArtifactTooLargeError
from src.services.orchestration.auth import UserRecord, actor_of
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.uploads import (
    MAX_URLS_PER_REQUEST,
    UploadError,
    UploadNotFoundError,
    UploadRecord,
    UploadSession,
)
from src.services.orchestration.uploads.video_preparation import (
    ServerVideoPreparationVerifier,
    VideoPreparationVerificationError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class TemporaryUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_ids: list[Annotated[str, Field(pattern=r"^upload-[a-zA-Z0-9_-]+$")]] = Field(max_length=100)


@router.post("/uploads/temporary/{action}")
def temporary_uploads(
    action: Literal["heartbeat", "discard"],
    request: TemporaryUploadRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> dict[str, list[str]]:
    from src.services.orchestration.uploads.temporary import TemporaryUploadService

    uploads = deps.uploads()
    service = TemporaryUploadService(uploads.database, uploads.resolver)
    owner_id = user.user_id if user else "anonymous"
    try:
        if action == "heartbeat":
            service.renew(request.upload_ids, owner_id)
            return {"deleted": []}
        return {"deleted": service.discard(request.upload_ids, owner_id)}
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except RuntimeStateConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


class UploadResponse(UploadRecord):
    """Public shape; local source fingerprints and verification internals stay server-side."""

    video_preparation_status: Literal["pending", "verified"] | None = None
    video_preparation_manifest: ClientVideoPreparationManifest | None = Field(default=None, exclude=True)
    video_preparation: ServerVideoPreparationVerification | None = Field(default=None, exclude=True)

    @classmethod
    def from_record(cls, record: UploadRecord) -> "UploadResponse":
        payload = record.model_dump(mode="python")
        payload["video_preparation_status"] = (
            "verified"
            if record.video_preparation is not None
            else "pending"
            if record.video_preparation_manifest is not None
            else None
        )
        return cls.model_validate(payload)


class UploadListResponse(BaseModel):
    """Video đã upload, mới nhất trước."""

    model_config = ConfigDict(extra="forbid")

    uploads: list[UploadResponse]


@router.post("/uploads", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_video(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    temporary: bool = Query(default=False),
    user: UserRecord | None = Depends(require_contributor),
) -> UploadResponse:
    """Nhận bytes video trong body; bytes gốc được giữ nguyên, checksum tính khi ghi."""
    service = deps.uploads()
    try:
        pending = await run_in_threadpool(service.begin, filename)
    except UploadError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    try:
        async for chunk in request.stream():
            if chunk:
                await run_in_threadpool(pending.publication.write, chunk)
        record = await run_in_threadpool(service.finish, pending, actor_of(user), temporary=temporary)
        return UploadResponse.from_record(record)
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
    return UploadListResponse(uploads=[UploadResponse.from_record(item) for item in deps.uploads().list()])


@router.put("/uploads/{upload_id}/video-preparation/manifest", response_model=UploadResponse)
def save_video_preparation_manifest(
    upload_id: str,
    manifest: ClientVideoPreparationManifest,
    user: UserRecord | None = Depends(require_contributor),
) -> UploadResponse:
    """Store the client declaration as pending; server verification is a separate request."""
    service = deps.uploads()
    try:
        current = service.get(upload_id)
        authorize_upload_mutation(user, current, operation="cập nhật metadata upload")
        return UploadResponse.from_record(service.save_video_preparation_manifest(upload_id, manifest))
    except (UploadError, UploadNotFoundError, RuntimeStateConflictError) as error:
        raise _upload_errors(error) from error


@router.put("/uploads/{upload_id}/video-preparation/frame-map", response_model=UploadResponse)
async def upload_video_frame_map(
    upload_id: str,
    request: Request,
    user: UserRecord | None = Depends(require_contributor),
) -> UploadResponse:
    """Stream a bounded JSONL frame map, then verify it against the received MP4 with ffprobe."""
    service = deps.uploads()
    try:
        current = service.get(upload_id)
        authorize_upload_mutation(user, current, operation="xác minh frame map upload")
    except (UploadError, UploadNotFoundError, RuntimeStateConflictError) as error:
        raise _upload_errors(error) from error
    if current.video_preparation_manifest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video chưa được chuẩn bị xong. Hãy tải lại video.",
        )
    limit = default_video_normalization_profile().max_frame_map_bytes
    length = request.headers.get("content-length")
    if length and length.isdecimal() and int(length) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Dữ liệu khung hình của video vượt giới hạn 32 MiB"
        )

    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="r2s_video_frame_map_", suffix=".jsonl", delete=False) as frame_map:
            path = Path(frame_map.name)
            size = 0
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Dữ liệu khung hình của video vượt giới hạn 32 MiB",
                    )
                await run_in_threadpool(frame_map.write, chunk)
        verification = await run_in_threadpool(
            ServerVideoPreparationVerifier(service.resolver).verify_and_publish,
            current,
            current.video_preparation_manifest,
            path,
        )
        record = await run_in_threadpool(service.save_video_preparation_verification, upload_id, verification)
        return UploadResponse.from_record(record)
    except VideoPreparationVerificationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except (UploadError, UploadNotFoundError, RuntimeStateConflictError, ValueError) as error:
        raise _upload_errors(error) from error
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


class UploadConfig(BaseModel):
    """Cách client nên upload: thẳng lên kho file hay qua API."""

    model_config = ConfigDict(extra="forbid")

    direct: bool
    max_bytes: int


class DirectUploadRequest(BaseModel):
    """Khai báo file trước khi upload thẳng."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    purpose: Literal["product", "input_assembly"] = "product"
    temporary: bool = False


class DirectUploadState(BaseModel):
    """Trạng thái phiên upload thẳng; không lộ id multipart hay bucket."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    original_name: str
    size_bytes: int
    part_size: int
    part_count: int
    status: str
    error: str | None
    uploaded_parts: list[int]


class PartUrlsRequest(BaseModel):
    """Xin link cho một nhóm phần."""

    model_config = ConfigDict(extra="forbid")

    part_numbers: list[int] = Field(min_length=1, max_length=MAX_URLS_PER_REQUEST)


class PartUrlsResponse(BaseModel):
    """Link PUT có hạn theo số thứ tự phần."""

    model_config = ConfigDict(extra="forbid")

    urls: dict[int, str]
    expires_in: int


def _state(session: UploadSession, uploaded: list[int] | None = None) -> DirectUploadState:
    return DirectUploadState(
        upload_id=session.upload_id,
        original_name=session.original_name,
        size_bytes=session.size_bytes,
        part_size=session.part_size,
        part_count=session.part_count,
        status=session.status,
        error=session.error,
        uploaded_parts=uploaded or [],
    )


def _upload_errors(error: Exception) -> HTTPException:
    if isinstance(error, UploadNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, (RuntimeStateConflictError, ArtifactAlreadyExistsError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


@router.get("/uploads/config", response_model=UploadConfig)
def upload_config() -> UploadConfig:
    """Client hỏi trước khi upload: có kho file thì upload thẳng."""
    current = deps.settings()
    return UploadConfig(direct=bool(current.artifact_s3_bucket), max_bytes=current.product_upload_max_bytes)


@router.post("/uploads/direct", response_model=DirectUploadState, status_code=status.HTTP_201_CREATED)
def begin_direct_upload(
    request: DirectUploadRequest, user: UserRecord | None = Depends(require_contributor)
) -> DirectUploadState:
    """Mở phiên upload thẳng; client xin link từng nhóm phần qua `/urls`."""
    try:
        return _state(
            deps.direct_uploads().begin(
                request.filename,
                request.size_bytes,
                actor_of(user),
                purpose=request.purpose,
                temporary=request.temporary,
            )
        )
    except (UploadError, ArtifactAlreadyExistsError) as error:
        raise _upload_errors(error) from error


@router.get("/uploads/direct/{upload_id}", response_model=DirectUploadState)
def get_direct_upload(upload_id: str) -> DirectUploadState:
    """Trạng thái + các phần đã lên (client dùng để nối lại hoặc chờ kiểm tra xong)."""
    service = deps.direct_uploads()
    try:
        session = service.get(upload_id)
    except UploadNotFoundError as error:
        raise _upload_errors(error) from error
    return _state(session, service.uploaded_parts(session))


@router.post("/uploads/direct/{upload_id}/urls", response_model=PartUrlsResponse)
def direct_upload_urls(
    upload_id: str,
    request: PartUrlsRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> PartUrlsResponse:
    """Link PUT có hạn cho tối đa 50 phần mỗi lần."""
    expires = deps.settings().artifact_presign_seconds
    try:
        service = deps.direct_uploads()
        session = service.get(upload_id)
        authorize_upload_session_mutation(user, session, operation="tạo link upload cho")
        urls = service.part_urls(upload_id, request.part_numbers, expires)
    except (UploadError, UploadNotFoundError, RuntimeStateConflictError) as error:
        raise _upload_errors(error) from error
    return PartUrlsResponse(urls=urls, expires_in=expires)


def _verify_in_background(upload_id: str) -> None:
    """Process boundary của tác vụ nền: lỗi bất kỳ → phiên FAILED, có log kèm cause."""
    service = deps.direct_uploads()
    try:
        service.verify(upload_id)
    except Exception:
        logger.exception("Kiểm tra upload %s thất bại", upload_id)
        try:
            service.fail(upload_id, "Không kiểm tra được video trên kho file; thử upload lại")
        except RuntimeStateConflictError:
            logger.info("Phiên %s đã đổi trạng thái trước khi ghi lỗi", upload_id)


@router.post("/uploads/direct/{upload_id}/complete", response_model=DirectUploadState)
def complete_direct_upload(
    upload_id: str,
    background: BackgroundTasks,
    user: UserRecord | None = Depends(require_contributor),
) -> DirectUploadState:
    """Ghép các phần; server tự tính checksum trong nền, client poll tới READY/FAILED.

    Gọi lại khi phiên đang VERIFYING sẽ lên lịch kiểm tra lại: tác vụ nền mất khi API
    khởi động lại thì phiên không kẹt mãi. Nhiều lần kiểm tra song song vẫn an toàn vì
    bước ghi kết quả là CAS theo trạng thái.
    """
    service = deps.direct_uploads()
    try:
        current = service.get(upload_id)
    except UploadNotFoundError as error:
        raise _upload_errors(error) from error
    authorize_upload_session_mutation(user, current, operation="hoàn tất upload của")
    if current.status == "VERIFYING":
        background.add_task(_verify_in_background, upload_id)
        return _state(current)
    try:
        session = service.complete(upload_id)
    except (UploadError, UploadNotFoundError, RuntimeStateConflictError) as error:
        raise _upload_errors(error) from error
    background.add_task(_verify_in_background, upload_id)
    return _state(session)


@router.post("/uploads/direct/{upload_id}/abort", response_model=DirectUploadState)
def abort_direct_upload(upload_id: str, user: UserRecord | None = Depends(require_contributor)) -> DirectUploadState:
    """Hủy upload dở, xóa các phần trên kho file."""
    try:
        service = deps.direct_uploads()
        session = service.get(upload_id)
        authorize_upload_session_mutation(user, session, operation="hủy upload của")
        return _state(service.abort(upload_id))
    except (UploadNotFoundError, RuntimeStateConflictError) as error:
        raise _upload_errors(error) from error
