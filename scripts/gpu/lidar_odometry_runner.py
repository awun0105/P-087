"""Small provider-side entrypoint for the isolated KISS-ICP environment."""

import argparse
import json
import os
import resource
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from kiss_icp.config import KISSConfig
from kiss_icp.kiss_icp import KissICP

_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


def run(manifest_path: Path, output_path: Path) -> None:
    """Run one ordered scan sequence and write exact provider matrices and metrics."""
    if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("odometry manifest exceeds the size limit")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "expected_provider_version",
        "profile",
        "scans",
    }:
        raise ValueError("odometry manifest has an unsupported schema")
    if manifest["schema_version"] != "1.0" or not isinstance(manifest["profile"], dict):
        raise ValueError("odometry manifest schema or profile is invalid")
    if version("kiss-icp") != manifest["expected_provider_version"]:
        raise RuntimeError("installed KISS-ICP version differs from the pinned worker contract")
    scans = manifest["scans"]
    profile = manifest["profile"]
    if not isinstance(scans, list) or len(scans) < 2:
        raise ValueError("odometry requires at least two ordered scan files")
    if set(profile) != {
        "min_range_m",
        "max_range_m",
        "voxel_size_m",
        "min_points_per_scan",
        "max_points_per_scan",
        "max_total_points",
        "max_num_threads",
        "timestamp_gap_threshold_seconds",
    }:
        raise ValueError("odometry profile fields differ from the pinned protocol")
    if not 0 <= float(profile["min_range_m"]) < float(profile["max_range_m"]):
        raise ValueError("KISS-ICP range bounds are invalid")
    if float(profile["voxel_size_m"]) <= 0 or int(profile["max_num_threads"]) < 1:
        raise ValueError("KISS-ICP voxel size and thread count must be positive")

    config = KISSConfig()
    config.data.deskew = False
    config.data.min_range = float(profile["min_range_m"])
    config.data.max_range = float(profile["max_range_m"])
    config.mapping.voxel_size = float(profile["voxel_size_m"])
    config.registration.max_num_threads = int(profile["max_num_threads"])
    odometry = KissICP(config)

    point_counts: list[int] = []
    poses: list[list[list[float]]] = []
    previous_timestamp = -float("inf")
    total_points = 0
    start = time.monotonic()
    cpu_start = time.process_time()
    for scan in scans:
        if not isinstance(scan, dict) or set(scan) != {"path", "timestamp_seconds"}:
            raise ValueError("odometry scan binding is invalid")
        timestamp = scan["timestamp_seconds"]
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not np.isfinite(timestamp):
            raise ValueError("odometry scan timestamp is invalid")
        if timestamp <= previous_timestamp:
            raise ValueError("odometry scan timestamps must be strictly increasing")
        previous_timestamp = float(timestamp)
        points = np.load(Path(scan["path"]), allow_pickle=False)
        if points.ndim != 2 or points.shape[1] != 3 or points.dtype.kind not in "fiu":
            raise ValueError("prepared scan must be a numeric Nx3 array")
        if len(points) < int(profile["min_points_per_scan"]) or len(points) > int(profile["max_points_per_scan"]):
            raise ValueError("prepared scan point count is outside its configured bounds")
        total_points += len(points)
        if total_points > int(profile["max_total_points"]):
            raise ValueError("prepared scan sequence exceeds its total point budget")
        if not np.isfinite(points).all():
            raise ValueError("prepared scan contains non-finite points")
        odometry.register_frame(points.astype(np.float64, copy=False), np.empty((0,), dtype=np.float64))
        matrix = np.asarray(odometry.last_pose, dtype=np.float64)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise RuntimeError("KISS-ICP returned an invalid pose matrix")
        point_counts.append(int(len(points)))
        poses.append(matrix.tolist())

    output: dict[str, Any] = {
        "schema_version": "1.0",
        "provider_id": "kiss-icp-python",
        "provider_version": version("kiss-icp"),
        "poses": poses,
        "point_counts": point_counts,
        "provider_elapsed_seconds": time.monotonic() - start,
        "provider_cpu_seconds": time.process_time() - cpu_start,
        "provider_peak_rss_bytes": max(1, int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)),
    }
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(temporary, output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.manifest, arguments.output)


if __name__ == "__main__":
    main()
