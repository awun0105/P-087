"""REC-06 similarity math: p_world = scale * R * p_sfm + translation_m.

Một distance anchor không xác định orientation/origin. Caller phải cung cấp
rotation/translation riêng; không suy canonical frame từ camera đầu hoặc GT.
"""

import math
from typing import Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import ContractModel
from src.services.reconstruction.rgb.camera_pose import CameraPose, Quaternion, Vector3


def _finite(values: tuple[float, ...]) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError("metric calculation requires finite values")


def unit_quaternion(rotation: Quaternion) -> Quaternion:
    """Kiểm xyzw và bỏ roundoff; không chấp nhận quaternion tùy ý rồi normalize."""
    _finite(rotation)
    norm = math.hypot(*rotation)
    if not math.isclose(norm, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("metric rotation must be a unit xyzw quaternion")
    return tuple(value / norm for value in rotation)


def rotate(point: Vector3, rotation: Quaternion) -> Vector3:
    """Quaternion action giữ handedness; không nhận reflection/nonuniform scale."""
    _finite(point)
    x, y, z, w = unit_quaternion(rotation)
    a, b, c = point
    tx, ty, tz = 2 * (y * c - z * b), 2 * (z * a - x * c), 2 * (x * b - y * a)
    result = (a + w * tx + y * tz - z * ty, b + w * ty + z * tx - x * tz, c + w * tz + x * ty - y * tx)
    _finite(result)
    return result


def compose_rotation(parent: Quaternion, local: Quaternion) -> Quaternion:
    """q_parent_from_local = q_parent_from_middle * q_middle_from_local."""
    x, y, z, w = unit_quaternion(parent)
    a, b, c, d = unit_quaternion(local)
    return unit_quaternion(
        (
            w * a + x * d + y * c - z * b,
            w * b - x * c + y * d + z * a,
            w * c + x * b - y * a + z * d,
            w * d - x * a - y * b - z * c,
        )
    )


def scale_from_distance(points: tuple[Vector3, Vector3], distance_m: float) -> float:
    """Suy đúng một scalar dương từ hai điểm khác nhau và measured distance."""
    _finite((*points[0], *points[1], distance_m))
    distance = math.dist(*points)
    if distance_m <= 0 or distance <= 0 or not math.isfinite(distance):
        raise ValueError("anchor requires distinct finite points and positive measured distance")
    scale = distance_m / distance
    if scale <= 0 or not math.isfinite(scale):
        raise ValueError("anchor scale is not representable as a finite positive value")
    return scale


class SimilarityTransform(ContractModel):
    """Transform nội bộ, tách similarity scale khỏi shared rigid Transform."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_frame: Literal["sfm_world"] = "sfm_world"
    target_frame: Literal["world"] = "world"
    semantics: Literal["parent_from_local"] = "parent_from_local"
    scale_m_per_sfm_unit: FiniteFloat = Field(gt=0)
    rotation_xyzw: Quaternion
    translation_m: Vector3

    @model_validator(mode="after")
    def _valid_rotation(self) -> Self:
        unit_quaternion(self.rotation_xyzw)
        return self

    def apply_point(self, point: Vector3) -> Vector3:
        """Translation đã là mét nên không nhân translation với scale lần nữa."""
        rotated = rotate(point, self.rotation_xyzw)
        result = tuple(self.scale_m_per_sfm_unit * value + offset for value, offset in zip(rotated, self.translation_m))
        _finite(result)
        return result

    def inverse_point(self, point: Vector3) -> Vector3:
        """Inverse dùng để chứng minh direction/round-trip, không xác nhận anchor."""
        relative = tuple(
            (value - offset) / self.scale_m_per_sfm_unit for value, offset in zip(point, self.translation_m)
        )
        x, y, z, w = self.rotation_xyzw
        return rotate(relative, (-x, -y, -z, w))


class CanonicalCameraPose(CameraPose):
    """Pose derivative tách raw CameraPose; intrinsics/local camera axes không đổi."""

    parent_frame: Literal["world"] = "world"
    unit: Literal["meter"] = "meter"


def canonical_camera_pose(pose: CameraPose, transform: SimilarityTransform) -> CanonicalCameraPose:
    """Scale camera center, compose orientation; không scale quaternion/intrinsics."""
    if isinstance(pose, CanonicalCameraPose):
        raise ValueError("camera pose is already canonical; refusing double scaling")
    payload = pose.model_dump() | {
        "translation": transform.apply_point(pose.translation),
        "rotation_xyzw": compose_rotation(transform.rotation_xyzw, pose.rotation_xyzw),
    }
    return CanonicalCameraPose.model_validate(payload)
