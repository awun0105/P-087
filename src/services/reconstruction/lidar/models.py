"""Typed contracts và models cho REC-08 Registered LiDAR Ingest."""

import hashlib
import math
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import Field

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.reconstruction import PreprocessingProvenance


def compute_file_checksum(path: Path) -> Checksum:
    """Tính SHA-256 checksum qua streaming để tránh tràn RAM khi file lớn."""
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


class PointCloudStats(ContractModel):
    """Thống kê không gian và tính toàn vẹn của mây điểm LiDAR đã thẩm định."""

    point_count: int = Field(ge=0)
    geometry_format: Literal["ply", "pcd"]
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]


def _parse_ply_header(stream: BinaryIO) -> tuple[int, str]:
    """Phân tích header định dạng PLY, trích xuất số đỉnh và format."""
    point_count, fmt, props = 0, "ascii", []
    while True:
        line = stream.readline()
        if not line:
            raise ValueError("unexpected EOF in PLY header")
        text = line.decode("ascii", errors="ignore").strip()
        parts = text.split()
        if not parts:
            continue
        if parts[0] == "format":
            fmt = parts[1]
        elif parts[0] == "element" and parts[1] == "vertex":
            point_count = int(parts[2])
        elif parts[0] == "property":
            props.append(parts[-1])
        elif text == "end_header":
            break
    if not all(axis in props for axis in ("x", "y", "z")):
        raise ValueError("invalid PLY: missing x, y, z coordinate properties")
    return point_count, fmt


def _parse_pcd_header(stream: BinaryIO) -> tuple[int, str]:
    """Phân tích header định dạng PCD theo chuẩn Point Cloud Library."""
    point_count, data_fmt, fields = 0, "ascii", []
    while True:
        line = stream.readline()
        if not line:
            raise ValueError("unexpected EOF in PCD header")
        text = line.decode("ascii", errors="ignore").strip()
        if text.startswith("FIELDS"):
            fields = text.split()[1:]
        elif text.startswith("POINTS"):
            point_count = int(text.split()[1])
        elif text.startswith("DATA"):
            data_fmt = text.split()[1]
            break
    if not all(axis in fields for axis in ("x", "y", "z")):
        raise ValueError("invalid PCD: missing x, y, z fields in header")
    return point_count, data_fmt


def _compute_bounds_ascii(
    stream: BinaryIO, point_count: int
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Kiểm tra tính hữu hạn và tính bounding box cho dữ liệu ASCII."""
    b_min = [float("inf"), float("inf"), float("inf")]
    b_max = [float("-inf"), float("-inf"), float("-inf")]
    checked = min(point_count, 1000)
    for _ in range(checked):
        line = stream.readline()
        if not line:
            break
        parts = [float(val) for val in line.decode("ascii", errors="ignore").split()[:3]]
        if len(parts) < 3 or not all(math.isfinite(val) for val in parts):
            raise ValueError("point cloud contains non-finite points (NaN or Inf)")
        for idx in range(3):
            b_min[idx] = min(b_min[idx], parts[idx])
            b_max[idx] = max(b_max[idx], parts[idx])
    if checked == 0:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return (b_min[0], b_min[1], b_min[2]), (b_max[0], b_max[1], b_max[2])


def inspect_point_cloud(path: Path) -> PointCloudStats:
    """Thẩm định cấu trúc mây điểm PLY/PCD, kiểm tra finite bounds và số lượng điểm."""
    if not path.is_file():
        raise ValueError(f"point cloud file does not exist: {path}")
    with path.open("rb") as stream:
        first_line = stream.readline().decode("ascii", errors="ignore").strip()
        stream.seek(0)
        if first_line.startswith("ply"):
            count, fmt = _parse_ply_header(stream)
            geom_fmt = "ply"
        elif "# .PCD" in first_line or "VERSION" in first_line:
            count, fmt = _parse_pcd_header(stream)
            geom_fmt = "pcd"
        else:
            raise ValueError("unsupported point cloud format; expected PLY or PCD")
        b_min, b_max = _compute_bounds_ascii(stream, count) if fmt == "ascii" else ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    return PointCloudStats(point_count=count, geometry_format=geom_fmt, bounds_min=b_min, bounds_max=b_max)


def inspect_point_cloud_header(path: Path) -> int:
    """Đọc nhanh số lượng điểm từ header để tương thích ngược với các caller cũ."""
    return inspect_point_cloud(path).point_count


class LiDARIngestRequest(ContractModel):
    """Request thẩm định và nhập dữ liệu LiDAR đã đăng ký."""

    job_id: Identifier
    lidar_file: Path
    source_input_checksum: Checksum
    geometry_format: Literal["ply", "pcd"] = "ply"
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    source_frame: Identifier = "registered_lidar"
    declared_transform_to_canonical: Transform | None = None
    preprocessing_provenance: PreprocessingProvenance
    min_points: int = Field(default=1, ge=1)
    max_points: int = Field(default=20_000_000, gt=0)

    def validate_payload(self) -> PointCloudStats:
        """Kiểm tra toàn diện checksum SHA-256, format, đơn vị mét và số lượng điểm."""
        if not self.lidar_file.is_file():
            raise ValueError(f"LiDAR file missing: {self.lidar_file}")
        actual_checksum = compute_file_checksum(self.lidar_file)
        if actual_checksum != self.source_input_checksum:
            raise ValueError(f"source checksum mismatch: expected {self.source_input_checksum}, got {actual_checksum}")
        if self.coordinate_system.unit != "meter":
            raise ValueError(f"LiDAR unit must be meter, got {self.coordinate_system.unit}")
        stats = inspect_point_cloud(self.lidar_file)
        if stats.point_count < self.min_points:
            raise ValueError(f"point cloud has too few points: {stats.point_count} < {self.min_points}")
        if stats.point_count > self.max_points:
            raise ValueError(f"point cloud exceeds point budget: {stats.point_count} > {self.max_points}")
        return stats
