"""Bản demo của scene.

Ba thao tác riêng:
- **Trạng thái đã lưu** (`/demo/baseline`, `/demo/reset`): Reviewer lưu scene hiện tại; Editor quay lại trạng thái đó.
- **Bản gốc** (`/demo/restore-root`): quay về revision đầu tiên cố định, giữ nguyên trạng thái đã lưu và lịch sử.
- **Đặt làm bản demo** (`/demo/publish`): Reviewer xuất scene vào thư viện mẫu (`PRODUCT_DEMO_DIR`), nơi `/new/try-demo`
  đọc. Thư viện mẫu công khai, nên chỉ xuất khi project đã xác nhận quyền sử dụng và ẩn danh, và Reviewer xác nhận.
"""

import logging
from collections.abc import Callable
from threading import Thread
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api import auth, schemas
from src.api.auth import require_contributor
from src.api.ownership import authorize_job_mutation
from src.api.studio import deps
from src.services.orchestration.auth import UserRecord, actor_of
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.projects import JobNotFoundError
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.samples import DemoManifest, DemoSource
from src.services.orchestration.samples.export import (
    SampleExportError,
    acquire_publish_lock,
    publication_status,
    publish_in_background,
    published_sample_id,
)
from src.services.orchestration.scene.demo import DemoState, clear_demo, demo_state, mark_demo, reset_demo, restore_root
from src.services.orchestration.scene.errors import (
    SceneError,
    SceneNotAvailableError,
    SceneRevisionConflictError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class DemoResetRequest(BaseModel):
    """Revision client đang giữ: scene đã đổi từ lúc mở trang thì từ chối thay vì ghi đè thay đổi chưa thấy."""

    model_config = ConfigDict(extra="forbid")

    expected_scene_revision: str


class DemoStateResponse(DemoState):
    """Trạng thái đã lưu và bản gốc kèm mẫu tương ứng trong thư viện mẫu."""

    published_sample_id: str | None = None
    #: Mẫu đang được chép vào thư viện (chạy nền sau `POST …/demo/publish`).
    publishing: bool = False
    #: Lỗi của lần chuẩn bị mẫu gần nhất; None khi chưa lỗi hoặc đã chuẩn bị lại.
    publish_error: str | None = None


class DemoPublishRequest(BaseModel):
    """Yêu cầu xuất scene vào thư viện mẫu; `confirm_public` là xác nhận của Reviewer rằng video được công khai."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=1000)
    confirm_public: bool

    @field_validator("title")
    @classmethod
    def _blank_title_means_default(cls, value: str | None) -> str | None:
        """Tên toàn dấu cách coi như không nhập: dùng tên scene thay vì làm bundle hỏng."""
        return value.strip() or None if value is not None else None


class DemoPublishResponse(BaseModel):
    """Mẫu được chuẩn bị ở nền; theo dõi bằng `publishing` / `publish_error` của `GET /jobs/{id}/demo`."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["publishing"] = "publishing"


def _with_publication(state: DemoState, job_id: str) -> DemoStateResponse:
    """Gắn mẫu đã xuất của job (tra theo `provenance.job_id` của thư viện)."""
    root = deps.settings().product_demo_dir
    try:
        sample_id = published_sample_id(deps.sample_catalog(), job_id)
    except Exception:  # noqa: BLE001 - trạng thái demo vẫn đọc được khi catalog tạm không truy cập được
        logger.warning("demo catalog unavailable while reading the demo state of %s", job_id, exc_info=True)
        sample_id = None
    publishing, error = publication_status(root, job_id)
    return DemoStateResponse(
        **state.model_dump(),
        published_sample_id=sample_id,
        publishing=publishing and sample_id is None,
        publish_error=None if sample_id is not None or publishing else error,
    )


def _run(job_id: str, action: str, operation: Callable[[ProjectRegistry, str], DemoState]) -> DemoState:
    """Chạy một thao tác bản demo và đổi lỗi miền thành mã HTTP."""
    try:
        return operation(deps.registry(), job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneNotAvailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Scene chưa dựng xong nên chưa làm bản demo được"
        ) from error
    except (SceneRevisionConflictError, RuntimeStateConflictError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Không {action}: scene vừa được người khác sửa, tải lại trang"
        ) from error
    except SceneError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.get("/jobs/{job_id}/demo", response_model=DemoStateResponse)
def get_demo_state(job_id: str) -> DemoStateResponse:
    """Trạng thái đã lưu, bản gốc và mẫu đã xuất của scene."""
    return _with_publication(_run(job_id, "đọc trạng thái demo", demo_state), job_id)


@router.post("/jobs/{job_id}/demo/baseline", response_model=DemoStateResponse)
def post_demo_baseline(job_id: str, user: UserRecord | None = Depends(auth.require_reviewer)) -> DemoStateResponse:
    """Lưu trạng thái hiện tại, thay thế trạng thái đã lưu trước đó (chỉ Reviewer)."""
    state = _run(job_id, "đánh dấu bản demo", lambda registry, job: mark_demo(registry, job, actor_of(user)))
    if user is not None:
        auth.auth_service().audit(user.user_id, "demo.mark", job_id, {"scene_revision": state.current_revision})
    return _with_publication(state, job_id)


@router.delete("/jobs/{job_id}/demo/baseline", response_model=DemoStateResponse)
def delete_demo_baseline(job_id: str, user: UserRecord | None = Depends(auth.require_reviewer)) -> DemoStateResponse:
    """Bỏ trạng thái đã lưu (chỉ Reviewer); nội dung scene giữ nguyên."""
    state = _run(job_id, "bỏ đánh dấu bản demo", clear_demo)
    if user is not None:
        auth.auth_service().audit(user.user_id, "demo.clear", job_id, {})
    return _with_publication(state, job_id)


@router.post("/jobs/{job_id}/demo/reset", response_model=DemoStateResponse)
def post_demo_reset(
    job_id: str, request: DemoResetRequest, user: UserRecord | None = Depends(require_contributor)
) -> DemoStateResponse:
    """Quay lại trạng thái đã lưu bằng một revision mới."""
    authorize_job_mutation(user, deps.registry(), job_id, operation="khôi phục bản demo của")
    state = _run(
        job_id, "khôi phục bản demo", lambda registry, job: reset_demo(registry, job, request.expected_scene_revision)
    )
    if user is not None:
        auth.auth_service().audit(user.user_id, "demo.reset", job_id, {"scene_revision": state.current_revision})
    return _with_publication(state, job_id)


@router.post("/jobs/{job_id}/demo/restore-root", response_model=DemoStateResponse)
def post_demo_restore_root(
    job_id: str, request: DemoResetRequest, user: UserRecord | None = Depends(require_contributor)
) -> DemoStateResponse:
    """Khôi phục scene về bản gốc ban đầu (rev-001) bằng một revision mới."""
    authorize_job_mutation(user, deps.registry(), job_id, operation="khôi phục bản gốc của")
    state = _run(
        job_id, "khôi phục bản gốc", lambda registry, job: restore_root(registry, job, request.expected_scene_revision)
    )
    if user is not None:
        auth.auth_service().audit(user.user_id, "demo.restore_root", job_id, {"scene_revision": state.current_revision})
    return _with_publication(state, job_id)


@router.post("/jobs/{job_id}/demo/publish", response_model=DemoPublishResponse, status_code=status.HTTP_202_ACCEPTED)
def post_demo_publish(
    job_id: str, request: DemoPublishRequest, user: UserRecord | None = Depends(auth.require_reviewer)
) -> DemoPublishResponse:
    """Xuất scene thành bản demo trong thư viện mẫu (chỉ Reviewer).

    Thư viện mẫu công khai (không cần đăng nhập) và bundle chứa video gốc, nên cần phiên Reviewer thật (kể cả khi tắt
    đăng nhập) và từ chối khi project chưa khai đã có quyền sử dụng và đã ẩn danh, bị chặn bởi kiểm tra riêng tư, hoặc
    Reviewer chưa xác nhận công khai.
    """
    if user is None:
        # Xuất vào thư viện công khai luôn cần Reviewer thật đăng nhập (và được ghi nhật ký), kể cả khi tắt đăng nhập.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Đăng nhập tài khoản Reviewer để đặt làm bản demo"
        )
    if not request.confirm_public:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Cần xác nhận video được phép công khai"
        )
    registry = deps.registry()
    try:
        job = registry.get_job(job_id)
        project = registry.get_project(job.project_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    attestation = project.source_rights_attestation
    if attestation.get("rights_to_use_confirmed") is not True or attestation.get("anonymization_confirmed") is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chỉ công khai được scene đã xác nhận quyền sử dụng và đã ẩn danh khi tạo",
        )
    privacy = schemas.privacy_state(project)
    if not privacy.dispatch_allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Scene đang bị chặn bởi kiểm tra riêng tư: {privacy.block_reason or 'chưa đạt'}",
        )
    title = request.title or project.name.strip() or "Scene"
    current = deps.settings()
    catalog = deps.sample_catalog()
    try:
        lock = acquire_publish_lock(current.product_demo_dir, catalog, job_id)
    except SampleExportError as error:  # gồm AlreadyPublishedError và "đang được xuất"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except OSError as error:
        logger.exception("demo publish lock failed for %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Không ghi được vào thư viện mẫu của máy chủ"
        ) from error

    def published(manifest: DemoManifest) -> None:
        auth.auth_service().audit(user.user_id, "demo.publish", job_id, {"sample_id": manifest.demo_id})

    # Chép bundle (tới vài GB) lâu hơn thời gian chờ của proxy: chạy nền, giao diện đọc trạng thái qua GET …/demo.
    Thread(
        target=publish_in_background,
        args=(registry, job_id, current, catalog, lock),
        kwargs={
            "title": title,
            "description": request.description.strip(),
            "source": DemoSource(dataset="Real2Sim Studio", sequence=project.name[:200], note=""),
            "recording_dir": current.product_rerun_recording_dir,
            "actor": user.user_id,
            "on_published": published,
        },
        name=f"demo-publish-{job_id}",
        daemon=True,
    ).start()
    return DemoPublishResponse()
