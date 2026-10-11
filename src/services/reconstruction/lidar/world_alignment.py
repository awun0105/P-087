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
    inlier_pair_count: int = 0
    rejected_pair_count: int = 0
    inlier_threshold_m: float = 0.0
    rank_ratio: float = 0.0
    prior_assumptions: tuple[str, ...] = ()
    base_inlier_threshold_m: float = 0.05
    max_outlier_fraction: float = 0.2
    ransac_iterations: int = 256
    random_seed: int = 0

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


def _fit_rigid(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray, str, float]:
    """Fit rigid transform for already paired metric camera centers."""
    mean_source, mean_target = source.mean(axis=0), target.mean(axis=0)
    centered_source, centered_target = source - mean_source, target - mean_target
    u, singular, vt = np.linalg.svd(centered_target.T @ centered_source)
    if singular[0] <= 0:
        raise WorldAlignmentError("các tâm camera trùng nhau")
    rank_ratio = float(singular[1] / singular[0])
    if rank_ratio < _COLLINEAR_RATIO:
        rotation, method = _yaw_only(centered_source, centered_target), "camera_centers_yaw_only"
    else:
        correction = np.diag([1.0, 1.0, float(np.sign(np.linalg.det(u) * np.linalg.det(vt)) or 1.0)])
        rotation, method = u @ correction @ vt, "camera_centers_rigid"
    translation = mean_target - rotation @ mean_source
    return rotation, translation, method, rank_ratio


def _residuals(source: np.ndarray, target: np.ndarray, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    return np.linalg.norm(target - (source @ rotation.T + translation), axis=1)


def _robust_cutoff(residuals: np.ndarray, base_threshold_m: float) -> float:
    median = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - median)))
    adaptive = median + 3.0 * 1.4826 * mad
    return min(max(base_threshold_m, adaptive), base_threshold_m * 4.0)


def fit_world_from_lidar_map(
    lidar_centers: list[Point],
    world_centers: list[Point],
    *,
    max_outlier_fraction: float = 0.2,
    inlier_threshold_m: float = 0.05,
    ransac_iterations: int = 256,
    random_seed: int = 0,
) -> WorldAlignment:
    """Robustly fit paired, same-frame camera centers without changing the metric scale.

    The deterministic, bounded consensus step rejects only a configured minority of bad
    pairs. It does not prove timestamp correctness or trajectory quality; those remain
    caller-provided priors and are reported with the fit.
    """
    if len(lidar_centers) != len(world_centers):
        raise WorldAlignmentError("hai tập tâm camera phải cùng số frame")
    if len(lidar_centers) < MIN_PAIRS:
        raise WorldAlignmentError(f"cần ít nhất {MIN_PAIRS} frame để khớp")
    if not math.isfinite(max_outlier_fraction) or not 0 <= max_outlier_fraction <= 0.5:
        raise WorldAlignmentError("tỉ lệ outlier phải nằm trong [0, 0.5]")
    if not math.isfinite(inlier_threshold_m) or inlier_threshold_m <= 0:
        raise WorldAlignmentError("ngưỡng inlier phải là mét dương và hữu hạn")
    if ransac_iterations < 1 or random_seed < 0:
        raise WorldAlignmentError("giới hạn RANSAC hoặc seed không hợp lệ")
    source, target = np.asarray(lidar_centers, dtype=float), np.asarray(world_centers, dtype=float)
    if source.shape != (len(lidar_centers), 3) or target.shape != (len(world_centers), 3):
        raise WorldAlignmentError("mỗi tâm camera phải có đúng ba tọa độ")
    if not (np.isfinite(source).all() and np.isfinite(target).all()):
        raise WorldAlignmentError("tâm camera phải hữu hạn")

    max_rejected = math.floor(len(source) * max_outlier_fraction)
    minimum_support = len(source) - max_rejected
    best_inliers: np.ndarray | None = None
    best_key: tuple[int, float, float] | None = None
    if max_rejected == 0:
        best_inliers = np.arange(len(source))
    else:
        random = np.random.default_rng(random_seed)
        for _ in range(ransac_iterations):
            sample = random.choice(len(source), size=MIN_PAIRS, replace=False)
            try:
                candidate_rotation, candidate_translation, _, _ = _fit_rigid(source[sample], target[sample])
            except (WorldAlignmentError, np.linalg.LinAlgError):
                continue
            candidate_residuals = _residuals(source, target, candidate_rotation, candidate_translation)
            cutoff = _robust_cutoff(candidate_residuals, inlier_threshold_m)
            inliers = np.flatnonzero(candidate_residuals <= cutoff)
            if len(inliers) < minimum_support:
                continue
            inlier_median = float(np.median(candidate_residuals[inliers]))
            inlier_rms = float(np.sqrt(np.mean(candidate_residuals[inliers] ** 2)))
            key = (len(inliers), -inlier_median, -inlier_rms)
            if best_key is None or key > best_key:
                best_key, best_inliers = key, inliers
    if best_inliers is None or len(best_inliers) < minimum_support:
        raise WorldAlignmentError(
            f"không tìm được đồng thuận quỹ đạo trong giới hạn loại bỏ {max_outlier_fraction:.0%} cặp"
        )

    inliers = best_inliers
    for _ in range(3):
        rotation, translation, method, rank_ratio = _fit_rigid(source[inliers], target[inliers])
        residuals = _residuals(source, target, rotation, translation)
        cutoff = _robust_cutoff(residuals, inlier_threshold_m)
        refined = np.flatnonzero(residuals <= cutoff)
        if len(refined) < minimum_support:
            raise WorldAlignmentError("đồng thuận quỹ đạo còn lại dưới giới hạn inlier đã cấu hình")
        if np.array_equal(refined, inliers):
            break
        inliers = refined
    rotation, translation, method, rank_ratio = _fit_rigid(source[inliers], target[inliers])
    residuals = _residuals(source, target, rotation, translation)
    cutoff = _robust_cutoff(residuals, inlier_threshold_m)
    final_inliers = np.flatnonzero(residuals <= cutoff)
    if len(final_inliers) < minimum_support:
        raise WorldAlignmentError("đồng thuận quỹ đạo cuối cùng vượt giới hạn outlier đã cấu hình")
    if not np.array_equal(final_inliers, inliers):
        inliers = final_inliers
        rotation, translation, method, rank_ratio = _fit_rigid(source[inliers], target[inliers])
        residuals = _residuals(source, target, rotation, translation)
        cutoff = _robust_cutoff(residuals, inlier_threshold_m)

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
        inlier_pair_count=len(inliers),
        rejected_pair_count=len(source) - len(inliers),
        inlier_threshold_m=cutoff,
        rank_ratio=rank_ratio,
        base_inlier_threshold_m=inlier_threshold_m,
        max_outlier_fraction=max_outlier_fraction,
        ransac_iterations=ransac_iterations,
        random_seed=random_seed,
        prior_assumptions=(
            "paired_centers_share_frame_identity_and_order",
            "both_center_sets_are_in_meters",
            "scale_is_fixed_to_one",
            *("straight_path_only_observes_yaw" for _ in [0] if method == "camera_centers_yaw_only"),
        ),
    )
