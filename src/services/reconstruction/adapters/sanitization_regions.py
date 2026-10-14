"""Hình học vùng che cho bước ẩn danh (AUD-18): nới hộp, lan theo thời gian, tô đặc.

Chỉ dùng thư viện chuẩn: runner trong `scene_runtime` nạp file này theo đường dẫn (runtime đó không có
pydantic), còn app import nó như module thường. Hộp là `(x1, y1, x2, y2)` theo pixel của frame gốc.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

Box = tuple[float, float, float, float]
#: Một vùng cần che: `kind` là "face" hoặc "license_plate"; `origin` là "detected", "propagated" hoặc "manual".
Region = dict[str, Any]

KINDS = ("face", "license_plate")


def iou(a: Box, b: Box) -> float:
    """Tỉ lệ giao trên hợp của hai hộp; hộp rỗng cho 0."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    intersection = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def expand_box(box: Box, width: int, height: int, scale: float) -> tuple[int, int, int, int]:
    """Nới hộp quanh tâm theo `scale` rồi cắt về biên ảnh; làm tròn ra ngoài để không hụt pixel mép."""
    if scale <= 0:
        raise ValueError("expand scale must be positive")
    center_x, center_y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    half_w, half_h = (box[2] - box[0]) * scale / 2, (box[3] - box[1]) * scale / 2
    x1, y1 = max(0, int(center_x - half_w)), max(0, int(center_y - half_h))
    x2, y2 = min(width, int(center_x + half_w) + 1), min(height, int(center_y + half_h) + 1)
    return x1, y1, max(x1, x2), max(y1, y2)


def propagate_regions(
    detected: Sequence[Sequence[Region]], radius: int, growth: float, overlap: float = 0.3
) -> list[list[Region]]:
    """Lan mỗi vùng phát hiện sang `radius` frame trước và sau, theo đúng thứ tự frame truyền vào.

    Detector có thể hụt một đối tượng ở vài frame liền nhau (mờ chuyển động, góc nghiêng). Vùng lan được nới
    thêm `growth` cho mỗi frame cách xa, vì camera di chuyển làm đối tượng trôi khỏi vị trí cũ. Frame đích đã
    có vùng phát hiện cùng loại chồng lên (IoU ≥ `overlap`) thì không thêm vùng lan.
    """
    if radius < 0 or growth < 0:
        raise ValueError("propagation radius and growth must not be negative")
    result: list[list[Region]] = [[dict(region) for region in frame] for frame in detected]
    for index, frame in enumerate(detected):
        for region in frame:
            for distance in range(1, radius + 1):
                for target in (index - distance, index + distance):
                    if not 0 <= target < len(detected):
                        continue
                    box = tuple(region["box"])
                    if any(
                        other["kind"] == region["kind"] and iou(tuple(other["box"]), box) >= overlap
                        for other in detected[target]
                    ):
                        continue
                    result[target].append(
                        {
                            "kind": region["kind"],
                            "box": list(box),
                            "score": None,
                            "origin": "propagated",
                            "extra_scale": 1 + growth * distance,
                        }
                    )
    return result


def fill_regions(image: Any, regions: Sequence[Region], scale: float, color: Sequence[int]) -> int:
    """Tô đặc mọi vùng lên mảng ảnh `H x W x C` tại chỗ; trả số pixel đã ghi đè.

    Tô đặc không đảo ngược được, khác với làm mờ: không còn thông tin gốc trong vùng che. Mỗi vùng được ghi
    lại hộp đã áp dụng thật (`applied_box`) để manifest phản ánh đúng byte đã xuất.
    """
    height, width = image.shape[:2]
    covered = 0
    for region in regions:
        x1, y1, x2, y2 = expand_box(tuple(region["box"]), width, height, scale * region.get("extra_scale", 1.0))
        region["applied_box"] = [x1, y1, x2, y2]
        if x2 > x1 and y2 > y1:
            image[y1:y2, x1:x2] = color
            covered += (x2 - x1) * (y2 - y1)
    return covered
