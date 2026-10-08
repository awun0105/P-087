"""Streaming integrity + exact bounds cho toàn bộ scalar PLY/PCD payload."""

import hashlib
import math
import struct
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO, Literal

import numpy as np
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel
from src.services.reconstruction.lidar.cloud_header import CloudHeader, read_header

_UNIT_TO_METERS = {"m": 1.0, "cm": 0.01, "mm": 0.001}


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
    return _load_xyz_points(path, max_points, supported_formats={"pcd"}, distance_unit="m")


def load_registration_xyz_points(
    path: Path,
    *,
    max_points: int,
    distance_unit: Literal["m", "cm", "mm"],
    expected_source_checksum: str,
    expected_header_checksum: str,
    expected_point_count: int,
    expected_geometry_format: Literal["pcd", "ply"],
) -> np.ndarray:
    """Decode the exact verified PCD/PLY payload and return XYZ coordinates in metres."""
    if distance_unit not in _UNIT_TO_METERS:
        raise ValueError("registration source distance unit must be m, cm, or mm")
    return _load_xyz_points(
        path,
        max_points,
        supported_formats={"pcd", "ply"},
        distance_unit=distance_unit,
        expected_source_checksum=expected_source_checksum,
        expected_header_checksum=expected_header_checksum,
        expected_point_count=expected_point_count,
        expected_geometry_format=expected_geometry_format,
    )


def _load_xyz_points(
    path: Path,
    max_points: int,
    *,
    supported_formats: set[str],
    distance_unit: Literal["m", "cm", "mm"],
    expected_source_checksum: str | None = None,
    expected_header_checksum: str | None = None,
    expected_point_count: int | None = None,
    expected_geometry_format: str | None = None,
) -> np.ndarray:
    if not path.is_file():
        raise ValueError("point cloud file does not exist")
    if (expected_source_checksum is None) != (expected_header_checksum is None):
        raise ValueError("source and header checksums must be supplied together")
    digest = hashlib.sha256() if expected_source_checksum is not None else None
    with path.open("rb") as stream:
        header = read_header(stream)
        if header.geometry_format not in supported_formats or header.encoding not in {
            "ascii",
            "binary",
            "binary_little_endian",
            "binary_big_endian",
        }:
            if supported_formats == {"pcd"}:
                raise ValueError("odometry supports PCD ascii and uncompressed binary scans only")
            raise ValueError("registration supports scalar PCD/PLY ascii and uncompressed binary clouds only")
        if header.point_count > max_points:
            budget = "per-scan" if supported_formats == {"pcd"} else "registration source"
            raise ValueError(f"point cloud exceeds {budget} point budget")
        if expected_geometry_format is not None and header.geometry_format != expected_geometry_format:
            raise ValueError("point-cloud format differs from the verified source")
        if expected_point_count is not None and header.point_count != expected_point_count:
            raise ValueError("point-cloud count differs from the verified source")
        if expected_header_checksum is not None:
            header_size = stream.tell()
            stream.seek(0)
            header_bytes = stream.read(header_size)
            if len(header_bytes) != header_size:
                raise ValueError("point-cloud header changed during payload decoding")
            actual_header_checksum = "sha256:" + hashlib.sha256(header_bytes).hexdigest()
            if actual_header_checksum != expected_header_checksum:
                raise ValueError("point-cloud header checksum differs from the verified source")
            if digest is None:
                raise ValueError("header checksum requires a source checksum")
            digest.update(header_bytes)
            stream.seek(header_size)
        points = np.empty((header.point_count, 3), dtype=np.float64)
        records = (
            _ascii_records(stream, header, digest.update if digest is not None else None)
            if header.encoding == "ascii"
            else _binary_records(stream, header, digest.update if digest is not None else None)
        )
        for row, record in enumerate(records):
            points[row] = [record[index] for index in header.xyz]
    if not np.isfinite(points).all():
        raise ValueError("point cloud contains non-finite points (NaN or Inf)")
    if digest is not None and "sha256:" + digest.hexdigest() != expected_source_checksum:
        raise ValueError("point-cloud source checksum differs from the verified source")
    points *= _UNIT_TO_METERS[distance_unit]
    return points


def _ascii_records(
    stream: BinaryIO, header: CloudHeader, on_bytes: Callable[[bytes], None] | None = None
) -> Iterator[tuple[float, ...]]:
    layout = struct.Struct("<" + "".join(header.codes))
    for _ in range(header.point_count):
        raw = stream.readline(1_048_577)
        if not raw or len(raw) > 1_048_576:
            raise ValueError("truncated or oversized point-cloud payload record")
        if on_bytes is not None:
            on_bytes(raw)
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
        if on_bytes is not None:
            on_bytes(chunk)
        if chunk.strip():
            raise ValueError("extra point-cloud payload beyond declared count")


def _binary_records(
    stream: BinaryIO, header: CloudHeader, on_bytes: Callable[[bytes], None] | None = None
) -> Iterator[tuple[float, ...]]:
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
        if on_bytes is not None:
            on_bytes(chunk)
        yield from layout.iter_unpack(chunk)
        remaining -= count
