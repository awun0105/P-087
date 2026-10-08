"""Versioned contracts for client-side video normalization and source mapping.

The browser's source fingerprint is client-declared. Only the prepared file's
received bytes can be verified by the server; this contract does not make the
local original a server-side source artifact.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from math import gcd
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum


class VideoResolutionPreset(StrEnum):
    """Maximum oriented bounding-box preset selected before local encoding."""

    P1080 = "1080p"
    P720 = "720p"
    P480 = "480p"


class PositiveRational(ContractModel):
    """A reduced, positive rational used for media time bases and pixel aspect."""

    numerator: int = Field(gt=0, strict=True)
    denominator: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def _require_reduced_form(self) -> Self:
        if gcd(self.numerator, self.denominator) != 1:
            raise ValueError("rational values must be in reduced form")
        return self


class VideoResolutionProfile(ContractModel):
    preset: VideoResolutionPreset
    max_long_edge_px: int = Field(ge=2, strict=True)
    max_short_edge_px: int = Field(ge=2, strict=True)
    target_bitrate_bps: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def _require_even_bounds(self) -> Self:
        if self.max_long_edge_px % 2 or self.max_short_edge_px % 2:
            raise ValueError("H.264 resolution bounds must be even")
        if self.max_long_edge_px < self.max_short_edge_px:
            raise ValueError("the long-edge bound cannot be smaller than the short-edge bound")
        return self


class VideoNormalizationProfile(ContractModel):
    """Content-addressed v1 policy; S5 qualifies rates against real captures."""

    schema_version: Literal["1.0"]
    profile_id: Literal["real2sim_client_video"]
    profile_version: Literal["1"]
    default_preset: VideoResolutionPreset
    presets: list[VideoResolutionProfile]
    max_frame_rate: PositiveRational
    frame_rate_policy: Literal["presentation_time_nearest_no_duplicate"]
    container: Literal["video/mp4"]
    video_codec_family: Literal["avc"]
    bitrate_mode: Literal["variable"]
    allow_upscale: Literal[False]
    preserve_display_aspect: Literal[True]
    crop_policy: Literal["none"]
    orientation_policy: Literal["apply_once_to_pixels"]
    dimension_rounding: Literal["even_down"]
    max_duration_error_frames: int = Field(ge=0, strict=True)
    max_frame_map_bytes: int = Field(gt=0, strict=True)
    audio_policy: Literal["preserve_compatible_or_explicit_omit"]
    color_policy: Literal["preserve_sdr_metadata_reject_hdr"]
    profile_checksum: Checksum

    @model_validator(mode="after")
    def _validate_profile(self) -> Self:
        expected = {
            VideoResolutionPreset.P1080: (1920, 1080, 8_000_000),
            VideoResolutionPreset.P720: (1280, 720, 4_000_000),
            VideoResolutionPreset.P480: (854, 480, 2_000_000),
        }
        actual = {
            item.preset: (item.max_long_edge_px, item.max_short_edge_px, item.target_bitrate_bps)
            for item in self.presets
        }
        if actual != expected or len(self.presets) != len(expected):
            raise ValueError("video profile must declare the v1 preset bounds and candidate rates exactly")
        if self.default_preset != VideoResolutionPreset.P720:
            raise ValueError("the v1 default resolution preset is 720p")
        if self.max_frame_rate != PositiveRational(numerator=30, denominator=1):
            raise ValueError("the v1 candidate frame-rate cap is 30/1")
        if self.max_frame_map_bytes != 33_554_432:
            raise ValueError("the v1 JSONL frame-map bound is 32 MiB")
        verify_content_checksum(self, "profile_checksum")
        return self


class VideoNormalizationBlocker(StrEnum):
    SECURE_CONTEXT_REQUIRED = "secure_context_required"
    WORKER_UNAVAILABLE = "worker_unavailable"
    DECODER_UNSUPPORTED = "decoder_unsupported"
    ENCODER_UNSUPPORTED = "encoder_unsupported"
    MP4_MUXER_UNAVAILABLE = "mp4_muxer_unavailable"
    STORAGE_UNKNOWN = "storage_unknown"
    STORAGE_INSUFFICIENT = "storage_insufficient"
    HDR_UNSUPPORTED = "hdr_unsupported"
    AUDIO_REQUIRES_EXPLICIT_OMISSION = "audio_requires_explicit_omission"
    VIDEO_METADATA_UNSUPPORTED = "video_metadata_unsupported"


class VideoNormalizationCapability(ContractModel):
    """Per-input browser capability result; never authorize a silent raw fallback."""

    schema_version: Literal["1.0"]
    profile_checksum: Checksum
    requested_preset: VideoResolutionPreset
    secure_context: bool
    worker_available: bool
    decoder_supported: bool
    encoder_supported: bool
    mp4_muxer_available: bool
    video_metadata_supported: bool
    hdr_supported: bool
    audio_policy_satisfied: bool
    available_storage_bytes: int | None = Field(default=None, ge=0, strict=True)
    required_storage_bytes: int = Field(ge=0, strict=True)
    blockers: list[VideoNormalizationBlocker]
    status: Literal["supported", "unsupported"]

    @model_validator(mode="after")
    def _validate_capability_result(self) -> Self:
        detected: set[VideoNormalizationBlocker] = set()
        if not self.secure_context:
            detected.add(VideoNormalizationBlocker.SECURE_CONTEXT_REQUIRED)
        if not self.worker_available:
            detected.add(VideoNormalizationBlocker.WORKER_UNAVAILABLE)
        if not self.decoder_supported:
            detected.add(VideoNormalizationBlocker.DECODER_UNSUPPORTED)
        if not self.encoder_supported:
            detected.add(VideoNormalizationBlocker.ENCODER_UNSUPPORTED)
        if not self.mp4_muxer_available:
            detected.add(VideoNormalizationBlocker.MP4_MUXER_UNAVAILABLE)
        if not self.video_metadata_supported:
            detected.add(VideoNormalizationBlocker.VIDEO_METADATA_UNSUPPORTED)
        if not self.hdr_supported:
            detected.add(VideoNormalizationBlocker.HDR_UNSUPPORTED)
        if not self.audio_policy_satisfied:
            detected.add(VideoNormalizationBlocker.AUDIO_REQUIRES_EXPLICIT_OMISSION)
        if self.available_storage_bytes is None:
            detected.add(VideoNormalizationBlocker.STORAGE_UNKNOWN)
        elif self.available_storage_bytes < self.required_storage_bytes:
            detected.add(VideoNormalizationBlocker.STORAGE_INSUFFICIENT)
        declared = set(self.blockers)
        if detected != declared:
            raise ValueError("capability blockers must exactly match failed browser or storage requirements")
        if self.status == "supported" and declared:
            raise ValueError("supported video preparation cannot contain blockers")
        if self.status == "unsupported" and not declared:
            raise ValueError("unsupported video preparation requires an explicit blocker")
        if self.profile_checksum != default_video_normalization_profile().profile_checksum:
            raise ValueError("capability result must bind the active v1 profile checksum")
        return self


class ClientVideoFingerprint(ContractModel):
    """Local original identity asserted by the browser, not verified by the server."""

    original_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0, strict=True)
    last_modified_ms: int = Field(ge=0, strict=True)
    declared_source_checksum: Checksum


class VideoColorMetadata(ContractModel):
    primaries: str | None = None
    transfer: str | None = None
    matrix: str | None = None
    range: str | None = None


class VideoStreamMetadata(ContractModel):
    """Observed stream values; frame rates remain exact rationals when present."""

    codec: str = Field(min_length=1, max_length=128)
    coded_width: int = Field(gt=0, strict=True)
    coded_height: int = Field(gt=0, strict=True)
    display_width: int = Field(gt=0, strict=True)
    display_height: int = Field(gt=0, strict=True)
    sample_aspect_ratio: PositiveRational
    rotation_degrees: Literal[0, 90, 180, 270]
    start_pts: int = Field(strict=True)
    duration_ticks: int = Field(gt=0, strict=True)
    time_base: PositiveRational
    frame_rate: PositiveRational | None = None
    frame_count: int = Field(gt=0, strict=True)
    color: VideoColorMetadata | None = None
    audio_track_count: int = Field(ge=0, strict=True)


class VideoPixelTransform(ContractModel):
    """Row-major map from source coded pixels to output, baking rotation and sample aspect once."""

    matrix: tuple[
        tuple[FiniteFloat, FiniteFloat, FiniteFloat],
        tuple[FiniteFloat, FiniteFloat, FiniteFloat],
        tuple[FiniteFloat, FiniteFloat, FiniteFloat],
    ]

    @model_validator(mode="after")
    def _require_invertible_affine_transform(self) -> Self:
        a, b, c = self.matrix
        if c[0] != 0 or c[1] != 0 or c[2] != 1:
            raise ValueError("pixel transform must use homogeneous affine row [0, 0, 1]")
        determinant = a[0] * b[1] - a[1] * b[0]
        if abs(determinant) < 1e-12:
            raise ValueError("pixel transform must be invertible")
        return self


class VideoFrameBinding(ContractModel):
    """One JSONL sidecar row binding an encoded presentation frame to its source."""

    schema_version: Literal["1.0"]
    output_frame_index: int = Field(ge=0, strict=True)
    output_pts: int = Field(strict=True)
    source_frame_index: int = Field(ge=0, strict=True)
    source_pts: int = Field(strict=True)


class VideoFrameMapDescriptor(ContractModel):
    """Bounded sidecar identity; the potentially large map is never in an API JSON body."""

    format: Literal["r2s_video_frame_map_jsonl_v1"]
    checksum: Checksum
    size_bytes: int = Field(gt=0, strict=True)
    entry_count: int = Field(gt=0, strict=True)
    source_frame_count: int = Field(gt=0, strict=True)


class PreparedVideoFile(ContractModel):
    """Identity of the final encoded bytes selected for upload."""

    content_type: Literal["video/mp4"]
    size_bytes: int = Field(gt=0, strict=True)
    checksum: Checksum


class AudioDisposition(StrEnum):
    SOURCE_HAS_NO_AUDIO = "source_has_no_audio"
    PRESERVED = "preserved"
    OMITTED_WITH_USER_CONSENT = "omitted_with_user_consent"


class ClientVideoPreparationManifest(ContractModel):
    """Client preparation receipt, bound to profile, output bytes and frame-map sidecar."""

    schema_version: Literal["1.0"]
    profile_checksum: Checksum
    selected_preset: VideoResolutionPreset
    implementation_id: str = Field(min_length=1, max_length=128)
    implementation_version: str = Field(min_length=1, max_length=64)
    source: ClientVideoFingerprint
    prepared_file: PreparedVideoFile
    source_video: VideoStreamMetadata
    prepared_video: VideoStreamMetadata
    pixel_transform: VideoPixelTransform
    frame_map: VideoFrameMapDescriptor
    audio_disposition: AudioDisposition
    preparation_checksum: Checksum

    @model_validator(mode="after")
    def _validate_preparation_contract(self) -> Self:
        profile = default_video_normalization_profile()
        if self.profile_checksum != profile.profile_checksum:
            raise ValueError("preparation manifest must bind the active v1 profile checksum")
        if self.frame_map.entry_count != self.prepared_video.frame_count:
            raise ValueError("frame-map entries must cover every prepared presentation frame")
        if self.frame_map.source_frame_count != self.source_video.frame_count:
            raise ValueError("frame-map source count must match the observed original video")
        if self.frame_map.size_bytes > profile.max_frame_map_bytes:
            raise ValueError("video frame-map sidecar exceeds the active profile byte limit")
        if self.prepared_video.rotation_degrees != 0:
            raise ValueError("prepared video must bake orientation once and clear rotation metadata")
        if self.prepared_video.sample_aspect_ratio != PositiveRational(numerator=1, denominator=1):
            raise ValueError("prepared video must use square pixels")
        if (
            self.prepared_video.coded_width != self.prepared_video.display_width
            or self.prepared_video.coded_height != self.prepared_video.display_height
        ):
            raise ValueError("prepared video display dimensions must match square-pixel coded dimensions")
        selected = next(item for item in profile.presets if item.preset == self.selected_preset)
        output_long = max(self.prepared_video.display_width, self.prepared_video.display_height)
        output_short = min(self.prepared_video.display_width, self.prepared_video.display_height)
        if output_long > selected.max_long_edge_px or output_short > selected.max_short_edge_px:
            raise ValueError("prepared video dimensions exceed the selected oriented resolution preset")
        if (
            self.prepared_video.display_width > self.source_video.display_width
            or self.prepared_video.display_height > self.source_video.display_height
        ):
            raise ValueError("prepared video must not upscale the source display dimensions")
        codec = self.prepared_video.codec.casefold()
        if codec not in {"avc", "h264"} and not codec.startswith("avc1."):
            raise ValueError("prepared video codec must match the v1 AVC profile")
        source_transfer = (self.source_video.color.transfer if self.source_video.color is not None else None) or ""
        if _is_hdr_transfer(source_transfer):
            raise ValueError("HDR source video is outside the v1 normalization profile")
        if not _preserves_sdr_color_metadata(self.source_video.color, self.prepared_video.color):
            raise ValueError("prepared video must preserve the observed SDR color metadata")
        if self.audio_disposition == AudioDisposition.SOURCE_HAS_NO_AUDIO:
            if self.source_video.audio_track_count != 0 or self.prepared_video.audio_track_count != 0:
                raise ValueError("no-audio disposition requires both source and output to have no audio")
        elif self.audio_disposition == AudioDisposition.PRESERVED:
            if (
                self.source_video.audio_track_count == 0
                or self.prepared_video.audio_track_count != self.source_video.audio_track_count
            ):
                raise ValueError("preserved-audio disposition requires every source audio track in the output")
        elif self.source_video.audio_track_count == 0 or self.prepared_video.audio_track_count != 0:
            raise ValueError("explicit audio omission requires source audio and an output without audio")
        verify_content_checksum(self, "preparation_checksum")
        return self


class ServerVideoPreparationVerification(ContractModel):
    """Server evidence for received prepared bytes; local-original metadata stays unverified."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["server_verified"] = "server_verified"
    uploaded_checksum: Checksum
    uploaded_size_bytes: int = Field(gt=0, strict=True)
    client_manifest: ClientVideoPreparationManifest
    observed_video: VideoStreamMetadata
    frame_map_ref: ProductArtifactRef
    original_source_status: Literal["client_declared_unverified"] = "client_declared_unverified"
    verification_checksum: Checksum

    @model_validator(mode="after")
    def _validate_verification(self) -> Self:
        if (
            self.uploaded_checksum != self.client_manifest.prepared_file.checksum
            or self.uploaded_size_bytes != self.client_manifest.prepared_file.size_bytes
        ):
            raise ValueError("verified upload identity differs from the client preparation declaration")
        if self.frame_map_ref.artifact_checksum != self.client_manifest.frame_map.checksum:
            raise ValueError("verified frame-map reference differs from the declared sidecar checksum")
        if (
            self.frame_map_ref.artifact_type != "VideoFrameMap"
            or self.frame_map_ref.data_class.value != "product_input"
        ):
            raise ValueError("frame-map reference must identify a product-input VideoFrameMap")
        if self.frame_map_ref.job_id is None:
            raise ValueError("frame-map reference must belong to an upload namespace")
        if not _same_prepared_stream(self.observed_video, self.client_manifest.prepared_video):
            raise ValueError("server-observed prepared video differs from the client declaration")
        verify_content_checksum(self, "verification_checksum")
        return self


