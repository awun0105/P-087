"""Pose camera của từng frame suy từ gói LiDAR (ADR 0009): quỹ đạo cảm biến + calibration camera ↔ LiDAR.

Quy ước của gói: dòng thứ *i* của quỹ đạo (và của file thời điểm frame) ứng với frame thứ *i* của video. Frame set
của job giữ đúng chỉ số frame gốc của video (`frame_id`), nên pose của một frame là dòng `frame_id` của quỹ đạo, ghép
với phép biến đổi camera → cảm biến. Không nội suy theo thời gian và không đoán khi video dài hơn quỹ đạo: lệch số
frame nghĩa là video không thuộc lượt quét này.

Kết quả ở hệ `lidar_map` (mét) và là **điểm xuất phát** cho COLMAP dựng bám theo quỹ đạo; nó chưa phải pose cuối.
"""

from dataclasses import dataclass

from src.models.contracts.coordinates import Transform
from src.services.reconstruction.alignment.transforms import compose_transforms
from src.services.reconstruction.lidar.fusion import ScanPose
from src.services.reconstruction.lidar.package import MAP_FRAME, SENSOR_FRAME


class CameraPriorError(ValueError):
    """Không suy được pose camera từ gói LiDAR; message hiển thị được cho người dùng."""


@dataclass(frozen=True)
class CameraPrior:
    """`lidar_map_from_camera` của một frame: tâm camera (mét) và hướng (quaternion xyzw)."""

    frame_id: int
    translation: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]


def camera_priors(
    poses: list[ScanPose], sensor_from_camera: Transform, frame_ids: tuple[int, ...]
) -> list[CameraPrior]:
    """Pose camera cho các frame đã trích; frame nằm ngoài quỹ đạo thì dừng với lý do rõ."""
    if not frame_ids:
        raise CameraPriorError("Không có frame nào để dựng pose")
    beyond = [frame_id for frame_id in frame_ids if frame_id >= len(poses)]
    if beyond:
        raise CameraPriorError(
            f"Video có frame thứ {max(beyond)} nhưng quỹ đạo chỉ có {len(poses)} pose (tính từ 0). Gói LiDAR cần đúng "
            "một pose cho mỗi frame của video: kiểm tra video và gói LiDAR có cùng một lượt quay không."
        )
    priors = []
    for frame_id in frame_ids:
        pose = poses[frame_id]
        map_from_sensor = Transform(
            parent_frame=MAP_FRAME,
            local_frame=SENSOR_FRAME,
            translation_xyz=pose.translation,
            rotation_quaternion_xyzw=pose.rotation_xyzw,
        )
        camera = compose_transforms(map_from_sensor, sensor_from_camera)
        priors.append(CameraPrior(frame_id, camera.translation_xyz, camera.rotation_quaternion_xyzw))
    return priors
