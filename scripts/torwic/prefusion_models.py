"""REC-07 offline request: nguồn/pose/frame explicit, không suy từ folder mặc định."""

from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import Field, FiniteFloat, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier
from src.models.contracts.reconstruction import DependencyOrigin


def safe_relative(value: str) -> str:
    """Không cho source/output refs vượt dataset root hoặc chứa native paths."""
    if not value or "\\" in value or PurePosixPath(value).is_absolute():
        raise ValueError("dataset reference must be relative")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("dataset reference contains unsafe components")
    return value


class SourceFile(ContractModel):
    """Byte identity của source được chuẩn bị offline; không là ProductArtifactRef."""

    relative_path: str
    checksum: Checksum

    _path = field_validator("relative_path")(safe_relative)


class ScanSource(SourceFile):
    """Frame ID phải khớp tên PCD và timestamp cùng index trong TorWIC source."""

    frame_id: int = Field(ge=0)

    @model_validator(mode="after")
    def _frame_name(self) -> Self:
        if PurePosixPath(self.relative_path).name != f"{self.frame_id:06d}.pcd":
            raise ValueError("scan filename does not match frame ID")
        return self


class PrefusionRequest(ContractModel):
    """Native frame vẫn UNVERIFIED; ingest/alignment phải xác nhận canonical riêng."""

    schema_version: Literal["1.0"] = "1.0"
    traversal_id: Identifier
    scans: list[ScanSource] = Field(min_length=1)
    trajectory: SourceFile
    timestamps: SourceFile
    calibration: SourceFile
    coordinate_evidence: SourceFile
    pose_origin: Literal[DependencyOrigin.ESTIMATED, DependencyOrigin.EXTERNAL, DependencyOrigin.GROUND_TRUTH]
    allow_ground_truth_poses: bool = False
    source_frame: Identifier
    target_frame: Identifier
    unit: Literal["meter"]
    transform_semantics: Literal["target_from_source"]
    timestamp_tolerance_s: FiniteFloat = Field(ge=0)
    quaternion_norm_tolerance: FiniteFloat = Field(ge=0, lt=0.01)
    voxel_size_m: FiniteFloat | None = Field(default=None, gt=0)
    min_range_m: FiniteFloat = Field(ge=0)
    max_range_m: FiniteFloat | None = Field(default=None, gt=0)
    max_scan_points: int = Field(gt=0)
    max_merged_points: int = Field(gt=0)

    @model_validator(mode="after")
    def _validate_declarations(self) -> Self:
        ids = [scan.frame_id for scan in self.scans]
        if ids != sorted(set(ids)):
            raise ValueError("scan IDs must be unique and ordered")
        uses_gt = self.pose_origin == DependencyOrigin.GROUND_TRUTH
        if uses_gt != self.allow_ground_truth_poses:
            raise ValueError("ground-truth pose use must be explicitly and consistently declared")
        if PurePosixPath(self.trajectory.relative_path).name == "traj_gt.txt" and not uses_gt:
            raise ValueError("traj_gt must retain its ground-truth origin")
        if self.source_frame == self.target_frame:
            raise ValueError("pose source and target frames must differ")
        if self.max_range_m is not None and self.max_range_m <= self.min_range_m:
            raise ValueError("maximum range must exceed minimum range")
        if any(PurePosixPath(ref.relative_path).name == "groundtruth_map.ply" for ref in self.sources()):
            raise ValueError("evaluation map is forbidden in prefusion")
        return self

    def sources(self) -> list[SourceFile]:
        """Exact dependency inventory, không glob đọc thêm scans ngoài request."""
        return [*self.scans, self.trajectory, self.timestamps, self.calibration, self.coordinate_evidence]


class PrefusionSettings(BaseSettings):
    """Local roots qua Settings/CLI, không serialize đường dẫn riêng vào artifact."""

    model_config = SettingsConfigDict(env_prefix="REC07_", extra="forbid")
    dataset_root: Path
    output_relative: str

    @field_validator("output_relative")
    @classmethod
    def _derived_output(cls, value: str) -> str:
        safe_relative(value)
        if not value.startswith("derived/"):
            raise ValueError("prefusion output must be a new attempt under derived/")
        return value
