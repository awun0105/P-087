"""Region box resolution: acceptance tests for T-004 (one test per criterion in the plan)."""

import math

import numpy as np
import pytest
from pydantic import ValidationError

from src.models.contracts.object_membership import RegionBox
from src.services.scene.editing.region_box import boxes_contain


def box(**changes: object) -> dict:
    return {"op": "add", "center_m": [0.0, 0.0, 0.5], "half_extents_m": [0.3, 0.3, 0.5], "yaw_rad": 0.0} | changes


@pytest.mark.parametrize("half", [0.005, 20.0])
def test_criterion_0_closed_half_extent_bounds_are_accepted(half: float) -> None:
    RegionBox.model_validate(box(half_extents_m=[half, half, half]))


@pytest.mark.parametrize("half", [0.0049, 20.0001])
def test_criterion_0_just_outside_half_extent_bounds_are_rejected(half: float) -> None:
    with pytest.raises(ValidationError):
        RegionBox.model_validate(box(half_extents_m=[half, half, half]))


def region(op: str = "add", center=(0.0, 0.0, 0.0), half=(1.0, 1.0, 1.0), yaw: float = 0.0) -> RegionBox:
    return RegionBox(op=op, center_m=center, half_extents_m=half, yaw_rad=yaw)


def test_axis_aligned_box_contains_its_interior_only() -> None:
    points = np.array([[0.0, 0.0, 0.0], [0.9, -0.9, 0.9], [1.1, 0.0, 0.0], [0.0, 0.0, -1.1]])
    assert boxes_contain(points, [region()]).tolist() == [True, True, False, False]


def test_box_rotated_45_degrees_follows_its_own_axes() -> None:
    along_x = [0.9 * math.cos(math.pi / 4), 0.9 * math.sin(math.pi / 4), 0.0]
    points = np.array([along_x, [0.8, 0.0, 0.0], [0.0, 0.9, 0.0], [0.0, 0.0, 0.9], [0.0, 0.0, 1.05]])
    inside = boxes_contain(points, [region(half=(1.0, 0.2, 1.0), yaw=math.pi / 4)])
    assert inside.tolist() == [True, False, False, True, False]


def test_subtract_box_carves_a_hole_out_of_the_add_box() -> None:
    points = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [-1.9, 0.0, 0.0], [2.5, 0.0, 0.0]])
    boxes = [region(half=(2.0, 2.0, 2.0)), region("subtract", half=(0.5, 0.5, 2.0))]
    assert boxes_contain(points, boxes).tolist() == [False, True, True, False]


def test_points_on_a_face_are_inside_and_two_micrometres_outside_are_not() -> None:
    on_face = np.array([[1.0, 0.2, 0.3], [-1.0, 0.0, -1.0], [1.0 + 0.5e-6, 0.0, 0.0]])
    just_outside = np.array([[1.0 + 2e-6, 0.0, 0.0], [0.0, 1.0 + 2e-6, 0.0], [0.0, 0.0, -1.0 - 2e-6]])
    assert boxes_contain(on_face, [region()]).tolist() == [True, True, True]
    assert boxes_contain(just_outside, [region()]).tolist() == [False, False, False]


def test_non_finite_points_are_never_inside() -> None:
    points = np.array([[np.nan, 0.0, 0.0], [0.0, np.inf, 0.0]])
    assert boxes_contain(points, [region()]).tolist() == [False, False]


def test_subtract_without_any_add_box_contains_nothing() -> None:
    assert not boxes_contain(np.zeros((3, 3)), [region("subtract")]).any()
