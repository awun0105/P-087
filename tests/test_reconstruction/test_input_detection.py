"""ADR 0004: nhận diện loại đầu vào theo bytes, từ chối rõ ràng khi không khớp."""

import struct
import zipfile
from pathlib import Path

import pytest

from src.services.reconstruction.inputs.detect import GAUSSIAN_FIELDS, InputRejectedError, detect_input

LIMIT = 10_000_000


def _ply(fields: tuple[str, ...], count: int = 2, truncate: int = 0) -> bytes:
    header = "ply\nformat binary_little_endian 1.0\ncomment test\n"
    header += f"element vertex {count}\n" + "".join(f"property float {name}\n" for name in fields) + "end_header\n"
    body = struct.pack(f"<{len(fields) * count}f", *([0.5] * len(fields) * count))
    return header.encode() + body[: len(body) - truncate]


def _gaussian(sh_rest: int = 45, **kwargs: int) -> bytes:
    return _ply(GAUSSIAN_FIELDS + tuple(f"f_rest_{index}" for index in range(sh_rest)), **kwargs)


def _write(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return path


COLMAP = {f"scene/sparse/0/{name}.bin": b"x" for name in ("cameras", "images", "points3D")}


def test_video_by_container_bytes_not_extension(tmp_path: Path) -> None:
    video = _write(tmp_path / "clip.bin", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16)
    assert detect_input(video, LIMIT).kind == "rgb_video"


def test_gaussian_ply_reports_count_and_sh_degree(tmp_path: Path) -> None:
    detection = detect_input(_write(tmp_path / "scene.ply", _gaussian(count=3)), LIMIT)
    assert detection.kind == "gaussian_ply"
    assert detection.gaussian is not None
    assert (detection.gaussian.gaussian_count, detection.gaussian.sh_degree) == (3, 3)
    assert detect_input(_write(tmp_path / "dc.ply", _gaussian(sh_rest=0)), LIMIT).gaussian.sh_degree == 0  # type: ignore[union-attr]


def test_truncated_and_malformed_gaussian_ply_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(InputRejectedError, match="bị cắt"):
        detect_input(_write(tmp_path / "cut.ply", _gaussian(truncate=4)), LIMIT)
    with pytest.raises(InputRejectedError, match="f_rest"):
        detect_input(_write(tmp_path / "sh.ply", _gaussian(sh_rest=7)), LIMIT)


def test_zip_with_gaussian_and_colmap(tmp_path: Path) -> None:
    members = {"scene/point_cloud.ply": _gaussian(), "scene/sparse/0/points3D.ply": _ply(("x", "y", "z"))} | COLMAP
    detection = detect_input(_zip(tmp_path / "bundle.zip", members), LIMIT)
    assert detection.kind == "gaussian_ply_colmap"
    assert (detection.ply_member, detection.colmap_dir, detection.colmap_format) == (
        "scene/point_cloud.ply",
        "scene/sparse/0",
        "bin",
    )


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ({"a.ply": _gaussian()}, "thiếu model COLMAP"),
        ({**COLMAP}, "đúng một file PLY"),
        ({"a.ply": _gaussian(), "b.ply": _gaussian(), **COLMAP}, "đúng một file PLY"),
        (
            {"a.ply": _gaussian(), **COLMAP, **{k.replace("0/", "1/"): v for k, v in COLMAP.items()}},
            "nhiều model",
        ),
        ({"../evil.ply": _gaussian(), **COLMAP}, "không an toàn"),
    ],
)
def test_invalid_zip_is_rejected(tmp_path: Path, members: dict[str, bytes], message: str) -> None:
    with pytest.raises(InputRejectedError, match=message):
        detect_input(_zip(tmp_path / "bad.zip", members), LIMIT)


