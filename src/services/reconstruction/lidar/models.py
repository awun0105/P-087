"""Typed contracts và models cho REC-08 Registered LiDAR Ingest."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.reconstruction import (
    PreprocessingProvenance,
)


def inspect_point_cloud_header(path: Path) -> int:
    """Đọc số lượng điểm từ header PLY hoặc PCD trong <1ms mà không nạp toàn bộ file."""
    if not path.is_file():
        raise ValueError(f"point cloud file does not exist: {path}")
    with path.open("rb") as stream:
        header_bytes = stream.read(4096)
    header_text = header_bytes.decode("ascii", errors="ignore")
    if header_text.startswith("ply"):
        for line in header_text.splitlines():
            if line.startswith("element vertex "):
                return int(line.split()[2])
        raise ValueError("invalid PLY: missing element vertex in header")
    if "# .PCD" in header_text or "VERSION" in header_text:
        for line in header_text.splitlines():
            if line.startswith("POINTS "):
                return int(line.split()[1])
        raise ValueError("invalid PCD: missing POINTS in header")
    raise ValueError("unsupported point cloud format; expected PLY or PCD")


def compute_file_checksum(path: Path) -> Checksum:
    """Tính SHA-256 checksum qua streaming để tránh tràn RAM."""
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


class LiDARIngestRequest(ContractModel):
    """Request thẩm định và nhập dữ liệu LiDAR đã đăng ký."""

    job_id: Identifier
    lidar_file: Path
    source_input_checksum: Checksum
    geometry_format: Literal["ply", "pcd"] = "ply"
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    source_frame: Identifier = "os_sensor"
    declared_transform_to_canonical: Transform | None = None
    preprocessing_provenance: PreprocessingProvenance
    min_points: int = Field(default=1, ge=1)
    max_points: int = Field(default=20_000_000, gt=0)

    def validate_payload(self) -> int:
        """Kiểm tra checksum, định dạng file, đơn vị mét và số lượng điểm."""
        if not self.lidar_file.is_file():
            raise ValueError(f"LiDAR file missing: {self.lidar_file}")
        actual_checksum = compute_file_checksum(self.lidar_file)
        if actual_checksum != self.source_input_checksum:
            raise ValueError(f"source checksum mismatch: expected {self.source_input_checksum}, got {actual_checksum}")
        if self.coordinate_system.unit != "meter":
            raise ValueError(f"LiDAR unit must be meter, got {self.coordinate_system.unit}")
        point_count = inspect_point_cloud_header(self.lidar_file)
        if point_count < self.min_points:
            raise ValueError(f"point cloud has too few points: {point_count} < {self.min_points}")
        if point_count > self.max_points:
            raise ValueError(f"point cloud exceeds point budget: {point_count} > {self.max_points}")
        return point_count
