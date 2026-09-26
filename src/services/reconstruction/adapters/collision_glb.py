"""Boundary của GLB tối giản do splat-transform 3.6.6 sinh, không là glTF importer."""

import json
import math
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.services.reconstruction.rgb.voxel import Vector3, world_from_native


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
    if document.get("asset") != {"version": "2.0", "generator": "splat-transform"}:
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


def read_collision_glb(path: Path) -> CollisionMesh:
    """Reject truncated/nonfinite/foreign-layout output trước publication."""
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
        if topology(mesh)["degenerate_triangles"]:
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


def canonicalize_collision(source: Path, destination: Path) -> CollisionMesh:
    """Chỉ bake R_x(+90°) vào derivative; giữ nguyên native tool output."""
    mesh = read_collision_glb(source)
    document, binary = _chunks(source.read_bytes())
    points = tuple(world_from_native(point) for point in mesh.positions)
    data = bytearray(binary)
    offset = document["bufferViews"][0]["byteOffset"]
    for index, point in enumerate(points):
        struct.pack_into("<fff", data, offset + index * 12, *point)
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
