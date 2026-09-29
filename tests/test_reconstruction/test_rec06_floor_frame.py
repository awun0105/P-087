"""REC-06: frame từ 3 điểm sàn + đoạn A/B, kiểm bằng scene tổng hợp có phép biến đổi đã biết."""

import math

import pytest

from src.services.reconstruction.rgb.canonical.floor_frame import floor_frame
from src.services.reconstruction.rgb.canonical.metric_math import SimilarityTransform, rotate, scale_from_distance

# Scene thật (mét, Z-up): sàn z=0, A ở gốc, B cách 2,4 m theo +X, camera cao 1,2–1,5 m.
WORLD_FLOOR = ((3.0, 1.0, 0.0), (-2.0, 4.0, 0.0), (1.0, -5.0, 0.0))
WORLD_A, WORLD_B = (0.0, 0.0, 0.0), (2.4, 0.0, 0.0)
WORLD_CAMERAS = [(1.0, 2.0, 1.2), (-1.0, 3.0, 1.5), (0.5, -2.0, 1.3)]

# SfM frame tùy ý: xoay lạ, scale 0,37 đơn vị/mét, tịnh tiến lạ.
SFM_FROM_WORLD_ROTATION = (0.2, -0.4, 0.3, math.sqrt(1 - 0.04 - 0.16 - 0.09))
SFM_UNITS_PER_METER = 0.37
SFM_OFFSET = (5.0, -7.0, 2.5)


def _to_sfm(point: tuple[float, float, float]) -> tuple[float, float, float]:
    rotated = rotate(point, SFM_FROM_WORLD_ROTATION)
    return tuple(SFM_UNITS_PER_METER * value + offset for value, offset in zip(rotated, SFM_OFFSET, strict=True))


def test_recovers_floor_origin_and_axes() -> None:
    floor = tuple(_to_sfm(point) for point in WORLD_FLOOR)
    a, b = _to_sfm(WORLD_A), _to_sfm(WORLD_B)
    scale = scale_from_distance((a, b), 2.4)
    frame = floor_frame(floor, a, b, scale, [_to_sfm(point) for point in WORLD_CAMERAS])
    transform = SimilarityTransform(
        scale_m_per_sfm_unit=scale, rotation_xyzw=frame.rotation_xyzw, translation_m=frame.translation_m
    )
    for point in floor:
        assert transform.apply_point(point)[2] == pytest.approx(0.0, abs=1e-9)  # sàn = z 0
    assert transform.apply_point(a) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)  # A ở gốc
    assert transform.apply_point(b) == pytest.approx((2.4, 0.0, 0.0), abs=1e-9)  # B trên +X, đúng 2,4 m
    for camera in WORLD_CAMERAS:
        assert transform.apply_point(_to_sfm(camera)) == pytest.approx(camera, abs=1e-9)
    assert frame.floor_residual_m == pytest.approx(0.0, abs=1e-9)


def test_normal_points_toward_cameras_even_if_floor_order_is_flipped() -> None:
    floor = tuple(_to_sfm(point) for point in reversed(WORLD_FLOOR))
    a, b = _to_sfm(WORLD_A), _to_sfm(WORLD_B)
    scale = scale_from_distance((a, b), 2.4)
    frame = floor_frame(floor, a, b, scale, [_to_sfm(point) for point in WORLD_CAMERAS])
    transform = SimilarityTransform(
        scale_m_per_sfm_unit=scale, rotation_xyzw=frame.rotation_xyzw, translation_m=frame.translation_m
    )
    assert all(transform.apply_point(_to_sfm(camera))[2] > 1.0 for camera in WORLD_CAMERAS)


def test_reports_residual_when_floor_points_are_not_coplanar_with_anchor_projection() -> None:
    floor = tuple(_to_sfm(point) for point in WORLD_FLOOR)
    lifted_a = _to_sfm((0.0, 0.0, 0.3))  # A cao 30 cm: gốc vẫn là hình chiếu xuống sàn
    b = _to_sfm((2.4, 0.0, 0.3))
    scale = scale_from_distance((lifted_a, b), 2.4)
    frame = floor_frame(floor, lifted_a, b, scale, [_to_sfm(point) for point in WORLD_CAMERAS])
    transform = SimilarityTransform(
        scale_m_per_sfm_unit=scale, rotation_xyzw=frame.rotation_xyzw, translation_m=frame.translation_m
    )
    assert transform.apply_point(lifted_a) == pytest.approx((0.0, 0.0, 0.3), abs=1e-9)


def test_rejects_degenerate_inputs() -> None:
    cameras = [_to_sfm(point) for point in WORLD_CAMERAS]
    a, b = _to_sfm(WORLD_A), _to_sfm(WORLD_B)
    collinear = (_to_sfm((0, 0, 0)), _to_sfm((1, 0, 0)), _to_sfm((2, 0, 0)))
    with pytest.raises(ValueError, match="thẳng hàng"):
        floor_frame(collinear, a, b, 1.0, cameras)
    floor = tuple(_to_sfm(point) for point in WORLD_FLOOR)
    with pytest.raises(ValueError, match="camera"):
        floor_frame(floor, a, b, 1.0, [])
    with pytest.raises(ValueError, match="scale"):
        floor_frame(floor, a, b, 0.0, cameras)
