"""Boundary của GLB tối giản do splat-transform 3.6.6 sinh, không là glTF importer."""

import json
import math
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.services.reconstruction.rgb.geometry.voxel import Vector3, world_from_native


@dataclass(frozen=True)
class CollisionMesh:
    """Positions/triangles của một mesh đã kiểm format và chỉ số."""

    positions: tuple[Vector3, ...]
    triangles: tuple[tuple[int, int, int], ...]


def _chunks(payload: bytes) -> tuple[dict, bytes]:
    if len(payload) < 28 or struct.unpack_from("<4sII", payload) != (b"glTF", 2, len(payload)):
        raise ValueError("invalid collision GLB header")
    length, kind = struct.unpack_from("<I4s", payload, 12)
    end = 20 + length
    if kind != b"JSON" or length % 4 or end + 8 > len(payload):
        raise ValueError("invalid collision JSON chunk")
    size, kind = struct.unpack_from("<I4s", payload, end)
    if kind != b"BIN\0" or size % 4 or end + 8 + size != len(payload):
        raise ValueError("invalid collision BIN chunk")
    document = json.loads(payload[20:end])
    if not isinstance(document, dict):
        raise ValueError("collision JSON must be an object")
    return document, payload[end + 8 :]


def _layout(document: dict, binary: bytes) -> None:
    # Pin upstream writer shape; unsupported node transforms/extensions phải fail closed.
    asset = document.get("asset")
    if (
        not isinstance(asset, dict)
        or set(asset) != {"version", "generator"}
        or asset.get("version") != "2.0"
        or asset.get("generator") not in {"splat-transform", "real2sim-lidar-collision"}
    ):
        raise ValueError("unsupported collision GLB producer")
    if document.get("scene") != 0 or document.get("scenes") != [{"nodes": [0]}]:
        raise ValueError("unsupported collision scene")
    if document.get("nodes") != [{"mesh": 0}]:
        raise ValueError("unexpected collision node transform")
    expected = [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]
    if document.get("meshes") != expected or document.get("buffers") != [{"byteLength": len(binary)}]:
        raise ValueError("unsupported collision mesh layout")
    if len(document.get("accessors", [])) != 2 or len(document.get("bufferViews", [])) != 2:
        raise ValueError("invalid collision accessors")
    if set(document) - {"asset", "scene", "scenes", "nodes", "meshes", "accessors", "bufferViews", "buffers"}:
        raise ValueError("unsupported collision GLB extensions")


def _array(document: dict, binary: bytes, index: int) -> tuple:
    accessor = document["accessors"][index]
    view = document["bufferViews"][index]
    if not isinstance(accessor, dict) or not isinstance(view, dict):
        raise ValueError("invalid collision accessor/view")
    component, kind, width, fmt = (5126, "VEC3", 12, "<fff") if index == 0 else (5125, "SCALAR", 4, "<I")
    count = accessor.get("count")
    expected = {"bufferView": index, "componentType": component, "count": count, "type": kind}
    actual = {k: v for k, v in accessor.items() if k not in {"min", "max"}}
    if actual != expected or type(count) is not int or count < 3:
        raise ValueError("invalid collision accessor type/count")
    offset = view.get("byteOffset")
    if type(offset) is not int or offset < 0 or offset % 4 or offset + count * width > len(binary):
        raise ValueError("collision buffer range exceeds payload")
    if view != {"buffer": 0, "byteOffset": offset, "byteLength": count * width, "target": 34962 + index}:
        raise ValueError("unsupported collision buffer view")
    return tuple(struct.iter_unpack(fmt, binary[offset : offset + count * width]))


def _ranges(document: dict, mesh: CollisionMesh) -> None:
    views = document["bufferViews"]
    if views[0]["byteOffset"] != 0 or views[1]["byteOffset"] != len(mesh.positions) * 12:
        raise ValueError("overlapping or noncontiguous collision buffers")
    accessor = document["accessors"][0]
    for key, operation in (("min", min), ("max", max)):
        expected = [operation(p[i] for p in mesh.positions) for i in range(3)]
        actual = accessor.get(key)
        if not isinstance(actual, list) or len(actual) != 3:
            raise ValueError("missing collision bounds")
        if any(not math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-7) for a, b in zip(actual, expected)):
            raise ValueError("collision bounds differ from positions")


def read_collision_glb(path: Path, *, allow_degenerate: bool = False) -> CollisionMesh:
    """Reject truncated/nonfinite/foreign-layout output trước publication.

    `allow_degenerate` chỉ dùng khi đọc output gốc của tool để canonical hóa; mọi mesh
    publish/consume vẫn phải sạch tam giác diện tích 0.
    """
    try:
        document, binary = _chunks(path.read_bytes())
        _layout(document, binary)
        positions = _array(document, binary, 0)
        indices = tuple(row[0] for row in _array(document, binary, 1))
        if len(indices) % 3 or any(i >= len(positions) for i in indices):
            raise ValueError("invalid collision triangle indices")
        if any(not math.isfinite(v) for point in positions for v in point):
            raise ValueError("nonfinite collision positions")
        triangles = tuple(zip(indices[::3], indices[1::3], indices[2::3], strict=True))
        mesh = CollisionMesh(positions, triangles)
        _ranges(document, mesh)
        if not allow_degenerate and topology(mesh)["degenerate_triangles"]:
            raise ValueError("degenerate collision triangles")
        if len(binary) != len(positions) * 12 + len(indices) * 4:
            raise ValueError("unexpected collision buffer payload")
        return mesh
    except (KeyError, TypeError, struct.error, UnicodeError) as error:
        raise ValueError("malformed collision GLB") from error


