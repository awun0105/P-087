"""Benchmark `metric_scale` — sai số của **đề xuất tỉ lệ tự động** (MoGe-2 hoặc căn chỉnh LiDAR) so với tỉ lệ thật.

Tỉ lệ thật của một job TorWIC = hệ số của phép đồng dạng khớp tâm camera hệ SfM của job vào quỹ đạo ground truth
(mét trên một đơn vị SfM). Đề xuất của hệ thống là `MetricProposal` mà worker ghi sau bước dựng 3DGS; người dùng xem
và xác nhận hoặc sửa. Sai số ở đây là của **đề xuất**, trước khi con người can thiệp.

    python -m eval.pose.scale_proposal_error --job <job-id> --traversal "<dataset>/Aisle_CW" \\
        --calibration "<dataset>/calibrations.txt" --start 100 --label <nhãn> --out-dir eval/results [--create]

`--create`: job cũ chưa có đề xuất thì chạy đúng bước đề xuất của sản phẩm (cần runtime MoGe đã cấu hình qua
`REC06_MOGE_PYTHON` / `REC06_MOGE_MODEL`) rồi mới chấm. Không có đề xuất và không `--create` → dừng, không bịa số.
"""

import argparse
import json
import tempfile
from pathlib import Path

from eval.reference.torwic import base_record, ground_truth_poses, job_poses, write_record
from src.services.orchestration.artifacts import FilesystemArtifactStore
from src.services.orchestration.projects.registry import get_project_registry
from src.services.reconstruction import MogeSettings, load_proposal, propose_metric
from src.services.reconstruction.alignment.similarity import fit_similarity


def proposal_error(proposed_scale: float, true_scale: float) -> float:
    """Sai số tương đối của tỉ lệ đề xuất (%): dương = scene bị phóng to hơn thật."""
    if true_scale <= 0:
        raise ValueError("tỉ lệ thật phải dương")
    return round(100 * (proposed_scale / true_scale - 1), 3)


def run(args: argparse.Namespace) -> dict:
    """Một bản ghi `metric_scale` cho đề xuất tỉ lệ của job."""
    registry = get_project_registry()
    resolver = registry.runtime_resolver
    preview = registry.get_preview(args.job)
    proposal = load_proposal(args.job, preview.source_visual_ref, resolver.locate)
    if proposal is None and args.create:
        settings = MogeSettings()
        if settings.python is None or settings.model is None:
            raise SystemExit("Chưa cấu hình runtime MoGe (REC06_MOGE_PYTHON, REC06_MOGE_MODEL)")
        with tempfile.TemporaryDirectory(dir=args.scratch) as scratch:
            propose_metric(
                args.job,
                preview.source_visual_ref,
                resolver.require,
                FilesystemArtifactStore(resolver),
                resolver.locate,
                Path(scratch) / "metric_proposal",
                settings,
            )
        proposal = load_proposal(args.job, preview.source_visual_ref, resolver.locate)
    if proposal is None:
        raise SystemExit(f"{args.job} chưa có đề xuất tỉ lệ (thêm --create để chạy bước đề xuất)")
    sfm, _ = job_poses(registry, args.job)
    truth = ground_truth_poses(args.traversal, args.calibration, sfm.frame_ids, args.start)
    fit = fit_similarity([tuple(c) for c in sfm.centers], [tuple(c) for c in truth.centers])
    record = base_record("metric_scale", args.label, args.job, args.traversal, args.start)
    record |= {
        "subject": "automatic_proposal",
        "proposal_method": proposal.method,
        "proposed_m_per_sfm_unit": round(proposal.scale_m_per_sfm_unit, 6),
        "true_m_per_sfm_unit": round(fit.scale, 6),
        "proposal_error_percent": proposal_error(proposal.scale_m_per_sfm_unit, fit.scale),
        "proposal_relative_uncertainty": round(proposal.relative_uncertainty, 4),
        "proposal_frames_used": proposal.frames_used,
        "registered_frames": len(sfm.frame_ids),
        "alignment_rms_m": round(float(fit.rms_residual), 4),
        # Đề xuất từ gói LiDAR có quỹ đạo ground truth dùng chính quỹ đạo này: không phải số đo độc lập.
        "scale_is_independent": proposal.method != "lidar_trajectory_alignment"
        or (proposal.alignment is not None and proposal.alignment.trajectory_origin != "ground_truth"),
    }
    out = args.out_dir / "metric_scale" / f"{args.label}.jsonl" if args.out_dir else None
    # Bản ghi theo job dùng mã riêng để không đè lên bản ghi `metric_scale` của scene đã xác nhận.
    write_record(registry, record | {"benchmark": "metric_scale_proposal"}, None)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main(argv: list[str] | None = None) -> int:
    """CLI; in bản ghi đã ghi."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job", required=True)
    parser.add_argument("--traversal", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--create", action="store_true", help="chạy bước đề xuất nếu job chưa có")
    parser.add_argument("--scratch", type=Path, default=None, help="thư mục tạm cho bước đề xuất")
    args = parser.parse_args(argv)
    print(json.dumps(run(args), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
