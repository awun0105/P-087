"""Inventory bất biến cho RGB frames; REC-03 đọc qua logical artifact refs."""

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef, SchemaVersion
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.video_preparation import ServerVideoPreparationVerification


class NormalizedRGBFrame(ContractModel):
    """Một frame được chọn, giữ source identity và timestamp chính xác."""

    frame_id: int = Field(ge=0)
    timestamp_sec: str
    image: ProductArtifactRef
    source_checksum: Checksum
    source_frame_id: int | None = Field(default=None, ge=0, exclude_if=lambda value: value is None)


class NormalizedRGBFrameSet(ContractModel):
    """Output nội bộ EX-REC; content identity độc lập byte JSON envelope."""

    schema_version: SchemaVersion
    input_manifest_checksum: Checksum
    quality_report_checksum: Checksum
    privacy_report_checksum: Checksum
    selection_checksum: Checksum
    timestamp_inventory_checksum: Checksum
    extraction_config_checksum: Checksum
    ffmpeg_version: str
    frames: list[NormalizedRGBFrame]
    video_preparation: ServerVideoPreparationVerification | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    #: Có khi các ảnh của frame set là bản đã che khuôn mặt/biển số (AUD-18): checksum của SanitizationManifest.
    sanitization_manifest_checksum: Checksum | None = Field(default=None, exclude_if=lambda value: value is None)
    frame_set_checksum: Checksum

    @model_validator(mode="after")
    def _validate_inventory(self) -> "NormalizedRGBFrameSet":
        ids = [frame.frame_id for frame in self.frames]
        if len(ids) < 2 or ids != sorted(set(ids)):
            raise ValueError("normalized RGB frame IDs must be ordered and unique")
        try:
            times = [Decimal(frame.timestamp_sec) for frame in self.frames]
        except InvalidOperation as error:
            raise ValueError("invalid RGB frame timestamp") from error
        if any(not time.is_finite() or time < 0 for time in times):
            raise ValueError("RGB frame timestamps must be finite and nonnegative")
        if any(after <= before for before, after in zip(times, times[1:], strict=False)):
            raise ValueError("RGB frame timestamps must increase strictly")
        timestamps = {str(frame.frame_id): frame.timestamp_sec for frame in self.frames}
        digest = hashlib.sha256(json.dumps(timestamps, sort_keys=True).encode()).hexdigest()
        if self.timestamp_inventory_checksum != "sha256:" + digest:
            raise ValueError("RGB timestamp inventory checksum mismatch")
        if canonical_content_checksum(self, "frame_set_checksum") != self.frame_set_checksum:
            raise ValueError("normalized RGB frame-set checksum mismatch")
        return self


class FrameSetResolver:
    """REC-03 boundary: resolve inventory và từng image theo byte checksum."""

    def __init__(
        self,
        resolve_source: Callable[[ProductArtifactRef], Path],
        resolve_derived: Callable[[ProductArtifactRef], Path],
    ) -> None:
        self.resolve_source = resolve_source
        self.resolve_derived = resolve_derived

    def _resolve(self, reference: ProductArtifactRef) -> Path:
        if reference.data_class.value == "product_input":
            return self.resolve_source(reference)
        return self.resolve_derived(reference)

    def load(self, reference: ProductArtifactRef) -> NormalizedRGBFrameSet:
        """Đọc frame-set envelope sau khi kiểm tra byte checksum."""
        if reference.artifact_type != "NormalizedRGBFrameSet":
            raise ValueError("artifact is not a normalized RGB frame set")
        path = self._resolve(reference)
        if not path.is_file() or _sha256(path) != reference.artifact_checksum:
            raise ValueError("normalized RGB frame-set bytes changed or missing")
        return NormalizedRGBFrameSet.model_validate_json(path.read_text())

    def materialize(self, frame_set: NormalizedRGBFrameSet) -> tuple[tuple[int, Path, str], ...]:
        """Cung cấp ảnh đúng thứ tự cho COLMAP, không đổi tên hay chuyển format."""
        rows = []
        for frame in frame_set.frames:
            path = self._resolve(frame.image)
            if not path.is_file() or _sha256(path) != frame.image.artifact_checksum:
                raise ValueError(f"frame artifact missing or checksum mismatch: {frame.frame_id}")
            rows.append((frame.frame_id, path, frame.timestamp_sec))
        return tuple(rows)


def frame_image_name(frame_id: int, source: Path) -> str:
    """Canonical frame identity keeps the source image format without re-encoding."""
    suffix = source.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("unsupported RGB frame image name")
    return f"{frame_id:06d}{suffix}"


def _sha256(path: Path) -> str:
    """Hash source bytes without loading a large frame into memory."""
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
