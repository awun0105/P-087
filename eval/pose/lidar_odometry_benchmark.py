"""Benchmark KISS-ICP trên nhiều chuỗi TorWIC: độ trôi quỹ đạo và độ khớp bản đồ ghép với `groundtruth_map.ply`.

Evaluation-only: quỹ đạo chuẩn và bản đồ chuẩn không bao giờ đi vào đường chạy sản phẩm. Mỗi chuỗi cho hai nhóm số:

- **Quỹ đạo** (B so với A): ATE/RPE của quỹ đạo KISS-ICP so với `traj_gt.txt`, căn rigid CHỈ ở pose đầu (không fit
  tỉ lệ, không căn cả đường, nên trôi vẫn lộ ra).
- **Bản đồ**: ghép scan bằng quỹ đạo chuẩn (trần) và bằng quỹ đạo KISS-ICP, rồi đo khoảng cách từng điểm tới
  `groundtruth_map.ply`. Bản đồ chuẩn là bản đồ toàn bộ dataset (kho + hành lang), nên dùng chung cho mọi chuỗi.

    .venv/bin/python -m eval.pose.lidar_odometry_benchmark \
        --scenes /media/usb/AI20K/TorWIC_Raw_Scenes --map data/torwic_slam/raw/global/groundtruth_map.ply \
        --odometry-python data/lidar_runtime/bin/python --out eval/results/lidar_odometry_torwic.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from eval.pose.colmap_fusion_benchmark import umeyama
from src.services.reconstruction.lidar.odometry import default_lidar_odometry_profile

REPO = Path(__file__).resolve().parents[2]
# Hồ sơ đo lấy các số từ hồ sơ mặc định CỦA SẢN PHẨM, trừ trần tổng điểm (benchmark nâng lên mức tối đa của hợp đồng để
# chạy đủ 600 scan; xem `--max-total-points`). Tiền xử lý KHÔNG giống hệt sản phẩm: ở đây bỏ điểm < 0,5 m trước giảm
# mẫu (sản phẩm giữ `min_range_m = 0`, nhưng điểm (0,0,0) không hợp lệ bị KISS-ICP loại sẵn nên khác biệt thực tế
# nhỏ). Cả bản đồ trần (quỹ đạo thực) lẫn bản đồ KISS-ICP đều dựng từ scan đã giảm mẫu, nên chỉ so được HIỆU của hai cột.
PROFILE = default_lidar_odometry_profile().model_dump(mode="json")
_WORKER_ONLY = ("prefilter_voxel_m",)  # worker xử lý trước, runner cô lập không nhận trường này
MAP_STEP, MAP_VOXEL, MAP_RADIUS, MAP_WINDOW = 5, 0.10, 40.0, 8.0


def read_pcd_xyz(path: Path) -> np.ndarray:
    """PCD nhị phân của Ouster: x y z đầu tiên; bỏ điểm không hữu hạn."""
    with path.open("rb") as stream:
        header: dict[str, list[str]] = {}
        while True:
            key, *value = stream.readline().decode().split()
            header[key] = value
            if key == "DATA":
                break
        if header["DATA"][0] != "binary":
            raise ValueError("chỉ hỗ trợ PCD binary")
        dtype = np.dtype(
            [
                (name, {"F": "f", "U": "u", "I": "i"}[kind] + size)
                for name, size, kind in zip(header["FIELDS"], header["SIZE"], header["TYPE"], strict=True)
            ]
        )
        data = np.frombuffer(stream.read(), dtype=dtype, count=int(header["POINTS"][0]))
    xyz = np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float64)
    return xyz[np.isfinite(xyz).all(axis=1)]


def read_ply_xyz(path: Path) -> np.ndarray:
    raw = path.read_bytes()
    header = raw[: raw.index(b"end_header\n") + 11]
    count = int(header.split(b"element vertex ")[1].split()[0])
    props = header.count(b"property float")
    return (
        np.frombuffer(raw[len(header) :], dtype="<f4", count=count * props)
        .reshape(count, props)[:, :3]
        .astype(np.float64)
    )


def poses_from_tum(rows: np.ndarray) -> np.ndarray:
    matrices = np.tile(np.eye(4), (len(rows), 1, 1))
    matrices[:, :3, :3] = Rotation.from_quat(rows[:, 4:8]).as_matrix()
    matrices[:, :3, 3] = rows[:, 1:4]
    return matrices


def run_kiss_icp(python: Path, scans: list[Path], times: np.ndarray, work: Path) -> dict:
    manifest = {
        "schema_version": "1.0",
        "expected_provider_version": "1.3.0",
        "profile": {k: v for k, v in PROFILE.items() if k not in _WORKER_ONLY},
        "scans": [{"path": str(path), "timestamp_seconds": float(t)} for path, t in zip(scans, times, strict=True)],
    }
    (work / "manifest.json").write_text(json.dumps(manifest))
    subprocess.run(
        [
            str(python),
            str(REPO / "scripts/gpu/lidar_odometry_runner.py"),
            "--manifest",
            str(work / "manifest.json"),
            "--output",
            str(work / "out.json"),
        ],
        check=True,
        capture_output=True,
    )
    return json.loads((work / "out.json").read_text())


def trajectory_metrics(estimate: np.ndarray, truth: np.ndarray) -> dict:
    aligned = (truth[0] @ np.linalg.inv(estimate[0])) @ estimate
    ate = np.linalg.norm(aligned[:, :3, 3] - truth[:, :3, 3], axis=1)
    path_length = float(np.linalg.norm(np.diff(truth[:, :3, 3], axis=0), axis=1).sum())

    def rpe(step: int) -> tuple[float, float]:
        translation, rotation = [], []
        for i in range(len(truth) - step):
            error = np.linalg.inv(np.linalg.inv(truth[i]) @ truth[i + step]) @ (
                np.linalg.inv(aligned[i]) @ aligned[i + step]
            )
            translation.append(np.linalg.norm(error[:3, 3]))
            rotation.append(np.degrees(np.linalg.norm(Rotation.from_matrix(error[:3, :3]).as_rotvec())))
        return float(np.mean(translation)), float(np.mean(rotation))

    # Căn toàn đường (không phụ thuộc hướng ban đầu): tách "sai hướng đặt" khỏi "sai hình dạng thật".
    fits = {}
    for label, with_scale in (("rigid", False), ("sim3", True)):
        scale, rotation, shift = umeyama(estimate[:, :3, 3], truth[:, :3, 3], with_scale=with_scale)
        residual = np.linalg.norm(scale * estimate[:, :3, 3] @ rotation.T + shift - truth[:, :3, 3], axis=1)
        fits[label] = (scale, float(residual.mean()), float(residual.max()))
    step_t, step_r = rpe(1)
    ten_t, ten_r = rpe(10)
    return {
        "path_length_m": round(path_length, 1),
        "ate_mean_m": round(float(ate.mean()), 3),
        "ate_max_m": round(float(ate.max()), 3),
        "ate_end_m": round(float(ate[-1]), 3),
        "drift_percent": round(100 * float(ate[-1]) / path_length, 2),
        "fullpath_rigid_ate_mean_m": round(fits["rigid"][1], 3),
        "fullpath_rigid_ate_max_m": round(fits["rigid"][2], 3),
        "fullpath_sim3_ate_mean_m": round(fits["sim3"][1], 3),
        "fullpath_sim3_scale": round(fits["sim3"][0], 4),
        "rpe1_translation_m": round(step_t, 4),
        "rpe1_rotation_deg": round(step_r, 3),
        "rpe10_translation_m": round(ten_t, 4),
        "rpe10_rotation_deg": round(ten_r, 3),
    }


def build_map(scans: list[Path], poses: np.ndarray) -> np.ndarray:
    chunks = []
    for index in range(0, len(poses), MAP_STEP):
        points = np.load(scans[index])
        distance = np.linalg.norm(points, axis=1)
        points = points[(distance > 1.0) & (distance < MAP_RADIUS)][::4]
        chunks.append(points @ poses[index][:3, :3].T + poses[index][:3, 3])
    merged = np.vstack(chunks)
    _, first = np.unique(np.floor(merged / MAP_VOXEL).astype(np.int64), axis=0, return_index=True)
    return merged[first]


def map_metrics(points: np.ndarray, truth_tree: cKDTree, path_tree: cKDTree) -> dict:
    points = points[path_tree.query(points)[0] < MAP_WINDOW]
    distance, _ = truth_tree.query(points)
    return {
        "points": int(len(points)),
        "mean_cm": round(float(distance.mean() * 100), 1),
        "median_cm": round(float(np.median(distance) * 100), 1),
        "p95_cm": round(float(np.percentile(distance, 95) * 100), 1),
        "within_10cm_percent": round(100 * float((distance < 0.10).mean()), 1),
        "within_20cm_percent": round(100 * float((distance < 0.20).mean()), 1),
    }


def grid_downsample(points: np.ndarray, cell: float) -> np.ndarray:
    """Giữ một điểm mỗi ô lưới `cell` mét (điểm đầu tiên); thứ tự ổn định."""
    if not cell > 0:
        raise ValueError("ô giảm mẫu phải là số mét dương")
    _, first = np.unique(np.floor(points / cell).astype(np.int64), axis=0, return_index=True)
    return points[np.sort(first)]


PREFILTER_CELL: float | None = PROFILE.get("prefilter_voxel_m")


def evaluate_scene(directory: Path, python: Path, truth_map: np.ndarray, truth_tree: cKDTree, max_scans: int) -> dict:
    truth_rows = np.loadtxt(directory / "traj_gt.txt")
    scan_paths = sorted((directory / "lidar_scans").glob("*.pcd"))[: len(truth_rows)]
    with tempfile.TemporaryDirectory(prefix="odom-bench-") as tmp:
        work = Path(tmp)
        probe = read_pcd_xyz(scan_paths[0])
        probe = probe[np.linalg.norm(probe, axis=1) > 0.5]
        count = min(max_scans, int(PROFILE["max_total_points"] * 0.9 // max(len(probe), 1)), len(scan_paths))
        arrays = []
        kept_counts = []
        for index, path in enumerate(scan_paths[:count]):
            points = read_pcd_xyz(path)
            points = points[np.linalg.norm(points, axis=1) > 0.5]
            if PREFILTER_CELL is not None:
                points = grid_downsample(points, PREFILTER_CELL)
            kept_counts.append(len(points))
            target = work / f"{index:06d}.npy"
            np.save(target, points)
            arrays.append(target)
        rows = truth_rows[:count]
        result = run_kiss_icp(python, arrays, rows[:, 0], work)
        estimate = np.array(result["poses"])
        truth = poses_from_tum(rows)
        aligned = (truth[0] @ np.linalg.inv(estimate[0])) @ estimate
        path_tree = cKDTree(truth[:, :3, 3])
        return {
            "scene": directory.name,
            "scans_used": count,
            "points_per_scan": int(len(probe)),
            "points_per_scan_after_prefilter": int(np.mean(kept_counts)),
            "prefilter_cell_m": PREFILTER_CELL,
            "duration_s": round(float(rows[-1, 0] - rows[0, 0]), 1),
            "trajectory": trajectory_metrics(estimate, truth),
            "map_with_truth_trajectory": map_metrics(build_map(arrays, truth), truth_tree, path_tree),
            "map_with_kiss_icp": map_metrics(build_map(arrays, aligned), truth_tree, path_tree),
            "kiss_icp_seconds": round(float(result["provider_elapsed_seconds"]), 1),
            "kiss_icp_peak_rss_gb": round(result["provider_peak_rss_bytes"] / 1e9, 2),
            "provider_version": result["provider_version"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--scenes", type=Path, required=True, help="thư mục chứa các kịch bản có lidar_scans/ và traj_gt.txt"
    )
    parser.add_argument("--map", type=Path, required=True, help="groundtruth_map.ply")
    parser.add_argument("--odometry-python", type=Path, required=True, help="interpreter cô lập có kiss-icp")
    parser.add_argument("--max-scans", type=int, default=600)
    parser.add_argument(
        "--prefilter-cell",
        type=float,
        help="giảm mẫu lưới (m) từng scan trước KISS-ICP và trước khi đếm điểm; mặc định theo hồ sơ sản phẩm",
    )
    parser.add_argument("--no-prefilter", action="store_true", help="tắt giảm mẫu (tái lập mốc hồ sơ v1/v2)")
    parser.add_argument("--voxel", type=float, help="voxel_size_m (mét); bỏ trống = mặc định của sản phẩm")
    parser.add_argument(
        "--max-total-points",
        type=int,
        default=100_000_000,
        help="trần tổng điểm; mặc định benchmark 100 triệu, sản phẩm dùng default_lidar_odometry_profile()",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.voxel is not None:
        PROFILE["voxel_size_m"] = args.voxel
    PROFILE["max_total_points"] = args.max_total_points
    global PREFILTER_CELL
    if args.no_prefilter and args.prefilter_cell is not None:
        parser.error("--no-prefilter và --prefilter-cell loại trừ nhau")
    if args.prefilter_cell is not None and not args.prefilter_cell > 0:
        parser.error("--prefilter-cell phải là số mét dương")
    if args.no_prefilter:
        PROFILE["prefilter_voxel_m"] = None
    elif args.prefilter_cell is not None:
        PROFILE["prefilter_voxel_m"] = args.prefilter_cell
    PREFILTER_CELL = PROFILE["prefilter_voxel_m"]
    truth_map = read_ply_xyz(args.map)
    truth_tree = cKDTree(truth_map)
    results = []
    for directory in sorted(path for path in args.scenes.iterdir() if (path / "traj_gt.txt").is_file()):
        print(f"[bench] {directory.name} …", file=sys.stderr, flush=True)
        results.append(evaluate_scene(directory, args.odometry_python, truth_map, truth_tree, args.max_scans))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"profile": PROFILE, "scenes": results}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
