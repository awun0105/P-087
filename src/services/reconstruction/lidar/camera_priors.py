"""Pose camera của từng frame suy từ gói LiDAR (ADR 0009): quỹ đạo cảm biến + calibration camera ↔ LiDAR.

Quy ước của gói: dòng thứ *i* của quỹ đạo (và của file thời điểm frame) ứng với frame thứ *i* của video. Frame set
của job giữ đúng chỉ số frame gốc của video (`frame_id`), nên pose của một frame là dòng `frame_id` của quỹ đạo, ghép
với phép biến đổi camera → cảm biến. Không nội suy theo thời gian và không đoán khi video dài hơn quỹ đạo: lệch số
frame nghĩa là video không thuộc lượt quét này.

Kết quả ở hệ `lidar_map` (mét) và là **điểm xuất phát** cho COLMAP dựng bám theo quỹ đạo; nó chưa phải pose cuối.
"""

import math
from dataclasses import dataclass

from src.models.contracts.coordinates import Transform
from src.models.contracts.video_preparation import ServerVideoPreparationVerification
from src.services.reconstruction.alignment.transforms import compose_transforms
from src.services.reconstruction.lidar.fusion import ScanPose
from src.services.reconstruction.lidar.package import MAP_FRAME, SENSOR_FRAME, CameraCalibration


class CameraPriorError(ValueError):
    """Không suy được pose camera từ gói LiDAR; message hiển thị được cho người dùng."""


@dataclass(frozen=True)
class CameraPrior:
    """`lidar_map_from_camera` của một frame: tâm camera (mét) và hướng (quaternion xyzw)."""

    frame_id: int
    translation: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]
    source_frame_id: int | None = None


def prepared_camera_calibration(
    sensor_from_camera: Transform,
    camera: CameraCalibration | None,
    verification: ServerVideoPreparationVerification,
) -> tuple[Transform, tuple[int, int, tuple[float, ...]] | None]:
    """Map calibrated camera axes and intrinsics through the verified source→output pixel transform."""
    manifest = verification.client_manifest
    matrix = manifest.pixel_transform.matrix
    rotation = _pixel_rotation(matrix)
    camera_basis_rotation = {
        0: (0.0, 0.0, 0.0, 1.0),
        90: (0.0, 0.0, -math.sqrt(0.5), math.sqrt(0.5)),
        180: (0.0, 0.0, -1.0, 0.0),
        270: (0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)),
    }[rotation]
    output_basis = Transform(
        parent_frame=sensor_from_camera.local_frame,
        local_frame="prepared_camera",
        translation_xyz=(0.0, 0.0, 0.0),
        rotation_quaternion_xyzw=camera_basis_rotation,
    )
    prepared_extrinsic = compose_transforms(sensor_from_camera, output_basis)
    if camera is None:
        return prepared_extrinsic, None

    source = manifest.source_video
    output = manifest.prepared_video
    scale_x, scale_y = source.coded_width / camera.width, source.coded_height / camera.height
    if abs(scale_x - scale_y) > max(scale_x, scale_y) * 1e-6:
        raise CameraPriorError(
            "LiDAR camera calibration aspect differs from the source video; paired normalization is unsafe"
        )
    k_source = (
        (camera.fx * scale_x, 0.0, camera.cx * scale_x),
        (0.0, camera.fy * scale_y, camera.cy * scale_y),
        (0.0, 0.0, 1.0),
    )
    q_source_from_prepared = {
        0: ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        90: ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        180: ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
        270: ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    }[rotation]
    affine = matrix
    transformed = _multiply(_multiply(affine, k_source), q_source_from_prepared)
    if abs(transformed[0][1]) > 1e-6 or abs(transformed[1][0]) > 1e-6:
        raise CameraPriorError("Pixel transform cannot be represented by the supported COLMAP camera model")
    fx, fy, cx, cy = transformed[0][0], transformed[1][1], transformed[0][2], transformed[1][2]
    if fx <= 0 or fy <= 0:
        raise CameraPriorError("Pixel transform produced invalid camera intrinsics")
    p1, p2 = camera.distortion[2:]
    tangential = {
        0: (p1, p2),
        90: (p2, -p1),
        180: (-p1, -p2),
        270: (-p2, p1),
    }[rotation]
    parameters = (fx, fy, cx, cy, camera.distortion[0], camera.distortion[1], *tangential)
    return prepared_extrinsic, (output.display_width, output.display_height, parameters)


def _pixel_rotation(matrix: tuple[tuple[float, float, float], ...]) -> int:
    a, b, _ = matrix
    tolerance = 1e-8
    if abs(a[1]) <= tolerance and abs(b[0]) <= tolerance:
        if a[0] > 0 and b[1] > 0:
            return 0
        if a[0] < 0 and b[1] < 0:
            return 180
    elif abs(a[0]) <= tolerance and abs(b[1]) <= tolerance:
        if a[1] < 0 and b[0] > 0:
            return 90
        if a[1] > 0 and b[0] < 0:
            return 270
    raise CameraPriorError("Pixel transform contains shear or reflection unsupported by calibrated LiDAR guidance")


def _multiply(
    left: tuple[tuple[float, float, float], ...], right: tuple[tuple[float, float, float], ...]
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(sum(left[row][index] * right[index][column] for index in range(3)) for column in range(3))
        for row in range(3)
    )


def camera_priors(
    poses: list[ScanPose],
    sensor_from_camera: Transform,
    frame_ids: tuple[int, ...],
    source_frame_ids: tuple[int, ...] | None = None,
    source_frame_count: int | None = None,
) -> list[CameraPrior]:
    """Pose camera cho các frame đã trích; frame nằm ngoài quỹ đạo thì dừng với lý do rõ."""
    if not frame_ids:
        raise CameraPriorError("Không có frame nào để dựng pose")
    if source_frame_ids is not None and len(source_frame_ids) != len(frame_ids):
        raise CameraPriorError("Output/source frame map length differs from selected frame IDs")
    if source_frame_ids is not None and source_frame_count != len(poses):
        raise CameraPriorError("Prepared video source frame count differs from the LiDAR trajectory pose count")
    pose_ids = source_frame_ids or frame_ids
    beyond = [frame_id for frame_id in pose_ids if frame_id < 0 or frame_id >= len(poses)]
    if beyond:
        raise CameraPriorError(
            f"Video có frame thứ {max(beyond)} nhưng quỹ đạo chỉ có {len(poses)} pose (tính từ 0). Gói LiDAR cần đúng "
            "một pose cho mỗi frame của video: kiểm tra video và gói LiDAR có cùng một lượt quay không."
        )
    priors = []
    for index, frame_id in enumerate(frame_ids):
        source_frame_id = pose_ids[index]
        pose = poses[source_frame_id]
        map_from_sensor = Transform(
            parent_frame=MAP_FRAME,
            local_frame=SENSOR_FRAME,
            translation_xyz=pose.translation,
            rotation_quaternion_xyzw=pose.rotation_xyzw,
        )
        camera = compose_transforms(map_from_sensor, sensor_from_camera)
        priors.append(
            CameraPrior(
                frame_id,
                camera.translation_xyz,
                camera.rotation_quaternion_xyzw,
                source_frame_id if source_frame_ids is not None else None,
            )
        )
    return priors
