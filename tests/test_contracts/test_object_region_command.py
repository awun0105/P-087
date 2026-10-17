"""ObjectRegionCommand rejects malformed box edits before any membership math runs."""

import math

import pytest
from pydantic import ValidationError

from src.models.contracts.object_membership import ObjectRegionCommand, RegionBox

CHECKSUM = "sha256:" + "a" * 64


def box(**changes: object) -> dict:
    return {"op": "add", "center_m": [0.0, 0.0, 0.5], "half_extents_m": [0.3, 0.3, 0.5], "yaw_rad": 0.0} | changes


def command(boxes: list[dict] | None = None, **changes: object) -> dict:
    return {
        "expected_scene_revision": "rev-007",
        "membership_checksum": CHECKSUM,
        "boxes": [box()] if boxes is None else boxes,
    } | changes


def test_valid_command_is_accepted() -> None:
    value = ObjectRegionCommand.model_validate(command([box(), box(op="subtract")], claim_from=["b"]))
    assert value.claim_from == ["b"]


def test_command_needs_an_add_box() -> None:
    with pytest.raises(ValidationError, match="at least one add box"):
        ObjectRegionCommand.model_validate(command([box(op="subtract")]))


def test_box_count_is_capped_at_sixteen() -> None:
    ObjectRegionCommand.model_validate(command([box() for _ in range(16)]))
    with pytest.raises(ValidationError):
        ObjectRegionCommand.model_validate(command([box() for _ in range(17)]))
    with pytest.raises(ValidationError):
        ObjectRegionCommand.model_validate(command([]))


@pytest.mark.parametrize("half", [0.0, 0.0049, 20.0001])
def test_half_extents_outside_the_closed_range_are_rejected(half: float) -> None:
    with pytest.raises(ValidationError):
        RegionBox.model_validate(box(half_extents_m=[half, 0.3, 0.5]))


@pytest.mark.parametrize("half", [0.005, 20.0])
def test_half_extents_on_the_closed_bounds_are_accepted(half: float) -> None:
    RegionBox.model_validate(box(half_extents_m=[half, 0.3, 0.5]))


@pytest.mark.parametrize(
    "change",
    [
        {"center_m": [math.nan, 0.0, 0.5]},
        {"center_m": [math.inf, 0.0, 0.5]},
        {"half_extents_m": [math.nan, 0.3, 0.5]},
        {"yaw_rad": math.nan},
    ],
)
def test_non_finite_numbers_are_rejected(change: dict) -> None:
    with pytest.raises(ValidationError):
        RegionBox.model_validate(box(**change))


def test_yaw_is_bounded_to_one_full_turn() -> None:
    RegionBox.model_validate(box(yaw_rad=2 * math.pi))
    with pytest.raises(ValidationError):
        RegionBox.model_validate(box(yaw_rad=2 * math.pi + 0.1))


def test_claim_from_must_not_repeat_and_is_capped() -> None:
    with pytest.raises(ValidationError, match="must not repeat"):
        ObjectRegionCommand.model_validate(command(claim_from=["b", "b"]))
    with pytest.raises(ValidationError):
        ObjectRegionCommand.model_validate(command(claim_from=[f"o{i}" for i in range(33)]))


def test_unknown_box_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RegionBox.model_validate(box(extra=1))
