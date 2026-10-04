"""Bộ video demo TorWIC: tìm traversal, ba biến thể mỗi traversal, FPS từ mốc thời gian, manifest có checksum."""

import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from scripts.demo.make_torwic_demo_videos import build, discover, fps_from_times, frame_paths, main, slug


def _png(path: Path, shade: int) -> None:
    """PNG RGB 32×32 một màu (ffmpeg cần ảnh thật, kích thước chẵn cho yuv420p)."""
    row = b"\x00" + bytes([shade, 255 - shade, 128]) * 32

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    payload = chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(row * 32))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + payload + chunk(b"IEND", b""))


def _traversal(directory: Path, frames: int, *, right: int | None = None, step: float = 0.1) -> None:
    for camera, count in (("image_left", frames), ("image_right", frames if right is None else right)):
        (directory / camera).mkdir(parents=True)
        for index in range(count):
            _png(directory / camera / f"{index:06d}.png", 20 * index % 255)
    (directory / "frame_times.txt").write_text("\n".join(f"{index * step:.18e}" for index in range(frames)) + "\n")


def _dataset(root: Path) -> Path:
    _traversal(root / "Aisle_CCW", 6)
    _traversal(root / "Hallway_Full_CW_Run_1__2022-10-12" / "Hallway_Full_CW_Run_1", 4, step=0.2)  # lồng một cấp
    _traversal(root / "Broken", 5, right=3)  # hai camera lệch số frame
    (root / "notes").mkdir()
    return root


def test_fps_and_names() -> None:
    assert slug("Hallway_Full_CW_Run_1__2022-10-12") == "Hallway_Full_CW_Run_1_2022_10_12"
    assert slug("TorWIC SLAM (v2)") == "TorWIC_SLAM_v2"


def test_fps_comes_from_frame_times(tmp_path: Path) -> None:
    times = tmp_path / "frame_times.txt"
    times.write_text("0.0\n0.1\n0.2\n0.3\n")
    assert fps_from_times(times) == pytest.approx(10.0)
    times.write_text("0.5\n")
    with pytest.raises(ValueError, match="ít nhất 2 mốc"):
        fps_from_times(times)
    times.write_text("3.0\n2.0\n1.0\n")
    with pytest.raises(ValueError, match="tăng dần"):
        fps_from_times(times)


def test_discover_finds_complete_traversals_only(tmp_path: Path) -> None:
    found = discover(_dataset(tmp_path))
    assert [(item.name, item.frames, round(item.fps, 3)) for item in found] == [
        ("Aisle_CCW", 6, 10.0),
        ("Hallway_Full_CW_Run_1_2022_10_12", 4, 5.0),  # tên lấy từ thư mục ngoài (có ngày chạy)
    ]
    combined = frame_paths(found[0], ("left", "right"))
    assert len(combined) == 12 and combined[5].parent.name == "image_left" and combined[6].parent.name == "image_right"
    assert combined[6].name == "000000.png"  # camera phải bắt đầu lại từ frame đầu


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="cần ffmpeg/ffprobe")
def test_build_writes_three_variants_per_traversal_and_is_resumable(tmp_path: Path) -> None:
    out = tmp_path / "videos"
    assert main(["--dataset-root", str(_dataset(tmp_path / "data")), "--out", str(out)]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    videos = {item["file"]: item for item in manifest["videos"]}
    assert manifest["purpose"] == "demo" and sorted(videos) == [
        "Aisle_CCW__left.mp4",
        "Aisle_CCW__left_right.mp4",
        "Aisle_CCW__right.mp4",
        "Hallway_Full_CW_Run_1_2022_10_12__left.mp4",
        "Hallway_Full_CW_Run_1_2022_10_12__left_right.mp4",
        "Hallway_Full_CW_Run_1_2022_10_12__right.mp4",
    ]
    combined = videos["Aisle_CCW__left_right.mp4"]
    assert combined["frames"] == 12 and combined["cameras"] == ["left", "right"] and combined["duration_seconds"] == 1.2
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=nb_read_frames,codec_name,pix_fmt", "-of", "json", str(out / combined["file"])],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream == {"codec_name": "h264", "pix_fmt": "yuv420p", "nb_read_frames": "12"}  # không chèn/rớt frame
    assert not list(out.glob("*.partial.mp4"))
    # Chạy lại: video đã có không bị ghép lại (cùng nội dung), --only chỉ làm đúng traversal được chọn.
    stamp = (out / "Aisle_CCW__left.mp4").stat().st_mtime_ns
    records = build(tmp_path / "data", out, ["Aisle_CCW"], force=False)
    assert [record.file for record in records] == [
        "Aisle_CCW__left.mp4",
        "Aisle_CCW__right.mp4",
        "Aisle_CCW__left_right.mp4",
    ]
    assert (out / "Aisle_CCW__left.mp4").stat().st_mtime_ns == stamp
    assert records[0].sha256 == videos["Aisle_CCW__left.mp4"]["sha256"]


def test_empty_dataset_reports_failure(tmp_path: Path) -> None:
    assert main(["--dataset-root", str(tmp_path), "--out", str(tmp_path / "out")]) == 1
