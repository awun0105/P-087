"""Khớp cứng `world_from_lidar_map` từ hai tập tâm camera (ADR 0009, L10)."""

import math

import numpy as np
import pytest

from src.services.reconstruction.lidar.world_alignment import WorldAlignmentError, fit_world_from_lidar_map


def _moved(points: np.ndarray, yaw: float, shift: tuple[float, float, float]) -> np.ndarray:
    cos, sin = math.cos(yaw), math.sin(yaw)
    return points @ np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]]).T + np.asarray(shift)


def test_recovers_rigid_transform_and_maps_points() -> None:
    lidar = np.array([[0.0, 0.0, 0.1], [1.0, 0.2, 0.1], [2.0, 1.0, 0.15], [2.5, 2.5, 0.1], [1.0, 3.0, 0.2]])
    world = _moved(lidar, 0.7, (-4.0, 2.0, 0.25))
    fit = fit_world_from_lidar_map([tuple(p) for p in lidar], [tuple(p) for p in world])
    assert fit.method == "camera_centers_rigid"
    assert fit.max_residual_m < 1e-9
    assert fit.transform.parent_frame == "world" and fit.transform.local_frame == "lidar_map"
    np.testing.assert_allclose(fit.apply(lidar), world, atol=1e-9)


def test_straight_path_uses_yaw_only_and_keeps_up_axis() -> None:
    lidar = np.array([[float(step), 0.0, 0.1] for step in range(6)])
    world = _moved(lidar, -1.2, (3.0, 1.0, 0.3))
    fit = fit_world_from_lidar_map([tuple(p) for p in lidar], [tuple(p) for p in world])
    assert fit.method == "camera_centers_yaw_only"
    # Điểm lệch khỏi đường đi vẫn phải giữ nguyên độ cao: không có xoay quanh trục đi.
    np.testing.assert_allclose(
        fit.apply(np.array([[2.0, 1.5, 1.0]])), _moved(np.array([[2.0, 1.5, 1.0]]), -1.2, (3.0, 1.0, 0.3)), atol=1e-9
    )


def test_reports_residual_of_noisy_centers() -> None:
    lidar = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    world = lidar.copy()
    world[0, 0] += 0.2
    fit = fit_world_from_lidar_map([tuple(p) for p in lidar], [tuple(p) for p in world])
    assert 0.0 < fit.median_residual_m <= fit.max_residual_m < 0.2


@pytest.mark.parametrize(
    ("lidar", "world"),
    [
        ([(0.0, 0.0, 0.0)] * 2, [(0.0, 0.0, 0.0)] * 2),
        ([(0.0, 0.0, 0.0)] * 3, [(0.0, 0.0, 0.0)] * 4),
        ([(1.0, 1.0, 1.0)] * 3, [(2.0, 2.0, 2.0)] * 3),
    ],
)
def test_rejects_degenerate_input(lidar: list, world: list) -> None:
    with pytest.raises(WorldAlignmentError):
        fit_world_from_lidar_map(lidar, world)
