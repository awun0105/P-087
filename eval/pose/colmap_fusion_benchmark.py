"""Benchmark COLMAP + LiDAR trên TorWIC: E0 (kiểm chuỗi nối bằng quỹ đạo thực) và E1 (COLMAP đơn).

Evaluation-only. Đầu vào là mô hình COLMAP dạng văn bản (`images.txt`) của một chuỗi, quỹ đạo thực `traj_gt.txt` và
`calibrations.txt` (T_os_from_cam). Tên ảnh là chỉ số scan (`000123.png`).

- **E1**: tâm camera COLMAP so với quỹ đạo thực sau một phép đồng dạng (xoay + tịnh tiến + tỉ lệ) khớp toàn đường:
  COLMAP đúng *hình dạng* tới đâu, và tỉ lệ mét ước được lệch bao nhiêu so với tỉ lệ thật (1,0).
- **E0**: cùng phép khớp nhưng thử hai giả thuyết về khung của `traj_gt.txt`: (a) là khung cảm biến LiDAR (`os_sensor`),
  (b) đã là khung camera. Giả thuyết đúng cho sai số khớp nhỏ hơn rõ rệt; chênh lệch cỡ cần-bù là đòn bẩy cánh tay.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

TORWIC_T_OS_CAM = {  # coordinate_metadata.json: T_cam1_os, nghĩa thật là os_from_cam (parent_from_local)
    "translation": (0.12944592, 0.04299934, -0.1137434),
    "quaternion_xyzw": (-0.6116725, 0.39292797, -0.3567415, 0.58668551),
}


def read_colmap_centers(images_txt: Path) -> dict[int, np.ndarray]:
    centers: dict[int, np.ndarray] = {}
    # Mỗi ảnh hai dòng: pose rồi điểm 2D. Dòng điểm 2D có thể RỖNG (ảnh không có quan sát) nên chỉ bỏ dòng chú thích.
    lines = [line for line in images_txt.read_text().splitlines() if not line.startswith("#")]
    for line in lines[::2]:
        if not line.strip():
            continue
        parts = line.split()
        qw, qx, qy, qz = map(float, parts[1:5])
        t = np.array(list(map(float, parts[5:8])))
        rotation = Rotation.from_quat([qx, qy, qz, qw]).as_matrix()  # world→cam
        index = int(re.match(r"(\d+)", Path(parts[9]).stem).group(1))
        centers[index] = -rotation.T @ t
    return centers


def umeyama(source: np.ndarray, target: np.ndarray, with_scale: bool = True) -> tuple[float, np.ndarray, np.ndarray]:
    mu_s, mu_t = source.mean(0), target.mean(0)
    s0, t0 = source - mu_s, target - mu_t
    u, d, vt = np.linalg.svd(t0.T @ s0 / len(source))
    sign = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[2, 2] = -1
    rotation = u @ sign @ vt
    scale = float(np.trace(np.diag(d) @ sign) / s0.var(0).sum()) if with_scale else 1.0
    return scale, rotation, mu_t - scale * rotation @ mu_s


def fit_report(source: np.ndarray, target: np.ndarray) -> dict:
    scale, rotation, translation = umeyama(source, target)
    residual = np.linalg.norm(scale * source @ rotation.T + translation - target, axis=1)
    return {
        "scale": round(scale, 4),
        "ate_mean_m": round(float(residual.mean()), 3),
        "ate_median_m": round(float(np.median(residual)), 3),
        "ate_p90_m": round(float(np.percentile(residual, 90)), 3),
        "ate_max_m": round(float(residual.max()), 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images-txt", type=Path, required=True)
    parser.add_argument("--traj-gt", type=Path, required=True)
    parser.add_argument("--registered-of", type=int, required=True, help="số ảnh đã đưa vào COLMAP")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    centers = read_colmap_centers(args.images_txt)
    truth = np.loadtxt(args.traj_gt)
    indices = sorted(centers)
    sfm = np.array([centers[i] for i in indices])
    lidar_xyz = truth[indices, 1:4]
    lidar_rot = Rotation.from_quat(truth[indices, 4:8]).as_matrix()
    cam_offset = np.array(TORWIC_T_OS_CAM["translation"])
    cam_rot = Rotation.from_quat(TORWIC_T_OS_CAM["quaternion_xyzw"]).as_matrix()
    cam_centers_if_lidar = lidar_xyz + lidar_rot @ cam_offset  # giả thuyết (a): traj_gt là khung os_sensor

    path_length = float(np.linalg.norm(np.diff(lidar_xyz, axis=0), axis=1).sum())
    report = {
        "registered_frames": len(indices),
        "input_frames": args.registered_of,
        "registered_percent": round(100 * len(indices) / args.registered_of, 1),
        "path_length_m": round(path_length, 1),
        "e1_colmap_vs_truth_as_is": fit_report(sfm, lidar_xyz),
        "e0_hypothesis_traj_gt_is_os_sensor": fit_report(sfm, cam_centers_if_lidar),
        "lever_arm_m": round(float(np.linalg.norm(cam_offset)), 3),
        "camera_rotation_deg_from_os": round(
            float(np.degrees(np.linalg.norm(Rotation.from_matrix(cam_rot).as_rotvec()))), 1
        ),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
