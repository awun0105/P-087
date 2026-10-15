"""Build reviewed object geometry and publish it through the existing SceneIR revision fence."""

from collections.abc import Callable
from pathlib import Path
from threading import Event

from src.config import Settings
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.objectify import _ensure_not_cancelled
from src.services.scene.editing.membership import StaleObjectMembershipRevisionError
from src.services.scene.geometry_state import object_geometry_state


class ObjectGeometryBuildError(RuntimeError):
    """A geometry build failed without changing the active scene."""

    def __init__(self, message: str, *, object_id: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.object_id = object_id
        self.retryable = retryable


def build_object_geometry(
    registry: ProjectRegistry,
    settings: Settings,
    job_id: str,
    *,
    expected_revision: str,
    workspace: Path,
    object_ids: set[str] | None = None,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> str:
    """Build source-bound geometry; publish one revision after all stages succeed."""
    _ensure_not_cancelled(cancel_event)
    scene = registry.scene.current(job_id).scene
    if scene.scene_revision != expected_revision:
        raise StaleObjectMembershipRevisionError(
            f"scene đã đổi: yêu cầu {expected_revision}, hiện tại {scene.scene_revision}"
        )
    if scene.environment.membership is None:
        raise ObjectGeometryBuildError("Scene không có source membership để dựng hình học.")
    if object_ids is None and object_geometry_state(scene) != "awaiting_review":
        raise ObjectGeometryBuildError("Scene phải đang duyệt tách vật trước khi tạo mesh.")
    raise ObjectGeometryBuildError("Geometry build stages are not implemented yet")
