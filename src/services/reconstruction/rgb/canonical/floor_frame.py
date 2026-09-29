"""Khai báo canonical frame cho video RGB từ các điểm người dùng chọn (REC-06).

Một distance anchor chỉ cho scale; hướng và gốc phải được khai báo tường minh (REC-06
§Implementation Plan). Với video người dùng, khai báo đến từ chính các điểm họ chọn:

- 3 điểm trên mặt sàn → pháp tuyến sàn = trục +Z (quay về phía camera), sàn = z 0
  (tổng quát hóa quyết định owner "dịch sàn về z=0", REC-06.md, commit 01305c9);
- đoạn A→B chiếu lên sàn → trục +X; gốc tọa độ = hình chiếu của A lên sàn.

Không suy từ GT hay camera đầu. Camera centers chỉ dùng để chọn chiều pháp tuyến
(camera ở phía trên sàn), không quyết định hướng hay gốc.
"""

import math

from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel
from src.services.reconstruction.rgb.canonical.metric_math import unit_quaternion
from src.services.reconstruction.rgb.pose.camera_pose import Quaternion, Vector3

#: Ngưỡng tương đối để coi 3 điểm là thẳng hàng / A→B gần như vuông góc sàn.
_DEGENERATE = 1e-6


class FloorFrame(ContractModel):
    """Kết quả dựng frame; `floor_residual_m` là sai lệch cao độ lớn nhất của điểm sàn."""

    rotation_xyzw: Quaternion
    translation_m: Vector3
    floor_normal_sfm: Vector3
    floor_residual_m: FiniteFloat = Field(ge=0)


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _scale(a: Vector3, k: float) -> Vector3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _unit(a: Vector3) -> Vector3:
    norm = math.sqrt(_dot(a, a))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("vector suy biến")
    return _scale(a, 1 / norm)


def _quaternion_from_rows(ex: Vector3, ey: Vector3, ez: Vector3) -> Quaternion:
    """Quaternion xyzw của ma trận R có các hàng ex, ey, ez (world = R · sfm)."""
    m00, m01, m02 = ex
    m10, m11, m12 = ey
    m20, m21, m22 = ez
    trace = m00 + m11 + m22
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    return unit_quaternion((x / norm, y / norm, z / norm, w / norm))


def floor_frame(
    floor_points: tuple[Vector3, Vector3, Vector3],
    point_a: Vector3,
    point_b: Vector3,
    scale_m_per_sfm_unit: float,
    camera_centers: list[Vector3],
) -> FloorFrame:
    """Dựng rotation/translation sao cho sàn ở z=0, +Z hướng về camera, A ở gốc, B trên +X."""
    if scale_m_per_sfm_unit <= 0 or not math.isfinite(scale_m_per_sfm_unit):
        raise ValueError("scale phải dương, hữu hạn")
    if not camera_centers:
        raise ValueError("cần camera centers để chọn chiều pháp tuyến sàn")
    p1, p2, p3 = floor_points
    edge_1, edge_2 = _sub(p2, p1), _sub(p3, p1)
    raw_normal = _cross(edge_1, edge_2)
    span = math.sqrt(_dot(edge_1, edge_1) * _dot(edge_2, edge_2))
    if span <= 0 or math.sqrt(_dot(raw_normal, raw_normal)) <= _DEGENERATE * span:
        raise ValueError("3 điểm sàn gần thẳng hàng; chọn 3 điểm trải rộng trên mặt sàn")
    normal = _unit(raw_normal)
    centroid = _scale(
        tuple(sum(point[i] for point in camera_centers) for i in range(3)),  # type: ignore[arg-type]
        1 / len(camera_centers),
    )
    if _dot(_sub(centroid, p1), normal) < 0:
        normal = _scale(normal, -1)

    direction = _sub(point_b, point_a)
    along_floor = _sub(direction, _scale(normal, _dot(direction, normal)))
    if math.sqrt(_dot(along_floor, along_floor)) <= _DEGENERATE * max(math.sqrt(_dot(direction, direction)), 1e-12):
        # A→B gần thẳng đứng: lấy cạnh sàn làm trục X, vẫn tường minh từ điểm người chọn.
        along_floor = _sub(edge_1, _scale(normal, _dot(edge_1, normal)))
    ex = _unit(along_floor)
    ez = normal
    ey = _cross(ez, ex)
    rotation = _quaternion_from_rows(ex, ey, ez)

    origin = _sub(point_a, _scale(normal, _dot(_sub(point_a, p1), normal)))
    rotated_origin = (_dot(ex, origin), _dot(ey, origin), _dot(ez, origin))
    translation = _scale(rotated_origin, -scale_m_per_sfm_unit)
    residual = max(abs(_dot(_sub(point, origin), normal)) * scale_m_per_sfm_unit for point in (p1, p2, p3))
    return FloorFrame(
        rotation_xyzw=rotation,
        translation_m=translation,
        floor_normal_sfm=normal,
        floor_residual_m=residual,
    )
