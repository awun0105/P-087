"""Đưa lưới GLB hệ canonical (mét, Z-up) sang không gian hiển thị Y-up của viewer.

Chế độ đi bộ của supersplat-viewer đọc **toạ độ đỉnh thô** của GLB va chạm, không áp
transform của node, trong khi Studio hiển thị scene hệ mét bằng phép xoay `(x, y, z) →
(x, z, −y)` (`frontend/.../source-frame.ts`, `DISPLAY_EULER.z_up`). Vì vậy lưới va chạm
phải được xoay sẵn trong dữ liệu. Đây là phép xoay thuần (định thức +1): thứ tự đỉnh của
tam giác giữ nguyên. Artifact đã publish không bị sửa; đây là bản dẫn xuất phục vụ viewer.
"""

import json
import struct

import numpy as np

_MAGIC, _JSON, _BIN = 0x46546C67, 0x4E4F534A, 0x004E4942
_FLOAT, _VEC3_BYTES = 5126, 12


def _chunks(payload: bytes) -> tuple[dict, bytearray]:
    if len(payload) < 20:
        raise ValueError("GLB quá ngắn")
    magic, version, length = struct.unpack_from("<III", payload, 0)
    if magic != _MAGIC or version != 2 or length != len(payload):
        raise ValueError("Không phải GLB 2.0 hợp lệ")
    json_length, json_type = struct.unpack_from("<II", payload, 12)
    if json_type != _JSON or 20 + json_length > len(payload):
        raise ValueError("GLB thiếu chunk JSON")
    document = json.loads(payload[20 : 20 + json_length])
    offset = 20 + json_length
    if offset + 8 > len(payload):
        raise ValueError("GLB thiếu chunk dữ liệu")
    bin_length, bin_type = struct.unpack_from("<II", payload, offset)
    if bin_type != _BIN or offset + 8 + bin_length > len(payload):
        raise ValueError("GLB thiếu chunk BIN")
    return document, bytearray(payload[offset + 8 : offset + 8 + bin_length])


def _pad(data: bytes, filler: bytes) -> bytes:
    return data + filler * (-len(data) % 4)


def display_space_glb(payload: bytes) -> bytes:
    """Xoay mọi accessor POSITION của GLB: `(x, y, z) → (x, z, −y)`; cập nhật min/max.

    Chỉ nhận layout phổ biến của lưới tĩnh (float32 VEC3, một buffer nhúng, không sparse);
    layout khác bị từ chối bằng ValueError thay vì trả lưới sai hướng.
    """
    document, binary = _chunks(payload)
    if len(document.get("buffers", [])) != 1:
        raise ValueError("GLB phải có đúng một buffer nhúng")
    positions = {
        primitive["attributes"]["POSITION"]
        for mesh in document.get("meshes", [])
        for primitive in mesh.get("primitives", [])
        if "POSITION" in primitive.get("attributes", {})
    }
    if not positions:
        raise ValueError("GLB không có lưới tam giác")
    for index in sorted(positions):
        accessor = document["accessors"][index]
        if accessor.get("componentType") != _FLOAT or accessor.get("type") != "VEC3" or "sparse" in accessor:
            raise ValueError("POSITION không phải float32 VEC3")
        view = document["bufferViews"][accessor["bufferView"]]
        stride = view.get("byteStride", _VEC3_BYTES)
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        count = int(accessor["count"])
        if stride < _VEC3_BYTES or count < 1 or start + (count - 1) * stride + _VEC3_BYTES > len(binary):
            raise ValueError("POSITION vượt ngoài buffer")
        points = np.ndarray(shape=(count, 3), dtype="<f4", buffer=binary, offset=start, strides=(stride, 4))
        rotated = np.stack([points[:, 0], points[:, 2], -points[:, 1]], axis=1)
        if not np.isfinite(rotated).all():
            raise ValueError("POSITION có giá trị không hữu hạn")
        points[:] = rotated
        accessor["min"] = [float(value) for value in rotated.min(axis=0)]
        accessor["max"] = [float(value) for value in rotated.max(axis=0)]
    document["buffers"][0]["byteLength"] = len(binary)
    encoded = _pad(json.dumps(document, separators=(",", ":")).encode("utf-8"), b" ")
    body = _pad(bytes(binary), b"\x00")
    total = 12 + 8 + len(encoded) + 8 + len(body)
    return b"".join(
        (
            struct.pack("<III", _MAGIC, 2, total),
            struct.pack("<II", len(encoded), _JSON),
            encoded,
            struct.pack("<II", len(body), _BIN),
            body,
        )
    )
