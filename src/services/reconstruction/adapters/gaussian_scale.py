"""Biến đổi tỷ lệ metric scale cho 3D Gaussian Splatting PLY (REC-05).

Áp dụng giải thuật từ Re3Sim:
- Tọa độ không gian: p' = s * p
- Log-scale covariance: scale_i' = scale_i + ln(s) (vì scale_i = ln(sigma_i))
"""

import math
import shutil
import struct
from pathlib import Path

PLY_TYPE_MAP: dict[str, tuple[str, int]] = {
    "char": ("b", 1),
    "int8": ("b", 1),
    "uchar": ("B", 1),
    "uint8": ("B", 1),
    "short": ("h", 2),
    "int16": ("h", 2),
    "ushort": ("H", 2),
    "uint16": ("H", 2),
    "int": ("i", 4),
    "int32": ("i", 4),
    "uint": ("I", 4),
    "uint32": ("I", 4),
    "float": ("f", 4),
    "float32": ("f", 4),
    "double": ("d", 8),
    "float64": ("d", 8),
}


def _parse_vertex_properties(lines: list[str]) -> tuple[int, int, dict[str, int]]:
    """Phân tích số đỉnh, stride và offset của các thuộc tính cần biến đổi."""
    count, offset = 0, 0
    offsets: dict[str, int] = {}
    for line in lines:
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0] == "element" and parts[1] == "vertex":
            count = int(parts[2])
        elif len(parts) >= 3 and parts[0] == "property" and parts[1] in PLY_TYPE_MAP:
            name = parts[2]
            if name in ("x", "y", "z", "scale_0", "scale_1", "scale_2"):
                offsets[name] = offset
            offset += PLY_TYPE_MAP[parts[1]][1]
    return count, offset, offsets


def _scale_vertex_buffer(data: bytearray, header_end: int, meta: tuple[int, int, dict[str, int]], scale: float) -> None:
    """Biến đổi in-place tọa độ xyz và log-scales trong buffer nhị phân."""
    count, stride, offsets = meta
    log_s = math.log(scale)
    has_scales = all(k in offsets for k in ("scale_0", "scale_1", "scale_2"))
    x_off, y_off, z_off = offsets["x"], offsets["y"], offsets["z"]
    for i in range(count):
        base = header_end + i * stride
        for off in (x_off, y_off, z_off):
            val = struct.unpack_from("<f", data, base + off)[0]
            struct.pack_into("<f", data, base + off, val * scale)
        if has_scales:
            s_base = base + offsets["scale_0"]
            s0, s1, s2 = struct.unpack_from("<fff", data, s_base)
            struct.pack_into("<fff", data, s_base, s0 + log_s, s1 + log_s, s2 + log_s)


def scale_gaussian_ply(src_path: Path, dst_path: Path, scale: float) -> None:
    """Sao chép và co giãn Gaussian PLY sang hệ mét chuẩn (working derivative)."""
    if abs(scale - 1.0) < 1e-9:
        shutil.copyfile(src_path, dst_path)
        return
    data = bytearray(src_path.read_bytes())
    marker = b"end_header\n"
    idx = data.find(marker)
    if idx == -1:
        shutil.copyfile(src_path, dst_path)
        return
    header_end = idx + len(marker)
    header_text = data[:header_end].decode("ascii", errors="replace")
    if "format binary_little_endian 1.0" not in header_text:
        shutil.copyfile(src_path, dst_path)
        return
    meta = _parse_vertex_properties(header_text.splitlines())
    if "x" in meta[2] and "y" in meta[2] and "z" in meta[2]:
        _scale_vertex_buffer(data, header_end, meta, scale)
    dst_path.write_bytes(data)
