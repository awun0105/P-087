"""Benchmark `metric_click_error`: ước lượng `e` — sai số vị trí một lần click trên 3DGS (mét).

`e` đi vào ngưỡng kiểm C–D của REC-06 (`2√2·e·(1 + L_CD/L_AB)`). Một điểm click là điểm trên bề
mặt 3DGS dưới con trỏ, nên sai số gồm hai phần độc lập:

1. **Bề mặt 3DGS lệch bề mặt thật:** tâm Gaussian đủ đục của master Brush (hệ SfM), đưa sang
   hệ LiDAR bằng căn chỉnh quỹ đạo (GT-assisted, chỉ dataset demo), đo tới điểm LiDAR gần nhất.
   Chỉ lấy vùng 1–8 m quanh đường camera — nơi người dùng thật sự chọn điểm. Số này đã gồm sai
   số căn chỉnh (RMS của fit) và khoảng cách lấy mẫu của LiDAR (báo kèm để đọc đúng).
2. **Lệch pixel khi click:** `k px × độ sâu / tiêu cự` với tiêu cự COLMAP của chính job.

Chỉ đo, không đổi `e`: owner chốt giá trị (REC-06). Dữ liệu GT-assisted chỉ dùng ở evaluator.

    python -m eval.geometry.click_error --job <job-id> --label <nhãn> \\
        --out eval/results/metric_click_error/<nhãn>.jsonl
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from src.services.orchestration.metric import MetricConfirmationService
from src.services.orchestration.projects.registry import get_project_registry
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.reconstruction.lidar.cloud_header import read_header
from src.services.reconstruction.rgb.canonical.lidar_assist import LidarAssist
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver
from src.services.reconstruction.views import camera_markers

PIXEL_ERRORS = (2, 5)


def _gaussians(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Tâm và độ đục (sau sigmoid) của Gaussian trong master PLY."""
    with path.open("rb") as stream:
        header = read_header(stream)
        offset = stream.tell()
    dtype = np.dtype([(name, "<" + code) for name, code in zip(header.fields, header.codes, strict=True)])
    rows = np.frombuffer(path.read_bytes()[offset:], dtype=dtype, count=header.point_count)
    xyz = np.stack([rows["x"], rows["y"], rows["z"]], axis=1).astype(float)
    opacity = 1 / (1 + np.exp(-rows["opacity"].astype(float)))
    return xyz, opacity


def _percentiles(values: np.ndarray) -> dict[str, float]:
    return {f"p{q}": round(float(np.percentile(values, q)), 4) for q in (25, 50, 75, 90)}


def run(args: argparse.Namespace) -> dict:
    registry = get_project_registry()
    resolve = registry.runtime_resolver.require
    support = MetricConfirmationService(registry).lidar_support(args.job)
    context = LidarAssist(resolve, lambda uri: registry.runtime_resolver.resolve(uri).is_file()).load(args.job, support)
    if context is None:
        raise SystemExit(f"{args.job} không có bản ghi LiDAR demo")
    preview = registry.get_preview(args.job)
    poses = CameraPoseResolver(resolve, FrameSetResolver(resolve, resolve))
    visual = VisualResolver(resolve, poses).load(preview.source_visual_ref)
    xyz, opacity = _gaussians(resolve(visual.master))
    fit = context.fit

    def to_world(points: np.ndarray) -> np.ndarray:
        return fit.scale * points @ rotation_matrix(fit.rotation_xyzw).T + np.asarray(fit.translation)

    cameras = to_world(np.array([marker.center for marker in camera_markers(preview.camera_pose_ref, resolve)]))
    world = to_world(xyz[opacity >= args.min_opacity])
    depth, _ = cKDTree(cameras).query(world)
    near = world[(depth >= 1.0) & (depth <= 8.0)]
    near_depth = depth[(depth >= 1.0) & (depth <= 8.0)]
    lidar = cKDTree(context.points_world)
    surface, _ = lidar.query(near)
    # Chỉ so ở nơi LiDAR thật sự phủ (≥ 5 điểm LiDAR trong 1 m): ngoài vùng đó khoảng cách lớn là
    # do thiếu dữ liệu đối chiếu, không phải do 3DGS sai.
    covered = np.array([len(hits) >= 5 for hits in lidar.query_ball_point(near, r=1.0)], dtype=bool)
    spacing, _ = cKDTree(context.points_world).query(
        context.points_world[:: max(1, len(context.points_world) // 50000)], k=2
    )
    pose_artifact = poses.load(preview.camera_pose_ref)
    focal = float(pose_artifact.cameras[0].parameters[0])
    # Tiêu cự của COLMAP theo pixel ảnh gốc; độ sâu quy đổi mét qua scale của căn chỉnh.
    pixel = {f"{k}px": _percentiles(k * near_depth / focal) for k in PIXEL_ERRORS}
    record = {
        "benchmark": "metric_click_error",
        "label": args.label,
        "recorded_at": datetime.now(UTC).isoformat(),
        "job_id": args.job,
        "assistance": "ground_truth_assisted_dataset_demo",
        "gaussians_used": int(len(near)),
        "min_opacity": args.min_opacity,
        "window_m": [1.0, 8.0],
        "surface_to_lidar_m": _percentiles(surface),
        "covered_fraction": round(float(covered.mean()), 3),
        "surface_to_lidar_covered_m": _percentiles(surface[covered]),
        "within_m_covered": {f"{t}": round(float((surface[covered] < t).mean()), 3) for t in (0.05, 0.1, 0.2, 0.5)},
        "alignment_rms_m": round(float(fit.rms_residual), 4),
        "lidar_spacing_m": _percentiles(spacing[:, 1]),
        "focal_px": round(focal, 2),
        "click_depth_m": _percentiles(near_depth),
        "pixel_error_m": pixel,
        "e_estimate_m": {
            # Hai nguồn độc lập cộng theo bình phương, ở trung vị, trong vùng LiDAR phủ.
            f"{k}px": round(
                float(np.hypot(np.percentile(surface[covered], 50), np.percentile(k * near_depth / focal, 50))), 4
            )
            for k in PIXEL_ERRORS
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="metric_click_error: ước lượng e từ 3DGS và LiDAR")
    parser.add_argument("--job", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-opacity", type=float, default=0.5)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
