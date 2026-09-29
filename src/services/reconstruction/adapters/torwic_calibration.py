"""Dataset-specific extrinsics helper; không tạo world alignment hay metric approval."""

import math
import re
from pathlib import Path

from src.models.contracts.coordinates import Transform


def normalize_torwic_extrinsics(
    translation_xyz: tuple[float, float, float],
    rotation_xyzw: tuple[float, float, float, float],
    frames: tuple[str, str] = ("os_sensor", "azure_left_camera"),
) -> Transform:
    """Chỉ sửa roundoff quaternion trong 1e-5; không biến dữ liệu sai thành rotation."""
    norm = math.hypot(*rotation_xyzw)
    if not math.isfinite(norm) or norm == 0 or abs(norm - 1.0) > 1e-5:
        raise ValueError("calibration quaternion must be finite and approximately unit")
    if not all(math.isfinite(value) for value in translation_xyz):
        raise ValueError("calibration translation must be finite")
    return Transform(
        parent_frame=frames[0],
        local_frame=frames[1],
        translation_xyz=translation_xyz,
        rotation_quaternion_xyzw=tuple(value / norm for value in rotation_xyzw),
    )


def parse_torwic_calibrations(calibration_path: Path) -> dict[str, float]:
    """Đọc cả key=value và key:value như REC-01, chặn duplicate numeric keys."""
    values: dict[str, float] = {}
    for line in calibration_path.read_text().splitlines():
        parts = re.split(r"[:=]", line.split("#", 1)[0], maxsplit=1)
        if len(parts) != 2:
            continue
        key, raw = (part.strip() for part in parts)
        try:
            number = float(raw)
        except ValueError:
            if key.startswith("T_cam"):
                raise ValueError("invalid numeric camera extrinsic") from None
            continue
        if key in values or not math.isfinite(number):
            raise ValueError("duplicate or nonfinite calibration value")
        values[key] = number
    return values


def load_torwic_cam_to_lidar_transform(calibration_path: Path, camera_prefix: str = "T_cam1_os") -> Transform:
    """Raw label T_cam1_os thực chất T_os_from_cam; không phải T_world_from_map."""
    values = parse_torwic_calibrations(calibration_path)
    keys = [f"{camera_prefix}.{suffix}" for suffix in ("px", "py", "pz", "qx", "qy", "qz", "qw")]
    if camera_prefix != "T_cam1_os" or any(key not in values for key in keys):
        raise ValueError("missing or unsupported camera extrinsic; provide explicit frame metadata")
    numbers = tuple(values[key] for key in keys)
    return normalize_torwic_extrinsics(numbers[:3], numbers[3:])


def load_torwic_lidar_to_camera_transform(calibration_path: Path) -> Transform:
    """Chiều LiDAR→camera là inverse, vẫn là sensor extrinsic, không world alignment."""
    from src.services.reconstruction.alignment.transforms import invert_transform

    return invert_transform(load_torwic_cam_to_lidar_transform(calibration_path))
