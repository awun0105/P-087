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


def test_rejects_bounded_trajectory_outlier_and_reports_prior_assumptions() -> None:
    lidar = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.5, 0.0],
            [3.0, 1.5, 0.1],
            [4.0, 2.0, 0.2],
            [5.0, 3.0, 0.1],
            [6.0, 4.0, 0.0],
            [7.0, 5.5, 0.1],
            [8.0, 7.0, 0.2],
            [9.0, 8.0, 0.1],
            [10.0, 9.5, 0.0],
            [11.0, 11.0, 0.1],
        ]
    )
    expected = _moved(lidar, 0.45, (-2.0, 4.0, 0.3))
    noisy = expected.copy()
    noisy[3] += (2.5, -3.0, 1.5)

    fit = fit_world_from_lidar_map([tuple(p) for p in lidar], [tuple(p) for p in noisy])

    assert fit.inlier_pair_count == 11
    assert fit.rejected_pair_count == 1
    assert fit.inlier_threshold_m <= 0.2
    assert "paired_centers_share_frame_identity_and_order" in fit.prior_assumptions
    np.testing.assert_allclose(
        fit.apply(lidar[[0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11]]), expected[[0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11]], atol=1e-8
    )


def test_rejects_trajectory_when_outlier_fraction_exceeds_bound() -> None:
    lidar = np.array([[float(index), float(index % 3), 0.0] for index in range(10)])
    world = _moved(lidar, 0.3, (1.0, -2.0, 0.0))
    world[:4] += np.array([2.0, -3.0, 1.0])

    with pytest.raises(WorldAlignmentError, match="giới hạn loại bỏ"):
        fit_world_from_lidar_map([tuple(p) for p in lidar], [tuple(p) for p in world])


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
