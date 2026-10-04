"""Khoét vật đã xác nhận khỏi collision mesh môi trường (SIM-02 cho môi trường).

Collision mesh REC-05 dựng từ cả scene nên đã chứa luôn khối của pallet/thùng. Khi vật đó có
collider hộp riêng trong gói mô phỏng, phần mesh trùng chỗ phải bỏ đi, nếu không Isaac thấy hai
vật cản chồng nhau và vật không thể di chuyển/tháo ra được. Chỉ bỏ tam giác có tâm nằm trong hộp
(nới thêm `margin_m`), không cắt tam giác — đủ cho collider thô, giữ nguyên toạ độ canonical.
"""

from dataclasses import dataclass

import numpy as np

from src.models.contracts.coordinates import Transform


@dataclass(frozen=True)
class CarveBox:
    """Hộp vật thể trong hệ canonical (tâm, quaternion xyzw, kích thước đầy đủ, mét)."""

    center: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]
    dimensions: tuple[float, float, float]

    @classmethod
    def from_transform(cls, transform: Transform, dimensions: tuple[float, float, float]) -> "CarveBox":
        """Hộp từ transform parent_from_local của SceneObject."""
        return cls(transform.translation_xyz, transform.rotation_quaternion_xyzw, dimensions)


def _rotation(quaternion: tuple[float, float, float, float]) -> np.ndarray:
    x, y, z, w = quaternion
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def carve_boxes(
    vertices: np.ndarray, faces: np.ndarray, boxes: list[CarveBox], margin_m: float = 0.05
) -> tuple[np.ndarray, np.ndarray, int]:
    """Bỏ tam giác có tâm trong bất kỳ hộp nào; trả (đỉnh, mặt đã đánh lại chỉ số, số tam giác bỏ)."""
    if not boxes or not len(faces):
        return vertices, faces, 0
    centroids = vertices[faces].mean(axis=1)
    inside = np.zeros(len(faces), dtype=bool)
    for box in boxes:
        # Đưa tâm tam giác về khung local của hộp: R^T (p - c), so với nửa kích thước + margin.
        local = (centroids - np.asarray(box.center)) @ _rotation(box.rotation_xyzw)
        half = np.asarray(box.dimensions) / 2 + margin_m
        inside |= np.all(np.abs(local) <= half, axis=1)
    kept = faces[~inside]
    used = np.unique(kept)
    remap = np.full(len(vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return vertices[used], remap[kept], int(inside.sum())
