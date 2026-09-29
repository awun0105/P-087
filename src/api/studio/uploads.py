"""Upload video: nhận raw body (không multipart) để stream file lớn thẳng vào artifact store.

File I/O đồng bộ chạy qua threadpool để không chặn event loop.
"""

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from src.api.studio import deps
from src.services.orchestration.artifacts import ArtifactAlreadyExistsError, ArtifactTooLargeError
from src.services.orchestration.uploads import UploadError, UploadRecord

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
