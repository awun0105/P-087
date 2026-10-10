"""Parser calibration camera ↔ LiDAR đa định dạng, luôn trả chiều biến đổi tường minh.

Quy ước chung của module: mọi extrinsic trả về là `parent_from_local`, tức điểm trong hệ `local`
nhân với biến đổi này ra điểm trong hệ `parent` (`p_parent = R · p_local + t`). Khớp với
`src.models.contracts.coordinates.Transform`. Không có parser nào đoán chiều từ tên khoá: hoặc
định dạng tự nói rõ chiều, hoặc người dùng phải khai tên frame LiDAR.

Định dạng nhận:
- `torwic_text`: `calibrations.txt` của TorWIC. Nhãn `T_cam1_os` trong file đó là **`T_os_from_cam`**
  (ngược với nghĩa chữ), nên parser đảo nghĩa có chủ ý.
- `lidar_camera_json`: `{"lidar_from_camera": {...}}` hoặc `{"camera_from_lidar": {...}}`, khối có
  `translation_xyz` + `rotation_xyzw` hoặc ma trận `matrix` 4×4.
- `ros_transform_yaml`: `geometry_msgs/TransformStamped` (hoặc `tf2_msgs/TFMessage` đúng một phần tử).
  Chiều lấy từ `header.frame_id` (cha) và `child_frame_id` (con); cần biết frame nào là LiDAR.
- `kalibr_camchain`: `camchain-imucam.yaml`. Kalibr chỉ cho camera ↔ IMU và nội tham số, **không** có
  LiDAR; muốn ra camera ↔ LiDAR phải ghép thêm một extrinsic IMU ↔ LiDAR có chiều rõ ràng.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
import yaml

CalibrationFormat = Literal["torwic_text", "lidar_camera_json", "ros_transform_yaml", "kalibr_camchain"]

#: YAML chỉ là metadata nhỏ; chặn kích thước và alias/anchor để không có bom mở rộng alias.
_MAX_YAML_BYTES = 256 * 1024
_YAML_ANCHOR_OR_ALIAS = re.compile(r"(^|[\s\[{,:-])[&*][A-Za-z_][\w-]*")
_QUATERNION_TOLERANCE = 1e-5
_ROTATION_TOLERANCE = 1e-6

_TORWIC_KEYS = tuple(f"T_cam1_os.{name}" for name in ("px", "py", "pz", "qx", "qy", "qz", "qw"))


class CalibrationParseError(ValueError):
    """File calibration không đọc được hoặc không xác định được chiều biến đổi."""


@dataclass(frozen=True)
class Extrinsic:
    """Một biến đổi cứng `parent_from_local` kèm tên hai frame."""

    parent_frame: str
    local_frame: str
    translation_xyz: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]
    source_format: CalibrationFormat

    def matrix(self) -> np.ndarray:
        result = np.eye(4)
        result[:3, :3] = _quaternion_to_rotation(self.rotation_xyzw)
        result[:3, 3] = self.translation_xyz
        return result

    def inverse(self) -> Extrinsic:
        """Đảo chiều: `local_from_parent`."""
        return extrinsic_from_matrix(
            np.linalg.inv(self.matrix()), parent=self.local_frame, local=self.parent_frame, source=self.source_format
        )


@dataclass(frozen=True)
class KalibrCamera:
    """Một khối camera của Kalibr camchain: nội tham số + `camera_from_imu`."""

    camera_name: str
    camera_model: str
    intrinsics: tuple[float, ...]
    distortion_model: str | None
    distortion_coeffs: tuple[float, ...]
    resolution: tuple[int, int] | None
    camera_from_imu: Extrinsic | None
    timeshift_cam_imu_seconds: float | None


# ---------------------------------------------------------------------------
# Toán rotation
# ---------------------------------------------------------------------------


def _quaternion_to_rotation(quaternion: tuple[float, float, float, float]) -> np.ndarray:
    x, y, z, w = quaternion
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _rotation_to_quaternion(rotation: np.ndarray) -> tuple[float, float, float, float]:
    """Shepperd: chọn nhánh theo phần tử đường chéo lớn nhất để ổn định số học."""
    trace = float(np.trace(rotation))
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2
        w, x = 0.25 * scale, (rotation[2, 1] - rotation[1, 2]) / scale
        y, z = (rotation[0, 2] - rotation[2, 0]) / scale, (rotation[1, 0] - rotation[0, 1]) / scale
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2
        w, x = (rotation[2, 1] - rotation[1, 2]) / scale, 0.25 * scale
        y, z = (rotation[0, 1] + rotation[1, 0]) / scale, (rotation[0, 2] + rotation[2, 0]) / scale
    elif rotation[1, 1] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2
        w, x = (rotation[0, 2] - rotation[2, 0]) / scale, (rotation[0, 1] + rotation[1, 0]) / scale
        y, z = 0.25 * scale, (rotation[1, 2] + rotation[2, 1]) / scale
    else:
        scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2
        w, x = (rotation[1, 0] - rotation[0, 1]) / scale, (rotation[0, 2] + rotation[2, 0]) / scale
        y, z = (rotation[1, 2] + rotation[2, 1]) / scale, 0.25 * scale
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    return (x / norm, y / norm, z / norm, w / norm)


def _checked_quaternion(values: tuple[float, ...], where: str) -> tuple[float, float, float, float]:
    if len(values) != 4 or not all(math.isfinite(item) for item in values):
        raise CalibrationParseError(f"{where}: quaternion cần 4 số hữu hạn (x, y, z, w)")
    norm = math.sqrt(sum(item * item for item in values))
    if abs(norm - 1.0) > _QUATERNION_TOLERANCE:
        raise CalibrationParseError(f"{where}: quaternion chưa chuẩn hoá (độ dài {norm:.6f}); không tự sửa dữ liệu sai")
    return (values[0] / norm, values[1] / norm, values[2] / norm, values[3] / norm)


def _checked_translation(values: tuple[float, ...], where: str) -> tuple[float, float, float]:
    if len(values) != 3 or not all(math.isfinite(item) for item in values):
        raise CalibrationParseError(f"{where}: translation cần 3 số hữu hạn")
    return (values[0], values[1], values[2])


def extrinsic_from_matrix(matrix: np.ndarray, *, parent: str, local: str, source: CalibrationFormat) -> Extrinsic:
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise CalibrationParseError("ma trận biến đổi phải là 4×4 hữu hạn")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-9):
        raise CalibrationParseError("hàng cuối của ma trận biến đổi phải là [0, 0, 0, 1]")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=_ROTATION_TOLERANCE) or not math.isclose(
        float(np.linalg.det(rotation)), 1.0, abs_tol=_ROTATION_TOLERANCE
    ):
        raise CalibrationParseError("phần quay của ma trận không phải phép quay hợp lệ (trực chuẩn, det = +1)")
    translation = tuple(float(item) for item in matrix[:3, 3])
    return Extrinsic(
        parent_frame=parent,
        local_frame=local,
        translation_xyz=_checked_translation(translation, "ma trận"),
        rotation_xyzw=_rotation_to_quaternion(rotation),
        source_format=source,
    )


def _matrix_from_rows(value: object, where: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as error:
        raise CalibrationParseError(f"{where}: ma trận chứa giá trị không phải số") from error
    if array.shape == (16,):
        array = array.reshape(4, 4)
    if array.shape != (4, 4):
        raise CalibrationParseError(f"{where}: cần ma trận 4×4 (hoặc 16 số theo hàng), nhận {array.shape}")
    return array


# ---------------------------------------------------------------------------
# TorWIC text
# ---------------------------------------------------------------------------


def looks_like_torwic_text(text: str) -> bool:
    return all(key in text for key in _TORWIC_KEYS)


def parse_torwic_text(text: str, *, lidar_frame: str = "lidar", camera_frame: str = "camera") -> Extrinsic:
    """`T_cam1_os.*` → `lidar_from_camera`. Nhãn của TorWIC ngược nghĩa chữ (xem đầu module)."""
    values: dict[str, float] = {}
    for raw in text.splitlines():
        key, separator, rest = raw.split("#", 1)[0].replace("=", ":", 1).partition(":")
        name = key.strip()
        if not separator or not name.startswith("T_cam1_os."):
            continue
        try:
            number = float(rest.strip())
        except ValueError as error:
            raise CalibrationParseError(f"{name}: không phải số") from error
        if name in values:
            raise CalibrationParseError(f"{name}: khai báo trùng")
        values[name] = number
    missing = [key for key in _TORWIC_KEYS if key not in values]
    if missing:
        raise CalibrationParseError(f"thiếu khoá extrinsic: {', '.join(missing)}")
    numbers = tuple(values[key] for key in _TORWIC_KEYS)
    return Extrinsic(
        parent_frame=lidar_frame,
        local_frame=camera_frame,
        translation_xyz=_checked_translation(numbers[:3], "T_cam1_os"),
        rotation_xyzw=_checked_quaternion(numbers[3:], "T_cam1_os"),
        source_format="torwic_text",
    )


# ---------------------------------------------------------------------------
# JSON của project
# ---------------------------------------------------------------------------


def parse_lidar_camera_json(text: str, *, lidar_frame: str = "lidar", camera_frame: str = "camera") -> Extrinsic:
    """`lidar_from_camera` hoặc `camera_from_lidar`; kết quả luôn là `lidar_from_camera`."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise CalibrationParseError(f"JSON không hợp lệ: {error.msg}") from error
    if not isinstance(document, dict):
        raise CalibrationParseError("JSON calibration phải là một object")
    has_forward, has_backward = "lidar_from_camera" in document, "camera_from_lidar" in document
    if has_forward and has_backward:
        raise CalibrationParseError("khai báo cả lidar_from_camera và camera_from_lidar; chọn một chiều duy nhất")
    if not (has_forward or has_backward):
        raise CalibrationParseError("thiếu khoá lidar_from_camera hoặc camera_from_lidar")
    key = "lidar_from_camera" if has_forward else "camera_from_lidar"
    block = document[key]
    if not isinstance(block, dict):
        raise CalibrationParseError(f"{key} phải là object")
    parent, local = (lidar_frame, camera_frame) if has_forward else (camera_frame, lidar_frame)
    if "matrix" in block:
        result = extrinsic_from_matrix(
            _matrix_from_rows(block["matrix"], key), parent=parent, local=local, source="lidar_camera_json"
        )
    else:
        try:
            translation = tuple(float(item) for item in block["translation_xyz"])
            rotation = tuple(float(item) for item in block["rotation_xyzw"])
        except (KeyError, TypeError, ValueError) as error:
            raise CalibrationParseError(f"{key}: cần translation_xyz + rotation_xyzw hoặc matrix") from error
        result = Extrinsic(
            parent_frame=parent,
            local_frame=local,
            translation_xyz=_checked_translation(translation, key),
            rotation_xyzw=_checked_quaternion(rotation, key),
            source_format="lidar_camera_json",
        )
    return result if has_forward else result.inverse()


