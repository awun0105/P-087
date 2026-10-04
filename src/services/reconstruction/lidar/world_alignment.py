"""Phép đặt đám mây LiDAR vào hệ `world` của scene đã xác nhận tỉ lệ (ADR 0009).

Job có gói LiDAR dựng pose bám theo quỹ đạo, nên sau bước xác nhận tỉ lệ ta có cùng một tập camera ở hai hệ mét:
`lidar_map` (quỹ đạo × calibration) và `world` (pose canonical). Phép `world_from_lidar_map` là phép **cứng** khớp hai
tập tâm camera đó; không có tỉ lệ vì cả hai đã là mét. Độ lệch còn lại sau khi khớp chính là sai số pose ↔ quỹ đạo và
được báo ra để người xem biết đám mây LiDAR nằm lệch scene bao nhiêu.

Đường đi gần thẳng không xác định được góc xoay quanh chính nó. Khi đó chỉ khớp góc quay quanh trục đứng: cả hai hệ
đều có Z hướng lên (quy ước của gói LiDAR và của hệ `world`).
"""

import math
from dataclasses import dataclass

import numpy as np

from src.models.contracts.coordinates import Transform
from src.services.reconstruction.alignment.similarity import _quaternion, rotation_matrix
from src.services.reconstruction.lidar.package import MAP_FRAME

Point = tuple[float, float, float]
MIN_PAIRS = 3
#: Dưới tỉ lệ này giữa hai giá trị suy biến lớn nhất thì coi đường đi là thẳng (góc quanh trục đi không tin được).
_COLLINEAR_RATIO = 0.02


class WorldAlignmentError(ValueError):
    """Không khớp được hai tập tâm camera."""


@dataclass(frozen=True)
class WorldAlignment:
    """`world_from_lidar_map` và độ lệch còn lại giữa hai tập tâm camera (mét)."""

    transform: Transform
    method: str
    pair_count: int
    rms_residual_m: float
    median_residual_m: float
    max_residual_m: float

    def apply(self, points: np.ndarray) -> np.ndarray:
        """Đưa mảng điểm `(N, 3)` từ `lidar_map` sang `world`."""
        rotation = rotation_matrix(self.transform.rotation_quaternion_xyzw)
        return points @ rotation.T + np.asarray(self.transform.translation_xyz)


def _yaw_only(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Phép quay quanh Z khớp hình chiếu ngang của hai tập điểm đã trừ trọng tâm."""
    cross = float((source[:, 0] * target[:, 1] - source[:, 1] * target[:, 0]).sum())
    dot = float((source[:, 0] * target[:, 0] + source[:, 1] * target[:, 1]).sum())
    if math.hypot(cross, dot) <= 0:
        raise WorldAlignmentError("các tâm camera trùng nhau trên mặt ngang; không xác định được hướng")
    yaw = math.atan2(cross, dot)
    cos, sin = math.cos(yaw), math.sin(yaw)
    return np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]])


def fit_world_from_lidar_map(lidar_centers: list[Point], world_centers: list[Point]) -> WorldAlignment:
    """Khớp cứng tâm camera theo quỹ đạo (`lidar_map`) vào tâm camera canonical (`world`), cùng thứ tự frame."""
    if len(lidar_centers) != len(world_centers):
        raise WorldAlignmentError("hai tập tâm camera phải cùng số frame")
    if len(lidar_centers) < MIN_PAIRS:
        raise WorldAlignmentError(f"cần ít nhất {MIN_PAIRS} frame để khớp")
    source, target = np.asarray(lidar_centers, dtype=float), np.asarray(world_centers, dtype=float)
    if not (np.isfinite(source).all() and np.isfinite(target).all()):
        raise WorldAlignmentError("tâm camera phải hữu hạn")
    mean_source, mean_target = source.mean(axis=0), target.mean(axis=0)
    centered_source, centered_target = source - mean_source, target - mean_target
    u, singular, vt = np.linalg.svd(centered_target.T @ centered_source)
    if singular[0] <= 0:
        raise WorldAlignmentError("các tâm camera trùng nhau")
    if singular[1] < _COLLINEAR_RATIO * singular[0]:
        rotation, method = _yaw_only(centered_source, centered_target), "camera_centers_yaw_only"
    else:
        correction = np.diag([1.0, 1.0, float(np.sign(np.linalg.det(u) * np.linalg.det(vt)) or 1.0)])
        rotation, method = u @ correction @ vt, "camera_centers_rigid"
    translation = mean_target - rotation @ mean_source
    residuals = np.linalg.norm(target - (source @ rotation.T + translation), axis=1)
    return WorldAlignment(
        transform=Transform(
            parent_frame="world",
            local_frame=MAP_FRAME,
            translation_xyz=tuple(float(value) for value in translation),
            rotation_quaternion_xyzw=_quaternion(rotation),
        ),
        method=method,
        pair_count=len(source),
        rms_residual_m=float(math.sqrt((residuals**2).mean())),
        median_residual_m=float(np.median(residuals)),
        max_residual_m=float(residuals.max()),
    )
