"""Server verification for a prepared MP4 and its bounded output→source map."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.video_preparation import (
    ClientVideoPreparationManifest,
    PositiveRational,
    ServerVideoPreparationVerification,
    VideoColorMetadata,
    VideoFrameBinding,
    VideoStreamMetadata,
    default_video_normalization_profile,
    validate_video_frame_map_rows,
)
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.uploads.models import UploadRecord


class VideoPreparationVerificationError(ValueError):
    """The received video or mapping does not match the declared preparation."""


class ServerVideoPreparationVerifier:
    """Verify server-received bytes and publish a checksummed map without retaining it in RAM."""

    def __init__(self, resolver: ArtifactResolver, ffprobe: str = "ffprobe") -> None:
        self.resolver = resolver
        self.ffprobe = ffprobe

    def verify_and_publish(
        self,
        upload: UploadRecord,
        manifest: ClientVideoPreparationManifest,
        frame_map_path: Path,
    ) -> ServerVideoPreparationVerification:
        if upload.input_kind != "rgb_video" or upload.media_type != "video/mp4":
            raise VideoPreparationVerificationError("Prepared video must be a server-recognized MP4 RGB upload")
        if upload.checksum != manifest.prepared_file.checksum or upload.size_bytes != manifest.prepared_file.size_bytes:
            raise VideoPreparationVerificationError("Prepared video digest or size differs from the received upload")
        if frame_map_path.stat().st_size != manifest.frame_map.size_bytes:
            raise VideoPreparationVerificationError("Video frame-map byte size differs from its descriptor")
        with frame_map_path.open("rb") as frame_map_stream:
            digest = "sha256:" + hashlib.file_digest(frame_map_stream, "sha256").hexdigest()
        if digest != manifest.frame_map.checksum:
            raise VideoPreparationVerificationError("Video frame-map checksum differs from its descriptor")

        source_ref = ProductArtifactRef(
            artifact_type="UploadedVideo",
            schema_version="1.0",
            artifact_uri=upload.artifact_uri,
            artifact_checksum=upload.checksum,
            data_class=ArtifactDataClass.PRODUCT_INPUT,
            producer_stage=StageId.INPUT_VALIDATE,
            job_id=upload.upload_id,
        )
        video_path = self.resolver.require(source_ref)
        if not video_path.is_file() or video_path.stat().st_size != upload.size_bytes:
            raise VideoPreparationVerificationError("Server could not resolve the exact uploaded video bytes")
        with video_path.open("rb") as video_stream:
            video_digest = "sha256:" + hashlib.file_digest(video_stream, "sha256").hexdigest()
        if video_digest != upload.checksum:
            raise VideoPreparationVerificationError("Server upload bytes changed after receipt")

        observed = self._probe(video_path)
        if not self._matches_prepared_stream(observed, manifest.prepared_video):
            raise VideoPreparationVerificationError("Server-observed MP4 stream differs from the preparation manifest")

        profile = default_video_normalization_profile()
        pts_stream = self._presentation_pts(video_path)
        try:
            with frame_map_path.open("rb") as frame_map_stream:
                checked_rows = self._checked_rows(frame_map_stream, pts_stream, manifest)
                validate_video_frame_map_rows(
                    checked_rows,
                    descriptor=manifest.frame_map,
                    source_frame_count=manifest.source_video.frame_count,
                    output_frame_count=observed.frame_count,
                    max_sidecar_bytes=profile.max_frame_map_bytes,
                )
                if next(pts_stream, None) is not None:
                    raise VideoPreparationVerificationError("Frame map omits one or more server-decoded video frames")
        except (ValidationError, UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            if isinstance(error, VideoPreparationVerificationError):
                raise
            raise VideoPreparationVerificationError(f"Video frame map is invalid: {error}") from error
        finally:
            close_pts = getattr(pts_stream, "close", None)
            if close_pts is not None:
                close_pts()

        map_ref = ProductArtifactRef(
            artifact_type="VideoFrameMap",
            schema_version="1.0",
            artifact_uri=(
                f"artifact://jobs/{upload.upload_id}/input/video_frame_map_"
                f"{manifest.frame_map.checksum.removeprefix('sha256:')}.jsonl"
            ),
            artifact_checksum=manifest.frame_map.checksum,
            data_class=ArtifactDataClass.PRODUCT_INPUT,
            producer_stage=StageId.INPUT_VALIDATE,
            job_id=upload.upload_id,
        )
        existing = self.resolver.locate(map_ref.artifact_uri)
        if existing is None:
            FilesystemArtifactStore(self.resolver).publish(map_ref, frame_map_path.read_bytes())
        elif not existing.is_file() or self._sha256_file(existing) != map_ref.artifact_checksum:
            raise VideoPreparationVerificationError("An immutable frame-map artifact already exists with other bytes")

        payload: dict[str, object] = {
            "schema_version": "1.0",
            "status": "server_verified",
            "uploaded_checksum": upload.checksum,
            "uploaded_size_bytes": upload.size_bytes,
            "client_manifest": manifest.model_dump(mode="json"),
            "observed_video": observed.model_dump(mode="json"),
            "frame_map_ref": map_ref.model_dump(mode="json"),
            "original_source_status": "client_declared_unverified",
            "verification_checksum": "sha256:" + "0" * 64,
        }
        from src.models.contracts.identity import canonical_content_checksum

        payload["verification_checksum"] = canonical_content_checksum(payload, "verification_checksum")
        return ServerVideoPreparationVerification.model_validate(payload)

    def _probe(self, video: Path) -> VideoStreamMetadata:
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,sample_aspect_ratio,time_base,start_pts,duration_ts,avg_frame_rate,nb_read_frames,color_primaries,color_transfer,color_space,color_range:stream_side_data=rotation:stream_tags=rotate",
            "-of",
            "json",
            str(video),
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=False, timeout=600)
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            raise VideoPreparationVerificationError("Server ffprobe could not inspect the prepared video") from error
        if result.returncode:
            raise VideoPreparationVerificationError("Server ffprobe rejected the prepared video")
        try:
            streams = json.loads(result.stdout)["streams"]
            video_stream = next(stream for stream in streams if stream["codec_type"] == "video")
            width, height = int(video_stream["width"]), int(video_stream["height"])
            sample_aspect = self._rational(video_stream.get("sample_aspect_ratio", "1:1"), ":")
            rotation = self._rotation(video_stream)
            display_width = round(width * sample_aspect.numerator / sample_aspect.denominator)
            display_height = height
            if rotation in {90, 270}:
                display_width, display_height = display_height, display_width
            color_values = {
                "primaries": self._color_value(video_stream.get("color_primaries")),
                "transfer": self._color_value(video_stream.get("color_transfer")),
                "matrix": self._color_value(video_stream.get("color_space")),
                "range": self._color_value(video_stream.get("color_range")),
            }
            color = VideoColorMetadata(**color_values) if any(color_values.values()) else None
            rate = self._optional_rational(video_stream.get("avg_frame_rate"), "/")
            return VideoStreamMetadata(
                codec=str(video_stream["codec_name"]),
                coded_width=width,
                coded_height=height,
                display_width=display_width,
                display_height=display_height,
                sample_aspect_ratio=sample_aspect,
                rotation_degrees=rotation,
                start_pts=int(video_stream["start_pts"]),
                duration_ticks=int(video_stream["duration_ts"]),
                time_base=self._rational(video_stream["time_base"], "/"),
                frame_rate=rate,
                frame_count=int(video_stream["nb_read_frames"]),
                color=color,
                audio_track_count=sum(stream.get("codec_type") == "audio" for stream in streams),
            )
        except (KeyError, StopIteration, TypeError, ValueError, ZeroDivisionError, ValidationError) as error:
            raise VideoPreparationVerificationError("Server ffprobe metadata is incomplete or invalid") from error

    def _presentation_pts(self, video: Path) -> Iterator[int]:
        pts_file = tempfile.TemporaryFile(mode="w+b")
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp",
            "-of",
            "csv=p=0",
            str(video),
        ]
        try:
            result = subprocess.run(command, stdout=pts_file, stderr=subprocess.PIPE, check=False, timeout=1800)
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            pts_file.close()
            raise VideoPreparationVerificationError(
                "Server could not read prepared video presentation timestamps"
            ) from error
        if result.returncode:
            pts_file.close()
            raise VideoPreparationVerificationError("Server could not decode prepared video presentation timestamps")
        pts_file.seek(0)

        def values() -> Iterator[int]:
            try:
                for line in pts_file:
                    try:
                        yield int(line.decode("ascii").strip().split(",", 1)[0])
                    except (UnicodeDecodeError, ValueError) as error:
                        raise VideoPreparationVerificationError(
                            "Server video PTS inventory contains an invalid value"
                        ) from error
            finally:
                pts_file.close()

        return values()

    @staticmethod
    def _checked_rows(
        stream: BinaryIO, actual_pts: Iterator[int], manifest: ClientVideoPreparationManifest
    ) -> Iterator[VideoFrameBinding]:
        previous_pts: int | None = None
        time_base = manifest.prepared_video.time_base
        min_interval = 1 / 30
        tick_tolerance = time_base.numerator / time_base.denominator
        for line in stream:
            if len(line) > 2048 or not line.endswith(b"\n"):
                raise VideoPreparationVerificationError("Video frame-map rows must be bounded newline-terminated JSON")
            row = VideoFrameBinding.model_validate_json(line)
            pts = next(actual_pts, None)
            if pts is None or row.output_pts != pts:
                raise VideoPreparationVerificationError("Frame-map output PTS differs from the server-decoded video")
            if (
                previous_pts is not None
                and (pts - previous_pts) * time_base.numerator / time_base.denominator < min_interval - tick_tolerance
            ):
                raise VideoPreparationVerificationError("Prepared video exceeds the 30 FPS profile limit")
            previous_pts = pts
            yield row

    @staticmethod
    def _matches_prepared_stream(observed: VideoStreamMetadata, declared: VideoStreamMetadata) -> bool:
        if observed.rotation_degrees != 0 or observed.sample_aspect_ratio != PositiveRational(
            numerator=1, denominator=1
        ):
            return False
        actual = observed.model_dump(mode="json")
        expected = declared.model_dump(mode="json")
        actual["codec"] = expected["codec"]
        # Average rate metadata varies across muxers; the exact PTS inventory is checked separately.
        actual["frame_rate"] = expected["frame_rate"]
        return actual == expected

    @staticmethod
    def _rotation(stream: dict) -> int:
        raw = next(
            (entry.get("rotation") for entry in stream.get("side_data_list", []) if entry.get("rotation") is not None),
            stream.get("tags", {}).get("rotate", "0"),
        )
        rotation = int(round(float(raw))) % 360
        if rotation not in {0, 90, 180, 270}:
            raise ValueError("unsupported video rotation")
        return rotation

    @staticmethod
    def _rational(raw: str, separator: str) -> PositiveRational:
        numerator, denominator = (int(value) for value in raw.split(separator, 1))
        return PositiveRational(numerator=numerator, denominator=denominator)

    @classmethod
    def _optional_rational(cls, raw: str | None, separator: str) -> PositiveRational | None:
        if not raw or raw in {"N/A", "0/0"}:
            return None
        return cls._rational(raw, separator)

    @staticmethod
    def _color_value(raw: str | None) -> str | None:
        return raw if raw and raw.casefold() not in {"unknown", "unspecified", "n/a"} else None

    @staticmethod
    def _sha256_file(path: Path) -> str:
        with path.open("rb") as stream:
            return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
