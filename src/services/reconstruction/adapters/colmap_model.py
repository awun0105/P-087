"""Đọc COLMAP TXT và đảo cam_from_world; không triển khai thuật toán SfM."""

import math
from dataclasses import dataclass
from pathlib import Path

from src.services.reconstruction.rgb.pose.camera_pose import CameraIntrinsics, CameraPose, SparseModelStats


@dataclass(frozen=True)
class ParsedSparseModel:
    """Một model hoàn chỉnh trong world frame riêng của nó."""

    directory: Path
    stats: SparseModelStats
    cameras: list[CameraIntrinsics]
    poses: list[CameraPose]


def _data_lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _camera(line: str) -> CameraIntrinsics:
    parts = line.split()
    if len(parts) < 5:
        raise ValueError("truncated COLMAP camera record")
    return CameraIntrinsics(
        camera_id=int(parts[0]),
        model=parts[1],
        width=int(parts[2]),
        height=int(parts[3]),
        parameters=[float(value) for value in parts[4:]],
    )


def _inverse_pose(values: list[float]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("nonfinite COLMAP pose")
    w, x, y, z, tx, ty, tz = values
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if not math.isclose(norm, 1.0, abs_tol=1e-5):
        raise ValueError("invalid COLMAP quaternion norm")
    w, x, y, z = (value / norm for value in (w, x, y, z))
    rotation = (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )
    center = tuple(-sum(rotation[j][i] * (tx, ty, tz)[j] for j in range(3)) for i in range(3))
    quaternion = (-x, -y, -z, w)
    # q và -q biểu diễn cùng rotation; chọn dấu canonical để diff ổn định.
    if next((v for v in reversed(quaternion) if v != 0), 1) < 0:
        quaternion = tuple(-v for v in quaternion)
    return center, quaternion


def _pose(line: str) -> CameraPose:
    parts = line.split()
    if len(parts) != 10 or not parts[9].endswith(".png") or not parts[9][:-4].isdigit():
        raise ValueError("invalid COLMAP image record or unexpected image name")
    center, quaternion = _inverse_pose([float(value) for value in parts[1:8]])
    return CameraPose(
        frame_id=int(parts[9][:-4]),
        image_id=int(parts[0]),
        camera_id=int(parts[8]),
        image_name=parts[9],
        translation=center,
        rotation_xyzw=quaternion,
    )


def _poses(path: Path) -> list[CameraPose]:
    # POINTS2D có thể rỗng; không lọc blank lines trước khi parse cặp record.
    lines = iter(path.read_text().splitlines())
    poses = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        poses.append(_pose(line))
        observations = next(lines, None)
        if observations is None or len(observations.split()) % 3:
            raise ValueError("truncated COLMAP POINTS2D record")
        values = observations.split()
        for index in range(0, len(values), 3):
            if not all(math.isfinite(float(x)) for x in values[index : index + 2]):
                raise ValueError("nonfinite COLMAP observation")
            int(values[index + 2])
    return sorted(poses, key=lambda pose: pose.frame_id)


def _point_count(path: Path) -> int:
    ids = set()
    for line in _data_lines(path):
        parts = line.split()
        if len(parts) < 10 or (len(parts) - 8) % 2:
            raise ValueError("invalid COLMAP point track")
        point_id = int(parts[0])
        if point_id in ids or point_id < 0:
            raise ValueError("duplicate or invalid COLMAP point ID")
        if not all(math.isfinite(float(x)) for x in parts[1:4] + [parts[7]]):
            raise ValueError("nonfinite COLMAP point")
        if any(not 0 <= int(x) <= 255 for x in parts[4:7]) or float(parts[7]) < 0:
            raise ValueError("invalid COLMAP point color or error")
        if any(int(x) < 0 for x in parts[8:]):
            raise ValueError("invalid COLMAP track reference")
        ids.add(point_id)
    return len(ids)


def read_sparse_model(directory: Path, frame_ids: tuple[int, ...]) -> ParsedSparseModel:
    """Reject model rỗng/hỏng/ngoài frame set trước khi xét model-selection."""
    cameras = sorted((_camera(line) for line in _data_lines(directory / "cameras.txt")), key=lambda c: c.camera_id)
    poses = _poses(directory / "images.txt")
    camera_ids = [camera.camera_id for camera in cameras]
    if len(camera_ids) != len(set(camera_ids)) or any(p.camera_id not in camera_ids for p in poses):
        raise ValueError("missing or duplicate COLMAP camera")
    ids = [pose.frame_id for pose in poses]
    if len(ids) != len(set(ids)) or not set(ids) <= set(frame_ids):
        raise ValueError("COLMAP model contains duplicate or foreign input frame")
    if len({p.image_id for p in poses}) != len(poses):
        raise ValueError("duplicate COLMAP image ID")
    stats = SparseModelStats(
        model_id=directory.name, registered_frames=len(poses), sparse_points=_point_count(directory / "points3D.txt")
    )
    return ParsedSparseModel(directory, stats, cameras, poses)


def select_sparse_model(models: list[ParsedSparseModel]) -> ParsedSparseModel:
    """Tie-break bằng numeric model ID, độc lập filesystem iteration order."""
    if not models:
        raise ValueError("COLMAP produced no valid sparse model; check overlap and texture")
    return min(models, key=lambda model: (-model.stats.registered_frames, int(model.stats.model_id)))
