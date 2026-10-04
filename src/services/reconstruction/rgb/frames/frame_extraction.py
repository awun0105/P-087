"""REC-02A: FFmpeg decode hoặc đóng gói RGB refs thành frame set bất biến."""

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.models.contracts.artifacts import ArtifactDataClass, Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import ExecutionError, InputFile, InputManifest, StageArtifact, StageId, StageStatus
from src.services.reconstruction.rgb.frames.frame_set import NormalizedRGBFrame, NormalizedRGBFrameSet, _sha256
from src.services.reconstruction.rgb.preflight.privacy import PrivacyDispatchProof, RGBPrivacyGate
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.preflight.quality_models import RGBFrameQuality, RGBQualityReport


class ExtractionConfig(ContractModel):
    """Policy explicit; `all_frames` không tự chèn/rớt frame theo FPS.

    `quality_accepted_stride` chỉ dành cho video: giữ mỗi frame thứ `frame_stride`
    trong các frame đã qua quality, để video 30fps không đổ hàng nghìn ảnh gần
    trùng vào COLMAP. `quality_sharpest_window` chia frame đã qua quality thành cửa
    sổ `frame_stride` frame liên tiếp và giữ frame nét nhất (blur_score thấp nhất,
    theo `blurdetect`: điểm cao = nhòe). Stride nằm trong config nên được bind qua checksum.
    """

    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["image_refs", "video_decode"]
    sampling_policy: Literal["quality_accepted", "quality_accepted_stride", "quality_sharpest_window"]
    timestamp_policy: Literal["source_timestamp", "source_pts"]
    frame_stride: int | None = Field(default=None, ge=2)
    config_checksum: Checksum

    @model_validator(mode="after")
    def _validate_policy(self) -> "ExtractionConfig":
        if self.mode == "image_refs":
            allowed = {("quality_accepted", "source_timestamp")}
        else:
            allowed = {
                ("quality_accepted", "source_pts"),
                ("quality_accepted_stride", "source_pts"),
                ("quality_sharpest_window", "source_pts"),
            }
        if (self.sampling_policy, self.timestamp_policy) not in allowed:
            raise ValueError("extraction mode and sampling/timestamp policy mismatch")
        strided = self.sampling_policy in {"quality_accepted_stride", "quality_sharpest_window"}
        if strided != (self.frame_stride is not None):
            raise ValueError("frame_stride is required exactly for strided sampling policies")
        # Bỏ field None khỏi identity: config cũ (chưa có stride) giữ nguyên checksum.
        identity = self.model_dump(mode="json", exclude_none=True)
        if canonical_content_checksum(identity, "config_checksum") != self.config_checksum:
            raise ValueError("extraction config checksum mismatch")
        return self


@dataclass(frozen=True)
class FrameExtractionRequest:
    """Input đã có REC-02 evidence; timestamp map đến từ source inventory."""

    manifest: InputManifest
    quality: RGBQualityReport
    privacy: PrivacyDispatchProof
    config: ExtractionConfig
    job_id: str
    timestamps: dict[int, str] | None = None


@dataclass(frozen=True)
class FrameExtractionResult:
    """Artifact published cùng stage record; không có false success."""

    frame_set: NormalizedRGBFrameSet
    reference: ProductArtifactRef
    stage: StageArtifact


@dataclass(frozen=True)
class FrameExtractionDependencies:
    """Process/storage/privacy dependencies được inject ở composition root."""

    writer: ArtifactWriter
    resolve_input: Callable[[str], Path]
    gate: RGBPrivacyGate
    decoder: "FFmpegFrameDecoder"


@dataclass(frozen=True)
class VideoDecodeResult:
    """Temporary decoded sequence cùng original PTS, chỉ sống trong stage."""

    images: tuple[Path, ...]
    timestamps: list[str]
    source_checksum: str


@dataclass(frozen=True)
class _ImageCandidate:
    file: InputFile
    quality: RGBFrameQuality
    timestamp: str


@dataclass(frozen=True)
class _ArtifactSpec:
    job_id: str
    path: str
    kind: str


@dataclass(frozen=True)
class FrameExtractionError(ValueError):
    """Lỗi stage có mã và remediation để worker ghi lại."""

    code: str
    message: str
    action: str

    def __str__(self) -> str:
        return self.message

    def to_execution_error(self) -> ExecutionError:
        """Translate to shared stage failure contract."""
        return ExecutionError(
            error_code=self.code,
            stage_id=StageId.FRAME_EXTRACT,
            human_message=self.message,
            retryable=False,
            details={"action": self.action},
        )

    def to_failed_stage(self) -> StageArtifact:
        """Worker có thể ghi FAIL mà không phát hành success artifact."""
        return StageArtifact(
            stage_id=StageId.FRAME_EXTRACT,
            status=StageStatus.FAILED,
            completed_at=datetime.now(UTC),
            error=self.to_execution_error(),
        )


