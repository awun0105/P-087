"""Checksum, timestamp và TUM pose validation trước khi Open3D đọc scan data."""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from scripts.torwic.prefusion_models import PrefusionRequest, SourceFile


@dataclass(frozen=True)
class ScanPose:
    """Native target_from_source pose; xyzw được normalize trong tolerance khai báo."""

    timestamp: float
    translation: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]


def checksum(path: Path) -> str:
    """Hash stream để không nạp cloud lớn vào RAM lần thứ hai."""
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def resolve_source(root: Path, reference: SourceFile) -> Path:
    """Bind bytes và chặn symlink thoát root dù relative name hợp lệ."""
    path = (root / reference.relative_path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("source is missing or escapes dataset root")
    if checksum(path) != reference.checksum:
        raise ValueError("source checksum mismatch")
    return path


def _parse_pose(line: str, tolerance: float) -> ScanPose:
    values = tuple(float(item) for item in line.split())
    if len(values) != 8 or not all(math.isfinite(value) for value in values):
        raise ValueError("TUM pose requires timestamp xyz xyzw finite values")
    norm = math.hypot(*values[4:])
    if norm == 0 or abs(norm - 1) > tolerance:
        raise ValueError("pose quaternion is not normalized within declared tolerance")
    return ScanPose(values[0], values[1:4], tuple(value / norm for value in values[4:]))


def _load_poses(path: Path, tolerance: float) -> list[ScanPose]:
    poses = [
        _parse_pose(line, tolerance)
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not poses or any(b.timestamp <= a.timestamp for a, b in zip(poses, poses[1:])):
        raise ValueError("pose timestamps must be nonempty, unique and ordered")
    return poses


def validate_inputs(root: Path, request: PrefusionRequest) -> dict[int, ScanPose]:
    """TorWIC indexed synchronization; không silently nearest-match hoặc interpolate."""
    paths = {ref.relative_path: resolve_source(root, ref) for ref in request.sources()}
    poses = _load_poses(paths[request.trajectory.relative_path], request.quaternion_norm_tolerance)
    times = [float(line) for line in paths[request.timestamps.relative_path].read_text().splitlines() if line.strip()]
    if len(times) != len(poses) or not all(math.isfinite(value) for value in times):
        raise ValueError("frame timestamps and pose inventory differ")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("frame timestamps must be unique and ordered")
    if any(abs(time - pose.timestamp) > request.timestamp_tolerance_s for time, pose in zip(times, poses)):
        raise ValueError("scan and pose timestamps are not synchronized")
    if request.scans[-1].frame_id >= len(poses):
        raise ValueError("selected scan has no pose")
    evidence = json.loads(paths[request.coordinate_evidence.relative_path].read_text())
    if evidence.get("source_frame_hypothesis") != request.source_frame:
        raise ValueError("source frame differs from coordinate evidence")
    return {scan.frame_id: poses[scan.frame_id] for scan in request.scans}
