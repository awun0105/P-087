"""Trạng thái hình học của SceneIR: đang chờ duyệt tách vật, hoặc đã sẵn sàng (có collider theo vật)."""

import logging
from typing import Literal, get_args

from src.models.contracts.scene import SceneIR
from src.services.orchestration.scene.errors import ObjectGeometryNotReadyError

ObjectGeometryState = Literal["awaiting_review", "ready"]

logger = logging.getLogger(__name__)


def object_geometry_state(scene: SceneIR) -> ObjectGeometryState:
    """Cổng chặn thao tác. Thiếu khóa hoặc None (scene cũ) → "ready"; giá trị lạ → ValueError."""
    state = scene.provenance.get("object_geometry")
    if state is None:
        return "ready"
    if state not in get_args(ObjectGeometryState):
        raise ValueError(f"unknown object_geometry state: {state!r}")
    return state


def object_geometry_view(scene: SceneIR) -> ObjectGeometryState | None:
    """Cho mọi chỗ **hiển thị** (T-055): thiếu khóa hoặc None → None (scene cũ, không có bước duyệt vật);
    giá trị lạ → "awaiting_review" (khoá lại cho an toàn) kèm cảnh báo. Không bao giờ ném."""
    state = scene.provenance.get("object_geometry")
    if state is None:
        return None
    if state in get_args(ObjectGeometryState):
        return state
    logger.warning("Giá trị object_geometry lạ %r ở scene %s; coi như chờ duyệt", state, scene.scene_revision)
    return "awaiting_review"


def has_geometry_review(scene: SceneIR) -> bool:
    """Scene có bước "Duyệt vật & Tạo mesh" (scene tạo trước luồng này thì không)."""
    return object_geometry_view(scene) is not None


def require_geometry_ready(scene: SceneIR, action: str) -> None:
    """Raise ObjectGeometryNotReadyError khi scene đang chờ duyệt; thiếu khóa (scene cũ) coi như ready."""
    if object_geometry_state(scene) == "awaiting_review":
        raise ObjectGeometryNotReadyError(f"Cần tạo mesh trước khi {action}.")
