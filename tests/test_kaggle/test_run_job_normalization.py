import subprocess
from pathlib import Path

import pytest

from scripts.kaggle.run_job import RunError, fit_video_dimensions, normalize_video


def test_fit_video_dimensions_landscape():
    # 4K landscape -> 1080p
    assert fit_video_dimensions(3840, 2160, "1080p") == (1920, 1080)
    # 1080p landscape -> 720p
    assert fit_video_dimensions(1920, 1080, "720p") == (1280, 720)
    # 720p with 1080p preset does not upscale
    assert fit_video_dimensions(1280, 720, "1080p") == (1280, 720)


def test_fit_video_dimensions_portrait():
    # 4K portrait -> 1080p preset
    assert fit_video_dimensions(2160, 3840, "1080p") == (1080, 1920)
    # 1080p portrait -> 720p preset
    assert fit_video_dimensions(1080, 1920, "720p") == (720, 1280)


def test_fit_video_dimensions_invalid_preset():
    with pytest.raises(ValueError, match="Preset không hợp lệ"):
        fit_video_dimensions(1920, 1080, "4k")


def test_normalize_video_synthetic(tmp_path: Path):
    # Tạo video test 60fps có audio
    raw_video = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=640x360:rate=60",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(raw_video),
        ],
        check=True,
    )
    assert raw_video.is_file()

    # Chuẩn hóa
    norm_path = normalize_video(raw_video, preset="720p")
    assert norm_path.is_file()
    assert norm_path.name == "sample_normalized.mp4"
    assert norm_path != raw_video

    # Kiểm tra metadata của file chuẩn hóa
    probe = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "csv=p=0",
            str(norm_path),
        ],
        text=True,
    ).strip()
    width, height, fps = probe.split(",")
    # 640x360 không bị upscale với preset 720p
    assert int(width) == 640
    assert int(height) == 360
    assert fps == "30/1"

    # Kiểm tra audio bị loại bỏ
    audio_probe = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(norm_path),
        ],
        text=True,
    ).strip()
    assert audio_probe == ""

    # Tái sử dụng file đã chuẩn hóa nếu không force
    reused = normalize_video(raw_video, preset="720p", force=False)
    assert reused == norm_path


def test_normalize_video_nonexistent(tmp_path: Path):
    missing = tmp_path / "does_not_exist.mp4"
    with pytest.raises(RunError, match="Video không tồn tại"):
        normalize_video(missing)