def test_zip_bomb_limit_and_unknown_bytes(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "big.zip", {"a.ply": _gaussian(), **COLMAP})
    with pytest.raises(InputRejectedError, match="vượt dung lượng"):
        detect_input(archive, 10)
    with pytest.raises(InputRejectedError, match="Không nhận diện"):
        detect_input(_write(tmp_path / "x.splat", b"\x01\x02\x03" * 20), LIMIT)


# ── Gói LiDAR (ADR 0009) ────────────────────────────────────────────────────────────────────────


def _pcd(count: int = 2) -> bytes:
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
        f"COUNT 1 1 1\nWIDTH {count}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {count}\nDATA binary\n"
    )
    return header.encode() + struct.pack(f"<{3 * count}f", *([0.5] * 3 * count))


def _trajectory(poses: int) -> bytes:
    return "".join(f"{index * 0.1} {index} 0 0 0 0 0 1\n" for index in range(poses)).encode()


def _times(count: int) -> bytes:
    return "".join(f"{index * 0.1}\n" for index in range(count)).encode()


CALIBRATION = "".join(
    f"T_cam1_os.{name}: {value}\n"
    for name, value in zip(("px", "py", "pz", "qx", "qy", "qz", "qw"), (0.1, 0, 0, 0, 0, 0, 1))
).encode()
IMU = b"0.1 0 0 0 0.2 0.1 -9.8\n" * 3


def _package(poses: int, **members: bytes) -> dict[str, bytes]:
    """Phần đi kèm bắt buộc của gói: quỹ đạo, calibration, thời điểm frame (+ file IMU không liên quan)."""
    return {
        "traj_gt.txt": _trajectory(poses),
        "calibrations.txt": CALIBRATION,
        "frame_times.txt": _times(poses),
        "imu_left.txt": IMU,
        **members,
    }


def test_bare_point_cloud_is_rejected_with_package_guidance(tmp_path: Path) -> None:
    """Đám mây nộp riêng lẻ không căn chỉnh được: từ chối và nói rõ gói cần gì."""
    for name, payload in (("cloud.ply", _ply(("x", "y", "z"), count=5)), ("cloud.pcd", _pcd(7))):
        with pytest.raises(InputRejectedError, match="nộp riêng lẻ.*quỹ đạo.*calibration.*thời điểm frame"):
            detect_input(_write(tmp_path / name, payload), LIMIT)


def test_scan_package_reports_scans_poses_and_members(tmp_path: Path) -> None:
    scans = {f"lidar/{index:06d}.pcd": _pcd() for index in range(3)}
    detection = detect_input(_zip(tmp_path / "ok.zip", _package(3, **scans)), LIMIT)
    assert detection.kind == "lidar_scan_sequence" and detection.lidar is not None
    lidar = detection.lidar
    assert (lidar.scan_count, lidar.pose_count, lidar.pairing) == (3, 3, "index_in_name")
    assert (lidar.trajectory_member, lidar.calibration_member, lidar.frame_times_member) == (
        "traj_gt.txt",
        "calibrations.txt",
        "frame_times.txt",
    )
    assert lidar.calibration_format == "torwic_txt" and lidar.cloud_member is None


