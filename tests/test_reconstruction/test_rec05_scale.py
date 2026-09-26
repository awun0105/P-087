"""Unit tests cho Gaussian PLY scaling (REC-05) theo giải thuật Re3Sim."""

import math
import struct
from pathlib import Path

from src.services.reconstruction.adapters.gaussian_scale import scale_gaussian_ply
from tests.test_reconstruction.test_rec04_brush import gaussian_ply


def test_scale_gaussian_ply_identity(tmp_path: Path) -> None:
    """Scale 1.0 giữ nguyên nội dung file nhị phân."""
    src = tmp_path / "src.ply"
    dst = tmp_path / "dst.ply"
    gaussian_ply(src)
    scale_gaussian_ply(src, dst, 1.0)
    assert dst.read_bytes() == src.read_bytes()


def test_scale_gaussian_ply_scales_coords_and_log_scales(tmp_path: Path) -> None:
    """Scale 2.0 nhân đôi xyz và cộng ln(2.0) vào scale_0, scale_1, scale_2."""
    src = tmp_path / "src.ply"
    dst = tmp_path / "dst.ply"
    gaussian_ply(src)
    scale_gaussian_ply(src, dst, 2.0)

    raw = dst.read_bytes()
    header_end = raw.find(b"end_header\n") + len(b"end_header\n")

    # Vertex 0: gốc ban đầu là (0, 0, 3) và log-scales là (-3, -3, -3)
    x, y, z = struct.unpack_from("<fff", raw, header_end)
    assert (x, y, z) == (0.0, 0.0, 6.0)

    # Offset của scale_0 là 28 bytes (x, y, z, f_dc_0, f_dc_1, f_dc_2, opacity = 7 floats)
    s0, s1, s2 = struct.unpack_from("<fff", raw, header_end + 28)
    expected_s = -3.0 + math.log(2.0)
    assert math.isclose(s0, expected_s, rel_tol=1e-5)
    assert math.isclose(s1, expected_s, rel_tol=1e-5)
    assert math.isclose(s2, expected_s, rel_tol=1e-5)


def test_scale_gaussian_ply_non_ply_fallback(tmp_path: Path) -> None:
    """File văn bản hoặc không phải binary PLY được sao chép an toàn không gây crash."""
    src = tmp_path / "plain.txt"
    dst = tmp_path / "plain_copy.txt"
    src.write_text("plain text data")
    scale_gaussian_ply(src, dst, 2.5)
    assert dst.read_text() == "plain text data"
