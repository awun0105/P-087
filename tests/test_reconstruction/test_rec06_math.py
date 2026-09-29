"""Known-distance fixture proof; không thay metric confirmation của scene thật."""

import math

import pytest

from src.services.reconstruction.rgb.canonical.metric_math import (
    SimilarityTransform,
    canonical_camera_pose,
    rotate,
    scale_from_distance,
)
from src.services.reconstruction.rgb.pose.camera_pose import CameraPose


def transform() -> SimilarityTransform:
    """Scale 2 + Rz90 + translation không đối xứng để bắt sai thứ tự."""
    return SimilarityTransform(
        scale_m_per_sfm_unit=2, rotation_xyzw=(0, 0, math.sqrt(0.5), math.sqrt(0.5)), translation_m=(10, 20, 30)
    )


def test_scale_direction_inverse_and_distance() -> None:
    """Point expectation tính tay, không dùng production inverse làm oracle duy nhất."""
    value = transform()
    assert scale_from_distance(((1, 0, 0), (4, 0, 0)), 6) == 2
    assert value.apply_point((1, 2, 3)) == pytest.approx((6, 22, 36))
    assert value.inverse_point((6, 22, 36)) == pytest.approx((1, 2, 3))
    assert math.dist(value.apply_point((0, 0, 0)), value.apply_point((0, 0, 4))) == pytest.approx(8)


def test_pose_orientation_and_no_double_scaling() -> None:
    """Rz90 * Rx90 không được nhầm thành Rx90 * Rz90; raw pose bất biến."""
    pose = CameraPose(
        frame_id=0,
        image_id=1,
        camera_id=1,
        image_name="000000.png",
        translation=(1, 2, 3),
        rotation_xyzw=(math.sqrt(0.5), 0, 0, math.sqrt(0.5)),
    )
    before = pose.model_dump()
    result = canonical_camera_pose(pose, transform())
    assert result.translation == pytest.approx((6, 22, 36))
    assert rotate((0, 1, 0), result.rotation_xyzw) == pytest.approx((0, 0, 1), abs=1e-12)
    assert rotate((1, 0, 0), result.rotation_xyzw) == pytest.approx((0, 1, 0), abs=1e-12)
    assert result.parent_frame == "world" and result.unit == "meter"
    assert pose.model_dump() == before
    with pytest.raises(ValueError, match="double scaling"):
        canonical_camera_pose(result, transform())


@pytest.mark.parametrize("distance", [0, -1, float("nan"), float("inf")])
def test_bad_measured_distance(distance: float) -> None:
    """Không xác nhận scale bằng khoảng cách không hợp lệ."""
    with pytest.raises(ValueError):
        scale_from_distance(((0, 0, 0), (1, 0, 0)), distance)


@pytest.mark.parametrize(
    "points", [((1, 1, 1), (1, 1, 1)), ((0, 0, 0), (float("nan"), 0, 0)), ((-1e308, 0, 0), (1e308, 0, 0))]
)
def test_degenerate_or_nonfinite_anchor(points: tuple) -> None:
    """Fail closed trước chia cho zero hoặc overflow."""
    with pytest.raises(ValueError):
        scale_from_distance(points, 2)


@pytest.mark.parametrize(
    "changes",
    [
        {"scale_m_per_sfm_unit": -1},
        {"scale_m_per_sfm_unit": float("inf")},
        {"rotation_xyzw": (0, 0, 0, 0)},
        {"rotation_xyzw": (0, 0, 0, 2)},
        {"translation_m": (0, float("inf"), 0)},
        {"source_frame": "world"},
    ],
)
def test_invalid_similarity(changes: dict) -> None:
    """Negative/reflection scale hoặc invalid quaternion không tới conversion."""
    with pytest.raises(ValueError):
        SimilarityTransform.model_validate(transform().model_dump() | changes)


def test_point_overflow_and_nan_rejected() -> None:
    """Finite config vẫn có thể gây overflow với payload quá lớn."""
    for point in ((1e308, 1e308, 1e308), (float("nan"), 0, 0)):
        with pytest.raises(ValueError):
            transform().apply_point(point)
