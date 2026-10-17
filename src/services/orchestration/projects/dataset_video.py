"""Create a replay-only MP4 from an ordered dataset image sequence."""

import json
import subprocess
import tempfile
from pathlib import Path


def _concat_quote(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "'\\''") + "'"


def compose_display_video(images: tuple[Path, ...], output: Path, *, ffmpeg: str = "ffmpeg") -> int:
    """Encode ordered JPG/PNG inputs at 3 fps; return encoded frame count."""
    if len(images) < 2 or any(
        not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"} for path in images
    ):
        raise ValueError("video composition needs at least two existing JPG/JPEG/PNG images")
    if output.exists():
        raise FileExistsError(f"display video already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="t045_concat_") as directory:
        concat = Path(directory) / "images.txt"
        rows = [f"file {_concat_quote(path)}\nduration 0.333333333333\n" for path in images]
        rows.append(f"file {_concat_quote(images[-1])}\n")
        concat.write_text("".join(rows), encoding="utf-8")
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-vf",
            "scale=min(1920\\,iw):min(1920\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-r",
            "3",
            "-frames:v",
            str(len(images)),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"ffmpeg display-video encode failed: {result.stderr.strip()}")
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode:
        raise RuntimeError(f"ffprobe display-video verification failed: {probe.stderr.strip()}")
    try:
        count = int(json.loads(probe.stdout)["streams"][0]["nb_read_frames"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("ffprobe did not report an encoded frame count") from error
    if count != len(images):
        raise RuntimeError(f"display video contains {count} frames; expected {len(images)}")
    return count
