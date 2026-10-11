"""Benchmark `recon_pose` và `metric_scale`: quỹ đạo camera và tỉ lệ mét của job so với ground truth TorWIC.

- **ATE** (sai số vị trí tuyệt đối): khoảng cách giữa tâm camera của job và tâm ground truth sau khi khớp hai quỹ đạo.
  Khớp đồng dạng (cho phép đổi tỉ lệ) đo **hình dạng** quỹ đạo; khớp cứng (giữ nguyên mét của job) đo cả sai số tỉ lệ.
- **RPE** (sai số tương đối giữa hai frame đã đăng ký liên tiếp): lệch của véc-tơ dịch chuyển (mét) và của góc quay
  (độ) sau khi đưa quỹ đạo job về hệ ground truth. Không phụ thuộc trôi tích luỹ.
- **Sai số tỉ lệ mét**: một mét của scene dài bao nhiêu mét thật (`1/scale − 1`, theo %). Chỉ có khi job đã xác nhận
  tỉ lệ; job chưa hoàn tất chỉ có ATE khớp đồng dạng và RPE.

    python -m eval.pose.trajectory_error --job <job-id> --traversal "<dataset>/Aisle_CW" \\
        --calibration "<dataset>/calibrations.txt" --start 100 --label <nhãn> \\
        --out-dir eval/results

Job dựng từ gói LiDAR có quỹ đạo ground truth đã *dùng* chính quỹ đạo này làm điểm xuất phát: với job đó các số ở đây
đo mức bám quỹ đạo, không phải độ chính xác độc lập (bản ghi ghi `job_used_this_trajectory`).
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from eval.reference.torwic import PoseSet, base_record, ground_truth_poses, job_poses, percentiles, write_record
from src.models.contracts.manifests import StageId
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects.registry import ProjectRegistry, get_project_registry
from src.services.reconstruction.alignment.similarity import fit_similarity, rotation_matrix
from src.services.reconstruction.lidar.world_alignment import fit_world_from_lidar_map


def _angle_deg(rotation: np.ndarray) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, (float(np.trace(rotation)) - 1.0) / 2.0))))


def trajectory_errors(estimate: PoseSet, truth: PoseSet) -> dict:
    """ATE khớp đồng dạng + RPE của một bộ pose so với ground truth cùng frame."""
    fit = fit_similarity([tuple(c) for c in estimate.centers], [tuple(c) for c in truth.centers])
    alignment = rotation_matrix(fit.rotation_xyzw)
    aligned = fit.scale * estimate.centers @ alignment.T + np.asarray(fit.translation)
    ate = np.linalg.norm(aligned - truth.centers, axis=1)
    step_error = np.linalg.norm(np.diff(aligned, axis=0) - np.diff(truth.centers, axis=0), axis=1)
    # Quay tương đối viết ở hệ thế giới (R_j·R_iᵀ) không phụ thuộc quy ước trục camera của hai nguồn.
    relative_estimate = [
        alignment @ (b @ a.T) @ alignment.T for a, b in zip(estimate.rotations, estimate.rotations[1:], strict=False)
    ]
    relative_truth = [b @ a.T for a, b in zip(truth.rotations, truth.rotations[1:], strict=False)]
    angle_error = np.array([_angle_deg(e @ t.T) for e, t in zip(relative_estimate, relative_truth, strict=True)])
    path_length = float(np.linalg.norm(np.diff(truth.centers, axis=0), axis=1).sum())
    return {
        "registered_frames": len(estimate.frame_ids),
        "path_length_m": round(path_length, 3),
        "ate_similarity_m": {
            "rmse": round(float(math.sqrt((ate**2).mean())), 4),
            "max": round(float(ate.max()), 4),
            **percentiles(ate),
        },
        "rpe_translation_m": {"rmse": round(float(math.sqrt((step_error**2).mean())), 4), **percentiles(step_error)},
        "rpe_rotation_deg": {"rmse": round(float(math.sqrt((angle_error**2).mean())), 4), **percentiles(angle_error)},
        "similarity_scale": fit.scale,
    }


def metric_errors(metric: PoseSet, truth: PoseSet) -> dict:
    """Sai số tỉ lệ mét và ATE khớp cứng của pose đã ở hệ mét."""
    scale = fit_similarity([tuple(c) for c in metric.centers], [tuple(c) for c in truth.centers]).scale
    rigid = fit_world_from_lidar_map([tuple(c) for c in metric.centers], [tuple(c) for c in truth.centers])
    return {
        # Một mét của scene dài `scale` mét thật.
        "true_m_per_scene_m": round(scale, 6),
        "scale_error_percent": round(100 * (1 / scale - 1), 3),
        "ate_rigid_m": {
            "rmse": round(rigid.rms_residual_m, 4),
            "p50": round(rigid.median_residual_m, 4),
            "max": round(rigid.max_residual_m, 4),
        },
        "rigid_alignment_method": rigid.method,
    }


def _used_this_trajectory(registry: ProjectRegistry, job_id: str) -> bool:
    """Job có nhận gói LiDAR mà quỹ đạo là ground truth của dataset không (đọc từ bản ghi gói của chính job)."""
    job = registry.get_job(job_id)
    stage = next(
        (item for item in job.stage_artifacts if item.stage_id == StageId.LIDAR_INGEST and item.artifact_uri), None
    )
    if stage is None or stage.artifact_checksum is None:
        return False
    path = registry.runtime_resolver.require_uri(stage.artifact_uri, stage.artifact_checksum)
    return json.loads(path.read_text()).get("trajectory_origin") == "ground_truth"


def run(args: argparse.Namespace) -> list[dict]:
    """Bản ghi `recon_pose`, và `metric_scale` nếu job đã có pose hệ mét."""
    registry = get_project_registry()
    sfm, metric = job_poses(registry, args.job)
    estimate = metric or sfm
    truth = ground_truth_poses(args.traversal, args.calibration, estimate.frame_ids, args.start)
    shared = {"job_used_this_trajectory": _used_this_trajectory(registry, args.job)}
    pose = base_record("recon_pose", args.label, args.job, args.traversal, args.start)
    pose |= shared | {"pose_frame": estimate.frame} | trajectory_errors(estimate, truth)
    records = [pose]
    if metric is not None:
        scale = base_record("metric_scale", args.label, args.job, args.traversal, args.start)
        # Nguồn số đo mà job dùng để lấy tỉ lệ: `lidar_demo` và `lidar_trajectory` (quỹ đạo ground truth) suy ra từ
        # chính quỹ đạo này, nên sai số tỉ lệ khi đó không phải số đo độc lập.
        bundle = job_bundle(registry, registry.get_job(args.job))
        source = bundle.provenance.get("distance_source") if bundle is not None else None
        independent = source not in {"lidar_demo", "lidar_trajectory"} or (
            source == "lidar_trajectory" and not shared["job_used_this_trajectory"]
        )
        records.append(
            scale
            | shared
            | {"distance_source": source, "scale_is_independent": independent}
            | metric_errors(metric, truth)
        )
    for record in records:
        out = args.out_dir / record["benchmark"] / f"{args.label}.jsonl" if args.out_dir else None
        write_record(registry, record, out)
    return records


def main(argv: list[str] | None = None) -> int:
    """CLI; in các bản ghi đã ghi."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job", required=True)
    parser.add_argument("--traversal", type=Path, required=True, help="thư mục traversal có traj_gt.txt")
    parser.add_argument("--calibration", type=Path, required=True, help="calibrations.txt của dataset")
    parser.add_argument("--start", type=int, default=0, help="ảnh của traversal ứng với frame 0 của video")
    parser.add_argument("--label", required=True)
    parser.add_argument("--out-dir", type=Path, help="gốc eval/results để thêm dòng JSONL tổng hợp")
    args = parser.parse_args(argv)
    print(json.dumps(run(args), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
