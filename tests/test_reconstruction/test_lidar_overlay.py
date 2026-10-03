"""Lớp LiDAR chồng lên scene (L11): đúng phép căn chỉnh đã xác nhận, thu gọn đủ nhỏ, không có khi chưa căn chỉnh."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.models.contracts.coordinates import Transform
from src.models.contracts.reconstruction import AlignmentStatus, ReconstructionBundle
from src.services.reconstruction.lidar.fusion import ply_bytes
from src.services.reconstruction.views import lidar_overlay_points


def _bundle(status: AlignmentStatus | None, cloud: object = "cloud") -> ReconstructionBundle:
    record = None
    if status is not None:
        record = SimpleNamespace(
            status=status,
            transform_target_from_source=Transform(
                parent_frame="world",
                local_frame="lidar_map",
                translation_xyz=(10.0, 0.0, 1.0),
                # Quay 90° quanh Z: (x, y) → (−y, x).
                rotation_quaternion_xyzw=(0.0, 0.0, 2**-0.5, 2**-0.5),
            ),
        )
    return ReconstructionBundle.model_construct(alignment_record=record, lidar_geometry_ref=cloud)


def test_points_are_placed_with_the_confirmed_alignment(tmp_path: Path) -> None:
    path = tmp_path / "lidar.ply"
    path.write_bytes(ply_bytes(np.array([[1.0, 0.0, 0.0], [0.0, 2.0, 0.5]])))
    points = lidar_overlay_points(_bundle(AlignmentStatus.CONFIRMED), lambda _ref: path)
    assert points is not None and points.dtype == np.dtype("<f4")
    np.testing.assert_allclose(points, [[10.0, 1.0, 1.0], [8.0, 0.0, 1.5]], atol=1e-5)


def test_large_cloud_is_thinned_evenly_under_the_limit(tmp_path: Path) -> None:
    grid = np.stack(np.meshgrid(np.arange(60), np.arange(60), np.arange(3)), axis=-1).reshape(-1, 3) * 0.05
    path = tmp_path / "lidar.ply"
    path.write_bytes(ply_bytes(grid.astype(float)))
    points = lidar_overlay_points(_bundle(AlignmentStatus.CONFIRMED), lambda _ref: path, max_points=500)
    assert points is not None and 50 < len(points) <= 500
    # Thu gọn theo lưới nên vẫn phủ hết bề rộng của đám mây, không chỉ giữ một góc.
    assert np.ptp(points[:, 0]) > 2.5 and np.ptp(points[:, 1]) > 2.5


@pytest.mark.parametrize(
    "bundle", [_bundle(None), _bundle(AlignmentStatus.DECLARED), _bundle(AlignmentStatus.CONFIRMED, None)]
)
def test_no_overlay_without_a_confirmed_alignment(bundle: ReconstructionBundle) -> None:
    def unreachable(_ref: object) -> Path:
        raise AssertionError("không được đọc đám mây khi chưa có căn chỉnh đã xác nhận")

    assert lidar_overlay_points(bundle, unreachable) is None
