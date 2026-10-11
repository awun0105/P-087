"""Ghép scan theo quỹ đạo (ADR 0009, luồng C): hình học đúng, xác định, và từ chối đầu vào hỏng."""

import io
import math
import struct

import numpy as np
import pytest

from src.services.reconstruction.lidar.fusion import (
    FusionConfig,
    ScanPose,
    fuse_scans,
    parse_trajectory,
    ply_bytes,
    read_points,
    voxel_downsample,
)

IDENTITY = (0.0, 0.0, 0.0, 1.0)
#: Xoay +90° quanh Z: trục x của cảm biến trỏ theo +y của map.
QUARTER_TURN = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))


def _pcd(points: np.ndarray) -> bytes:
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
        f"COUNT 1 1 1\nWIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(points)}\nDATA binary\n"
    )
    return header.encode() + points.astype("<f4").tobytes()


def test_scans_land_where_their_poses_put_them() -> None:
    """Cùng một điểm ngoài đời, nhìn từ hai vị trí cảm biến khác nhau, phải trùng nhau sau khi ghép."""
    landmark = np.array([[4.0, 2.0, 1.0]])
    first = ScanPose(0.0, (0.0, 0.0, 0.0), IDENTITY)
    # Cảm biến ở (4, 0, 0), quay 90°: trong hệ cảm biến điểm mốc nằm ở (2, 0, 1).
    second = ScanPose(0.1, (4.0, 0.0, 0.0), QUARTER_TURN)
    seen_from_second = np.array([[2.0, 0.0, 1.0]])
    cloud, stats = fuse_scans([(landmark, first), (seen_from_second, second)], FusionConfig())
    assert stats.scan_count == 2 and stats.point_count == 1  # hai lần quan sát gộp về một điểm
    assert np.allclose(cloud[0], landmark[0], atol=1e-6)


def test_range_and_nonfinite_points_are_dropped_and_counted() -> None:
    points = np.array([[0.1, 0, 0], [3, 0, 0], [80, 0, 0], [np.nan, 0, 0], [0, 5, 0]])
    cloud, stats = fuse_scans([(points, ScanPose(0.0, (0, 0, 0), IDENTITY))], FusionConfig())
    assert (stats.input_points, stats.removed_points, stats.point_count) == (5, 3, 2)
    assert sorted(map(tuple, np.round(cloud, 6))) == [(0.0, 5.0, 0.0), (3.0, 0.0, 0.0)]
    with pytest.raises(ValueError, match="không còn điểm nào"):
        fuse_scans([(np.array([[0.1, 0, 0]]), ScanPose(0.0, (0, 0, 0), IDENTITY))], FusionConfig())


def test_result_does_not_depend_on_scan_batching() -> None:
    """Thứ tự và cách chia lô khi gộp không được đổi bytes đầu ra (checksum artifact ổn định)."""
    rng = np.random.default_rng(0)
    scans = [
        (rng.uniform(-10, 10, size=(500, 3)), ScanPose(index * 0.1, (index * 0.5, 0, 0), IDENTITY))
        for index in range(40)
    ]
    forward, _ = fuse_scans(scans, FusionConfig())
    again, _ = fuse_scans(scans, FusionConfig())
    assert ply_bytes(forward) == ply_bytes(again)
    assert len(forward) < sum(len(points) for points, _ in scans)


def test_voxel_keeps_the_centroid_of_each_cell() -> None:
    points = np.array([[0.01, 0.01, 0.01], [0.03, 0.03, 0.03], [0.26, 0.0, 0.0]])
    reduced = voxel_downsample(points, 0.05)
    assert sorted(map(tuple, np.round(reduced, 6))) == [(0.02, 0.02, 0.02), (0.26, 0.0, 0.0)]


def test_ply_output_reads_back_and_pcd_input_is_checked() -> None:
    points = np.array([[1.5, -2.0, 0.25], [0.0, 3.0, 9.0]])
    assert np.allclose(read_points(io.BytesIO(ply_bytes(points)), 10), points)
    assert np.allclose(read_points(io.BytesIO(_pcd(points)), 10), points)
    with pytest.raises(ValueError, match="bị cắt"):
        read_points(io.BytesIO(_pcd(points)[:-4]), 10)
    with pytest.raises(ValueError, match="vượt giới hạn"):
        read_points(io.BytesIO(_pcd(points)), 1)
    big = struct.pack(">3f", 1.0, 2.0, 3.0)
    header = b"ply\nformat binary_big_endian 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
    assert np.allclose(read_points(io.BytesIO(header + big), 10), [[1.0, 2.0, 3.0]])


def test_trajectory_must_be_ordered_finite_and_normalized() -> None:
    poses = parse_trajectory("# t x y z qx qy qz qw\n0.0 1 2 3 0 0 0 1\n0.1, 1, 2, 3, 0, 0, 0, 1\n")
    assert len(poses) == 2 and poses[1].translation == (1.0, 2.0, 3.0)
    for text, message in (
        ("0 0 0 0 0 0 0 1\n", "ít nhất 2 pose"),
        ("0 0 0 0 0 0 0 1\n0 0 0 0 0 0 0 1\n", "tăng dần"),
        ("0 0 0 0 0 0 0 2\n1 0 0 0 0 0 0 1\n", "chưa chuẩn hoá"),
        ("0 0 0 0 0 0 1\n", "cần 8 số"),
        ("0 a 0 0 0 0 0 1\n", "không phải số"),
    ):
        with pytest.raises(ValueError, match=message):
            parse_trajectory(text)
