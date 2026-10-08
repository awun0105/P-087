"""Bản demo của scene: xem trạng thái, đánh dấu mốc gốc (Reviewer), khôi phục về mốc gốc (Editor).

Khôi phục tạo revision SceneIR mới mang nội dung của mốc gốc; không chạy lại bước xử lý nào.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from src.api import auth
from src.api.auth import require_contributor
from src.api.ownership import authorize_job_mutation
from src.api.studio import deps
from src.services.orchestration.auth import UserRecord, actor_of
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.projects import JobNotFoundError
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.demo import DemoState, clear_demo, demo_state, mark_demo, reset_demo
from src.services.orchestration.scene.errors import (
    SceneError,
    SceneNotAvailableError,
    SceneRevisionConflictError,
)

router = APIRouter()


class DemoResetRequest(BaseModel):
    """Revision client đang giữ: scene đã đổi từ lúc mở trang thì từ chối thay vì ghi đè thay đổi chưa thấy."""

    model_config = ConfigDict(extra="forbid")

    expected_scene_revision: str


def _run(job_id: str, action: str, operation: Callable[[ProjectRegistry, str], DemoState]) -> DemoState:
    """Chạy một thao tác bản demo và đổi lỗi miền thành mã HTTP."""
    try:
        return operation(deps.registry(), job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SceneNotAvailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Scene chưa có SceneIR để làm bản demo"
        ) from error
    except (SceneRevisionConflictError, RuntimeStateConflictError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Không {action}: scene vừa được người khác sửa, tải lại trang"
        ) from error
    except SceneError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.get("/jobs/{job_id}/demo", response_model=DemoState)
def get_demo_state(job_id: str) -> DemoState:
    """Scene có phải bản demo không và có đang đúng mốc gốc không."""
    return _run(job_id, "đọc trạng thái demo", demo_state)


@router.post("/jobs/{job_id}/demo/baseline", response_model=DemoState)
def post_demo_baseline(job_id: str, user: UserRecord | None = Depends(auth.require_reviewer)) -> DemoState:
    """Lấy revision hiện tại làm bản demo gốc (chỉ Reviewer)."""
    state = _run(job_id, "đánh dấu bản demo", lambda registry, job: mark_demo(registry, job, actor_of(user)))
    if user is not None:
        auth.auth_service().audit(user.user_id, "demo.mark", job_id, {"scene_revision": state.current_revision})
    return state


@router.delete("/jobs/{job_id}/demo/baseline", response_model=DemoState)
def delete_demo_baseline(job_id: str, user: UserRecord | None = Depends(auth.require_reviewer)) -> DemoState:
    """Bỏ đánh dấu bản demo (chỉ Reviewer); nội dung scene giữ nguyên."""
    state = _run(job_id, "bỏ đánh dấu bản demo", clear_demo)
    if user is not None:
        auth.auth_service().audit(user.user_id, "demo.clear", job_id, {})
    return state


@router.post("/jobs/{job_id}/demo/reset", response_model=DemoState)
def post_demo_reset(
    job_id: str, request: DemoResetRequest, user: UserRecord | None = Depends(require_contributor)
) -> DemoState:
    """Khôi phục scene về bản demo gốc bằng một revision mới."""
    authorize_job_mutation(user, deps.registry(), job_id, operation="khôi phục bản demo của")
    state = _run(
        job_id, "khôi phục bản demo", lambda registry, job: reset_demo(registry, job, request.expected_scene_revision)
    )
    if user is not None:
        auth.auth_service().audit(user.user_id, "demo.reset", job_id, {"scene_revision": state.current_revision})
    return state
