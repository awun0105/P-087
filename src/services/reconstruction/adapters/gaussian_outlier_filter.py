"""Bounded, opt-in statistical outlier removal for binary 3DGS PLY inputs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from src.models.contracts.reconstruction import GeometryStatisticalFilterEvidence
from src.services.reconstruction.rgb.geometry.voxel import StatisticalOutlierRemovalConfig

_MAX_HEADER_BYTES = 1024 * 1024
_QUERY_CHUNK_ROWS = 8192
_PLY_TYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "<i2",
    "int16": "<i2",
    "ushort": "<u2",
    "uint16": "<u2",
    "int": "<i4",
    "int32": "<i4",
    "uint": "<u4",
    "uint32": "<u4",
    "float": "<f4",
    "float32": "<f4",
    "double": "<f8",
    "float64": "<f8",
}


def _checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def _layout(source: Path) -> tuple[bytes, int, np.dtype, int, int]:
    """Validate a fixed-width binary PLY and return header, count, dtype and size."""
    header_lines: list[bytes] = []
    header_bytes = 0
    with source.open("rb") as stream:
        while True:
            line = stream.readline(_MAX_HEADER_BYTES - header_bytes + 1)
            if not line:
                raise ValueError("Gaussian PLY has no complete header")
            if len(line) > _MAX_HEADER_BYTES - header_bytes:
                raise ValueError("Gaussian PLY header exceeds the configured limit")
            header_lines.append(line)
            header_bytes += len(line)
            if line.rstrip(b"\r\n") == b"end_header":
                data_offset = stream.tell()
                break

    try:
        decoded = [line.decode("ascii").strip() for line in header_lines]
    except UnicodeDecodeError as error:
        raise ValueError("Gaussian PLY header must be ASCII") from error
    format_lines = [line for line in decoded if line.startswith("format ")]
    if not decoded or decoded[0] != "ply" or format_lines != ["format binary_little_endian 1.0"]:
        raise ValueError("SOR supports only PLY binary_little_endian 1.0")

    current_element: str | None = None
    current_count = 0
    vertex_count: int | None = None
    vertex_line_index: int | None = None
    fields: list[tuple[str, str]] = []
    for index, line in enumerate(decoded):
        tokens = line.split()
        if not tokens or tokens[0] in {"ply", "format", "comment", "obj_info", "end_header"}:
            continue
        if tokens[0] == "element":
            if len(tokens) != 3:
                raise ValueError("Gaussian PLY has an invalid element declaration")
            current_element = tokens[1]
            try:
                current_count = int(tokens[2])
            except ValueError as error:
                raise ValueError("Gaussian PLY element count is invalid") from error
            if current_count < 0:
                raise ValueError("Gaussian PLY element count cannot be negative")
            if current_element == "vertex":
                if vertex_count is not None:
                    raise ValueError("Gaussian PLY must contain exactly one vertex element")
                vertex_count = current_count
                vertex_line_index = index
            elif current_count:
                raise ValueError("SOR cannot safely rewrite PLY files with non-vertex elements")
            continue
        if tokens[0] == "property":
            if current_element == "vertex":
                if len(tokens) != 3 or tokens[1] == "list":
                    raise ValueError("SOR requires scalar Gaussian vertex properties")
                ply_type, name = tokens[1], tokens[2]
                numpy_type = _PLY_TYPES.get(ply_type)
                if numpy_type is None:
                    raise ValueError(f"SOR does not support PLY property type '{ply_type}'")
                fields.append((name, numpy_type))
            elif current_count:
                raise ValueError("SOR cannot safely rewrite PLY list properties")

    if vertex_count is None or vertex_count <= 0 or vertex_line_index is None:
        raise ValueError("Gaussian PLY requires a non-empty vertex element")
    names = [name for name, _ in fields]
    if len(names) != len(set(names)):
        raise ValueError("Gaussian PLY contains duplicate vertex property names")
    if not {"x", "y", "z"} <= set(names):
        raise ValueError("Gaussian PLY is missing x/y/z vertex properties")
    dtype = np.dtype(fields, align=False)
    for axis in ("x", "y", "z"):
        if dtype[axis].kind != "f":
            raise ValueError("Gaussian position properties must use floating-point types")
    expected_size = data_offset + vertex_count * dtype.itemsize
    if source.stat().st_size != expected_size:
        raise ValueError("Gaussian PLY payload size does not match its vertex declaration")
    return b"".join(header_lines), data_offset, dtype, vertex_count, vertex_line_index


def filter_gaussian_ply(
    source: Path,
    destination: Path,
    config: StatisticalOutlierRemovalConfig,
) -> GeometryStatisticalFilterEvidence:
    """Write a deterministic SOR subset while retaining every source vertex field.

    This is diagnostic cleanup only. SOR cannot distinguish a true sparse obstacle
    from a floater, so callers must keep it opt-in and preserve the original PLY.
    """
    if source.resolve() == destination.resolve():
        raise ValueError("SOR output must not overwrite its source PLY")
    source_checksum = _checksum(source)
    header, offset, dtype, count, vertex_line_index = _layout(source)
    if count > config.max_gaussians:
        raise ValueError("Gaussian count exceeds the configured SOR resource bound")
    if count <= config.neighbors:
        raise ValueError("Gaussian count must exceed the configured SOR neighbor count")

    rows = np.memmap(source, dtype=dtype, mode="r", offset=offset, shape=(count,))
    try:
        return _filter_mapped_rows(
            source,
            source_checksum,
            destination,
            config,
            header,
            vertex_line_index,
            rows,
            count,
        )
    finally:
        rows._mmap.close()


def _filter_mapped_rows(
    source: Path,
    source_checksum: str,
    destination: Path,
    config: StatisticalOutlierRemovalConfig,
    header: bytes,
    vertex_line_index: int,
    rows: np.memmap,
    count: int,
) -> GeometryStatisticalFilterEvidence:
    points = np.empty((count, 3), dtype=np.float64)
    points[:, 0], points[:, 1], points[:, 2] = rows["x"], rows["y"], rows["z"]
    if not np.isfinite(points).all():
        raise ValueError("Gaussian position contains a non-finite value")

    tree = cKDTree(points, compact_nodes=True, balanced_tree=True, copy_data=False)
    mean_distances = np.empty(count, dtype=np.float64)
    neighbor_count = config.neighbors + 1
    for start in range(0, count, _QUERY_CHUNK_ROWS):
        stop = min(start + _QUERY_CHUNK_ROWS, count)
        distances, _ = tree.query(points[start:stop], k=neighbor_count, workers=1)
        mean_distances[start:stop] = distances[:, 1:].mean(axis=1)

    mean = float(mean_distances.mean())
    deviation = float(mean_distances.std())
    threshold = mean + config.standard_deviation_ratio * deviation
    retained_indices = np.flatnonzero(mean_distances <= threshold)
    if not len(retained_indices):
        raise ValueError("SOR removed every Gaussian")

    lines = header.splitlines(keepends=True)
    original_line = lines[vertex_line_index]
    line_ending = b"\r\n" if original_line.endswith(b"\r\n") else b"\n"
    lines[vertex_line_index] = f"element vertex {len(retained_indices)}".encode("ascii") + line_ending
    if destination.exists():
        raise FileExistsError(destination)
    created = False
    try:
        with destination.open("xb") as stream:
            created = True
            stream.write(b"".join(lines))
            for start in range(0, len(retained_indices), _QUERY_CHUNK_ROWS):
                indices = retained_indices[start : start + _QUERY_CHUNK_ROWS]
                stream.write(np.ascontiguousarray(rows[indices]).tobytes())
        if _checksum(source) != source_checksum:
            raise ValueError("Gaussian source changed while SOR was running")
        return GeometryStatisticalFilterEvidence(
            input_checksum=source_checksum,
            output_checksum=_checksum(destination),
            input_gaussian_count=count,
            retained_gaussian_count=len(retained_indices),
            removed_gaussian_count=count - len(retained_indices),
            neighbors=config.neighbors,
            standard_deviation_ratio=config.standard_deviation_ratio,
            max_gaussians=config.max_gaussians,
            mean_neighbor_distance_m=mean,
            standard_deviation_m=deviation,
            threshold_m=threshold,
        )
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
