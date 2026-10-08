"""Streaming integrity + exact bounds cho toàn bộ scalar PLY/PCD payload."""

import math
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Literal

import numpy as np
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel
from src.services.reconstruction.lidar.cloud_header import CloudHeader, read_header


class PointCloudStats(ContractModel):
    """Bounds đã tính từ mọi điểm, không phải placeholder/header estimate."""

    point_count: int = Field(gt=0)
    geometry_format: Literal["ply", "pcd"]
    bounds_min: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    bounds_max: tuple[FiniteFloat, FiniteFloat, FiniteFloat]


def inspect_point_cloud(path: Path, max_points: int = 20_000_000) -> PointCloudStats:
    """Bound header/count trước decode; kiểm tất cả points và exact payload size."""
    if not path.is_file():
        raise ValueError("point cloud file does not exist")
    with path.open("rb") as stream:
        header = read_header(stream)
        if header.point_count > max_points:
            raise ValueError("point cloud exceeds point budget")
        records = _ascii_records(stream, header) if header.encoding == "ascii" else _binary_records(stream, header)
        low, high = [math.inf] * 3, [-math.inf] * 3
        for record in records:
            point = [record[index] for index in header.xyz]
            if not all(math.isfinite(value) for value in point):
                raise ValueError("point cloud contains non-finite points (NaN or Inf)")
            low = [min(a, b) for a, b in zip(low, point, strict=True)]
            high = [max(a, b) for a, b in zip(high, point, strict=True)]
    return PointCloudStats(
        point_count=header.point_count,
        geometry_format=header.geometry_format,
        bounds_min=tuple(low),
        bounds_max=tuple(high),
    )


def inspect_point_cloud_header(path: Path) -> int:
    """Header-only count; không phải bằng chứng payload đã hợp lệ."""
    with path.open("rb") as stream:
        return read_header(stream).point_count


def load_xyz_points(path: Path, max_points: int = 5_000_000) -> np.ndarray:
    """Decode a bounded ASCII/binary PCD into finite XYZ metres for odometry."""
    if not path.is_file():
        raise ValueError("point cloud file does not exist")
    with path.open("rb") as stream:
        header = read_header(stream)
        if header.geometry_format != "pcd" or header.encoding not in {"ascii", "binary"}:
            raise ValueError("odometry supports PCD ascii and uncompressed binary scans only")
        if header.point_count > max_points:
            raise ValueError("point cloud exceeds per-scan point budget")
        points = np.empty((header.point_count, 3), dtype=np.float64)
        records = _ascii_records(stream, header) if header.encoding == "ascii" else _binary_records(stream, header)
        for row, record in enumerate(records):
            points[row] = [record[index] for index in header.xyz]
    if not np.isfinite(points).all():
        raise ValueError("point cloud contains non-finite points (NaN or Inf)")
    return points


def _ascii_records(stream: BinaryIO, header: CloudHeader) -> Iterator[tuple[float, ...]]:
    layout = struct.Struct("<" + "".join(header.codes))
    for _ in range(header.point_count):
        raw = stream.readline(1_048_577)
        if not raw or len(raw) > 1_048_576:
            raise ValueError("truncated or oversized point-cloud payload record")
        try:
            values = raw.decode("ascii").split()
            if len(values) != len(header.codes):
                raise ValueError("point-cloud payload field count mismatch")
            record = tuple(float(v) if c in "fd" else int(v) for v, c in zip(values, header.codes, strict=True))
            # Enforce declared scalar width; rounding must match native float32 reader.
            decoded = layout.unpack(layout.pack(*record))
        except (UnicodeDecodeError, OverflowError, struct.error) as error:
            raise ValueError("invalid point-cloud scalar payload") from error
        yield decoded
    while chunk := stream.read(65536):
        if chunk.strip():
            raise ValueError("extra point-cloud payload beyond declared count")


def _binary_records(stream: BinaryIO, header: CloudHeader) -> Iterator[tuple[float, ...]]:
    endian = ">" if header.encoding == "binary_big_endian" else "<"
    layout = struct.Struct(endian + "".join(header.codes))
    start = stream.tell()
    stream.seek(0, 2)
    if stream.tell() - start != header.point_count * layout.size:
        raise ValueError("binary point-cloud payload length mismatch")
    stream.seek(start)
    remaining = header.point_count
    while remaining:
        count = min(remaining, max(1, 65536 // layout.size))
        chunk = stream.read(count * layout.size)
        if len(chunk) != count * layout.size:
            raise ValueError("truncated binary point-cloud payload")
        yield from layout.iter_unpack(chunk)
        remaining -= count
