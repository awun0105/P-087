"""Region box resolution: acceptance tests for T-004 (one test per criterion in the plan)."""

import pytest
from pydantic import ValidationError

from src.models.contracts.object_membership import RegionBox


def box(**changes: object) -> dict:
    return {"op": "add", "center_m": [0.0, 0.0, 0.5], "half_extents_m": [0.3, 0.3, 0.5], "yaw_rad": 0.0} | changes


@pytest.mark.parametrize("half", [0.005, 20.0])
def test_criterion_0_closed_half_extent_bounds_are_accepted(half: float) -> None:
    RegionBox.model_validate(box(half_extents_m=[half, half, half]))


@pytest.mark.parametrize("half", [0.0049, 20.0001])
def test_criterion_0_just_outside_half_extent_bounds_are_rejected(half: float) -> None:
    with pytest.raises(ValidationError):
        RegionBox.model_validate(box(half_extents_m=[half, half, half]))
