"""Video mẫu đã xử lý sẵn: danh sách, manifest và file (allow-list + checksum)."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict

from src.api import auth
from src.api.studio import deps
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.samples import DemoManifest, DemoUnavailableError, SampleSummary, distributed
from src.services.orchestration.storage import artifact_remote

router = APIRouter()


class SampleListResponse(BaseModel):
    """Video mẫu đã xử lý sẵn, hiển thị cạnh ô tải video lên."""

    model_config = ConfigDict(extra="forbid")

    samples: list[SampleSummary]


@router.get("/samples", response_model=SampleListResponse)
def list_samples() -> SampleListResponse:
    """Mọi video mẫu hợp lệ trong thư viện; rỗng khi deployment chưa có bundle nào."""
    current = deps.settings()
    return SampleListResponse(
        samples=[
            sample
            for sample in deps.sample_library().summaries()
            if not distributed.unpublished(current, sample.sample_id)
        ]
    )


@router.get("/samples/{sample_id}", response_model=DemoManifest)
def get_sample(sample_id: str) -> DemoManifest:
    """Manifest của một video mẫu: stage, thời lượng thật, thông số, file."""
    try:
        if distributed.unpublished(deps.settings(), sample_id):
            raise DemoUnavailableError("Mẫu đã được bỏ khỏi thư viện demo")
        return deps.sample_library().bundle(sample_id).manifest()
    except DemoUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/samples/{sample_id}/files/{name}")
def get_sample_file(sample_id: str, name: str) -> Response:
    """Một file của video mẫu; chỉ tên trong allow-list và đúng checksum mới được trả."""
    try:
        if distributed.unpublished(deps.settings(), sample_id):
            raise DemoUnavailableError("Mẫu đã được bỏ khỏi thư viện demo")
        entry, path = deps.sample_library().bundle(sample_id).file(name)
    except DemoUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    settings = deps.settings()
    remote = artifact_remote(settings)
    if remote is not None:
        key = f"{settings.product_demo_object_prefix.strip('/')}/{sample_id}/files/{entry.name}"
        found = remote.store.head(key)
        if found is not None and found.checksum == entry.checksum:
            return RedirectResponse(remote.store.presign_get(key, settings.artifact_presign_seconds), status_code=307)
    return FileResponse(
        path,
        media_type=entry.media_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/samples/{sample_id}")
def remove_sample(sample_id: str, user: UserRecord | None = Depends(auth.require_reviewer)) -> dict[str, str]:
    """Reviewer gỡ mẫu khỏi thư viện công khai; không xoá dự án hay artifact."""
    if user is None:
        raise HTTPException(status_code=401, detail="Đăng nhập tài khoản Reviewer để bỏ mẫu khỏi demo")
    try:
        if distributed.enabled(deps.settings()):
            distributed.unpublish(deps.settings(), sample_id)
        deps.sample_library().unpublish(sample_id)
    except DemoUnavailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=503, detail="Không cập nhật được thư viện demo; thử lại sau") from error
    auth.auth_service().audit(user.user_id, "demo.unpublish", sample_id, {})
    return {"sample_id": sample_id}