class FFmpegFrameDecoder:
    """Một process boundary FFmpeg/ffprobe, không giữ private state của tool."""

    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def version(self) -> str:
        """Version thực tế thuộc provenance của frame set."""
        return self._run([self.ffmpeg, "-version"]).stdout.splitlines()[0]

    def timestamps(self, video: Path) -> list[str]:
        """Frame presentation timestamps của decoded video theo thứ tự output."""
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(video),
        ]
        try:
            frames = json.loads(self._run(command).stdout)["frames"]
            values = [frame["best_effort_timestamp_time"] for frame in frames]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise FrameExtractionError(
                "FRAME_PTS_INVALID", "Video has invalid frame timestamps", "Provide a video with ordered PTS"
            ) from error
        if len(values) < 2:
            raise FrameExtractionError(
                "FRAME_COUNT_INVALID", "Video has fewer than two decoded frames", "Provide more RGB frames"
            )
        return values

    def decode(self, video: Path, output: Path, frame_ids: list[int] | None = None) -> tuple[Path, ...]:
        """Giải mã một lần; `frame_ids` (tăng dần) → chỉ ghi các frame đó, theo đúng thứ tự.

        Chọn frame bằng filter `select` trong script file để video dài không phải
        ghi hàng chục nghìn PNG tạm ra đĩa. Không dùng `-y` hay xóa output cũ.
        """
        selection: list[str] = []
        if frame_ids is not None:
            if not frame_ids or frame_ids != sorted(set(frame_ids)) or frame_ids[0] < 0:
                raise FrameExtractionError(
                    "FRAME_SELECTION_INVALID", "Frame selection must be ordered and unique", "Rerun extraction"
                )
            script = output / "select.filter"
            script.write_text("select=" + "+".join(f"eq(n\\,{frame_id})" for frame_id in frame_ids))
            selection = ["-filter_script:v", str(script)]
        command = [
            self.ffmpeg,
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
            *selection,
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgb24",
            "-start_number",
            "0",
            str(output / "%06d.png"),
        ]
        self._run(command)
        return tuple(sorted(output.glob("[0-9][0-9][0-9][0-9][0-9][0-9].png")))

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=1800)
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            raise FrameExtractionError(
                "FFMPEG_UNAVAILABLE", "FFmpeg/ffprobe did not run", "Install and configure FFmpeg"
            ) from error
        if result.returncode:
            raise FrameExtractionError("FFMPEG_FAILED", "FFmpeg/ffprobe failed", "Check RGB input and FFmpeg runtime")
        return result