def _same_prepared_stream(observed: VideoStreamMetadata, declared: VideoStreamMetadata) -> bool:
    """Compare server-observable values, allowing codec labels from equivalent AVC parsers."""
    observed_codec = observed.codec.casefold()
    declared_codec = declared.codec.casefold()
    observed_avc = observed_codec in {"avc", "h264"} or observed_codec.startswith("avc1.")
    declared_avc = declared_codec in {"avc", "h264"} or declared_codec.startswith("avc1.")
    actual = observed.model_dump(mode="json")
    expected = declared.model_dump(mode="json")
    actual.pop("frame_rate", None)
    expected.pop("frame_rate", None)
    actual["codec"] = expected["codec"]
    return observed_avc and declared_avc and actual == expected


def _is_hdr_transfer(value: str) -> bool:
    normalized = value.casefold().replace("_", "-").replace(" ", "-")
    return "2084" in normalized or "arib-std-b67" in normalized or normalized in {"pq", "hlg"}


def _preserves_sdr_color_metadata(
    source: VideoColorMetadata | None,
    prepared: VideoColorMetadata | None,
) -> bool:
    """Preserve observed source colorimetry while allowing standard SDR defaults for unknown fields."""
    if prepared is not None and _is_hdr_transfer(prepared.transfer or ""):
        return False
    if source is None:
        return True
    if prepared is None:
        return all(value is None for value in source.model_dump().values())
    return (
        (source.primaries is None or source.primaries == prepared.primaries)
        and (source.transfer is None or source.transfer == prepared.transfer)
        and (source.matrix is None or source.matrix == prepared.matrix)
        and (source.range is None or source.range == prepared.range)
    )


