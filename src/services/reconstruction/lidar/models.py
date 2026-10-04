"""Typed contracts và models cho REC-08 Registered LiDAR Ingest."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.reconstruction import PreprocessingProvenance
from src.services.reconstruction.lidar.cloud_payload import (
    PointCloudStats,
    inspect_point_cloud,
    inspect_point_cloud_header,  # noqa: F401 - backward-compatible import boundary
)


def compute_file_checksum(path: Path) -> Checksum:
    """Tính SHA-256 checksum qua streaming để tránh tràn RAM khi file lớn."""
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


class PrefusedLiDARSource(ContractModel):
    """Native REC-07 output không mang canonical CoordinateSystem hay approval."""

    source_input_checksum: Checksum
    source_frame: Identifier
    unit: Literal["meter"]
    coordinate_status: Literal["UNVERIFIED"]
    confirmed_rgb_alignment: Literal[False]
    preprocessing_provenance: PreprocessingProvenance


class LiDARIngestRequest(ContractModel):
    """Request thẩm định và nhập dữ liệu LiDAR đã đăng ký."""

    job_id: Identifier
    lidar_file: Path
    source_input_checksum: Checksum
    geometry_format: Literal["ply", "pcd"] = "ply"
    coordinate_system: CoordinateSystem
    source_frame: Identifier
    declared_transform_to_canonical: Transform | None = None
    preprocessing_provenance: PreprocessingProvenance
    min_points: int = Field(default=1, ge=1)
    max_points: int = Field(default=20_000_000, gt=0)

    def validate_payload(self) -> PointCloudStats:
        """Kiểm tra toàn diện checksum SHA-256, format, đơn vị mét và số lượng điểm."""
        if not self.lidar_file.is_file():
            raise ValueError("LiDAR file missing")
        actual_checksum = compute_file_checksum(self.lidar_file)
        if actual_checksum != self.source_input_checksum:
            raise ValueError(f"source checksum mismatch: expected {self.source_input_checksum}, got {actual_checksum}")
        if self.coordinate_system.unit != "meter":
            raise ValueError(f"LiDAR unit must be meter, got {self.coordinate_system.unit}")
        stats = inspect_point_cloud(self.lidar_file, self.max_points)
        if stats.geometry_format != self.geometry_format:
            raise ValueError("declared geometry format does not match payload")
        self._validate_frame()
        if stats.point_count < self.min_points:
            raise ValueError(f"point cloud has too few points: {stats.point_count} < {self.min_points}")
        if stats.point_count > self.max_points:
            raise ValueError(f"point cloud exceeds point budget: {stats.point_count} > {self.max_points}")
        return stats

    def _validate_frame(self) -> None:
        transform = self.declared_transform_to_canonical
        if transform is not None:
            from src.services.reconstruction.alignment.transforms import validated_transform

            validated_transform(transform)
            if transform.parent_frame != "world" or transform.local_frame != self.source_frame:
                raise ValueError("declared transform must map source frame to canonical world")
