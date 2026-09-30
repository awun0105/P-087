"""So sánh ba hướng khôi phục tỉ lệ trên cùng một video (ADR 0004 §5, demo Aisle_CW).

- RGB only (MoGe-2 → ColmapSparseDepthProjector → RobustScaleAligner, ADR 0001 §2 P1): chưa
  triển khai — chỉ mô tả luồng, **không có số** (không điền số giả).
- Anchor người dùng: transform của bản xác nhận REC-06 (A/B + 3 điểm sàn).
- LiDAR: phép đồng dạng SfM → world từ căn chỉnh quỹ đạo (REC-09, GT-assisted).

Chỉ đọc artifact đã có và tính số liệu hiển thị; không xác nhận hay publish gì.
"""

import math
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import FiniteFloat

from src.models.contracts.artifacts import ContractModel
from src.services.reconstruction.alignment.similarity import SimilarityFit, rotation_matrix
from src.services.reconstruction.rgb.canonical.metric_math import SimilarityTransform

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]

RGB_ONLY_STEPS = (
    "MoGe-2 dự đoán bản đồ độ sâu theo mét cho từng ảnh",
    "Chiếu điểm COLMAP lên ảnh để ghép cặp độ sâu SfM ↔ độ sâu MoGe",
    "Giải tỉ lệ thuần (không dịch) bằng median/least-squares, gắn nhãn ESTIMATED",
)


class ModeResult(ContractModel):
    """Kết quả một hướng; `available=False` khi hướng đó chưa chạy cho scene này."""

    mode: Literal["rgb_only", "user_anchor", "lidar"]
    title: str
    status: Literal["mock", "measured", "missing"]
    note: str
    steps: list[str] = []
    scale_m_per_sfm_unit: FiniteFloat | None = None
    camera_height_mean_m: FiniteFloat | None = None
    camera_height_range_m: tuple[FiniteFloat, FiniteFloat] | None = None


class ModeDifference(ContractModel):
    """Độ lệch anchor người dùng so với LiDAR (LiDAR làm tham chiếu)."""

    scale_diff_percent: FiniteFloat
    floor_tilt_deg: FiniteFloat
    camera_height_diff_m: FiniteFloat
    check_segment_user_m: FiniteFloat | None = None
    check_segment_lidar_m: FiniteFloat | None = None
    check_segment_error_m: FiniteFloat | None = None


class ModeComparison(ContractModel):
    """Ba cột so sánh + độ lệch (khi có đủ hai hướng đo được)."""

    job_id: str
    modes: list[ModeResult]
    difference: ModeDifference | None = None
    lidar_ground_truth_assisted: bool = True


def _up_in_sfm(rotation_xyzw: tuple[float, float, float, float]) -> np.ndarray:
    """Trục +Z của world biểu diễn trong hệ SfM: R^T·ez (world = s·R·sfm + t)."""
    return rotation_matrix(rotation_xyzw).T @ np.array([0.0, 0.0, 1.0])


def _heights(points: np.ndarray) -> tuple[float, tuple[float, float]]:
    return float(points[:, 2].mean()), (float(points[:, 2].min()), float(points[:, 2].max()))


def compare_modes(
    job_id: str,
    camera_centers_sfm: Sequence[Vector3],
    user: SimilarityTransform | None,
    lidar: SimilarityFit | None,
    check_segment_sfm: tuple[Vector3, Vector3] | None = None,
) -> ModeComparison:
    """Tính các cột so sánh từ hai transform (nếu có) trên cùng camera của scene."""
    cameras = [tuple(point) for point in camera_centers_sfm]
    modes = [
        ModeResult(
            mode="rgb_only",
            title="RGB only (tự ước lượng)",
            status="mock",
            note="Mô phỏng · P1 chưa triển khai: cần MoGe-2 trên GPU; scene giữ đơn vị tùy ý.",
            steps=list(RGB_ONLY_STEPS),
        )
    ]
    user_points = lidar_points = None
    if user is not None:
        user_points = np.array([user.apply_point(point) for point in cameras])
        mean, span = _heights(user_points)
        modes.append(
            ModeResult(
                mode="user_anchor",
                title="Anchor người dùng",
                status="measured",
                note="Tỉ lệ từ đoạn A–B, sàn từ 3 điểm người dùng chọn trên 3DGS.",
                scale_m_per_sfm_unit=user.scale_m_per_sfm_unit,
                camera_height_mean_m=mean,
                camera_height_range_m=span,
            )
        )
    else:
        modes.append(
            ModeResult(
                mode="user_anchor",
                title="Anchor người dùng",
                status="missing",
                note="Chưa xác nhận tỉ lệ mét cho scene này.",
            )
        )
    if lidar is not None:
        lidar_points = np.array([lidar.apply(point) for point in cameras])
        mean, span = _heights(lidar_points)
        modes.append(
            ModeResult(
                mode="lidar",
                title="LiDAR",
                status="measured",
                note=f"Căn chỉnh quỹ đạo camera ↔ LiDAR, sai lệch RMS {lidar.rms_residual * 100:.1f} cm (GT-assisted).",
                scale_m_per_sfm_unit=lidar.scale,
                camera_height_mean_m=mean,
                camera_height_range_m=span,
            )
        )
    else:
        modes.append(
            ModeResult(
                mode="lidar", title="LiDAR", status="missing", note="Scene không có dữ liệu LiDAR (video người dùng)."
            )
        )
    difference = None
    if user is not None and lidar is not None and user_points is not None and lidar_points is not None:
        cosine = float(np.clip(_up_in_sfm(user.rotation_xyzw) @ _up_in_sfm(lidar.rotation_xyzw), -1.0, 1.0))
        segment = None
        if check_segment_sfm is not None:
            a, b = check_segment_sfm
            segment = (
                math.dist(user.apply_point(a), user.apply_point(b)),
                math.dist(lidar.apply(a), lidar.apply(b)),
            )
        difference = ModeDifference(
            scale_diff_percent=(user.scale_m_per_sfm_unit / lidar.scale - 1) * 100,
            floor_tilt_deg=math.degrees(math.acos(cosine)),
            camera_height_diff_m=float(user_points[:, 2].mean() - lidar_points[:, 2].mean()),
            check_segment_user_m=segment[0] if segment else None,
            check_segment_lidar_m=segment[1] if segment else None,
            check_segment_error_m=abs(segment[0] - segment[1]) if segment else None,
        )
    return ModeComparison(job_id=job_id, modes=modes, difference=difference)
