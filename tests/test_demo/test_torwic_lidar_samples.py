"""Bộ mẫu video + gói LiDAR TorWIC: ba file khớp nhau từng frame và được Studio nhận diện đúng luồng B / C."""

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from scripts.demo.make_torwic_lidar_samples import build, main, scan_indices, segment_lines
from src.services.reconstruction.inputs.detect import detect_input
from tests.test_demo.test_torwic_demo_videos import _traversal

CALIBRATION = "".join(
    f"T_cam1_os.{key}: {value}\n"
    for key, value in zip("px py pz qx qy qz qw".split(), "0 0 0 0 0 0 1".split(), strict=True)
)


def _pcd(points: np.ndarray) -> bytes:
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
        f"COUNT 1 1 1\nWIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(points)}\nDATA binary\n"
    )
    return header.encode() + points.astype("<f4").tobytes()


def _dataset(root: Path, frames: int = 12) -> Path:
    """Traversal tổng hợp: robot đi thẳng theo +x, mỗi frame một scan nhìn thấy một mảng sàn dưới cảm biến."""
    directory = root / "Aisle_CW"
    _traversal(directory, frames)
    (directory / "lidar").mkdir()
    grid = np.stack(np.meshgrid(np.arange(-2, 2, 0.1), np.arange(-2, 2, 0.1)), axis=-1).reshape(-1, 2)
    scan = np.column_stack([grid, np.full(len(grid), -1.0)])
    for index in range(frames):
        (directory / "lidar" / f"{index:06d}.pcd").write_bytes(_pcd(scan))
    (directory / "traj_gt.txt").write_text(
        "".join(f"{index * 0.1} {index * 0.5} 0 1 0 0 0 1\n" for index in range(frames))
    )
    (root / "calibrations.txt").write_text(CALIBRATION)
    return root


def test_segment_and_scan_selection() -> None:
    assert segment_lines("a\nb\nc\nd\n", 1, 2) == "b\nc\n"
    with pytest.raises(ValueError, match="vượt quá 4 frame"):
        segment_lines("a\nb\nc\nd\n", 2, 5)
    assert scan_indices(10, 4) == [0, 4, 8]
    with pytest.raises(ValueError, match="scan-step"):
        scan_indices(10, 0)


def test_three_files_match_frame_for_frame_and_route_to_flows_b_and_c(tmp_path: Path) -> None:
    out = tmp_path / "out"
    records = build(_dataset(tmp_path / "data"), "Aisle_CW", 2, 8, 2, out)
    assert [record.file for record in records] == [
        "Aisle_CW_2_9__left.mp4",
        "Aisle_CW_2_9__lidar_scans.zip",
        "Aisle_CW_2_9__lidar_registered.zip",
    ]
    assert all(record.trajectory_origin == "ground_truth" and record.scans == 4 for record in records)
    raw = detect_input(out / records[1].file, 10**9)
    assert raw.kind == "lidar_scan_sequence" and raw.lidar is not None
    # Tám frame của đoạn → tám pose; scan đặt tên theo chỉ số frame trong đoạn (0, 2, 4, 6).
    assert (raw.lidar.pose_count, raw.lidar.scan_count, raw.lidar.pairing) == (8, 4, "index_in_name")
    with zipfile.ZipFile(out / records[1].file) as archive:
        assert sorted(name for name in archive.namelist() if name.endswith(".pcd")) == [
            f"lidar/{index:06d}.pcd" for index in (0, 2, 4, 6)
        ]
        # Dòng đầu của quỹ đạo trong gói là pose của frame `start` trong dataset (x = 2 × 0,5 m).
        assert archive.read("traj_gt.txt").decode().splitlines()[0].split()[1] == "1.0"
    registered = detect_input(out / records[2].file, 10**9)
    assert registered.kind == "registered_lidar" and registered.lidar is not None
    assert registered.lidar.pose_count == 8 and registered.lidar.point_count and registered.lidar.point_count > 100


def test_cli_writes_manifest_and_reports_bad_segments(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data, out = _dataset(tmp_path / "data"), tmp_path / "out"
    arguments = ["--dataset-root", str(data), "--traversal", "Aisle_CW", "--out", str(out), "--scan-step", "3"]
    assert main([*arguments, "--start", "0", "--count", "6"]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["samples"]) == 3 and "ground truth" in manifest["note"]
    assert main([*arguments, "--start", "0", "--count", "6"]) == 0  # chạy lại không nhân đôi bản ghi
    assert len(json.loads((out / "manifest.json").read_text())["samples"]) == 3
    assert main([*arguments, "--start", "10", "--count", "50"]) == 1
    assert "vượt quá 12 frame" in capsys.readouterr().err
