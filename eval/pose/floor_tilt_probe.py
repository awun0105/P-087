"""Đo độ nghiêng của mặt sàn (evaluation-only): trong khung cảm biến, trong hệ thế giới của `traj_gt`, và trong `.ply` chuẩn.

Giả định có chủ ý và được ghi rõ: cảm biến *gần thẳng đứng* (trục z lên trên), để chọn nửa thấp của scan làm ứng viên sàn.
Đây là công cụ đo cho dataset TorWIC, KHÔNG phải bộ ước lượng hướng "lên" mount-agnostic của sản phẩm.

    .venv/bin/python -m eval.pose.floor_tilt_probe --scenes /media/usb/AI20K/TorWIC_Raw_Scenes \
        --map data/torwic_slam/raw/global/groundtruth_map.ply --out eval/results/floor_tilt_torwic.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from eval.pose.lidar_odometry_benchmark import read_pcd_xyz, read_ply_xyz


def fit_floor_normal(
    points: np.ndarray, *, seed: int = 0, iterations: int = 400, threshold_m: float = 0.04
) -> np.ndarray:
    """Pháp tuyến (hướng +z) của mặt phẳng lớn nhất trong nửa thấp của vùng 1,5-12 m; RANSAC rồi tinh chỉnh SVD."""
    distance = np.linalg.norm(points, axis=1)
    points = points[(distance > 1.5) & (distance < 12)]
    points = points[points[:, 2] < np.percentile(points[:, 2], 40)]
    rng = np.random.default_rng(seed)
    best: tuple[int, np.ndarray] | None = None
    for _ in range(iterations):
        sample = points[rng.choice(len(points), 3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        length = np.linalg.norm(normal)
        if length < 1e-9:
            continue
        normal /= length
        inliers = np.abs((points - sample[0]) @ normal) < threshold_m
        if best is None or inliers.sum() > best[0]:
            best = (int(inliers.sum()), inliers)
    assert best is not None
    inlier_points = points[best[1]]
    normal = np.linalg.svd(inlier_points - inlier_points.mean(0), full_matrices=False)[2][2]
    return normal if normal[2] > 0 else -normal


def tilt_deg(normal: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip(normal[2], -1.0, 1.0))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenes", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scan-step", type=int, default=100)
    args = parser.parse_args(argv)

    scenes = []
    first_truth: np.ndarray | None = None
    for directory in sorted(path for path in args.scenes.iterdir() if (path / "traj_gt.txt").is_file()):
        truth = np.loadtxt(directory / "traj_gt.txt")
        first_truth = truth if first_truth is None else first_truth
        sensor, world = [], []
        for index in range(0, min(600, len(truth)), args.scan_step):
            normal = fit_floor_normal(read_pcd_xyz(directory / "lidar_scans" / f"{index:06d}.pcd"))
            sensor.append(tilt_deg(normal))
            world.append(tilt_deg(Rotation.from_quat(truth[index, 4:8]).as_matrix() @ normal))
        scenes.append(
            {
                "scene": directory.name,
                "scans_sampled": len(sensor),
                "floor_tilt_in_sensor_frame_deg": {
                    "median": round(float(np.median(sensor)), 2),
                    "all": [round(v, 2) for v in sensor],
                },
                "floor_tilt_in_gt_world_deg": {
                    "median": round(float(np.median(world)), 2),
                    "max": round(float(np.max(world)), 2),
                },
            }
        )
    ground_truth_map = read_ply_xyz(args.map)
    path_tree = cKDTree(first_truth[:600, 1:3])
    near = ground_truth_map[path_tree.query(ground_truth_map[:, :2])[0] < 6.0]
    map_floor = fit_floor_normal_world(near)
    report = {"scenes": scenes, "ground_truth_map_floor_tilt_deg": round(tilt_deg(map_floor), 2)}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


def fit_floor_normal_world(points: np.ndarray) -> np.ndarray:
    """Sàn của bản đồ chuẩn trong hệ thế giới: nửa thấp theo z, RANSAC rồi SVD (không lọc theo khoảng cách cảm biến)."""
    low = points[points[:, 2] < np.percentile(points[:, 2], 30)]
    rng = np.random.default_rng(0)
    best = None
    for _ in range(600):
        sample = low[rng.choice(len(low), 3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        length = np.linalg.norm(normal)
        if length < 1e-9:
            continue
        normal /= length
        inliers = np.abs((low - sample[0]) @ normal) < 0.03
        if best is None or inliers.sum() > best[0]:
            best = (int(inliers.sum()), inliers)
    chosen = low[best[1]]
    normal = np.linalg.svd(chosen - chosen.mean(0), full_matrices=False)[2][2]
    return normal if normal[2] > 0 else -normal


if __name__ == "__main__":
    raise SystemExit(main())
