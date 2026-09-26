"""Data models và transform helpers cho REC-09 RGB-LiDAR Alignment."""

import math
from pathlib import Path

from pydantic import Field

from src.models.contracts.artifacts import ContractModel, Identifier, JsonObject, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.reconstruction import AlignmentStatus


def invert_transform(transform: Transform) -> Transform:
    """Nghịch đảo rigid transform: R^T và -R^T * t."""
    tx, ty, tz = transform.translation_xyz
    qx, qy, qz, qw = transform.rotation_quaternion_xyzw
    inv_q = (-qx, -qy, -qz, qw)
    # R^T * t
    a, b, c = tx, ty, tz
    two = 2.0
    two_y_c, two_z_b = two * (inv_q[1] * c - inv_q[2] * b), two * (inv_q[2] * a - inv_q[0] * c)
    two_x_b = two * (inv_q[0] * b - inv_q[1] * a)
    rx = a + inv_q[3] * two_y_c + inv_q[1] * two_x_b - inv_q[2] * two_z_b
    ry = b + inv_q[3] * two_z_b + inv_q[2] * two_y_c - inv_q[0] * two_x_b
    rz = c + inv_q[3] * two_x_b + inv_q[0] * two_z_b - inv_q[1] * two_y_c
    return Transform(
        parent_frame=transform.local_frame,
        local_frame=transform.parent_frame,
        translation_xyz=(-rx, -ry, -rz),
        rotation_quaternion_xyzw=inv_q,
    )


def normalize_torwic_extrinsics(
    translation_xyz: tuple[float, float, float], rotation_xyzw: tuple[float, float, float, float]
) -> Transform:
    """Chuẩn hóa extrinsic TorWIC: chuyển T_os_from_cam thành T_world_from_lidar."""
    norm = math.sqrt(sum(c * c for c in rotation_xyzw))
    if not math.isclose(norm, 1.0, rel_tol=1e-5):
        rotation_xyzw = tuple(c / norm for c in rotation_xyzw)
    return Transform(
        parent_frame="world",
        local_frame="registered_lidar",
        translation_xyz=translation_xyz,
        rotation_quaternion_xyzw=rotation_xyzw,
    )


def parse_torwic_calibrations(calibration_path: Path) -> dict[str, float]:
    """Đọc file calibrations.txt của TorWIC và trích xuất các tham số extrinsic dạng float."""
    values: dict[str, float] = {}
    for line in calibration_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        try:
            values[key.strip()] = float(val.strip())
        except ValueError:
            continue
    return values


def load_torwic_cam_to_lidar_transform(calibration_path: Path, camera_prefix: str = "T_cam1_os") -> Transform:
    """Tạo Transform chuẩn hóa từ calibration thật của TorWIC giữa camera và OS128 LiDAR."""
    vals = parse_torwic_calibrations(calibration_path)
    t = (vals[f"{camera_prefix}.px"], vals[f"{camera_prefix}.py"], vals[f"{camera_prefix}.pz"])
    q = (
        vals[f"{camera_prefix}.qx"],
        vals[f"{camera_prefix}.qy"],
        vals[f"{camera_prefix}.qz"],
        vals[f"{camera_prefix}.qw"],
    )
    return normalize_torwic_extrinsics(t, q)


class AlignmentRequest(ContractModel):
    """Yêu cầu xác nhận alignment giữa RGB Geometry và LiDAR Geometry."""

    job_id: Identifier
    rgb_geometry_ref: ProductArtifactRef
    lidar_geometry_ref: ProductArtifactRef
    transform_target_from_source: Transform
    method: Identifier = "calibration_known_transform"
    status: AlignmentStatus = AlignmentStatus.CONFIRMED
    evidence_refs: list[ProductArtifactRef] = Field(default_factory=list)
    same_scene_attestation: bool = True
    provenance: JsonObject = Field(default_factory=dict)
