"""So sánh kết quả đã xác nhận với LiDAR; không điền số khi chưa có đề xuất."""

import math

import pytest

from src.services.reconstruction.alignment.similarity import fit_similarity
from src.services.reconstruction.rgb.canonical.metric_math import SimilarityTransform
from src.services.reconstruction.rgb.canonical.mode_comparison import compare_modes

CAMERAS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.5, 0.0), (3.0, 1.0, 0.1)]


def _lidar(scale: float) -> object:
    source = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    return fit_similarity(source, [(scale * x, scale * y, scale * z + 0.35) for x, y, z in source])


def test_rgb_only_is_missing_without_numbers_and_missing_modes_are_marked() -> None:
    result = compare_modes("job-1", CAMERAS, None, None)
    rgb, user, lidar = result.modes
    assert rgb.status == "missing" and rgb.scale_m_per_sfm_unit is None and rgb.steps
    assert user.status == "missing" and lidar.status == "missing" and result.difference is None


def test_difference_reports_scale_tilt_height_and_check_segment() -> None:
    tilt = math.radians(2.0)  # người dùng chọn sàn nghiêng 2° quanh trục X
    user = SimilarityTransform(
        scale_m_per_sfm_unit=2.1,
        rotation_xyzw=(math.sin(tilt / 2), 0.0, 0.0, math.cos(tilt / 2)),
        translation_m=(0.0, 0.0, 0.35),
    )
    result = compare_modes("job-1", CAMERAS, user, _lidar(2.0), ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
    diff = result.difference
    assert diff is not None
    assert diff.scale_diff_percent == pytest.approx(5.0)
    assert diff.floor_tilt_deg == pytest.approx(2.0, abs=1e-6)
    assert diff.check_segment_user_m == pytest.approx(2.1) and diff.check_segment_lidar_m == pytest.approx(2.0)
    assert diff.check_segment_error_m == pytest.approx(0.1)
