"""Video mẫu đã xử lý sẵn: danh sách, manifest và file (allow-list + checksum)."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from src.api.studio import deps
from src.services.orchestration.samples import DemoManifest, DemoUnavailableError, SampleSummary

router = APIRouter()


class SampleListResponse(BaseModel):
    """Video mẫu đã xử lý sẵn, hiển thị cạnh ô tải video lên."""

    model_config = ConfigDict(extra="forbid")

    samples: list[SampleSummary]


@router.get("/samples", response_model=SampleListResponse)
def list_samples() -> SampleListResponse:
    """Mọi video mẫu hợp lệ trong thư viện; rỗng khi deployment chưa có bundle nào."""
    return SampleListResponse(samples=deps.sample_library().summaries())


@router.get("/samples/{sample_id}", response_model=DemoManifest)
def get_sample(sample_id: str) -> DemoManifest:
    """Manifest của một video mẫu: stage, thời lượng thật, thông số, file."""
    try:
        return deps.sample_library().bundle(sample_id).manifest()
    except DemoUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/samples/{sample_id}/files/{name}")
def get_sample_file(sample_id: str, name: str) -> FileResponse:
    """Một file của video mẫu; chỉ tên trong allow-list và đúng checksum mới được trả."""
    try:
        entry, path = deps.sample_library().bundle(sample_id).file(name)
    except DemoUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return FileResponse(
        path,
        media_type=entry.media_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
