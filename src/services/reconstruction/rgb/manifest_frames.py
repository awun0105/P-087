"""Adapter InputManifest cho RGB frame set, không rò layout dataset."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.manifests import InputManifest
from src.services.reconstruction.rgb.quality import RGBQualityRequest, RGBValidationError, RGBVideoRequest
from src.services.reconstruction.rgb.quality_models import RGBFrameAsset, RGBQualityProfile


@dataclass(frozen=True)
class RGBManifestFrameSelection:
    """RGB IDs đã chọn; evaluation-only IDs không vào input."""

    manifest: InputManifest
    frame_ids: tuple[int, ...]
    selection_checksum: str
    profile: RGBQualityProfile


class RGBManifestFrameAdapter:
    """Chỉ resolve RGB files đã khai báo qua resolver được inject."""

    def __init__(self, resolve: Callable[[str], Path]) -> None:
        self.resolve = resolve

    def build_request(self, selection: RGBManifestFrameSelection) -> RGBQualityRequest:
        """Gắn source paths với InputManifest checksum trước khi đo."""
        manifest = selection.manifest
        verify_content_checksum(manifest, "input_manifest_checksum")
        if not manifest.input_configuration.rgb_present:
            raise RGBValidationError("RGB_MODALITY_MISSING", "InputManifest has no RGB modality", "Supply RGB input")
        image_files = [item for item in manifest.files if item.media_type == "image/png"]
        if len(image_files) != len(selection.frame_ids) or not image_files:
            raise RGBValidationError(
                "RGB_MANIFEST_SELECTION_MISMATCH",
                "RGB frame selection differs from InputManifest",
                "Bind one PNG input file to each selected reconstruction ID",
            )
        frames = tuple(
            RGBFrameAsset(frame_id, self.resolve(item.artifact_uri), item.checksum, size_bytes=item.size_bytes)
            for frame_id, item in zip(selection.frame_ids, image_files, strict=True)
        )
        return RGBQualityRequest(
            frames, manifest.input_manifest_checksum, selection.selection_checksum, selection.profile
        )

    def build_video_request(self, manifest: InputManifest, profile: RGBQualityProfile) -> RGBVideoRequest:
        """Resolve đúng một video mp4/mov; từ chối input mơ hồ."""
        verify_content_checksum(manifest, "input_manifest_checksum")
        if not manifest.input_configuration.rgb_present:
            raise RGBValidationError("RGB_MODALITY_MISSING", "InputManifest has no RGB modality", "Supply RGB input")
        videos = [item for item in manifest.files if item.media_type in {"video/mp4", "video/quicktime"}]
        if len(videos) != 1:
            raise RGBValidationError(
                "RGB_VIDEO_MANIFEST_INVALID", "Expected exactly one declared RGB video", "Supply one mp4/mov input file"
            )
        item = videos[0]
        return RGBVideoRequest(
            self.resolve(item.artifact_uri), item.checksum, item.size_bytes, manifest.input_manifest_checksum, profile
        )
