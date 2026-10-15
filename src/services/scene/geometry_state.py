"""Trạng thái hình học của SceneIR: đang chờ duyệt tách vật, hoặc đã sẵn sàng (có collider theo vật)."""

from typing import Literal, get_args

from src.models.contracts.scene import SceneIR

ObjectGeometryState = Literal["awaiting_review", "ready"]


def object_geometry_state(scene: SceneIR) -> ObjectGeometryState:
    """Thiếu khóa (scene cũ) → "ready"; giá trị lạ → ValueError."""
    state = scene.provenance.get("object_geometry", "ready")
    if state not in get_args(ObjectGeometryState):
        raise ValueError(f"unknown object_geometry state: {state!r}")
    return state
