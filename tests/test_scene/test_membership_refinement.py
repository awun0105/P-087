"""Annotated ownership, overlap and floor-contact regressions without GPU inference."""

import numpy as np
import pytest

from eval.fixtures.segmentation import cases, floor_model
from eval.object.segmentation_quality import ownership_metrics
from src.services.scene.association.refinement import exclusive_mask_labels, object_point_mask, refine_owners
from src.services.scene.decomposition.gaussian_split import assign_floor_gaussians_to_background


def rows_for(points: np.ndarray) -> np.ndarray:
    names = ["x", "y", "z", "opacity", *[f"scale_{i}" for i in range(3)], *[f"rot_{i}" for i in range(4)]]
    rows = np.zeros(len(points), dtype=[(name, "f4") for name in names])
    for i, name in enumerate(("x", "y", "z")):
        rows[name] = points[:, i]
    rows["rot_0"] = 1
    rows["opacity"] = 3
    for i in range(3):
        rows[f"scale_{i}"] = np.log(0.01)
    return rows


def test_occluded_seeds_are_not_returned_to_background_or_stolen_by_another_object():
    truth = np.array([0, 0, 1, 1, -1, -1])
    share = np.array([[0, 0], [0.6, 0.9], [0.8, 0.7], [0, 0], [0.8, 0.8], [0, 0]])
    baseline = np.where(share.max(axis=1) > 0.5, share.argmax(axis=1), -1)
    refined = refine_owners(share, [np.array([0, 1]), np.array([2, 3])], 0.5)
    assert ownership_metrics(truth, baseline)["completeness"] < 1
    assert ownership_metrics(truth, baseline)["background_leakage"] == 1
    np.testing.assert_array_equal(refined, truth)
    with pytest.raises(ValueError, match="exclusive"):
        refine_owners(share, [np.array([0]), np.array([0])], 0.5)


def test_overlap_abstains_instead_of_stealing_pixels_by_mask_area():
    a = np.array([[1, 1, 0], [0, 1, 0]], dtype=bool)
    b = np.array([[0, 1, 1], [0, 0, 0]], dtype=bool)
    expected = np.array([[0, -2, 1], [-1, 0, -1]])
    np.testing.assert_array_equal(exclusive_mask_labels([(0, a), (1, b)], a.shape), expected)
    np.testing.assert_array_equal(exclusive_mask_labels([(1, b), (0, a)], a.shape), expected)


def test_near_floor_leg_retained_but_planar_floor_below_plane_and_invalid_geometry_are_not():
    model = floor_model(cases()[-1])
    points = np.array([[0, 0, 0.003], [0.1, 0, 0.003], [0.2, 0, 0], [0.3, 0, -0.01], [0.4, 0, 0.003], [0.5, 0, 0.1]])
    rows = rows_for(points)
    rows["scale_2"][1] = np.log(0.0001)  # flat floor parallel to the plane, with positive reconstruction noise
    rows["rot_0"][4] = 0  # invalid quaternion cannot justify a rescue
    truth = np.array([0, -1, -1, -1, -1, 0])
    initial = np.zeros(len(rows), dtype=np.int32)
    baseline = assign_floor_gaussians_to_background(rows, initial, model)
    refined = assign_floor_gaussians_to_background(rows, initial, model, refinement=True)
    assert ownership_metrics(truth, baseline)["completeness"] == 0.5
    np.testing.assert_array_equal(refined, truth)
    # No rescue inside the measured uncertainty interval; unmeasured fallback keeps its protected band.
    noisy = model.model_copy(update={"robust_noise_sigma_m": 0.002})
    assert not object_point_mask(points, noisy)[:5].any()
    uncertain = model.model_copy(update={"status": "uncertain"})
    assert not object_point_mask(points, uncertain).any()


def test_floor_shape_guard_uses_fitted_normal_and_gaussian_rotation():
    from scipy.spatial.transform import Rotation

    model = floor_model(cases()[-1])
    rotation = Rotation.from_euler("x", 30, degrees=True)
    normal = rotation.apply([0.0, 0.0, 1.0])
    points = np.array([normal * 0.003, normal * 0.003])
    rows = rows_for(points)
    # First covariance is thin parallel to the tilted plane; second is thick along its normal.
    quat = rotation.as_quat()
    for axis, value in zip((1, 2, 3, 0), quat, strict=True):
        rows[f"rot_{axis}"] = value
    rows["scale_2"] = np.log([0.0001, 0.05])
    tilted = model.model_copy(update={"plane_normal_world": tuple(normal)})
    np.testing.assert_array_equal(
        assign_floor_gaussians_to_background(rows, np.zeros(2, dtype=int), tilted, refinement=True), [-1, 0]
    )
