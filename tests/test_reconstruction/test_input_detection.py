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


# ── LiDAR (ADR 0009 §1) ─────────────────────────────────────────────────────────────────────────


def _pcd(count: int = 2) -> bytes:
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
        f"COUNT 1 1 1\nWIDTH {count}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {count}\nDATA binary\n"
    )
    return header.encode() + struct.pack(f"<{3 * count}f", *([0.5] * 3 * count))


def _trajectory(poses: int) -> bytes:
    return "".join(f"{index * 0.1} {index} 0 0 0 0 0 1\n" for index in range(poses)).encode()


def test_point_cloud_file_is_registered_lidar(tmp_path: Path) -> None:
    ply = detect_input(_write(tmp_path / "cloud.ply", _ply(("x", "y", "z"), count=5)), LIMIT)
    assert ply.kind == "registered_lidar" and ply.lidar is not None
    assert (ply.lidar.geometry_format, ply.lidar.point_count) == ("ply", 5)
    pcd = detect_input(_write(tmp_path / "cloud.pcd", _pcd(7)), LIMIT)
    assert pcd.kind == "registered_lidar" and pcd.lidar is not None
    assert (pcd.lidar.geometry_format, pcd.lidar.point_count) == ("pcd", 7)
    assert pcd.gaussian is None


def test_scan_sequence_needs_exactly_one_trajectory(tmp_path: Path) -> None:
    scans = {f"lidar/{index:06d}.pcd": _pcd() for index in range(3)}
    detection = detect_input(_zip(tmp_path / "ok.zip", {**scans, "traj_gt.txt": _trajectory(3)}), LIMIT)
    assert detection.kind == "lidar_scan_sequence" and detection.lidar is not None
    assert (detection.lidar.scan_count, detection.lidar.pose_count) == (3, 3)
    assert detection.lidar.trajectory_member == "traj_gt.txt" and detection.lidar.pairing == "index_in_name"

    # File thời gian (một số mỗi dòng) và IMU (7 cột) đi kèm dataset không bị nhầm là quỹ đạo.
    extras = {"frame_times.txt": b"0.0\n0.1\n0.2\n", "imu.txt": b"0.1 0 0 0 0.2 0.1 -9.8\n" * 3}
    with_extras = detect_input(_zip(tmp_path / "extras.zip", {**scans, **extras, "traj_gt.txt": _trajectory(3)}), LIMIT)
    assert with_extras.lidar is not None and with_extras.lidar.trajectory_member == "traj_gt.txt"

    with pytest.raises(InputRejectedError, match="không có file quỹ đạo.*không tự ước lượng quỹ đạo"):
        detect_input(_zip(tmp_path / "raw.zip", {**scans, **extras}), LIMIT)
    with pytest.raises(InputRejectedError, match="2 file quỹ đạo"):
        detect_input(_zip(tmp_path / "two.zip", {**scans, "a.txt": _trajectory(3), "b.txt": _trajectory(3)}), LIMIT)
    with pytest.raises(InputRejectedError, match="tải thẳng file"):
        detect_input(_zip(tmp_path / "one.zip", {"cloud.pcd": _pcd()}), LIMIT)


def test_scan_sequence_pairs_every_scan_with_a_pose(tmp_path: Path) -> None:
    # Nộp một phần scan: tên là chỉ số pose, miễn chỉ số nằm trong quỹ đạo.
    subset = {f"{index:06d}.pcd": _pcd() for index in (100, 110)}
    partial = detect_input(_zip(tmp_path / "subset.zip", {**subset, "traj.txt": _trajectory(200)}), LIMIT)
    assert partial.lidar is not None and (partial.lidar.scan_count, partial.lidar.pose_count) == (2, 200)
    with pytest.raises(InputRejectedError, match="vượt quá quỹ đạo"):
        detect_input(_zip(tmp_path / "beyond.zip", {**subset, "traj.txt": _trajectory(50)}), LIMIT)

    named = {"scan_a.pcd": _pcd(), "scan_b.pcd": _pcd()}
    ordered = detect_input(_zip(tmp_path / "named.zip", {**named, "traj.txt": _trajectory(2)}), LIMIT)
    assert ordered.lidar is not None and ordered.lidar.pairing == "sorted_order"
    with pytest.raises(InputRejectedError, match="khác số pose"):
        detect_input(_zip(tmp_path / "count.zip", {**named, "traj.txt": _trajectory(5)}), LIMIT)
    with pytest.raises(InputRejectedError, match="không đọc được"):
        detect_input(
            _zip(tmp_path / "bad.zip", {"a.pcd": b"not a cloud", "b.pcd": _pcd(), "t.txt": _trajectory(2)}), LIMIT
        )
