"""Regressions: validate toàn payload, không giả geometry từ header."""

import struct
from pathlib import Path

import pytest

from src.services.reconstruction.lidar import inspect_point_cloud


def _ply(path: Path, data: bytes, count: int = 1) -> Path:
    header = (
        f"ply\nformat binary_little_endian 1.0\nelement vertex {count}\n"
        "property uchar red\nproperty double z\nproperty float x\nproperty float y\nend_header\n"
    )
    path.write_bytes(header.encode() + data)
    return path


def test_binary_bounds_use_declared_properties(tmp_path: Path) -> None:
    cloud = _ply(tmp_path / "cloud.ply", struct.pack("<Bdff", 255, -8, 3, 5))
    stats = inspect_point_cloud(cloud)
    assert stats.bounds_min == stats.bounds_max == (3, 5, -8)


@pytest.mark.parametrize("payload", [b"", b"\x00" * 16, b"\x00" * 18])
def test_binary_rejects_wrong_payload_length(tmp_path: Path, payload: bytes) -> None:
    with pytest.raises(ValueError, match="payload"):
        inspect_point_cloud(_ply(tmp_path / "cloud.ply", payload))


def test_nonfinite_after_first_thousand_is_rejected(tmp_path: Path) -> None:
    cloud = tmp_path / "cloud.ply"
    cloud.write_text(
        "ply\nformat ascii 1.0\nelement vertex 1001\nproperty float x\n"
        "property float y\nproperty float z\nend_header\n" + "1 2 3\n" * 1000 + "nan 0 0\n"
    )
    with pytest.raises(ValueError, match="non-finite"):
        inspect_point_cloud(cloud)


def test_ascii_truncated_cloud_rejected(tmp_path: Path) -> None:
    cloud = tmp_path / "cloud.ply"
    cloud.write_text(
        "ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\n"
        "property float y\nproperty float z\nend_header\n1 2 3\n"
    )
    with pytest.raises(ValueError, match="payload"):
        inspect_point_cloud(cloud)


@pytest.mark.parametrize("encoding", ["ascii", "binary_little_endian", "binary_big_endian"])
def test_all_encodings_have_exact_bounds(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "cloud.ply"
    header = (
        f"ply\nformat {encoding} 1.0\nelement vertex 1001\nproperty float y\n"
        "property float z\nproperty float x\nend_header\n"
    )
    values = [(2, 3, 1)] * 1000 + [(-8, 11, 50)]
    if encoding == "ascii":
        body = "".join(f"{y} {z} {x}\n" for y, z, x in values).encode()
    else:
        endian = ">" if encoding == "binary_big_endian" else "<"
        body = b"".join(struct.pack(endian + "fff", *v) for v in values)
    path.write_bytes(header.encode() + body)
    stats = inspect_point_cloud(path)
    assert stats.bounds_min == (1, -8, 3)
    assert stats.bounds_max == (50, 2, 11)


@pytest.mark.parametrize("encoding", ["ascii", "binary"])
def test_pcd_reordered_vector_fields(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "cloud.pcd"
    header = (
        "# .PCD v0.7\nVERSION 0.7\nFIELDS descriptor z x y\nSIZE 4 8 4 4\n"
        f"TYPE F F F F\nCOUNT 2 1 1 1\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA {encoding}\n"
    )
    body = b"9 8 -7 5 3\n" if encoding == "ascii" else struct.pack("<ffdff", 9, 8, -7, 5, 3)
    path.write_bytes(header.encode() + body)
    stats = inspect_point_cloud(path)
    assert stats.geometry_format == "pcd"
    assert stats.bounds_min == stats.bounds_max == (5, 3, -7)
    path.write_bytes(path.read_bytes()[:-5])
    with pytest.raises(ValueError, match="payload"):
        inspect_point_cloud(path)


def test_budget_checked_before_decoding(tmp_path: Path) -> None:
    path = _ply(tmp_path / "cloud.ply", b"", count=100)
    with pytest.raises(ValueError, match="point budget"):
        inspect_point_cloud(path, max_points=99)


def test_binary_nan_rejected(tmp_path: Path) -> None:
    path = _ply(tmp_path / "cloud.ply", struct.pack("<Bdff", 0, float("nan"), 0, 0))
    with pytest.raises(ValueError, match="non-finite"):
        inspect_point_cloud(path)


@pytest.mark.parametrize("property_line", ["property list uchar float xyz", "property float x"])
def test_ambiguous_vertex_layout_rejected(tmp_path: Path, property_line: str) -> None:
    path = tmp_path / "cloud.ply"
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\n"
        f"property float z\n{property_line}\nend_header\n1 2 3 4\n"
    )
    with pytest.raises(ValueError, match="layout|unique fields"):
        inspect_point_cloud(path)
