"""Evaluator đối chứng TorWIC (`eval/pose`, `eval/geometry`): công thức đúng trên dữ liệu dựng tay."""

import math
import struct
from pathlib import Path

import numpy as np
import pytest

from eval.geometry.surface_error import map_points, near_path, surface_scores
from eval.pose.scale_proposal_error import proposal_error
from eval.pose.trajectory_error import metric_errors, trajectory_errors
from eval.reference.torwic import PoseSet


def _yaw(angle: float) -> np.ndarray:
    cos, sin = math.cos(angle), math.sin(angle)
    return np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]])


def _truth() -> PoseSet:
    centers = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.5, 0.0], [2.5, 1.5, 0.1], [2.0, 2.5, 0.0]])
    rotations = np.array([_yaw(0.2 * index) for index in range(len(centers))])
    return PoseSet(tuple(range(len(centers))), centers, rotations, "torwic_map")


def _moved(truth: PoseSet, scale: float) -> PoseSet:
    """Cùng quỹ đạo nhưng ở hệ khác (xoay, tịnh tiến, đổi tỉ lệ) và quy ước trục camera khác."""
    world = _yaw(1.1)
    camera_axes = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
    centers = (truth.centers @ world.T) / scale + np.array([5.0, -2.0, 1.0])
    rotations = np.array([world @ rotation @ camera_axes for rotation in truth.rotations])
    return PoseSet(truth.frame_ids, centers, rotations, "world")


def test_identical_trajectory_in_another_frame_has_no_error() -> None:
    truth = _truth()
    errors = trajectory_errors(_moved(truth, 1.0), truth)
    assert errors["ate_similarity_m"]["rmse"] == 0.0 and errors["rpe_translation_m"]["rmse"] == 0.0
    assert errors["rpe_rotation_deg"]["rmse"] < 1e-3
    assert errors["path_length_m"] == pytest.approx(4.363, abs=1e-3)


def test_scale_error_is_reported_with_its_sign() -> None:
    truth = _truth()
    # Scene nhỏ hơn thật 4%: một mét của scene dài 1,04 mét thật.
    errors = metric_errors(_moved(truth, 1.04), truth)
    assert errors["true_m_per_scene_m"] == pytest.approx(1.04, abs=1e-6)
    assert errors["scale_error_percent"] == pytest.approx(-3.846, abs=1e-3)
    assert errors["ate_rigid_m"]["rmse"] > 0.01
    assert trajectory_errors(_moved(truth, 1.04), truth)["ate_similarity_m"]["rmse"] == 0.0


def test_one_displaced_camera_shows_in_ate_and_rpe() -> None:
    truth = _truth()
    estimate = _moved(truth, 1.0)
    estimate.centers[2] += np.array([0.0, 0.0, 0.3])
    errors = trajectory_errors(estimate, truth)
    assert 0.05 < errors["ate_similarity_m"]["max"] < 0.3
    assert errors["rpe_translation_m"]["rmse"] > 0.05


def test_surface_scores_follow_their_definitions() -> None:
    truth = np.array([[float(x), 0.0, 0.0] for x in range(10)])
    estimate = np.array([[0.0, 0.0, 0.02], [1.0, 0.0, 0.08], [2.0, 0.0, 0.5]])
    scores = surface_scores(estimate, truth)
    assert scores["accuracy_m"]["mean"] == pytest.approx(0.2, abs=1e-4)
    assert scores["at_5cm"]["precision"] == pytest.approx(1 / 3, abs=1e-4)
    assert scores["at_10cm"]["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert scores["at_10cm"]["recall"] == pytest.approx(0.2, abs=1e-4)
    assert scores["chamfer_m"] == pytest.approx(
        scores["accuracy_m"]["mean"] + scores["completeness_m"]["mean"], abs=1e-3
    )
    with pytest.raises(ValueError, match="không còn điểm"):
        surface_scores(np.empty((0, 3)), truth)


def test_near_path_keeps_only_points_inside_the_window() -> None:
    points = np.array([[0.0, 0.5, 0.0], [0.0, 9.0, 0.0], [3.0, -1.0, 0.0]])
    kept = near_path(points, np.array([[0.0, 0.0, 0.0], [3.0, 0.0, 0.0]]), 2.0)
    assert kept.tolist() == [[0.0, 0.5, 0.0], [3.0, -1.0, 0.0]]


def test_map_reader_accepts_the_dataset_layout_with_normals_and_empty_faces(tmp_path: Path) -> None:
    header = (
        "ply\nformat binary_little_endian 1.0\ncomment VCGLIB generated\nelement vertex 2\n"
        "property float x\nproperty float y\nproperty float z\nproperty float nx\nproperty float ny\nproperty float nz\n"
        "element face 0\nproperty list uchar int vertex_indices\nend_header\n"
    )
    path = tmp_path / "map.ply"
    path.write_bytes(header.encode() + struct.pack("<12f", 1, 2, 3, 0, 0, 1, 4, 5, 6, 0, 1, 0))
    assert map_points(path).tolist() == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    path.write_bytes(header.encode() + struct.pack("<6f", 1, 2, 3, 0, 0, 1))
    with pytest.raises(ValueError, match="thiếu dữ liệu"):
        map_points(path)


def test_proposal_error_is_relative_to_the_true_scale() -> None:
    assert proposal_error(1.2, 1.2) == 0.0
    assert proposal_error(1.212, 1.2) == pytest.approx(1.0, abs=1e-3)
    assert proposal_error(1.14, 1.2) == pytest.approx(-5.0, abs=1e-3)
    with pytest.raises(ValueError, match="dương"):
        proposal_error(1.0, 0.0)