def default_video_normalization_profile() -> VideoNormalizationProfile:
    """Build the immutable v1 candidate profile and its canonical checksum."""
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "profile_id": "real2sim_client_video",
        "profile_version": "1",
        "default_preset": VideoResolutionPreset.P720.value,
        "presets": [
            {"preset": "1080p", "max_long_edge_px": 1920, "max_short_edge_px": 1080, "target_bitrate_bps": 8_000_000},
            {"preset": "720p", "max_long_edge_px": 1280, "max_short_edge_px": 720, "target_bitrate_bps": 4_000_000},
            {"preset": "480p", "max_long_edge_px": 854, "max_short_edge_px": 480, "target_bitrate_bps": 2_000_000},
        ],
        "max_frame_rate": {"numerator": 30, "denominator": 1},
        "frame_rate_policy": "presentation_time_nearest_no_duplicate",
        "container": "video/mp4",
        "video_codec_family": "avc",
        "bitrate_mode": "variable",
        "allow_upscale": False,
        "preserve_display_aspect": True,
        "crop_policy": "none",
        "orientation_policy": "apply_once_to_pixels",
        "dimension_rounding": "even_down",
        "max_duration_error_frames": 1,
        "max_frame_map_bytes": 33_554_432,
        "audio_policy": "preserve_compatible_or_explicit_omit",
        "color_policy": "preserve_sdr_metadata_reject_hdr",
        "profile_checksum": "sha256:" + "0" * 64,
    }
    payload["profile_checksum"] = canonical_content_checksum(payload, "profile_checksum")
    return VideoNormalizationProfile.model_validate(payload)


