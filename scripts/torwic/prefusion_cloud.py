"""Open3D 0.19 primitives trong isolated offline runtime, không import vào API."""

from pathlib import Path

import numpy as np
import open3d as o3d

from scripts.torwic.prefusion_inputs import ScanPose, resolve_source
from scripts.torwic.prefusion_models import PrefusionRequest


def _transform(pose: ScanPose) -> np.ndarray:
    """Open3D quaternion API nhận wxyz; TUM source được giữ xyzw ở boundary."""
    x, y, z, w = pose.rotation_xyzw
    matrix = np.eye(4)
    matrix[:3, :3] = o3d.geometry.get_rotation_matrix_from_quaternion((w, x, y, z))
    matrix[:3, 3] = pose.translation
    return matrix


def _read_filtered(path: Path, request: PrefusionRequest) -> tuple[o3d.geometry.PointCloud, dict[str, int]]:
    cloud = o3d.io.read_point_cloud(path)
    points = np.asarray(cloud.points)
    count = len(points)
    if not count or count > request.max_scan_points:
        raise ValueError("scan is empty or exceeds declared point budget")
    finite = np.isfinite(points).all(axis=1)
    ranges = np.linalg.norm(points, axis=1)
    valid = finite & (ranges >= request.min_range_m)
    if request.max_range_m is not None:
        valid &= ranges <= request.max_range_m
    filtered = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points[valid]))
    if filtered.is_empty():
        raise ValueError("scan is empty after finite/range filtering")
    return filtered, {"input_points": count, "removed_points": count - int(valid.sum())}


def _sorted_cloud(cloud: o3d.geometry.PointCloud) -> o3d.geometry.PointCloud:
    """Stabilize Open3D hash-grid iteration order trước ghi byte checksum."""
    points = np.asarray(cloud.points)
    order = np.lexsort((points[:, 2], points[:, 1], points[:, 0]))
    return o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points[order]))


def fuse(root: Path, request: PrefusionRequest, poses: dict[int, ScanPose]) -> tuple[o3d.geometry.PointCloud, dict]:
    """Downsample mỗi scan rồi merge/final voxel; không tự viết point-cloud primitives."""
    if o3d.__version__ != "0.19.0":
        raise ValueError("prefusion requires audited Open3D 0.19.0")
    o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Error)
    merged, stats = o3d.geometry.PointCloud(), []
    for scan in request.scans:
        cloud, counts = _read_filtered(resolve_source(root, scan), request)
        cloud.transform(_transform(poses[scan.frame_id]))
        if request.voxel_size_m is not None:
            cloud = cloud.voxel_down_sample(request.voxel_size_m)
        if len(merged.points) + len(cloud.points) > request.max_merged_points:
            raise ValueError("merged cloud exceeds declared point budget; reduce selection")
        merged += cloud
        stats.append({"frame_id": scan.frame_id, **counts, "merged_points": len(cloud.points)})
    if request.voxel_size_m is not None:
        merged = merged.voxel_down_sample(request.voxel_size_m)
    result = _sorted_cloud(merged)
    if result.is_empty() or not np.isfinite(np.asarray(result.points)).all():
        raise ValueError("prefusion output is empty or nonfinite")
    return result, {
        "scans": stats,
        "point_count": len(result.points),
        "bounds_min": result.get_min_bound().tolist(),
        "bounds_max": result.get_max_bound().tolist(),
    }


def write_cloud(path: Path, cloud: o3d.geometry.PointCloud) -> None:
    """Native PLY, kiểm bool result và đọc lại để không publish truncated output."""
    if not o3d.io.write_point_cloud(path, cloud, write_ascii=False, compressed=False):
        raise ValueError("Open3D failed to write registered cloud")
    actual = o3d.io.read_point_cloud(path)
    if not np.array_equal(np.asarray(actual.points), np.asarray(cloud.points)):
        raise ValueError("registered cloud failed exact coordinate roundtrip")