# ---------------------------------------------------------------------------
# YAML (ROS, Kalibr)
# ---------------------------------------------------------------------------


def _load_yaml(text: str) -> dict[str, object]:
    if len(text.encode("utf-8")) > _MAX_YAML_BYTES:
        raise CalibrationParseError("YAML calibration vượt giới hạn 256 KiB")
    if _YAML_ANCHOR_OR_ALIAS.search(text):
        raise CalibrationParseError("YAML calibration không được dùng anchor/alias")
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise CalibrationParseError("YAML không hợp lệ") from error
    if not isinstance(document, dict):
        raise CalibrationParseError("YAML calibration phải là một mapping")
    return document


def _number_tuple(value: object, keys: tuple[str, ...], where: str) -> tuple[float, ...]:
    if not isinstance(value, dict) or any(key not in value for key in keys):
        raise CalibrationParseError(f"{where}: cần các khoá {', '.join(keys)}")
    try:
        return tuple(float(value[key]) for key in keys)
    except (TypeError, ValueError) as error:
        raise CalibrationParseError(f"{where}: giá trị không phải số") from error


def parse_ros_transform_yaml(text: str, *, lidar_frame_id: str | None) -> Extrinsic:
    """`TransformStamped` → `lidar_from_camera`.

    `header.frame_id` là frame cha, `child_frame_id` là frame con, và `transform` là pose của con
    trong cha, tức `p_parent = T · p_child`. Cần `lidar_frame_id` để biết đầu nào là LiDAR; không có
    hoặc không khớp đầu nào thì từ chối thay vì đoán.
    """
    document = _load_yaml(text)
    stamped = document
    if "transforms" in document:
        transforms = document["transforms"]
        if not isinstance(transforms, list) or len(transforms) != 1 or not isinstance(transforms[0], dict):
            raise CalibrationParseError("TFMessage phải có đúng một transform camera ↔ LiDAR")
        stamped = transforms[0]
    header = stamped.get("header")
    parent = header.get("frame_id") if isinstance(header, dict) else None
    child = stamped.get("child_frame_id")
    if not isinstance(parent, str) or not isinstance(child, str) or not parent or not child or parent == child:
        raise CalibrationParseError("thiếu header.frame_id hoặc child_frame_id (hoặc hai frame trùng nhau)")
    transform = stamped.get("transform")
    if not isinstance(transform, dict):
        raise CalibrationParseError("thiếu khối transform")
    translation = _number_tuple(transform.get("translation"), ("x", "y", "z"), "transform.translation")
    rotation = _number_tuple(transform.get("rotation"), ("x", "y", "z", "w"), "transform.rotation")
    extrinsic = Extrinsic(
        parent_frame=parent,
        local_frame=child,
        translation_xyz=_checked_translation(translation, "transform.translation"),
        rotation_xyzw=_checked_quaternion(rotation, "transform.rotation"),
        source_format="ros_transform_yaml",
    )
    if lidar_frame_id is None:
        raise CalibrationParseError(
            f"file nối {parent} và {child} nhưng chưa biết frame nào là LiDAR; hãy khai tên frame LiDAR"
        )
    if parent == lidar_frame_id:
        return extrinsic  # lidar_from_camera
    if child == lidar_frame_id:
        return extrinsic.inverse()
    raise CalibrationParseError(f"frame LiDAR đã khai ({lidar_frame_id}) không khớp {parent} hay {child}")


