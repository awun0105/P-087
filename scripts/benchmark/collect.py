"""Tổng hợp benchmark `pipeline_runtime` vào `eval/results/pipeline_runtime/<nhãn>.jsonl`.

    python -m scripts.benchmark.collect --all --label aisle-cw-demo --gpu-hourly-usd 0.34
    python -m scripts.benchmark.collect --job job-abc123 --label local-t2000

Nhãn gom các lần chạy cùng mục đích (dataset + cấu hình + máy); thiếu nhãn → `unlabeled`.
Giao thức và ý nghĩa từng field: `eval/protocols/pipeline_runtime.md`.

Đọc cùng DATABASE_URL/ARTIFACT_ROOT (và kho file nếu có) như API. Bản ghi đã có
(job + attempt + phase) không ghi lại, nên chạy nhiều lần an toàn. Số liệu chỉ là những gì
đo được; ô không đo được để trống, không ước đoán.
"""

import argparse
import json
import re
from pathlib import Path

from src.config import get_settings
from src.services.orchestration.benchmark import BENCHMARK_KIND, PipelineRuntimeBenchmark, build_benchmark
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing.capability import latest as latest_capability
from src.services.orchestration.projects.registry import get_project_registry

RESULTS_ROOT = Path("eval/results")


def _existing(path: Path) -> set[tuple[str, int, str]]:
    if not path.is_file():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            phase = record.get("snapshot_phase")
            if phase not in {"partial", "terminal"}:
                phase = "terminal" if record.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"} else "partial"
            keys.add((record["job_id"], record["attempt"], phase))
    return keys


def _row(benchmark: PipelineRuntimeBenchmark) -> str:
    phase = benchmark.snapshot_phase or (
        "terminal" if benchmark.status in {"SUCCEEDED", "FAILED", "CANCELLED"} else "partial"
    )
    total = (
        f"{benchmark.total_seconds:.0f}s"
        if benchmark.total_seconds is not None
        else "partial"
        if phase == "partial"
        else "—"
    )
    worker = f"{benchmark.worker_process_seconds:.0f}s" if benchmark.worker_process_seconds is not None else "—"
    queue = f"{benchmark.queue_seconds:.0f}s" if benchmark.queue_seconds is not None else "—"
    waiting = f"{benchmark.user_wait_seconds:.0f}s" if benchmark.user_wait_seconds is not None else "—"
    sog = f"{benchmark.sog_size_bytes / 1e6:.2f}MB" if benchmark.sog_size_bytes else "—"
    cost = f"${benchmark.estimated_gpu_cost_usd:.3f}" if benchmark.estimated_gpu_cost_usd is not None else "—"
    gpu = benchmark.machine.gpu_name if benchmark.machine and benchmark.machine.gpu_name else "—"
    frames = str(benchmark.actual_frame_count) if benchmark.actual_frame_count is not None else "—"
    stages = " ".join(
        f"{stage.stage_id.removeprefix('ST-')}={stage.seconds:.0f}s"
        for stage in benchmark.stages
        if stage.seconds is not None
    )
    return (
        f"{benchmark.job_id:18} {benchmark.status:10} {phase:8} {frames:>6} "
        f"{total:>8} {worker:>8} {queue:>7} {waiting:>8} "
        f"{sog:>9} {cost:>8}  {gpu:14} {stages}"
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="Mọi job của mọi project")
    target.add_argument("--job", action="append", help="Job cụ thể (lặp lại được)")
    parser.add_argument("--label", default="unlabeled", help="Nhãn nhóm lần chạy, vd aisle-cw-demo")
    parser.add_argument("--gpu-hourly-usd", type=float, help="Đơn giá GPU/giờ để ước tính chi phí")
    parser.add_argument("--out", type=Path, help="Mặc định eval/results/pipeline_runtime/<nhãn>.jsonl")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", args.label):
        parser.error("Nhãn chỉ gồm chữ thường, số, '.', '_' hoặc '-'")
    args.out = args.out or RESULTS_ROOT / BENCHMARK_KIND / f"{args.label}.jsonl"

    settings = get_settings()
    registry = get_project_registry()
    machine = latest_capability(RuntimeDatabase(settings.database_url))
    job_ids = args.job or [
        job.job_id for project in registry.list_projects() for job in registry.list_jobs(project.project_id)
    ]
    seen = _existing(args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    print(
        f"{'job':18} {'status':10} {'phase':8} {'frames':>6} {'job wall':>8} {'worker':>8} "
        f"{'queue':>7} {'user wait':>8} "
        f"{'SOG':>9} {'chi phí':>8}  {'GPU':14} stage"
    )
    with args.out.open("a", encoding="utf-8") as stream:
        for job_id in job_ids:
            benchmark = build_benchmark(
                registry,
                job_id,
                machine=machine,
                gpu_hourly_usd=args.gpu_hourly_usd
                if args.gpu_hourly_usd is not None
                else settings.benchmark_gpu_hourly_usd,
                label=args.label,
            )
            print(_row(benchmark))
            phase = benchmark.snapshot_phase or "partial"
            if (benchmark.job_id, benchmark.attempt, phase) in seen:
                continue
            stream.write(benchmark.model_dump_json() + "\n")
            seen.add((benchmark.job_id, benchmark.attempt, phase))
            written += 1
    print(f"Đã ghi {written} bản ghi mới vào {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
