"""Record preflight RGB thuộc EX-REC; giữ nguyên shared artifact schemas."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, SchemaVersion
from src.models.contracts.identity import canonical_content_checksum


@dataclass(frozen=True)
class RGBFrameAsset:
    """Frame đã resolve; đường dẫn máy không đi vào report publish."""

    frame_id: int
    path: Path
    checksum: str
    timestamp_sec: str | None = None
    size_bytes: int | None = None


class RGBQualityProfile(ContractModel):
    """Policy đo/lọc có version do dataset owner cấp."""

    schema_version: SchemaVersion
    profile_id: Identifier
    measurement_width: int = Field(gt=0)
    measurement_height: int = Field(gt=0)
    blur_exclude_gt: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    active_transition_px_gt: float = Field(ge=0, allow_inf_nan=False)
    warn_active_ratio_lt: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    warn_static_run_gt: int | None = Field(default=None, ge=0)
    profile_checksum: Checksum

    @model_validator(mode="after")
    def _check_identity(self) -> "RGBQualityProfile":
        if canonical_content_checksum(self, "profile_checksum") != self.profile_checksum:
            raise ValueError("RGB quality profile checksum mismatch")
        return self


class RGBFrameQuality(ContractModel):
    """Quyết định giữ/loại frame gắn source checksum."""

    frame_id: int = Field(ge=0)
    source_checksum: Checksum
    timestamp_sec: str | None = None
    blur_score: float = Field(ge=0, allow_inf_nan=False)
    quality: Literal["accepted", "excluded"]
    reasons: list[Literal["blur"]]
    motion_px: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _check_reason(self) -> "RGBFrameQuality":
        if self.reasons != (["blur"] if self.quality == "excluded" else []):
            raise ValueError("RGB frame quality reason does not match decision")
        return self


class RGBMotionDiagnostics(ContractModel):
    """Proxy image motion và coverage; chưa phải SfM acceptance."""

    observed_transition_count: int = Field(ge=0)
    active_transition_count: int = Field(ge=0)
    active_ratio: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    max_static_run: int = Field(ge=0)
    max_selection_gap: int = Field(ge=0)
    motion_p90_px: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    motion_p95_px: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fast_transition_frame_ids: list[int]
    warnings: list[str]
    registration_feasibility: Literal["NOT_ESTABLISHED_PRE_COLMAP"] = "NOT_ESTABLISHED_PRE_COLMAP"


class RGBQualityReport(ContractModel):
    """Quality mask bất biến và diagnostic chỉ dựa trên input."""

    schema_version: SchemaVersion
    source_manifest_checksum: Checksum
    selection_checksum: Checksum
    profile_checksum: Checksum
    ffmpeg_version: str
    producer_version: Identifier
    selected_frame_ids: list[int]
    effective_reconstruction_frame_ids: list[int]
    excluded_frame_ids: list[int]
    frames: list[RGBFrameQuality]
    motion: RGBMotionDiagnostics
    report_checksum: Checksum

    @model_validator(mode="after")
    def _check_selection(self) -> "RGBQualityReport":
        if self.selected_frame_ids != sorted(set(self.selected_frame_ids)):
            raise ValueError("quality selected frame IDs must be ordered and unique")
        if self.selected_frame_ids != [frame.frame_id for frame in self.frames]:
            raise ValueError("quality frame inventory differs from selected IDs")
        kept = [frame.frame_id for frame in self.frames if frame.quality == "accepted"]
        removed = [frame.frame_id for frame in self.frames if frame.quality == "excluded"]
        if kept != self.effective_reconstruction_frame_ids or removed != self.excluded_frame_ids:
            raise ValueError("quality mask differs from effective reconstruction IDs")
        if canonical_content_checksum(self, "report_checksum") != self.report_checksum:
            raise ValueError("RGB quality report checksum mismatch")
        return self