def validate_video_frame_map_rows(
    rows: Iterable[VideoFrameBinding],
    *,
    descriptor: VideoFrameMapDescriptor,
    source_frame_count: int,
    output_frame_count: int,
    max_sidecar_bytes: int,
) -> None:
    """Validate JSONL rows in one pass without retaining the potentially large mapping."""
    if descriptor.size_bytes > max_sidecar_bytes:
        raise ValueError("video frame-map sidecar exceeds the configured byte limit")
    if descriptor.source_frame_count != source_frame_count or descriptor.entry_count != output_frame_count:
        raise ValueError("video frame-map descriptor does not match stream frame counts")
    count = 0
    previous_source_index = -1
    previous_source_pts: int | None = None
    previous_output_pts: int | None = None
    for row in rows:
        if row.output_frame_index != count:
            raise ValueError("video frame-map output indices must be contiguous from zero")
        if row.source_frame_index <= previous_source_index or row.source_frame_index >= source_frame_count:
            raise ValueError("video frame-map source indices must be increasing and in range")
        if previous_source_pts is not None and row.source_pts <= previous_source_pts:
            raise ValueError("video frame-map source PTS must be strictly increasing")
        if previous_output_pts is not None and row.output_pts <= previous_output_pts:
            raise ValueError("video frame-map output PTS must be strictly increasing")
        count += 1
        previous_source_index = row.source_frame_index
        previous_source_pts = row.source_pts
        previous_output_pts = row.output_pts
    if count != descriptor.entry_count:
        raise ValueError("video frame-map row count does not match its descriptor")
