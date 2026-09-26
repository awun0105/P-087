"""Strict scalar-cloud envelope trước native IO; không suy geometry từ header.

Open3D v0.19.0 FilePLY.cpp preallocates vertex buffer trước ply_read; Python
read_point_cloud không trả success flag. Cần kiểm envelope/payload riêng trước
khi dùng Open3D transform/filter. List elements và compressed PCD chưa qualify.
"""

from dataclasses import dataclass
from typing import BinaryIO, Literal

PLY_TYPES = {
    "char": "b",
    "int8": "b",
    "uchar": "B",
    "uint8": "B",
    "short": "h",
    "int16": "h",
    "ushort": "H",
    "uint16": "H",
    "int": "i",
    "int32": "i",
    "uint": "I",
    "uint32": "I",
    "float": "f",
    "float32": "f",
    "double": "d",
    "float64": "d",
}
PCD_TYPES = {
    ("F", 4): "f",
    ("F", 8): "d",
    ("I", 1): "b",
    ("I", 2): "h",
    ("I", 4): "i",
    ("I", 8): "q",
    ("U", 1): "B",
    ("U", 2): "H",
    ("U", 4): "I",
    ("U", 8): "Q",
}


@dataclass(frozen=True)
class CloudHeader:
    """Scalar layout đã validate; xyz offsets là index record, không byte offset."""

    geometry_format: Literal["ply", "pcd"]
    encoding: str
    point_count: int
    fields: tuple[str, ...]
    codes: tuple[str, ...]

    @property
    def xyz(self) -> tuple[int, int, int]:
        """Coordinate lookup theo field name, không giả định ba cột đầu."""
        return (self.fields.index("x"), self.fields.index("y"), self.fields.index("z"))


def _line(stream: BinaryIO) -> list[str]:
    raw = stream.readline(8193)
    if not raw or len(raw) > 8192 or stream.tell() > 131072:
        raise ValueError("invalid or oversized point-cloud header")
    try:
        return raw.decode("ascii").strip().split()
    except UnicodeDecodeError as error:
        raise ValueError("point-cloud header must be ASCII") from error


def read_header(stream: BinaryIO) -> CloudHeader:
    """Đọc envelope có budget; reject unknown/ambiguous format thay vì đoán."""
    first = _line(stream)
    stream.seek(0)
    if first == ["ply"]:
        header = _ply_header(stream)
    elif first and (first[0] == "VERSION" or first[0].startswith("#")):
        header = _pcd_header(stream)
    else:
        raise ValueError("unsupported point cloud format; expected PLY or PCD")
    if header.point_count < 1:
        raise ValueError("point cloud has too few points")
    if len(set(header.fields)) != len(header.fields) or not all(a in header.fields for a in ("x", "y", "z")):
        raise ValueError("point cloud requires unique fields including x, y, z")
    return header


def _ply_header(stream: BinaryIO) -> CloudHeader:
    _line(stream)
    fmt = _line(stream)
    if len(fmt) != 3 or fmt[0] != "format" or fmt[2] != "1.0":
        raise ValueError("invalid PLY format header")
    if fmt[1] not in {"ascii", "binary_little_endian", "binary_big_endian"}:
        raise ValueError("unsupported PLY encoding")
    count, fields, codes = None, [], []
    while True:
        parts = _line(stream)
        if not parts or parts[0] in {"comment", "obj_info"}:
            continue
        if parts == ["end_header"]:
            break
        if len(parts) == 3 and parts[:2] == ["element", "vertex"] and count is None:
            count = int(parts[2])
        elif len(parts) == 3 and parts[0] == "property" and count is not None and parts[1] in PLY_TYPES:
            fields.append(parts[2])
            codes.append(PLY_TYPES[parts[1]])
        else:
            raise ValueError("unsupported PLY layout: require scalar vertex-only cloud")
    if count is None:
        raise ValueError("missing PLY vertex count")
    return CloudHeader("ply", fmt[1], count, tuple(fields), tuple(codes))


def _pcd_header(stream: BinaryIO) -> CloudHeader:
    values: dict[str, list[str]] = {}
    while True:
        parts = _line(stream)
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] in values:
            raise ValueError("duplicate PCD header key")
        values[parts[0]] = parts[1:]
        if parts[0] == "DATA":
            break
    required = {"VERSION", "FIELDS", "SIZE", "TYPE", "WIDTH", "HEIGHT", "POINTS", "DATA"}
    if not required.issubset(values) or set(values) - required - {"COUNT", "VIEWPOINT"}:
        raise ValueError("incomplete or unsupported PCD header")
    if values["VERSION"] not in ([".7"], ["0.7"]) or values["DATA"] not in (["ascii"], ["binary"]):
        raise ValueError("unsupported PCD encoding/version; convert compressed input offline")
    for key in ("WIDTH", "HEIGHT", "POINTS"):
        if len(values[key]) != 1 or int(values[key][0]) < 1:
            raise ValueError("invalid PCD dimensions")
    count = int(values["POINTS"][0])
    if count != int(values["WIDTH"][0]) * int(values["HEIGHT"][0]):
        raise ValueError("PCD POINTS must equal WIDTH * HEIGHT")
    fields, codes = _pcd_fields(values)
    return CloudHeader("pcd", values["DATA"][0], count, fields, codes)


def _pcd_fields(values: dict[str, list[str]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    names = values["FIELDS"]
    counts = values.get("COUNT", ["1"] * len(names))
    if not len(names) == len(values["SIZE"]) == len(values["TYPE"]) == len(counts):
        raise ValueError("PCD field layout length mismatch")
    fields, codes = [], []
    for name, size, kind, count in zip(names, values["SIZE"], values["TYPE"], counts, strict=True):
        key, repeat = (kind, int(size)), int(count)
        if key not in PCD_TYPES or not 1 <= repeat <= 1024 or (name in {"x", "y", "z"} and repeat != 1):
            raise ValueError("unsupported PCD scalar field layout")
        fields.extend([name] if repeat == 1 else [f"{name}[{index}]" for index in range(repeat)])
        codes.extend([PCD_TYPES[key]] * repeat)
    return tuple(fields), tuple(codes)
