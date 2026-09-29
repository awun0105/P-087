"""Upload video.

Hai đường: (1) upload thẳng từ trình duyệt lên kho file bằng link multipart có hạn
(deployment cloud, ADR 0003) — API không cõng bytes; (2) raw body stream vào artifact
store qua API (local/không có kho file). File I/O đồng bộ chạy qua threadpool.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api.studio import deps
from src.services.orchestration.artifacts import ArtifactAlreadyExistsError, ArtifactTooLargeError
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.uploads import (
    MAX_URLS_PER_REQUEST,
    UploadError,
    UploadNotFoundError,
    UploadRecord,
    UploadSession,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class UploadListResponse(BaseModel):
    """Video đã upload, mới nhất trước."""

    model_config = ConfigDict(extra="forbid")

    uploads: list[UploadRecord]


@router.post("/uploads", response_model=UploadRecord, status_code=status.HTTP_201_CREATED)
async def upload_video(request: Request, filename: str = Query(..., min_length=1, max_length=255)) -> UploadRecord:
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
    return UploadListResponse(uploads=deps.uploads().list())


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
def begin_direct_upload(request: DirectUploadRequest) -> DirectUploadState:
    """Mở phiên upload thẳng; client xin link từng nhóm phần qua `/urls`."""
    try:
        return _state(deps.direct_uploads().begin(request.filename, request.size_bytes))
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
def direct_upload_urls(upload_id: str, request: PartUrlsRequest) -> PartUrlsResponse:
    """Link PUT có hạn cho tối đa 50 phần mỗi lần."""
    expires = deps.settings().artifact_presign_seconds
    try:
        urls = deps.direct_uploads().part_urls(upload_id, request.part_numbers, expires)
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
def complete_direct_upload(upload_id: str, background: BackgroundTasks) -> DirectUploadState:
    """Ghép các phần; server tự tính checksum trong nền, client poll tới READY/FAILED."""
    try:
        session = deps.direct_uploads().complete(upload_id)
    except (UploadError, UploadNotFoundError, RuntimeStateConflictError) as error:
        raise _upload_errors(error) from error
    background.add_task(_verify_in_background, upload_id)
    return _state(session)


@router.post("/uploads/direct/{upload_id}/abort", response_model=DirectUploadState)
def abort_direct_upload(upload_id: str) -> DirectUploadState:
    """Hủy upload dở, xóa các phần trên kho file."""
    try:
        return _state(deps.direct_uploads().abort(upload_id))
    except (UploadNotFoundError, RuntimeStateConflictError) as error:
        raise _upload_errors(error) from error
