"""Trạng thái hình học của SceneIR: đang chờ duyệt tách vật, hoặc đã sẵn sàng (có collider theo vật)."""

from typing import Literal, get_args

from src.models.contracts.scene import SceneIR
from src.services.orchestration.scene.errors import ObjectGeometryNotReadyError

ObjectGeometryState = Literal["awaiting_review", "ready"]


def object_geometry_state(scene: SceneIR) -> ObjectGeometryState:
    """Thiếu khóa (scene cũ) → "ready"; giá trị lạ → ValueError."""
    state = scene.provenance.get("object_geometry", "ready")
    if state not in get_args(ObjectGeometryState):
        raise ValueError(f"unknown object_geometry state: {state!r}")
    return state


def require_geometry_ready(scene: SceneIR, action: str) -> None:
    """Raise ObjectGeometryNotReadyError khi scene đang chờ duyệt; thiếu khóa (scene cũ) coi như ready."""
    if object_geometry_state(scene) == "awaiting_review":
        raise ObjectGeometryNotReadyError(f"Cần tạo mesh trước khi {action}.")
