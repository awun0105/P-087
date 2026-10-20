"""Chọn RGB theo input quality; SfM viability do REC-03 quyết định."""

import hashlib
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import ExecutionError, StageId
from src.models.contracts.retryability import classify_retryability
from src.services.reconstruction.rgb.preflight.ffmpeg_probe import FFmpegProbeError, FFmpegRGBProbe
from src.services.reconstruction.rgb.preflight.quality_models import (
    RGBFrameAsset,
    RGBFrameQuality,
    RGBMotionDiagnostics,
    RGBQualityProfile,
    RGBQualityReport,
)


@dataclass(frozen=True)
class RGBQualityRequest:
    """Reconstruction assets cùng source/selection identities bất biến."""

    frames: tuple[RGBFrameAsset, ...]
    source_manifest_checksum: str
    selection_checksum: str
    profile: RGBQualityProfile


@dataclass(frozen=True)
class RGBVideoRequest:
    """Video mp4/mov đã resolve, gắn InputManifest và source bytes."""

    path: Path
    checksum: str
    size_bytes: int
    source_manifest_checksum: str
    profile: RGBQualityProfile


@dataclass(frozen=True)
class _VideoPasses:
    """Bốn lượt decode toàn video đang chạy song song."""

    info: "Future[tuple[int, int, int]]"
    hashes: "Future[list[str]]"
    blur: "Future[list[float]]"
    motion: "Future[list[float | None]]"


@dataclass(frozen=True)
class _ReportParts:
    rows: list[RGBFrameQuality]
    diagnostics: RGBMotionDiagnostics
    version: str


@dataclass(frozen=True)
class RGBValidationError(ValueError):
    """Lỗi input có mã và cách xử lý rõ ràng."""

    code: str
    message: str
    action: str

    def __str__(self) -> str:
        return self.message

    def to_execution_error(self) -> ExecutionError:
        """Map lỗi validation sang shared worker error contract."""
        details = {"action": self.action}
        return ExecutionError(
            error_code=self.code,
            stage_id=StageId.INPUT_VALIDATE,
            human_message=str(self),
            retryable=classify_retryability(self.code, details),
            details=details,
        )


