"""Lưới va chạm cho chế độ đi bộ: xoay đúng một phép (x, y, z) → (x, z, −y), không đụng chỉ số tam giác."""

import json
import struct

import numpy as np
import pytest

from src.services.orchestration.jobs.display_glb import display_space_glb

POINTS = np.array([[0, 0, 0], [1, 0, 0], [0, 2, 0], [0, 0, 3]], dtype="<f4")
INDICES = np.array([0, 1, 2, 0, 2, 3], dtype="<u4")


def build_glb(
    points: np.ndarray = POINTS, indices: np.ndarray = INDICES, *, stride: int = 12, **accessor: object
) -> bytes:
    """GLB một lưới; `stride` > 12 chèn dữ liệu xen kẽ sau mỗi đỉnh để kiểm bước nhảy."""
    vertex = bytearray()
    for point in points:
        vertex += point.astype("<f4").tobytes() + b"\xab" * (stride - 12)
    binary = bytes(vertex) + indices.tobytes()
    view = {"buffer": 0, "byteOffset": 0, "byteLength": len(vertex)}
    if stride != 12:
        view["byteStride"] = stride
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [view, {"buffer": 0, "byteOffset": len(vertex), "byteLength": indices.nbytes}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(points),
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [1, 2, 3],
                **accessor,
            },
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
    }
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(encoded) + 8 + len(binary)
    return b"".join(
        (struct.pack("<III", 0x46546C67, 2, total), struct.pack("<II", len(encoded), 0x4E4F534A), encoded,
         struct.pack("<II", len(binary), 0x004E4942), binary)
    )  # fmt: skip


def parse(payload: bytes, stride: int = 12) -> tuple[dict, np.ndarray, np.ndarray]:
    magic, version, length = struct.unpack_from("<III", payload, 0)
    assert (magic, version, length) == (0x46546C67, 2, len(payload)) and len(payload) % 4 == 0
    json_length = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20 : 20 + json_length])
    binary = payload[20 + json_length + 8 :]
    count = document["accessors"][0]["count"]
    points = np.ndarray((count, 3), dtype="<f4", buffer=binary, strides=(stride, 4)).copy()
    start = document["bufferViews"][1]["byteOffset"]
    indices = np.frombuffer(binary, dtype="<u4", count=document["accessors"][1]["count"], offset=start)
    return document, points, indices


@pytest.mark.parametrize("stride", [12, 24])
def test_positions_rotate_into_display_space_and_triangles_are_untouched(stride: int) -> None:
    document, points, indices = parse(display_space_glb(build_glb(stride=stride)), stride)
    # Z-up → Y-up: trục lên (z = 3) thành y = 3; trục y = 2 thành z = −2.
    assert points.tolist() == [[0, 0, 0], [1, 0, 0], [0, 0, -2], [0, 3, 0]]
    assert indices.tolist() == INDICES.tolist()
    assert document["accessors"][0]["min"] == [0, 0, -2] and document["accessors"][0]["max"] == [1, 3, 0]
    # Phép xoay thuần: pháp tuyến tam giác xoay cùng phép đó, không lật mặt.
    before = np.cross(POINTS[1] - POINTS[0], POINTS[2] - POINTS[0])
    after = np.cross(points[1] - points[0], points[2] - points[0])
    assert after.tolist() == [before[0], before[2], -before[1]]


def test_transform_is_a_quarter_turn_not_a_mirror() -> None:
    once = display_space_glb(build_glb())
    four = once
    for _ in range(3):
        four = display_space_glb(four)
    assert parse(four)[1].tolist() == POINTS.tolist()  # bốn lần xoay 90° quay về chỗ cũ
    assert parse(display_space_glb(once))[1].tolist() != POINTS.tolist()


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not a glb at all, just bytes!",
        build_glb()[:-8],  # cắt cụt
        build_glb(componentType=5130),  # double
        build_glb(type="VEC2"),
        build_glb(sparse={"count": 1}),
        build_glb(count=999),  # accessor vượt buffer
        build_glb(points=np.array([[0, np.nan, 0]] * 3, dtype="<f4"), indices=np.array([0, 1, 2], dtype="<u4")),
    ],
)
def test_unsupported_or_broken_glb_is_rejected_not_served_misoriented(payload: bytes) -> None:
    with pytest.raises(ValueError):
        display_space_glb(payload)


def test_glb_without_triangle_mesh_is_rejected() -> None:
    document = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}], "meshes": []}
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    payload = b"".join(
        (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(encoded) + 8 + 4), struct.pack("<II", len(encoded), 0x4E4F534A),
         encoded, struct.pack("<II", 4, 0x004E4942), b"\\x00\\x00\\x00\\x00"[:4])
    )  # fmt: skip
    with pytest.raises(ValueError, match="không có lưới"):
        display_space_glb(payload)


def test_carve_drops_triangles_inside_a_box_and_keeps_the_rest() -> None:
    from src.services.orchestration.jobs.display_glb import CarveBox

    # Tam giác 0 có trọng tâm (0,33; 0,67; 0) — trong hộp; tam giác 1 có trọng tâm (0; 0,67; 1) — ngoài hộp.
    box = CarveBox(center=(0.3, 0.6, 0.0), rotation_xyzw=(0.0, 0.0, 0.0, 1.0), half_extents=(0.2, 0.2, 0.2))
    document, _points, indices = parse(display_space_glb(build_glb(), [box]))
    assert document["accessors"][1]["count"] == 3
    assert indices[:3].tolist() == [0, 2, 3]


def test_carve_box_respects_its_rotation() -> None:
    from src.services.orchestration.jobs.display_glb import CarveBox

    # Hộp dài theo X, quay 90° quanh Z → dài theo Y.
    box = CarveBox(center=(0.0, 0.0, 0.0), rotation_xyzw=(0.0, 0.0, 2**-0.5, 2**-0.5), half_extents=(1.0, 0.1, 0.1))
    inside = box.contains(np.array([[0.0, 0.9, 0.0], [0.9, 0.0, 0.0]]))
    assert inside.tolist() == [True, False]
