from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Literal

import numpy as np
import pytest

from src.services.reconstruction.lidar.cloud_payload import load_registration_xyz_points


def _checksum(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _payload(
    geometry_format: Literal["pcd", "ply"],
    encoding: Literal["ascii", "binary", "binary_little_endian", "binary_big_endian"],
) -> tuple[bytes, bytes]:
    if geometry_format == "ply":
        header = (
            f"ply\nformat {encoding} 1.0\nelement vertex 2\n"
            "property uchar intensity\nproperty double z\nproperty float x\nproperty float y\nend_header\n"
        ).encode()
    else:
        header = (
            "# .PCD v0.7\nVERSION 0.7\nFIELDS intensity z x y\nSIZE 1 8 4 4\n"
            f"TYPE U F F F\nCOUNT 1 1 1 1\nWIDTH 2\nHEIGHT 1\nPOINTS 2\nDATA {encoding}\n"
        ).encode()
    if encoding == "ascii":
        body = b"6 300 100 200\n7 600 400 500\n"
    else:
        endian = ">" if encoding == "binary_big_endian" else "<"
        body = struct.pack(endian + "Bdff", 6, 300, 100, 200) + struct.pack(endian + "Bdff", 7, 600, 400, 500)
    return header, body


def _load(
    path: Path,
    header: bytes,
    body: bytes,
    *,
    geometry_format: Literal["pcd", "ply"],
    distance_unit: Literal["m", "cm", "mm"],
    max_points: int = 2,
    expected_point_count: int = 2,
    expected_source_checksum: str | None = None,
    expected_header_checksum: str | None = None,
) -> np.ndarray:
    return load_registration_xyz_points(
        path,
        max_points=max_points,
        distance_unit=distance_unit,
        expected_source_checksum=expected_source_checksum or _checksum(header + body),
        expected_header_checksum=expected_header_checksum or _checksum(header),
        expected_point_count=expected_point_count,
        expected_geometry_format=geometry_format,
    )


@pytest.mark.parametrize(
    ("geometry_format", "encoding", "distance_unit", "expected"),
    [
        ("ply", "ascii", "cm", [[1, 2, 3], [4, 5, 6]]),
        ("ply", "binary_little_endian", "mm", [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]),
        ("ply", "binary_big_endian", "m", [[100, 200, 300], [400, 500, 600]]),
        ("pcd", "ascii", "mm", [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]),
        ("pcd", "binary", "cm", [[1, 2, 3], [4, 5, 6]]),
    ],
)
def test_registration_cloud_decodes_supported_layouts_and_converts_units(
    tmp_path: Path,
    geometry_format: Literal["pcd", "ply"],
    encoding: Literal["ascii", "binary", "binary_little_endian", "binary_big_endian"],
    distance_unit: Literal["m", "cm", "mm"],
    expected: list[list[float]],
) -> None:
    header, body = _payload(geometry_format, encoding)
    path = tmp_path / f"cloud.{geometry_format}"
    path.write_bytes(header + body)

    points = _load(path, header, body, geometry_format=geometry_format, distance_unit=distance_unit)

    np.testing.assert_allclose(points, expected)


def test_registration_cloud_rejects_source_or_header_checksum_drift(tmp_path: Path) -> None:
    header, body = _payload("ply", "ascii")
    path = tmp_path / "cloud.ply"
    path.write_bytes(header + body)
    with pytest.raises(ValueError, match="source checksum"):
        _load(
            path,
            header,
            body,
            geometry_format="ply",
            distance_unit="m",
            expected_source_checksum=_checksum(header + body + b"different"),
        )

    with pytest.raises(ValueError, match="header checksum"):
        _load(
            path,
            header,
            body,
            geometry_format="ply",
            distance_unit="m",
            expected_header_checksum=_checksum(b"forged header"),
        )


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b"6 300 100 200\n", "truncated"),
        (b"6 300 100 200\n7 600 nan 500\n", "non-finite"),
    ],
)
def test_registration_cloud_rejects_truncated_or_nonfinite_ascii_payload(
    tmp_path: Path, body: bytes, error: str
) -> None:
    header, _ = _payload("ply", "ascii")
    path = tmp_path / "cloud.ply"
    path.write_bytes(header + body)

    with pytest.raises(ValueError, match=error):
        _load(
            path,
            header,
            body,
            geometry_format="ply",
            distance_unit="m",
        )


def test_registration_cloud_enforces_profile_point_budget_before_payload_decode(tmp_path: Path) -> None:
    header, body = _payload("pcd", "binary")
    path = tmp_path / "cloud.pcd"
    path.write_bytes(header + body)

    with pytest.raises(ValueError, match="point budget"):
        _load(
            path,
            header,
            body,
            geometry_format="pcd",
            distance_unit="m",
            max_points=1,
        )


def test_registration_cloud_rejects_changed_count_and_unit_declarations(tmp_path: Path) -> None:
    header, body = _payload("ply", "ascii")
    path = tmp_path / "cloud.ply"
    path.write_bytes(header + body)
    with pytest.raises(ValueError, match="count differs"):
        _load(
            path,
            header,
            body,
            geometry_format="ply",
            distance_unit="m",
            expected_point_count=1,
        )
    with pytest.raises(ValueError, match="distance unit"):
        load_registration_xyz_points(
            path,
            max_points=2,
            distance_unit="feet",  # type: ignore[arg-type]
            expected_source_checksum=_checksum(header + body),
            expected_header_checksum=_checksum(header),
            expected_point_count=2,
            expected_geometry_format="ply",
        )
