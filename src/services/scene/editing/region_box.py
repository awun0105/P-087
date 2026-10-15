"""Region boxes → Gaussian membership for one object (T-004). Pure functions: no I/O, no scene state."""

import math

import numpy as np

from src.models.contracts.object_membership import RegionBox

#: Dung sai tuyệt đối khi kiểm điểm nằm trên mặt box; khớp `CONTAINS_TOLERANCE_M` của frontend (box-model.ts).
CONTAINS_TOLERANCE_M = 1e-6


def _box_contains(points_local: np.ndarray, box: RegionBox) -> np.ndarray:
    center = np.asarray(box.center_m, dtype=float)
    half = np.asarray(box.half_extents_m, dtype=float)
    cos_yaw, sin_yaw = math.cos(box.yaw_rad), math.sin(box.yaw_rad)
    relative = points_local - center
    # Điểm không hữu hạn cho inf × 0 = NaN; so sánh với NaN luôn sai nên điểm rơi vào "ngoài box" như mong muốn.
    with np.errstate(invalid="ignore"):
        along_x = relative[:, 0] * cos_yaw + relative[:, 1] * sin_yaw
        along_y = -relative[:, 0] * sin_yaw + relative[:, 1] * cos_yaw
        along_z = relative[:, 2]
        return (
            (np.abs(along_x) <= half[0] + CONTAINS_TOLERANCE_M)
            & (np.abs(along_y) <= half[1] + CONTAINS_TOLERANCE_M)
            & (np.abs(along_z) <= half[2] + CONTAINS_TOLERANCE_M)
        )


def boxes_contain(points_local: np.ndarray, boxes: list[RegionBox]) -> np.ndarray:
    """inside = ∪ add \\ ∪ subtract; điểm trên mặt box tính là bên trong (dung sai 1e-6)."""
    inside = np.zeros(len(points_local), dtype=bool)
    for box in boxes:
        if box.op == "add":
            inside |= _box_contains(points_local, box)
    for box in boxes:
        if box.op == "subtract":
            inside &= ~_box_contains(points_local, box)
    return inside
