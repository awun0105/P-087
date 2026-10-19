"""Số liệu hiển thị của đề xuất tự động, bản xác nhận REC-06 và LiDAR.

Port bổ sung đề xuất và nguồn số đo từ artifact; hàm này chỉ tính transform/camera, không publish.
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
    "Ước lượng độ sâu từ các ảnh của video",
    "Đối chiếu với mô hình 3D để tìm tỉ lệ mét",
    "Tạo đề xuất tỉ lệ để kiểm tra trước khi xác nhận",
)


class ModeResult(ContractModel):
    """Số liệu và trạng thái của một nguồn tỉ lệ, đọc từ artifact của job."""

    mode: Literal["rgb_only", "user_anchor", "lidar"]
    title: str
    status: Literal["estimated", "confirmed", "measured", "missing"]
    note: str
    steps: list[str] = []
    scale_m_per_sfm_unit: FiniteFloat | None = None
    relative_uncertainty: FiniteFloat | None = None
    frames_used: int | None = None
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
            title="MoGe-2 · Ước lượng tự động",
            status="missing",
            note="Job này chưa có đề xuất MoGe-2. Có thể dùng khoảng cách đo ngoài đời để xác nhận tỉ lệ.",
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
                title="Kết quả đã xác nhận",
                status="confirmed",
                note="Khoảng cách do người dùng đo ngoài đời; mặt sàn từ các điểm đã chọn trên scene.",
                scale_m_per_sfm_unit=user.scale_m_per_sfm_unit,
                camera_height_mean_m=mean,
                camera_height_range_m=span,
            )
        )
    else:
        modes.append(
            ModeResult(
                mode="user_anchor",
                title="Kết quả đã xác nhận",
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
