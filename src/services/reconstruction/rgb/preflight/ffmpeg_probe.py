"""FFmpeg CLI boundary để đo chất lượng RGB frame có thể lặp lại."""

import json
import math
import re
import statistics
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from src.services.reconstruction.rgb.preflight.quality_models import RGBFrameAsset, RGBQualityProfile

_BLUR_LINE = re.compile(r"lavfi\.blur=([0-9.eE+-]+)")
_LOCAL_MOTION = re.compile(r"\(LM\s+(-?\d+)\s+(-?\d+)\s+")


class FFmpegProbeError(ValueError):
    """RGB không decode được hoặc FFmpeg filter cần thiết thất bại."""


class FFmpegRGBProbe:
    """Wrap FFmpeg có sẵn; không publish symlink sequence tạm."""

    def __init__(self, binary: str = "ffmpeg", timeout_sec: int = 1800) -> None:
        self.binary = binary
        self.timeout_sec = timeout_sec

    def version(self) -> str:
        """Ghi version binary thực tế vào provenance phép đo."""
        return self._run([self.binary, "-version"]).stdout.splitlines()[0]

    def video_info(self, video: Path) -> tuple[int, int, int]:
        """Yêu cầu RGB stream đếm được, không rỗng, dimensions dương."""
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,width,height",
            "-of",
            "json",
            str(video),
        ]
        try:
            streams = json.loads(self._run(command).stdout)["streams"]
            info = tuple(int(streams[0][field]) for field in ("nb_read_frames", "width", "height"))
        except (KeyError, ValueError, TypeError, IndexError, json.JSONDecodeError) as error:
            raise FFmpegProbeError("RGB video stream metadata is invalid") from error
        if len(streams) != 1 or any(value <= 0 for value in info):
            raise FFmpegProbeError("RGB video has no valid counted stream")
        return info

    def video_has_identical_frames(self, video: Path, expected_count: int) -> bool:
        """Decoded frames trùng hệt là tín hiệu static input chắc chắn."""
        command = [
            self.binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            "-threads",
            "1",
            "-i",
            str(video),
            "-map",
            "0:v:0",
            "-vf",
            "format=gray",
            "-f",
            "framemd5",
            "-",
        ]
        lines = [line for line in self._run(command).stdout.splitlines() if line and not line.startswith("#")]
        hashes = [line.rsplit(",", 1)[-1].strip() for line in lines]
        if len(hashes) != expected_count or not all(hashes):
            raise FFmpegProbeError("RGB video decoded-frame inventory is incomplete")
        return len(set(hashes)) == 1

    def video_blur_scores(self, video: Path, profile: RGBQualityProfile) -> list[float]:
        """Decode toàn video qua cùng blur filter đã chuẩn hóa."""
        with tempfile.TemporaryDirectory(prefix="rec02_video_") as temp_name:
            output = Path(temp_name) / "blur.txt"
            filt = self._filter_prefix(profile) + f",format=gray,blurdetect,metadata=print:file={output}"
            self._run(self._video_command(video, filt))
            scores = [float(match) for match in _BLUR_LINE.findall(output.read_text())]
        if not scores or any(not math.isfinite(score) for score in scores):
            raise FFmpegProbeError("RGB video blur probe produced invalid observations")
        return scores

    def video_motion_scores(self, video: Path, profile: RGBQualityProfile) -> list[float | None]:
        """Đo visual transitions theo thứ tự video gốc."""
        with tempfile.TemporaryDirectory(prefix="rec02_video_") as temp_name:
            output = Path(temp_name) / "motion.trf"
            filt = self._filter_prefix(profile) + f",format=yuv420p,vidstabdetect=result={output}"
            self._run(self._video_command(video, filt))
            return [self._line_motion(line) for line in output.read_text().splitlines() if line.startswith("Frame ")]

    def blur_scores(self, frames: tuple[RGBFrameAsset, ...], profile: RGBQualityProfile) -> list[float]:
        """Decode mọi PNG đã chọn ở fixed grayscale resolution."""
        with self._sequence(frames) as (pattern, directory):
            output = directory / "blur.txt"
            filt = self._filter_prefix(profile) + f",format=gray,blurdetect,metadata=print:file={output}"
            self._run(self._command(pattern, filt))
            scores = [float(match) for match in _BLUR_LINE.findall(output.read_text())]
        if len(scores) != len(frames) or any(not math.isfinite(score) for score in scores):
            raise FFmpegProbeError("RGB blur probe did not decode every selected frame")
        return scores

    def motion_scores(self, frames: tuple[RGBFrameAsset, ...], profile: RGBQualityProfile) -> list[float | None]:
        """Đo median local translation của từng cặp frame liên tiếp."""
        with self._sequence(frames) as (pattern, directory):
            output = directory / "motion.trf"
            filt = self._filter_prefix(profile) + f",format=yuv420p,vidstabdetect=result={output}"
            self._run(self._command(pattern, filt))
            scores = [self._line_motion(line) for line in output.read_text().splitlines() if line.startswith("Frame ")]
        if len(scores) != len(frames):
            raise FFmpegProbeError("RGB motion probe did not return every selected frame")
        return scores

    @staticmethod
    def _filter_prefix(profile: RGBQualityProfile) -> str:
        if profile.measurement_orientation == "fit_oriented_bounds":
            return (
                "scale=w='if(gte(dar,1),min(iw,"
                f"{profile.measurement_width}),min(iw,{profile.measurement_height}))':"
                "h='if(gte(dar,1),min(ih,"
                f"{profile.measurement_height}),min(ih,{profile.measurement_width}))':"
                "force_original_aspect_ratio=decrease:force_divisible_by=2:flags=bicubic"
            )
        return f"scale={profile.measurement_width}:{profile.measurement_height}:flags=bicubic"

    def _command(self, pattern: Path, filt: str) -> list[str]:
        return [
            self.binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-framerate",
            "10",
            "-start_number",
            "0",
            "-i",
            str(pattern),
            "-vf",
            filt,
            "-f",
            "null",
            "-",
        ]

    def _video_command(self, video: Path, filt: str) -> list[str]:
        """Diagnostic pass không sample hoặc drop frame."""
        return [
            self.binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-i",
            str(video),
            "-map",
            "0:v:0",
            "-vf",
            filt,
            "-f",
            "null",
            "-",
        ]

    @staticmethod
    def _line_motion(line: str) -> float | None:
        vectors = [(int(dx), int(dy)) for dx, dy in _LOCAL_MOTION.findall(line)]
        if not vectors:
            return None
        return math.hypot(statistics.median(dx for dx, _ in vectors), statistics.median(dy for _, dy in vectors))

    @staticmethod
    @contextmanager
    def _sequence(frames: tuple[RGBFrameAsset, ...]) -> Iterator[tuple[Path, Path]]:
        if not frames or any(frame.path.suffix.lower() != ".png" for frame in frames):
            raise FFmpegProbeError("RGB frame probe requires a nonempty PNG sequence")
        with tempfile.TemporaryDirectory(prefix="rec02_probe_") as temp_name:
            directory = Path(temp_name)
            for index, frame in enumerate(frames):
                (directory / f"{index:06d}.png").symlink_to(frame.path.resolve())
            yield directory / "%06d.png", directory

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=self.timeout_sec)
        except FileNotFoundError as error:
            raise FFmpegProbeError("FFmpeg/ffprobe executable is unavailable") from error
        except subprocess.TimeoutExpired as error:
            raise FFmpegProbeError("FFmpeg RGB probe timed out") from error
        if result.returncode:
            raise FFmpegProbeError(f"FFmpeg RGB probe failed (exit {result.returncode})")
        return result
