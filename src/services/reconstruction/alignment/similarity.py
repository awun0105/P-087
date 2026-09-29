"""Fit phép đồng dạng target = s·R·source + t từ các cặp điểm tương ứng (Umeyama 1991).

Dùng cho REC-09 khi có tâm camera của cùng frame ở hai hệ (SfM và world/LiDAR).
Trả kèm residual để consumer tự quyết chấp nhận; hàm không tự xác nhận alignment.
"""

import math

import numpy as np
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
Quaternion = tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]

#: Tối thiểu 3 cặp không thẳng hàng mới xác định được rotation.
MIN_PAIRS = 3


class SimilarityFit(ContractModel):
    """Kết quả fit; residual tính bằng đơn vị của target (mét với world)."""

    scale: FiniteFloat = Field(gt=0)
    rotation_xyzw: Quaternion
    translation: Vector3
    pair_count: int = Field(ge=MIN_PAIRS)
    rms_residual: FiniteFloat = Field(ge=0)
    max_residual: FiniteFloat = Field(ge=0)
    residuals: list[FiniteFloat]

    def apply(self, point: Vector3) -> Vector3:
        """Đưa một điểm từ hệ source sang target."""
        rotated = rotation_matrix(self.rotation_xyzw) @ np.asarray(point, dtype=float)
        return tuple(float(value) for value in self.scale * rotated + np.asarray(self.translation))  # type: ignore[return-value]


def rotation_matrix(quaternion: Quaternion) -> np.ndarray:
    """Ma trận quay 3×3 của quaternion xyzw (đã chuẩn hóa)."""
    x, y, z, w = quaternion
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _quaternion(matrix: np.ndarray) -> Quaternion:
    """Quaternion xyzw (w ≥ 0) của ma trận quay 3×3."""
    m = matrix
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    sign = 1.0 if w >= 0 else -1.0
    return (sign * x / norm, sign * y / norm, sign * z / norm, sign * w / norm)


def fit_similarity(source: list[Vector3], target: list[Vector3]) -> SimilarityFit:
    """Umeyama có chặn phản xạ (det R = +1); từ chối cặp điểm suy biến."""
    if len(source) != len(target):
        raise ValueError("số điểm source và target phải bằng nhau")
    if len(source) < MIN_PAIRS:
        raise ValueError(f"cần ít nhất {MIN_PAIRS} cặp điểm")
    src = np.asarray(source, dtype=float)
    dst = np.asarray(target, dtype=float)
    if not (np.isfinite(src).all() and np.isfinite(dst).all()):
        raise ValueError("điểm phải hữu hạn")
    mu_src, mu_dst = src.mean(axis=0), dst.mean(axis=0)
    src_c, dst_c = src - mu_src, dst - mu_dst
    variance = (src_c**2).sum() / len(src)
    if variance <= 0:
        raise ValueError("các điểm source trùng nhau")
    covariance = dst_c.T @ src_c / len(src)
    u, singular, vt = np.linalg.svd(covariance)
    # Cặp điểm gần thẳng hàng: giá trị suy biến thứ hai ~0 → rotation quanh trục đó không xác định.
    if singular[1] <= 1e-9 * max(singular[0], 1e-300):
        raise ValueError("các điểm gần thẳng hàng; không xác định được rotation")
    correction = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        correction[2, 2] = -1.0
    rotation = u @ correction @ vt
    scale = float(np.trace(np.diag(singular) @ correction) / variance)
    translation = mu_dst - scale * rotation @ mu_src
    residuals = np.linalg.norm(dst - (scale * (rotation @ src.T).T + translation), axis=1)
    return SimilarityFit(
        scale=scale,
        rotation_xyzw=_quaternion(rotation),
        translation=tuple(float(value) for value in translation),  # type: ignore[arg-type]
        pair_count=len(src),
        rms_residual=float(math.sqrt((residuals**2).mean())),
        max_residual=float(residuals.max()),
        residuals=[float(value) for value in residuals],
    )