def test_registered_package_is_one_cloud_with_the_same_companions(tmp_path: Path) -> None:
    for name, payload, fmt in (("map.ply", _ply(("x", "y", "z"), count=9), "ply"), ("map.pcd", _pcd(9), "pcd")):
        detection = detect_input(_zip(tmp_path / f"{fmt}.zip", _package(4, **{name: payload})), LIMIT)
        assert detection.kind == "registered_lidar" and detection.lidar is not None
        assert (detection.lidar.cloud_member, detection.lidar.point_count, detection.lidar.geometry_format) == (
            name,
            9,
            fmt,
        )
        assert detection.lidar.scan_count is None and detection.lidar.pose_count == 4
    json_calibration = b'{"lidar_from_camera": {"translation_xyz": [0, 0, 0], "rotation_xyzw": [0, 0, 0, 1]}}'
    members = {**_package(4, **{"map.pcd": _pcd(9)}), "calibrations.txt": json_calibration}
    assert detect_input(_zip(tmp_path / "json.zip", members), LIMIT).lidar.calibration_format == "json"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("drop", "message"),
    [
        ("traj_gt.txt", "không có file quỹ đạo.*không tự ước lượng quỹ đạo"),
        ("calibrations.txt", "thiếu file calibration"),
        ("frame_times.txt", "thiếu file thời điểm frame"),
    ],
)
def test_package_missing_a_companion_is_rejected(tmp_path: Path, drop: str, message: str) -> None:
    """Scan thô (hay đám mây đã đăng ký) thiếu quỹ đạo, calibration hoặc thời điểm frame đều bị từ chối rõ lý do."""
    for clouds in ({f"{index:06d}.pcd": _pcd() for index in range(3)}, {"map.pcd": _pcd()}):
        members = _package(3, **clouds)
        del members[drop]
        with pytest.raises(InputRejectedError, match=message):
            detect_input(_zip(tmp_path / f"{len(clouds)}-{drop}.zip", members), LIMIT)


def test_package_rejects_ambiguous_or_inconsistent_members(tmp_path: Path) -> None:
    scans = {f"{index:06d}.pcd": _pcd() for index in range(3)}
    with pytest.raises(InputRejectedError, match="2 file quỹ đạo"):
        detect_input(_zip(tmp_path / "two.zip", {**_package(3, **scans), "other.txt": _trajectory(3)}), LIMIT)
    with pytest.raises(InputRejectedError, match="không khớp quỹ đạo"):
        detect_input(_zip(tmp_path / "times.zip", {**_package(3, **scans), "frame_times.txt": _times(5)}), LIMIT)
    with pytest.raises(InputRejectedError, match="vượt quá quỹ đạo"):
        detect_input(_zip(tmp_path / "beyond.zip", _package(3, **{"000100.pcd": _pcd(), "000110.pcd": _pcd()})), LIMIT)
    with pytest.raises(InputRejectedError, match="khác số pose"):
        detect_input(_zip(tmp_path / "count.zip", _package(5, **{"a.pcd": _pcd(), "b.pcd": _pcd()})), LIMIT)
    with pytest.raises(InputRejectedError, match="không đọc được"):
        detect_input(_zip(tmp_path / "bad.zip", _package(2, **{"a.pcd": b"not a cloud", "b.pcd": _pcd()})), LIMIT)
    with pytest.raises(InputRejectedError, match="scan thô phải là .pcd"):
        clouds = {"a.ply": _ply(("x", "y", "z")), "b.ply": _ply(("x", "y", "z"))}
        detect_input(_zip(tmp_path / "plies.zip", _package(2, **clouds)), LIMIT)


def test_scan_subset_and_name_order_pairing(tmp_path: Path) -> None:
    subset = {f"{index:06d}.pcd": _pcd() for index in (100, 110)}
    partial = detect_input(_zip(tmp_path / "subset.zip", _package(200, **subset)), LIMIT)
    assert partial.lidar is not None and (partial.lidar.scan_count, partial.lidar.pose_count) == (2, 200)
    named = {"scan_a.pcd": _pcd(), "scan_b.pcd": _pcd()}
    ordered = detect_input(_zip(tmp_path / "named.zip", _package(2, **named)), LIMIT)
    assert ordered.lidar is not None and ordered.lidar.pairing == "sorted_order"


def test_gaussian_zip_with_colmap_point_cloud_is_not_a_lidar_package(tmp_path: Path) -> None:
    """points3D.ply của COLMAP là đám mây điểm nhưng ZIP này vẫn là 3DGS + COLMAP."""
    members = {"s/point_cloud.ply": _gaussian(), "s/sparse/0/points3D.ply": _ply(("x", "y", "z")), **COLMAP}
    assert detect_input(_zip(tmp_path / "scene.zip", members), LIMIT).kind == "gaussian_ply_colmap"
