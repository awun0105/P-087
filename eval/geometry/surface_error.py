"""Benchmark `recon_geometry`: bề mặt 3DGS của job so với bản đồ điểm ground truth của TorWIC.

Tâm các Gaussian đủ đục của bản 3DGS gốc (hệ SfM) được đưa sang hệ bản đồ bằng phép đồng dạng khớp tâm camera của job
với quỹ đạo ground truth, rồi so với `groundtruth_map.ply`:

- **Độ chính xác** (accuracy): khoảng cách từ điểm của job tới điểm ground truth gần nhất — job có dựng sai chỗ không.
- **Độ đầy đủ** (completeness): khoảng cách từ điểm ground truth tới điểm của job gần nhất — job có bỏ sót không.
- **Chamfer** = trung bình accuracy + trung bình completeness. **Precision / Recall / F-score** ở 5 cm và 10 cm.

Chỉ xét vùng trong `--window` mét quanh đường camera (mặc định 8 m), ở cả hai phía. Bản đồ ground truth phủ cả những
chỗ camera không nhìn thấy (sau kệ, trên cao), nên completeness và recall là **cận dưới bi quan**; số đã gồm sai số
của phép khớp (ghi kèm RMS) và mật độ điểm của bản đồ (ghi kèm khoảng cách lấy mẫu).

    python -m eval.geometry.surface_error --job <job-id> --traversal "<dataset>/Aisle_CW" \\
        --calibration "<dataset>/calibrations.txt" --map "<dataset>/groundtruth_map.ply" --start 100 \\
        --label <nhãn> --out-dir eval/results
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from eval.geometry.click_error import _gaussians
from eval.reference.torwic import base_record, ground_truth_poses, job_poses, write_record
from src.services.orchestration.projects.registry import get_project_registry
from src.services.reconstruction.alignment.similarity import fit_similarity, rotation_matrix
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver

THRESHOLDS_M = (0.05, 0.10)


def surface_scores(estimate: np.ndarray, truth: np.ndarray) -> dict:
    """Accuracy, completeness, Chamfer và precision/recall/F-score giữa hai tập điểm cùng hệ mét."""
    if not len(estimate) or not len(truth):
        raise ValueError("không còn điểm nào trong vùng so sánh")
    accuracy, _ = cKDTree(truth).query(estimate)
    completeness, _ = cKDTree(estimate).query(truth)
    scores: dict = {
        "accuracy_m": {"mean": round(float(accuracy.mean()), 4), "p50": round(float(np.median(accuracy)), 4)},
        "completeness_m": {
            "mean": round(float(completeness.mean()), 4),
            "p50": round(float(np.median(completeness)), 4),
        },
        "chamfer_m": round(float(accuracy.mean() + completeness.mean()), 4),
    }
    for threshold in THRESHOLDS_M:
        precision = float((accuracy < threshold).mean())
        recall = float((completeness < threshold).mean())
        f_score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores[f"at_{round(threshold * 100)}cm"] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f_score": round(f_score, 4),
        }
    return scores


_PLY_TYPES = {"float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8", "uchar": "u1", "uint8": "u1"}


def map_points(path: Path) -> np.ndarray:
    """Toạ độ đỉnh của bản đồ ground truth (PLY binary little-endian; phần `face` rỗng của file gốc được bỏ qua)."""
    with path.open("rb") as stream:
        fields: list[tuple[str, str]] = []
        count, in_vertex = 0, False
        for raw in iter(stream.readline, b""):
            words = raw.decode("ascii", "replace").split()
            if words[:1] == ["end_header"]:
                break
            if words[:2] == ["format", "binary_little_endian"] or words[:1] in (["ply"], ["comment"]):
                continue
            if words[:1] == ["format"]:
                raise ValueError("bản đồ ground truth phải là PLY binary little-endian")
            if words[:1] == ["element"]:
                in_vertex = words[1] == "vertex"
                count = int(words[2]) if in_vertex else count
            elif words[:1] == ["property"] and in_vertex:
                if words[1] not in _PLY_TYPES:
                    raise ValueError(f"kiểu thuộc tính đỉnh không hỗ trợ: {words[1]}")
                fields.append((words[2], _PLY_TYPES[words[1]]))
        rows = np.fromfile(stream, dtype=np.dtype(fields), count=count)
    if len(rows) != count or count == 0:
        raise ValueError("bản đồ ground truth thiếu dữ liệu đỉnh")
    return np.stack([rows["x"], rows["y"], rows["z"]], axis=1).astype(float)


def near_path(points: np.ndarray, path: np.ndarray, window: float) -> np.ndarray:
    """Các điểm cách đường camera không quá `window` mét."""
    distance, _ = cKDTree(path).query(points)
    return points[distance <= window]


def run(args: argparse.Namespace) -> dict:
    """Một bản ghi `recon_geometry` cho job."""
    registry = get_project_registry()
    resolve = registry.runtime_resolver.require
    sfm, _ = job_poses(registry, args.job)
    truth = ground_truth_poses(args.traversal, args.calibration, sfm.frame_ids, args.start)
    fit = fit_similarity([tuple(c) for c in sfm.centers], [tuple(c) for c in truth.centers])
    preview = registry.get_preview(args.job)
    visual = VisualResolver(resolve, CameraPoseResolver(resolve, FrameSetResolver(resolve, resolve))).load(
        preview.source_visual_ref
    )
    xyz, opacity = _gaussians(resolve(visual.master))
    surface = fit.scale * xyz[opacity >= args.min_opacity] @ rotation_matrix(fit.rotation_xyzw).T
    surface = near_path(surface + np.asarray(fit.translation), truth.centers, args.window)
    reference = near_path(map_points(args.map), truth.centers, args.window)
    spacing, _ = cKDTree(reference).query(reference[:: max(1, len(reference) // 50000)], k=2)
    record = base_record("recon_geometry", args.label, args.job, args.traversal, args.start)
    record |= {
        "surface": "gaussian_centers",
        "min_opacity": args.min_opacity,
        "window_m": args.window,
        "job_points": len(surface),
        "reference_points": len(reference),
        "alignment_rms_m": round(float(fit.rms_residual), 4),
        "reference_spacing_p50_m": round(float(np.median(spacing[:, 1])), 4),
        **surface_scores(surface, reference),
    }
    write_record(registry, record, args.out_dir / "recon_geometry" / f"{args.label}.jsonl" if args.out_dir else None)
    return record


def main(argv: list[str] | None = None) -> int:
    """CLI; in bản ghi đã ghi."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job", required=True)
    parser.add_argument("--traversal", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True, help="groundtruth_map.ply của dataset")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--window", type=float, default=8.0)
    parser.add_argument("--min-opacity", type=float, default=0.5)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(run(args), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
