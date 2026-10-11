"""Canonical coordinate, metric và transform contracts."""

import math
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from src.models.contracts.artifacts import ContractModel, Identifier

CANONICAL_UNIT = "meter"
CANONICAL_UP_AXIS = "Z"
CANONICAL_HANDEDNESS = "right"
CANONICAL_WORLD_FRAME = "world"
TRANSFORM_SEMANTICS = "parent_from_local"
QUATERNION_ORDER = "xyzw"
ANGLE_UNIT = "radian"


class CoordinateSystem(ContractModel):
    """Canonical coordinate convention shared by every track."""

    unit: Literal["meter"] = CANONICAL_UNIT
    up_axis: Literal["Z"] = CANONICAL_UP_AXIS
    handedness: Literal["right"] = CANONICAL_HANDEDNESS
    world_frame: Literal["world"] = CANONICAL_WORLD_FRAME


class Transform(ContractModel):
    """Rigid transform mapping local coordinates into the parent frame."""

    semantics: Literal["parent_from_local"] = TRANSFORM_SEMANTICS
    parent_frame: Identifier
    local_frame: Identifier
    translation_xyz: tuple[float, float, float]
    rotation_quaternion_xyzw: tuple[float, float, float, float]
    quaternion_order: Literal["xyzw"] = QUATERNION_ORDER
    angle_unit: Literal["radian"] = ANGLE_UNIT

    @property
    def canonical_name(self) -> str:
        """Expose transform direction without relying on source dataset labels."""
        return f"T_{self.parent_frame}_from_{self.local_frame}"

    @model_validator(mode="after")
    def _validate_quaternion(self) -> Self:
        norm = math.sqrt(sum(component * component for component in self.rotation_quaternion_xyzw))
        if not math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("rotation_quaternion_xyzw must be normalized")
        if self.parent_frame == self.local_frame:
            raise ValueError("parent_frame and local_frame must differ")
        return self


class MetricScaleStatus(StrEnum):
    """Metric confirmation state for reconstruction and scene artifacts."""

    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"


class MetricScale(ContractModel):
    """Metric scale expressed as meters per canonical unit."""

    status: MetricScaleStatus
    meters_per_unit: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _require_confirmed_scale(self) -> Self:
        if self.status == MetricScaleStatus.CONFIRMED and self.meters_per_unit is None:
            raise ValueError("meters_per_unit is required when metric scale is CONFIRMED")
        return self