class RGBQualityValidator:
    """Verify source bytes, áp blur mask rồi đo motion của sequence."""

    def __init__(self, probe: FFmpegRGBProbe) -> None:
        self.probe = probe

    def validate(self, request: RGBQualityRequest) -> RGBQualityReport:
        """Tạo report có checksum, không sửa canonical RGB input."""
        self._verify_sources(request.frames)
        try:
            blur = self.probe.blur_scores(request.frames, request.profile)
        except FFmpegProbeError as error:
            raise RGBValidationError(
                "RGB_DECODE_FAILED", "RGB frames cannot be decoded", "Replace corrupt/unsupported RGB frames and retry"
            ) from error
        rows = self._quality_rows(request, blur)
        effective = tuple(frame for frame, row in zip(request.frames, rows, strict=True) if row.quality == "accepted")
        if len(effective) < 2:
            raise RGBValidationError(
                "RGB_TOO_FEW_USABLE_FRAMES",
                "Fewer than two RGB frames remain",
                "Provide more decodable reconstruction frames",
            )
        motion_failed = False
        try:
            motion = self.probe.motion_scores(effective, request.profile)
        except FFmpegProbeError:
            motion = [None] * len(effective)
            motion_failed = True
        version = self.probe.version()
        updated = self._with_motion(rows, effective, motion)
        diagnostics = self._diagnostics(effective, motion, request.profile)
        if motion_failed:
            diagnostics.warnings.append("MOTION_PROBE_FAILED")
        return self._report(request, _ReportParts(updated, diagnostics, version))

    def validate_video(self, video: RGBVideoRequest) -> RGBQualityReport:
        """Probe video gốc; REC-02A sở hữu published frame extraction.

        Bốn lượt decode toàn video (đếm frame, MD5, blur, motion) độc lập nhau và mỗi lượt chỉ dùng một luồng để
        kết quả ổn định, nên chạy cùng lúc: video 5 phút mất thời gian của lượt chậm nhất thay vì tổng cả bốn.
        Lỗi vẫn được báo theo đúng thứ tự cũ.
        """
        self._verify_video(video)
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="rec02-video") as pool:
            passes = _VideoPasses(
                info=pool.submit(self.probe.video_info, video.path),
                hashes=pool.submit(self.probe.video_frame_hashes, video.path),
                blur=pool.submit(self.probe.video_blur_scores, video.path, video.profile),
                motion=pool.submit(self.probe.video_motion_scores, video.path, video.profile),
            )
            blur = self._decode_video(passes)
            count = len(blur)
            frames = tuple(RGBFrameAsset(i, video.path, video.checksum) for i in range(count))
            request = RGBQualityRequest(frames, video.source_manifest_checksum, video.checksum, video.profile)
            rows = self._quality_rows(request, blur)
            effective = tuple(frame for frame, row in zip(frames, rows, strict=True) if row.quality == "accepted")
            if len(effective) < 2:
                raise RGBValidationError(
                    "RGB_TOO_FEW_USABLE_FRAMES", "Fewer than two RGB frames remain", "Provide more decodable RGB frames"
                )
            motion, motion_failed = self._video_motion(passes.motion, count)
        selected_motion = [motion[frame.frame_id] for frame in effective]
        updated = self._with_motion(rows, effective, selected_motion)
        diagnostics = self._diagnostics(effective, selected_motion, video.profile)
        if motion_failed:
            diagnostics.warnings.append("MOTION_PROBE_FAILED")
        return self._report(request, _ReportParts(updated, diagnostics, self.probe.version()))

    @staticmethod
    def _decode_video(passes: "_VideoPasses") -> list[float]:
        """Full decode, frame count và exact-static là structural gates."""
        try:
            count, _, _ = passes.info.result()
            hashes = passes.hashes.result()
            if len(hashes) != count:
                raise FFmpegProbeError("RGB video decoded-frame inventory is incomplete")
            if len(set(hashes)) == 1:
                raise RGBValidationError(
                    "RGB_STATIC_SEQUENCE", "All decoded RGB frames are identical", "Provide a moving-camera RGB video"
                )
            blur = passes.blur.result()
        except FFmpegProbeError as error:
            raise RGBValidationError(
                "RGB_DECODE_FAILED", "RGB video cannot be fully decoded", "Provide a supported, complete mp4/mov video"
            ) from error
        if count != len(blur) or count < 2:
            raise RGBValidationError(
                "RGB_DECODE_COUNT_MISMATCH",
                "RGB decoded frame count differs from metadata",
                "Replace corrupt/incomplete RGB video",
            )
        return blur

    @staticmethod
    def _verify_video(video: RGBVideoRequest) -> None:
        if video.path.suffix.lower() not in {".mp4", ".mov"}:
            raise RGBValidationError(
                "RGB_FORMAT_UNSUPPORTED", "RGB video format is unsupported", "Provide mp4 or mov input"
            )
        if not video.path.is_file() or video.path.stat().st_size != video.size_bytes or video.size_bytes == 0:
            raise RGBValidationError(
                "RGB_SOURCE_MISSING", "RGB video is missing or changed", "Restore the immutable input bytes"
            )
        if _sha256_file(video.path) != video.checksum:
            raise RGBValidationError(
                "RGB_CHECKSUM_MISMATCH",
                "RGB video checksum changed",
                "Restore the immutable input or create a new InputManifest",
            )

    @staticmethod
    def _video_motion(pending: "Future[list[float | None]]", count: int) -> tuple[list[float | None], bool]:
        try:
            scores = pending.result()
        except FFmpegProbeError:
            return [None] * count, True
        return (scores, False) if len(scores) == count else ([None] * count, True)

    @staticmethod
    def _verify_sources(frames: tuple[RGBFrameAsset, ...]) -> None:
        ids = [frame.frame_id for frame in frames]
        if len(frames) < 2 or ids != sorted(set(ids)) or any(item < 0 for item in ids):
            raise RGBValidationError(
                "RGB_SEQUENCE_INVALID",
                "RGB frame IDs must be unique and ordered",
                "Supply at least two ordered reconstruction frames",
            )
        for frame in frames:
            if not frame.path.is_file() or frame.path.stat().st_size == 0:
                raise RGBValidationError(
                    "RGB_SOURCE_MISSING", "RGB source frame is missing or empty", "Restore the referenced source bytes"
                )
            if frame.size_bytes is not None and frame.path.stat().st_size != frame.size_bytes:
                raise RGBValidationError(
                    "RGB_SIZE_MISMATCH", "RGB source size differs from InputManifest", "Restore immutable source bytes"
                )
            if _sha256_file(frame.path) != frame.checksum:
                raise RGBValidationError(
                    "RGB_CHECKSUM_MISMATCH",
                    "RGB source checksum changed",
                    "Restore the immutable input or create a new input manifest",
                )
        if len({frame.checksum for frame in frames}) == 1:
            raise RGBValidationError(
                "RGB_STATIC_SEQUENCE", "All RGB frames are byte-identical", "Provide a moving-camera RGB sequence"
            )

    @staticmethod
    def _quality_rows(request: RGBQualityRequest, scores: list[float]) -> list[RGBFrameQuality]:
        rows = []
        for frame, score in zip(request.frames, scores, strict=True):
            excluded = request.profile.blur_exclude_gt is not None and score > request.profile.blur_exclude_gt
            rows.append(
                RGBFrameQuality(
                    frame_id=frame.frame_id,
                    source_checksum=frame.checksum,
                    timestamp_sec=frame.timestamp_sec,
                    blur_score=score,
                    quality="excluded" if excluded else "accepted",
                    reasons=["blur"] if excluded else [],
                )
            )
        return rows

    @staticmethod
    def _with_motion(
        rows: list[RGBFrameQuality], frames: tuple[RGBFrameAsset, ...], scores: list[float | None]
    ) -> list[RGBFrameQuality]:
        if len(frames) != len(scores):
            raise RGBValidationError(
                "RGB_MOTION_COUNT_MISMATCH",
                "Motion observations are incomplete",
                "Rerun preflight with a complete RGB sequence",
            )
        mapped = {
            frame.frame_id: score if index and frame.frame_id == frames[index - 1].frame_id + 1 else None
            for index, (frame, score) in enumerate(zip(frames, scores, strict=True))
        }
        return [
            row.model_copy(update={"motion_px": mapped[row.frame_id]}) if row.frame_id in mapped else row
            for row in rows
        ]

    @staticmethod
    def _diagnostics(
        frames: tuple[RGBFrameAsset, ...], scores: list[float | None], profile: RGBQualityProfile
    ) -> RGBMotionDiagnostics:
        observed = [
            (frame.frame_id, score)
            for index, (frame, score) in enumerate(zip(frames, scores, strict=True))
            if index and frame.frame_id == frames[index - 1].frame_id + 1 and score is not None
        ]
        values = [score for _, score in observed]
        active = sum(score > profile.active_transition_px_gt for score in values)
        ratio = active / len(values) if values else None
        static_run = _max_static_run(observed, profile.active_transition_px_gt)
        gaps = [right.frame_id - left.frame_id - 1 for left, right in zip(frames, frames[1:], strict=False)]
        p90 = _quantile(values, 0.9) if values else None
        p95 = _quantile(values, 0.95) if values else None
        warnings = _motion_warnings(ratio, static_run, profile)
        if any(score is None for score in scores[1:]):
            warnings.append("MOTION_ESTIMATE_INCOMPLETE")
        return RGBMotionDiagnostics(
            observed_transition_count=len(values),
            active_transition_count=active,
            active_ratio=ratio,
            max_static_run=static_run,
            max_selection_gap=max(gaps, default=0),
            motion_p90_px=p90,
            motion_p95_px=p95,
            fast_transition_frame_ids=[i for i, score in observed if score > p95] if p95 is not None else [],
            warnings=warnings,
        )

    @staticmethod
    def _report(request: RGBQualityRequest, parts: _ReportParts) -> RGBQualityReport:
        rows = parts.rows
        payload = {
            "schema_version": "1.0",
            "source_manifest_checksum": request.source_manifest_checksum,
            "selection_checksum": request.selection_checksum,
            "profile_checksum": request.profile.profile_checksum,
            "ffmpeg_version": parts.version,
            "producer_version": "rec02-preflight-v1",
            "selected_frame_ids": [row.frame_id for row in rows],
            "effective_reconstruction_frame_ids": [row.frame_id for row in rows if row.quality == "accepted"],
            "excluded_frame_ids": [row.frame_id for row in rows if row.quality == "excluded"],
            "frames": [row.model_dump(mode="json") for row in rows],
            "motion": parts.diagnostics.model_dump(mode="json"),
            "report_checksum": "sha256:" + "0" * 64,
        }
        payload["report_checksum"] = canonical_content_checksum(payload, "report_checksum")
        return RGBQualityReport.model_validate(payload)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (position - low)


def _max_static_run(observed: list[tuple[int, float]], floor: float) -> int:
    longest = current = 0
    previous = None
    for frame_id, score in observed:
        current = current + 1 if score <= floor and previous == frame_id - 1 else int(score <= floor)
        longest = max(longest, current)
        previous = frame_id
    return longest


def _motion_warnings(ratio: float | None, static_run: int, profile: RGBQualityProfile) -> list[str]:
    warnings = []
    if ratio is None:
        warnings.append("NO_ADJACENT_MOTION_OBSERVATIONS")
    elif profile.warn_active_ratio_lt is not None and ratio < profile.warn_active_ratio_lt:
        warnings.append("ACTIVE_RATIO_BELOW_REFERENCE")
    if profile.warn_static_run_gt is not None and static_run > profile.warn_static_run_gt:
        warnings.append("STATIC_RUN_ABOVE_REFERENCE")
    return warnings
