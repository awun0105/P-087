"""Benchmark `collision_path_clearance` cho **hình học va chạm dựng từ LiDAR**, so với mesh từ 3DGS của cùng job.

ADR 0009 yêu cầu đo trước khi kết luận mesh từ LiDAR tốt hơn mesh từ 3DGS. Với một job có gói LiDAR đã chạy xong:

1. đặt đám mây LiDAR đã đăng ký vào hệ `world` của scene (khớp cứng tâm camera theo quỹ đạo với pose canonical);
2. chia ô voxel đúng độ phân giải của REC-05 → các ô bị chiếm;
3. đếm vị trí camera mà khối robot đặt tại đó chạm ô bị chiếm — cùng phép kiểm với mesh 3DGS (`blocked_positions`).

Camera gắn trên robot đã đi qua các vị trí đó, nên mọi vị trí bị chặn là vật cản giả.

    python -m eval.path.lidar_clearance --job-root <artifacts/jobs/job-…> --profile configs/product/geometry_v1.json \\
        --label aisle-cw-lidar-job --out eval/results/collision_path_clearance/aisle-cw-lidar-job.jsonl

Thêm `--package <gói scan thô .zip> --min-range 0.5 2 3` để ghép lại riêng các scan cùng thời gian với video ở nhiều
ngưỡng tầm đo gần: điểm rất gần cảm biến thường là thứ đi cùng robot (thân robot, người đi theo), không phải vật cản
tĩnh, và phép này cho biết chúng gây bao nhiêu phần chặn nhầm.

Kết quả phụ thuộc nguồn quỹ đạo của gói (`trajectory_origin`): gói mẫu TorWIC dùng ground truth, ghi rõ trong mỗi dòng.
"""

import argparse
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from eval.path.path_clearance import blocked_positions
from src.services.reconstruction.adapters.collision_glb import read_collision_glb, topology
from src.services.reconstruction.finalize import GeometryProfile
from src.services.reconstruction.lidar.camera_priors import camera_priors
from src.services.reconstruction.lidar.fusion import FusionConfig, fuse_scans, parse_trajectory, read_points
from src.services.reconstruction.lidar.package import LidarPackageRecord
from src.services.reconstruction.lidar.world_alignment import fit_world_from_lidar_map

MAX_POINTS = 50_000_000


def occupied_cells(points: np.ndarray, resolution: float) -> np.ndarray:
    """Tâm các ô voxel có điểm LiDAR."""
    return (np.unique(np.floor(points / resolution).astype(np.int64), axis=0) + 0.5) * resolution


def refuse(package: Path, last_frame: int, min_range: float) -> tuple[np.ndarray, int]:
    """Ghép lại các scan của gói có chỉ số frame ≤ `last_frame` (cùng thời gian với video) với tầm gần `min_range`."""
    with zipfile.ZipFile(package) as archive:
        members = {
            int(match.group(1)): name
            for name in archive.namelist()
            if (match := re.search(r"(\d+)\.pcd$", name)) and int(match.group(1)) <= last_frame
        }
        trajectory = next(name for name in archive.namelist() if Path(name).name.startswith("traj"))
        poses = parse_trajectory(archive.read(trajectory).decode("utf-8"))

        def scans():  # noqa: ANN202 - generator cục bộ
            for index in sorted(members):
                yield read_points(io.BytesIO(archive.read(members[index])), MAX_POINTS), poses[index]

        cloud, _ = fuse_scans(scans(), FusionConfig(min_range_m=min_range))
    return cloud, len(members)


def _only(root: Path, pattern: str) -> Path:
    """File duy nhất khớp mẫu dưới thư mục job; nhiều hơn một nghĩa là job có nhiều lần chạy, phải chỉ rõ."""
    found = sorted(root.glob(pattern))
    if len(found) != 1:
        raise ValueError(f"cần đúng một file {pattern} dưới {root}, thấy {len(found)}")
    return found[0]