def parse_kalibr_camchain(text: str) -> list[KalibrCamera]:
    """Mọi khối `camN` của Kalibr. `T_cam_imu` là IMU → camera, tức `camera_from_imu`."""
    document = _load_yaml(text)
    cameras: list[KalibrCamera] = []
    for name in sorted(key for key in document if isinstance(key, str) and re.fullmatch(r"cam\d+", key)):
        block = document[name]
        if not isinstance(block, dict):
            raise CalibrationParseError(f"{name} phải là mapping")
        model = block.get("camera_model")
        intrinsics = block.get("intrinsics")
        if not isinstance(model, str) or not isinstance(intrinsics, list) or not intrinsics:
            raise CalibrationParseError(f"{name}: thiếu camera_model hoặc intrinsics")
        try:
            numbers = tuple(float(item) for item in intrinsics)
            coefficients = tuple(float(item) for item in block.get("distortion_coeffs") or ())
        except (TypeError, ValueError) as error:
            raise CalibrationParseError(f"{name}: intrinsics/distortion_coeffs không phải số") from error
        resolution = block.get("resolution")
        camera_from_imu = None
        if block.get("T_cam_imu") is not None:
            camera_from_imu = extrinsic_from_matrix(
                _matrix_from_rows(block["T_cam_imu"], f"{name}.T_cam_imu"),
                parent=name,
                local="imu",
                source="kalibr_camchain",
            )
        shift = block.get("timeshift_cam_imu")
        cameras.append(
            KalibrCamera(
                camera_name=name,
                camera_model=model,
                intrinsics=numbers,
                distortion_model=block.get("distortion_model")
                if isinstance(block.get("distortion_model"), str)
                else None,
                distortion_coeffs=coefficients,
                resolution=(int(resolution[0]), int(resolution[1]))
                if isinstance(resolution, list) and len(resolution) == 2
                else None,
                camera_from_imu=camera_from_imu,
                timeshift_cam_imu_seconds=float(shift) if isinstance(shift, (int, float)) else None,
            )
        )
    if not cameras:
        raise CalibrationParseError("không có khối camN nào trong camchain")
    return cameras


def compose_lidar_from_camera(camera_from_imu: Extrinsic, lidar_from_imu: Extrinsic) -> Extrinsic:
    """`lidar_from_camera = lidar_from_imu · inverse(camera_from_imu)` từ hai extrinsic có chiều rõ ràng.

    Chỉ ghép khi hai đầu IMU cùng một frame; kết quả đánh dấu nguồn Kalibr vì thành phần camera đến từ đó.
    """
    if camera_from_imu.local_frame != lidar_from_imu.local_frame:
        raise CalibrationParseError(
            f"hai extrinsic không chung frame IMU ({camera_from_imu.local_frame} ≠ {lidar_from_imu.local_frame})"
        )
    imu_from_camera = camera_from_imu.inverse()
    return extrinsic_from_matrix(
        lidar_from_imu.matrix() @ imu_from_camera.matrix(),
        parent=lidar_from_imu.parent_frame,
        local=camera_from_imu.parent_frame,
        source="kalibr_camchain",
    )