def topology(mesh: CollisionMesh) -> dict[str, int]:
    """Đo edge incidence thay vì suy watertight từ exit code hoặc file extension."""
    edges: Counter = Counter()
    degenerate = 0
    for a, b, c in mesh.triangles:
        p, q, r = mesh.positions[a], mesh.positions[b], mesh.positions[c]
        u, v = tuple(y - x for x, y in zip(p, q)), tuple(y - x for x, y in zip(p, r))
        cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        degenerate += len({a, b, c}) < 3 or sum(x * x for x in cross) == 0
        edges.update(tuple(sorted(edge)) for edge in ((a, b), (b, c), (c, a)))
    return dict(
        vertices=len(mesh.positions),
        triangles=len(mesh.triangles),
        degenerate_triangles=degenerate,
        boundary_edges=sum(count == 1 for count in edges.values()),
        nonmanifold_edges=sum(count > 2 for count in edges.values()),
    )


def _is_degenerate(mesh: CollisionMesh, triangle: tuple[int, int, int]) -> bool:
    a, b, c = triangle
    p, q, r = mesh.positions[a], mesh.positions[b], mesh.positions[c]
    u, v = tuple(y - x for x, y in zip(p, q)), tuple(y - x for x, y in zip(p, r))
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return len({a, b, c}) < 3 or sum(x * x for x in cross) == 0


def encode_collision_glb(mesh: CollisionMesh) -> bytes:
    """Encode canonical world-space vertices in the bounded collision GLB layout."""
    if len(mesh.positions) < 3 or not mesh.triangles:
        raise ValueError("collision mesh needs vertices and triangles")
    if any(not math.isfinite(value) for point in mesh.positions for value in point):
        raise ValueError("collision mesh positions must be finite")
    if any(index < 0 or index >= len(mesh.positions) for triangle in mesh.triangles for index in triangle):
        raise ValueError("collision mesh contains an out-of-range triangle index")
    if topology(mesh)["degenerate_triangles"]:
        raise ValueError("collision mesh contains degenerate triangles")
    if any(abs(value) > 3.4028234663852886e38 for point in mesh.positions for value in point):
        raise ValueError("collision mesh positions exceed GLB float32 range")

    position_bytes = b"".join(struct.pack("<fff", *point) for point in mesh.positions)
    indices = tuple(index for triangle in mesh.triangles for index in triangle)
    index_bytes = b"".join(struct.pack("<I", index) for index in indices)
    binary = position_bytes + index_bytes
    bounds = [min(point[axis] for point in mesh.positions) for axis in range(3)]
    upper = [max(point[axis] for point in mesh.positions) for axis in range(3)]
    document = {
        "asset": {"version": "2.0", "generator": "real2sim-lidar-collision"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(position_bytes), "byteLength": len(index_bytes), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(mesh.positions),
                "type": "VEC3",
                "min": bounds,
                "max": upper,
            },
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
    }
    encoded = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    payload = struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
    payload += struct.pack("<I4s", len(encoded), b"JSON") + encoded
    payload += struct.pack("<I4s", len(binary), b"BIN\0") + binary
    return payload


def canonicalize_collision(source: Path, destination: Path) -> CollisionMesh:
    """Bake R_x(+90°) vào derivative và bỏ tam giác diện tích 0; giữ nguyên native tool output.

    splat-transform 3.6.6 sau bước gộp mặt đồng phẳng có thể để lại vài tam giác thẳng
    hàng (Aisle_CW 2026-09-30: 397/225.142). Chúng không có diện tích nên không đổi bề mặt
    va chạm; số đã bỏ đo được bằng `degenerate_removed(source)` và ghi vào report.
    """
    mesh = read_collision_glb(source, allow_degenerate=True)
    kept = [triangle for triangle in mesh.triangles if not _is_degenerate(mesh, triangle)]
    if not kept:
        raise ValueError("collision mesh has no non-degenerate triangles")
    document, _ = _chunks(source.read_bytes())
    points = tuple(world_from_native(point) for point in mesh.positions)
    positions = b"".join(struct.pack("<fff", *point) for point in points)
    indices = b"".join(struct.pack("<3I", *triangle) for triangle in kept)
    data = positions + indices
    document["bufferViews"][1]["byteOffset"] = len(positions)
    document["bufferViews"][1]["byteLength"] = len(indices)
    document["accessors"][1]["count"] = len(kept) * 3
    document["buffers"][0]["byteLength"] = len(data)
    document["accessors"][0]["min"] = [min(p[i] for p in points) for i in range(3)]
    document["accessors"][0]["max"] = [max(p[i] for p in points) for i in range(3)]
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    payload = struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(data))
    payload += struct.pack("<I4s", len(encoded), b"JSON") + encoded
    payload += struct.pack("<I4s", len(data), b"BIN\0") + data
    with destination.open("xb") as stream:
        stream.write(payload)
    return read_collision_glb(destination)


def degenerate_removed(source: Path) -> int:
    """Số tam giác diện tích 0 trong output gốc của tool (đã bị bỏ khỏi derivative)."""
    return topology(read_collision_glb(source, allow_degenerate=True))["degenerate_triangles"]
