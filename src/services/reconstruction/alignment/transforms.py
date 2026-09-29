"""Rigid frame math: ADAPT concept composition từ Re3Sim, không copy dependency graph."""

import math

from src.models.contracts.coordinates import Transform
from src.services.reconstruction.rgb.canonical.metric_math import compose_rotation, rotate


def validated_transform(transform: Transform) -> Transform:
    """Shared metadata cũng phải finite trước khi dùng tính toán hoặc xác nhận."""
    value = Transform.model_validate(transform.model_dump())
    if not all(math.isfinite(item) for item in (*value.translation_xyz, *value.rotation_quaternion_xyzw)):
        raise ValueError("rigid transform requires finite coordinates and quaternion")
    norm = math.hypot(*value.rotation_quaternion_xyzw)
    return value.model_copy(
        update={"rotation_quaternion_xyzw": tuple(v / norm for v in value.rotation_quaternion_xyzw)}
    )


def invert_transform(transform: Transform) -> Transform:
    """Nghịch đảo T_parent_from_local giữ đúng frame labels và -R^T t."""
    transform = validated_transform(transform)
    x, y, z, w = transform.rotation_quaternion_xyzw
    inverse = (-x, -y, -z, w)
    translation = rotate(transform.translation_xyz, inverse)
    return Transform(
        parent_frame=transform.local_frame,
        local_frame=transform.parent_frame,
        rotation_quaternion_xyzw=inverse,
        translation_xyz=tuple(-value for value in translation),
    )


def compose_transforms(parent: Transform, local: Transform) -> Transform:
    """T_A_from_B * T_B_from_C; extrinsic đơn lẻ không được relabel thành world."""
    parent, local = validated_transform(parent), validated_transform(local)
    if parent.local_frame != local.parent_frame:
        raise ValueError("cannot compose transforms with disconnected frames")
    offset = rotate(local.translation_xyz, parent.rotation_quaternion_xyzw)
    return Transform(
        parent_frame=parent.parent_frame,
        local_frame=local.local_frame,
        rotation_quaternion_xyzw=compose_rotation(parent.rotation_quaternion_xyzw, local.rotation_quaternion_xyzw),
        translation_xyz=tuple(a + b for a, b in zip(parent.translation_xyz, offset)),
    )
