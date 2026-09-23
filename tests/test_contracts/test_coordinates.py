"""Positive and negative proof for canonical coordinate contracts."""

import pytest
from pydantic import ValidationError

from src.models.contracts.coordinates import CoordinateSystem, Transform


def test_canonical_coordinate_and_transform_defaults() -> None:
    """The approved convention is encoded as typed defaults."""
    coordinate = CoordinateSystem()
    transform = Transform(
        parent_frame="world",
        local_frame="object-001",
        translation_xyz=(0.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )

    assert coordinate.model_dump() == {
        "unit": "meter",
        "up_axis": "Z",
        "handedness": "right",
        "world_frame": "world",
    }
    assert transform.semantics == "parent_from_local"
    assert transform.quaternion_order == "xyzw"
    assert transform.angle_unit == "radian"
    assert transform.canonical_name == "T_world_from_object-001"


@pytest.mark.parametrize(
    ("field", "value"),
    [("up_axis", "Y"), ("handedness", "left"), ("unit", "centimeter")],
)
def test_noncanonical_coordinate_is_rejected(field: str, value: str) -> None:
    """External conventions must be converted before entering shared contracts."""
    payload = CoordinateSystem().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        CoordinateSystem.model_validate(payload)


def test_non_normalized_quaternion_is_rejected() -> None:
    """Invalid rotations fail at the contract boundary."""
    with pytest.raises(ValidationError, match="must be normalized"):
        Transform(
            parent_frame="world",
            local_frame="object-001",
            translation_xyz=(0.0, 0.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 2.0),
        )
