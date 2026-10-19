"""Dependency dùng chung của các route product, cùng mẫu với `src/api/studio/deps.py`.

Route gọi `deps.registry()` / `deps.settings()` qua module này, nên test chỉ cần patch `get_project_registry` hoặc
`get_settings` ở đúng một chỗ.
"""

from collections.abc import Callable

from fastapi import HTTPException, status

from src.api import schemas
from src.config import Settings, get_settings
from src.models.contracts.manifests import JobManifest
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.projects import (
    JobNotFoundError,
    ProjectNotFoundError,
    ProjectRecord,
    ProjectRegistry,
    get_project_registry,
)
from src.services.orchestration.samples.session_context import demo_runtime
from src.services.orchestration.scene import SceneEditor, SceneEditResult, SceneError, SceneRevisionConflictError
from src.services.orchestration.scene.errors import SceneHeadNotReadyError, SceneNotAvailableError


def registry() -> ProjectRegistry:
    """Registry dùng chung; fixture chỉ được nạp một lần."""
    scoped = demo_runtime.get()
    return scoped.registry if scoped is not None else get_project_registry()


def settings() -> Settings:
    """Settings hiện hành; đi qua đây để test thay được thư mục và cấu hình."""
    scoped = demo_runtime.get()
    return scoped.settings if scoped is not None else get_settings()


def project_or_404(project_id: str) -> ProjectRecord:
    """Project theo id; không có thì 404 với lý do của registry."""
    try:
        return registry().get_project(project_id)
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def job_or_404(job_id: str) -> JobManifest:
    """JobManifest theo id; không có thì 404 với lý do của registry."""
    try:
        return registry().get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def scene_unavailable(error: SceneNotAvailableError) -> HTTPException:
    """Lỗi HTTP cho một scene chưa đọc được, dùng chung cho mọi route.

    Job chưa publish SceneIR là 404. SceneIR đã có nhưng head chưa sẵn sàng (chưa repair, đang ghi) là 409 với câu
    dành cho người dùng; lệnh repair trong `str(error)` chỉ dành cho log.
    """
    if isinstance(error, SceneHeadNotReadyError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.user_message)
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def scene_mutation(mutate: Callable[[SceneEditor], SceneEditResult]) -> schemas.SceneEditResponse:
    """Map lỗi thao tác scene giống `/scene/edits`: revision cũ/bất biến artifact → 409, lệnh sai → 422."""
    try:
        return schemas.scene_edit_response(mutate(registry().scene))
    except SceneNotAvailableError as error:
        raise scene_unavailable(error) from error
    except SceneRevisionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except SceneError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
