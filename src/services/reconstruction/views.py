"""Đọc nhẹ artifact REC để hiển thị từng bước (ADR 0005); không tính toán, không publish.

Chỉ trả ref ảnh frame và vị trí/hướng camera (vài KB) để trình duyệt không phải đọc
file nội bộ nặng của REC.
"""

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import FiniteFloat

from src.models.contracts.artifacts import ContractModel, ProductArtifactRef
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]


class CameraMarker(ContractModel):
    """Tâm và hướng một camera (parent_from_camera); đơn vị theo artifact nguồn."""

    frame_id: int
    center: Vector3
    rotation_xyzw: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]


def frame_images(
    frame_set: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]
) -> list[ProductArtifactRef]:
    """Ref ảnh của frame set đã publish (checksum do REC kiểm khi nạp)."""
    return [frame.image for frame in FrameSetResolver(resolve, resolve).load(frame_set).frames]


def camera_markers(poses: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]) -> list[CameraMarker]:
    """Tâm camera từ artifact pose (raw SfM hoặc canonical mét), sắp theo frame."""
    document = json.loads(resolve(poses).read_bytes())
    if document.get("transform_semantics") != "parent_from_local":
        raise ValueError("camera pose artifact phải là parent_from_camera")
    markers = [
        CameraMarker(
            frame_id=pose["frame_id"], center=tuple(pose["translation"]), rotation_xyzw=tuple(pose["rotation_xyzw"])
        )
        for pose in document["poses"]
    ]
    return sorted(markers, key=lambda marker: marker.frame_id)
