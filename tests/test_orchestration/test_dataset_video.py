import json
import subprocess
from pathlib import Path

import pytest

from src.services.orchestration.projects.dataset_video import compose_display_video


def test_composes_ordered_image_sequence_as_small_h264_video(tmp_path: Path) -> None:
    images = []
    for index, color in enumerate(("red", "green", "blue")):
        image = tmp_path / f"{index:03d}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color={color}:s=2200x1000",
                "-frames:v",
                "1",
                str(image),
            ],
            check=True,
        )
        images.append(image)
    output = tmp_path / "display.mp4"
    assert compose_display_video(tuple(images), output) == len(images)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height,avg_frame_rate,nb_read_frames",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    assert stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p"
    assert max(stream["width"], stream["height"]) <= 1920
    assert stream["avg_frame_rate"] == "3/1" and int(stream["nb_read_frames"]) == len(images)


def test_composition_rejects_missing_or_unsupported_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least two"):
        compose_display_video((tmp_path / "missing.jpg",), tmp_path / "out.mp4")