class RGBFrameExtractor:
    """Đóng gói frame-set; reader/writer inject để giữ core dataset agnostic."""

    def __init__(self, dependencies: FrameExtractionDependencies) -> None:
        self.deps = dependencies

    def execute(self, request: FrameExtractionRequest) -> FrameExtractionResult:
        """Không publish manifest nếu source/quality/privacy thiếu hoặc lệch."""
        try:
            return self._perform(request)
        except FrameExtractionError:
            raise
        except ValueError as error:
            raise FrameExtractionError(
                "FRAME_INVENTORY_INVALID",
                "RGB frame inventory or timestamps are invalid",
                "Check ordered source metadata",
            ) from error
        except (OSError, RuntimeError) as error:
            raise FrameExtractionError(
                "FRAME_IO_FAILED", "RGB frame artifact I/O failed", "Check source and immutable artifact storage"
            ) from error

    def _perform(self, request: FrameExtractionRequest) -> FrameExtractionResult:
        """Thực thi stage sau khi failure boundary đã được đặt."""
        self._validate_request(request)
        version = self.deps.decoder.version()
        if request.config.mode == "image_refs":
            frames = self._image_frames(request)
        else:
            frames = self._video_frames(request)
        frame_set = self._frame_set(request, frames, version)
        payload = frame_set.model_dump_json(indent=2).encode("utf-8") + b"\n"
        ref = self._reference(_ArtifactSpec(request.job_id, "rec02a/frame_set.json", "NormalizedRGBFrameSet"), payload)
        published = ProductArtifactRef.model_validate(self.deps.writer.publish(ref, payload).model_dump())
        stage = StageArtifact(
            stage_id=StageId.FRAME_EXTRACT,
            status=StageStatus.SUCCEEDED,
            artifact_type=ref.artifact_type,
            artifact_uri=ref.artifact_uri,
            artifact_checksum=ref.artifact_checksum,
            data_class=ArtifactDataClass.DERIVED,
            completed_at=datetime.now(UTC),
        )
        return FrameExtractionResult(frame_set, published, stage)

    def _validate_request(self, request: FrameExtractionRequest) -> None:
        try:
            verify_content_checksum(request.manifest, "input_manifest_checksum")
            verify_content_checksum(request.quality, "report_checksum")
            self.deps.gate.require_dispatch(request.manifest, request.privacy)
        except ValueError as error:
            raise FrameExtractionError(
                "FRAME_UPSTREAM_INVALID", "REC-02 evidence is invalid", "Reissue the matching REC-02 evidence"
            ) from error
        if not self._matches_quality_source(request) or request.quality.selected_frame_ids != [
            row.frame_id for row in request.quality.frames
        ]:
            raise FrameExtractionError(
                "FRAME_QUALITY_MISMATCH", "Quality mask belongs to another input", "Use the matching REC-02 report"
            )
        if len(request.quality.effective_reconstruction_frame_ids) < 2:
            raise FrameExtractionError(
                "FRAME_COUNT_INVALID", "Too few accepted RGB frames", "Provide more usable RGB input"
            )
        if not request.job_id or "/" in request.job_id:
            raise FrameExtractionError("FRAME_JOB_INVALID", "Invalid extraction job ID", "Supply a valid job ID")

    @staticmethod
    def _matches_quality_source(request: FrameExtractionRequest) -> bool:
        """Dataset quality có thể bind với preparation manifest đã khai báo."""
        if request.quality.source_manifest_checksum == request.manifest.input_manifest_checksum:
            return True
        provenance = request.manifest.preparation_provenance or {}
        return (
            request.manifest.source_type.value == "dataset"
            and request.config.mode == "image_refs"
            and request.quality.source_manifest_checksum == provenance.get("preparation_manifest_checksum")
            and request.quality.selection_checksum == provenance.get("split_checksum")
        )

    def _image_frames(self, request: FrameExtractionRequest) -> list[NormalizedRGBFrame]:
        files = [file for file in request.manifest.files if file.media_type == "image/png"]
        if len(files) != len(request.quality.frames) or request.timestamps is None:
            raise FrameExtractionError(
                "FRAME_INPUT_MISMATCH", "Image inventory/timestamps are incomplete", "Supply ordered source timestamps"
            )
        expected_ids = set(request.quality.selected_frame_ids)
        if set(request.timestamps) != expected_ids:
            raise FrameExtractionError(
                "FRAME_TIMESTAMP_MISMATCH",
                "Timestamp IDs differ from selected frames",
                "Use the source timestamp inventory",
            )
        rows = []
        for file, quality in zip(files, request.quality.frames, strict=True):
            candidate = _ImageCandidate(file, quality, request.timestamps[quality.frame_id])
            row = self._image_row(request.job_id, candidate)
            if row is not None:
                rows.append(row)
        return rows

    def _image_row(self, job_id: str, candidate: _ImageCandidate) -> NormalizedRGBFrame | None:
        file, quality = candidate.file, candidate.quality
        path = self.deps.resolve_input(file.artifact_uri)
        if not path.is_file() or path.stat().st_size != file.size_bytes or _sha256(path) != file.checksum:
            raise FrameExtractionError(
                "FRAME_SOURCE_CHANGED", "RGB input bytes changed", "Restore the InputManifest source"
            )
        if quality.source_checksum != file.checksum:
            raise FrameExtractionError(
                "FRAME_QUALITY_MISMATCH", "Quality row source checksum differs", "Rerun REC-02 quality"
            )
        if quality.timestamp_sec is not None and quality.timestamp_sec != candidate.timestamp:
            raise FrameExtractionError(
                "FRAME_TIMESTAMP_MISMATCH",
                "Source timestamp differs from REC-02 quality",
                "Use the source timestamp inventory",
            )
        if quality.quality != "accepted":
            return None
        ref = self._source_ref(job_id, file)
        return NormalizedRGBFrame(
            frame_id=quality.frame_id, timestamp_sec=candidate.timestamp, image=ref, source_checksum=file.checksum
        )

    @staticmethod
    def _source_ref(job_id: str, file: InputFile) -> ProductArtifactRef:
        return ProductArtifactRef(
            artifact_type="RGBFrame",
            schema_version="1.0",
            artifact_uri=file.artifact_uri,
            artifact_checksum=file.checksum,
            data_class=file.data_class,
            producer_stage=StageId.INPUT_VALIDATE,
            job_id=job_id,
        )

    def _video_frames(self, request: FrameExtractionRequest) -> list[NormalizedRGBFrame]:
        files = [file for file in request.manifest.files if file.media_type in {"video/mp4", "video/quicktime"}]
        if len(files) != 1 or request.timestamps is not None:
            raise FrameExtractionError(
                "FRAME_INPUT_MISMATCH", "Expected one video and source PTS policy", "Supply one RGB video"
            )
        file = files[0]
        video = self.deps.resolve_input(file.artifact_uri)
        if not video.is_file() or video.stat().st_size != file.size_bytes or _sha256(video) != file.checksum:
            raise FrameExtractionError(
                "FRAME_SOURCE_CHANGED", "RGB video bytes changed", "Restore the InputManifest source"
            )
        if any(row.source_checksum != file.checksum for row in request.quality.frames):
            raise FrameExtractionError(
                "FRAME_QUALITY_MISMATCH", "Video quality source checksum differs", "Rerun REC-02 quality"
            )
        chosen = self._chosen_frames(request)
        with tempfile.TemporaryDirectory(prefix="rec02a_frames_") as directory:
            timestamps = self.deps.decoder.timestamps(video)
            if len(timestamps) != len(request.quality.frames) or request.quality.selected_frame_ids != list(
                range(len(timestamps))
            ):
                raise FrameExtractionError(
                    "FRAME_DECODE_MISMATCH", "Decoded frames differ from REC-02", "Rerun validation on this video"
                )
            images = self.deps.decoder.decode(video, Path(directory), [row.frame_id for row in chosen])
            if len(images) != len(chosen):
                raise FrameExtractionError(
                    "FRAME_DECODE_MISMATCH", "Decoded frames differ from REC-02", "Rerun validation on this video"
                )
            return self._publish_video_frames(request, chosen, VideoDecodeResult(images, timestamps, file.checksum))

    @staticmethod
    def _chosen_frames(request: FrameExtractionRequest) -> list[RGBFrameQuality]:
        """Frame giữ lại theo sampling policy, luôn trong tập đã qua quality."""
        accepted = [row for row in request.quality.frames if row.quality == "accepted"]
        stride = request.config.frame_stride or 1
        if request.config.sampling_policy == "quality_sharpest_window":
            windows = (accepted[index : index + stride] for index in range(0, len(accepted), stride))
            return [min(window, key=lambda row: (row.blur_score, row.frame_id)) for window in windows]
        return accepted[::stride]

    def _publish_video_frames(
        self, request: FrameExtractionRequest, chosen: list[RGBFrameQuality], decoded: VideoDecodeResult
    ) -> list[NormalizedRGBFrame]:
        rows = []
        for quality, image in zip(chosen, decoded.images, strict=True):
            frame_id = quality.frame_id
            payload = image.read_bytes()
            ref = self._reference(
                _ArtifactSpec(request.job_id, f"rec02a/frames/{frame_id:06d}.png", "RGBFrame"), payload
            )
            published = ProductArtifactRef.model_validate(self.deps.writer.publish(ref, payload).model_dump())
            rows.append(
                NormalizedRGBFrame(
                    frame_id=frame_id,
                    timestamp_sec=decoded.timestamps[frame_id],
                    image=published,
                    source_checksum=decoded.source_checksum,
                )
            )
        return rows

    @staticmethod
    def _frame_set(
        request: FrameExtractionRequest, frames: list[NormalizedRGBFrame], version: str
    ) -> NormalizedRGBFrameSet:
        timestamp_identity = {str(frame.frame_id): frame.timestamp_sec for frame in frames}
        digest = hashlib.sha256(json.dumps(timestamp_identity, sort_keys=True).encode()).hexdigest()
        payload = dict(
            schema_version="1.0",
            input_manifest_checksum=request.manifest.input_manifest_checksum,
            quality_report_checksum=request.quality.report_checksum,
            privacy_report_checksum=request.privacy.report.report_checksum,
            selection_checksum=request.quality.selection_checksum,
            timestamp_inventory_checksum="sha256:" + digest,
            extraction_config_checksum=request.config.config_checksum,
            ffmpeg_version=version,
            frames=[frame.model_dump(mode="json") for frame in frames],
            frame_set_checksum="sha256:" + "0" * 64,
        )
        payload["frame_set_checksum"] = canonical_content_checksum(payload, "frame_set_checksum")
        return NormalizedRGBFrameSet.model_validate(payload)

    @staticmethod
    def _reference(spec: _ArtifactSpec, payload: bytes) -> ProductArtifactRef:
        return ProductArtifactRef(
            artifact_type=spec.kind,
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{spec.job_id}/{spec.path}",
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.FRAME_EXTRACT,
            job_id=spec.job_id,
        )
