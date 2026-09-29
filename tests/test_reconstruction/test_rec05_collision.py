"""GLB proof độc lập với GPU; tetrahedron fixture không thay real smoke."""

import json
import struct
from pathlib import Path

import pytest

from src.services.reconstruction.adapters.collision_glb import (
    canonicalize_collision,
    degenerate_removed,
    read_collision_glb,
    topology,
)


def collision_fixture() -> tuple[dict, bytes]:
    """Tetrahedron không đối xứng giúp phát hiện nhầm trục/scale."""
    points = ((0, 0, 0), (2, 0, 0), (0, 3, 0), (0, 0, 4))
    indices = (0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3)
    binary = b"".join(struct.pack("<fff", *p) for p in points) + struct.pack("<12I", *indices)
    document = dict(
        asset={"version": "2.0", "generator": "splat-transform"},
        scene=0,
        scenes=[{"nodes": [0]}],
        nodes=[{"mesh": 0}],
        meshes=[{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        buffers=[{"byteLength": len(binary)}],
        bufferViews=[
            {"buffer": 0, "byteOffset": 0, "byteLength": 48, "target": 34962},
            {"buffer": 0, "byteOffset": 48, "byteLength": 48, "target": 34963},
        ],
        accessors=[
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3", "min": [0, 0, 0], "max": [2, 3, 4]},
            {"bufferView": 1, "componentType": 5125, "count": 12, "type": "SCALAR"},
        ],
    )
    return document, binary


def write_fixture(path: Path, parts: tuple[dict, bytes]) -> bytes:
    """Encoder fixture chủ động; không dùng production writer để tự xác nhận."""
    document, binary = parts
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    payload = struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
    payload += struct.pack("<I4s", len(encoded), b"JSON") + encoded
    payload += struct.pack("<I4s", len(binary), b"BIN\0") + binary
    path.write_bytes(payload)
    return payload


def test_collision_rotation_and_closed_topology(tmp_path: Path) -> None:
    """Proper rotation không scale, không sửa source và không overwrite derivative."""
    source, output = tmp_path / "native.glb", tmp_path / "world.glb"
    original = write_fixture(source, collision_fixture())
    mesh = canonicalize_collision(source, output)
    assert mesh.positions == ((0, 0, 0), (2, 0, 0), (0, 0, 3), (0, -4, 0))
    assert topology(mesh) == dict(
        vertices=4, triangles=4, degenerate_triangles=0, boundary_edges=0, nonmanifold_edges=0
    )
    assert source.read_bytes() == original
    with pytest.raises(FileExistsError):
        canonicalize_collision(source, output)


@pytest.mark.parametrize(
    "case", ["truncated", "transform", "bounds", "overlap", "indices", "nan", "degenerate", "list"]
)
def test_invalid_collision_rejected(tmp_path: Path, case: str) -> None:
    """Không publish mesh malformed dù tool trả exit zero."""
    document, binary = collision_fixture()
    if case == "transform":
        document["nodes"][0]["scale"] = [2, 2, 2]
    elif case == "bounds":
        document["accessors"][0]["max"] = [1, 1, 1]
    elif case == "overlap":
        document["bufferViews"][1]["byteOffset"] = 0
    elif case == "indices":
        binary = binary[:48] + struct.pack("<I", 999) + binary[52:]
    elif case == "nan":
        binary = struct.pack("<f", float("nan")) + binary[4:]
    elif case == "degenerate":
        binary = binary[:48] + struct.pack("<3I", 0, 0, 0) + binary[60:]
    elif case == "list":
        document = []
    path = tmp_path / "invalid.glb"
    payload = write_fixture(path, (document, binary))
    if case == "truncated":
        path.write_bytes(payload[:-1])
    with pytest.raises(ValueError):
        read_collision_glb(path)


def test_canonical_derivative_drops_zero_area_triangles(tmp_path: Path) -> None:
    """Output tool có tam giác thẳng hàng: derivative bỏ chúng, bề mặt còn lại giữ nguyên."""
    document, binary = collision_fixture()
    triangles = len(binary[48:]) // 12
    extra = struct.pack("<3I", 0, 1, 1)  # lặp đỉnh → diện tích 0
    document["accessors"][1]["count"] += 3
    document["bufferViews"][1]["byteLength"] += 12
    document["buffers"][0]["byteLength"] += 12
    source, output = tmp_path / "native.glb", tmp_path / "world.glb"
    write_fixture(source, (document, binary + extra))
    with pytest.raises(ValueError, match="degenerate"):
        read_collision_glb(source)
    mesh = canonicalize_collision(source, output)
    assert len(mesh.triangles) == triangles and topology(mesh)["degenerate_triangles"] == 0
    assert degenerate_removed(source) == 1