def run(args: argparse.Namespace) -> list[dict]:
    """Một dòng cho mesh 3DGS của job, một dòng cho đám mây LiDAR của job, rồi mỗi ngưỡng tầm gần một dòng."""
    profile = GeometryProfile.model_validate_json(args.profile.read_text())
    radius, height = profile.capsule_radius_m, profile.capsule_height_m
    record = LidarPackageRecord.model_validate_json(_only(args.job_root, "rec08/*/lidar_package.json").read_bytes())
    lidar_dir = _only(args.job_root, "rec08/*/lidar_package.json").parent
    canonical = json.loads(_only(args.job_root, "rec06/*/camera_poses.json").read_text())
    poses = sorted(canonical["poses"], key=lambda item: item["frame_id"])
    centers = np.array([pose["translation"] for pose in poses])
    trajectory = parse_trajectory((lidar_dir / Path(record.trajectory_ref.artifact_uri).name).read_text())
    priors = camera_priors(trajectory, record.sensor_from_camera, tuple(pose["frame_id"] for pose in poses))
    alignment = fit_world_from_lidar_map([prior.translation for prior in priors], [tuple(c) for c in centers])
    with (lidar_dir / Path(record.lidar_geometry_ref.artifact_uri).name).open("rb") as stream:
        cloud = alignment.apply(read_points(stream, MAX_POINTS))
    mesh = read_collision_glb(_only(args.job_root, "rec05/*/collision.glb"))
    mesh_vertices = np.asarray(mesh.positions, dtype=float).reshape(-1, 3)
    mesh_blocked = blocked_positions(mesh_vertices, centers, radius, height)
    common = {
        "job_id": record.job_id,
        "trajectory_origin": record.trajectory_origin,
        "camera_positions": len(centers),
        "robot_radius_m": radius,
        "robot_height_m": height,
        "resolution_m": profile.resolution_m,
    }
    rows = [
        {
            **common,
            "source": "rgb_3dgs_mesh",
            "triangles": topology(mesh)["triangles"],
            "blocked_positions": len(mesh_blocked),
            "blocked_fraction": round(len(mesh_blocked) / len(centers), 4),
            "blocked_frame_indices": mesh_blocked,
        }
    ]
    lidar = {
        **common,
        "alignment_method": alignment.method,
        "alignment_median_m": round(alignment.median_residual_m, 4),
    }
    clouds: list[tuple[dict, np.ndarray]] = [({"source": "lidar_occupancy", "cloud": "job_registered"}, cloud)]
    for min_range in args.min_range if args.package else ():
        refused, scans_used = refuse(args.package, poses[-1]["frame_id"], min_range)
        label = {"source": "lidar_occupancy", "cloud": "refused_video_span", "min_range_m": min_range}
        clouds.append((label | {"scans_used": scans_used}, alignment.apply(refused)))
    for label, points in clouds:
        cells = occupied_cells(points, profile.resolution_m)
        # Sàn LiDAR dày hơn sàn của mesh 3DGS (nhiễu đo + sai số pose), nên đo thêm với dải sàn rộng hơn 3 cm của
        # benchmark để tách "chặn do sàn" khỏi "chặn do vật phía trên sàn".
        for floor_band in args.floor_band:
            blocked = blocked_positions(cells[cells[:, 2] > floor_band], centers, radius, height)
            rows.append(
                {
                    **lidar,
                    **label,
                    "floor_band_m": floor_band,
                    "lidar_points": len(points),
                    "occupied_cells": len(cells),
                    "blocked_positions": len(blocked),
                    "blocked_fraction": round(len(blocked) / len(centers), 4),
                    "blocked_frame_indices": blocked,
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    """Ghi JSONL (append) theo quy ước eval/protocols/BENCHMARKS.md."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job-root", type=Path, required=True, help="thư mục artifacts/jobs/<job_id> của job")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--package", type=Path, help="gói scan thô (.zip) để ghép lại theo --min-range")
    parser.add_argument("--floor-band", type=float, nargs="+", default=[0.03, 0.15])
    parser.add_argument("--min-range", type=float, nargs="+", default=[0.5, 2.0, 3.0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = run(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    measured_at = datetime.now(UTC).isoformat()
    with args.out.open("a", encoding="utf-8") as stream:
        for row in rows:
            record = {"benchmark": "collision_path_clearance", "label": args.label, "measured_at": measured_at, **row}
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(json.dumps({k: v for k, v in record.items() if k != "blocked_frame_indices"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
