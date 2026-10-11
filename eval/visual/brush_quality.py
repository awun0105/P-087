"""Benchmark `recon_visual_quality`: chất lượng ảnh render của 3DGS Brush trên ảnh giữ lại.

Giao thức theo cách báo cáo của 3DGS/SuGaR/Frosting (chỉ lấy phương pháp, không chép code Inria):
giữ lại mỗi ảnh thứ 8 của chính tập ảnh đã đăng ký (Brush `--eval-split-every 8`), render đúng
camera đó, chấm PSNR/SSIM (Brush tự tính, render nền đen, làm tròn 8-bit) và LPIPS-VGG
(`src/services/reconstruction/adapters/lpips_runner.py`, gói `lpips` BSD-2) ở nhiều mốc bước. Ảnh held-out của benchmark
split dataset không đi vào đây: job nguồn chỉ nhận video train split.

Đầu vào là camera pose REC-03 mà một job sản phẩm đã publish (cùng ảnh, cùng COLMAP), nên cấu
hình lấy mẫu/COLMAP được so qua job, còn cấu hình Brush so bằng tham số ở đây.

    python -m eval.visual.brush_quality --job <job-id> --label <nhãn> --work <thư mục tạm> \\
        [--iters 30000 --max-splats 1500000 --max-resolution 1280] \\
        --out eval/results/recon_visual_quality/<nhãn>.jsonl
"""

import argparse
import json
import re
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageId, StageStatus
from src.services.orchestration.projects.registry import get_project_registry
from src.services.reconstruction.adapters.brush import LPIPS_RUNNER
from src.services.reconstruction.adapters.brush_input import BrushInputAdapter
from src.services.reconstruction.adapters.brush_runtime import (
    BrushRuntimeSettings,
    Invocation,
    VisualProcess,
    brush_command,
)
from src.services.reconstruction.adapters.colmap_runtime import ColmapProcess, ColmapRuntimeSettings
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.splat.visual import BrushConfig

EVAL_LINE = re.compile(r"Eval iter (\d+): PSNR ([0-9.]+), ssim ([0-9.]+)")
LPIPS_SCRIPT = LPIPS_RUNNER


def rerun_flags(args: argparse.Namespace) -> tuple[str, ...]:
    """Cờ Brush để ghi quá trình train ra Rerun (camera COLMAP, ảnh render ↔ ảnh thật ở mỗi mốc eval, số liệu, splat).

    Brush tự kết nối tới viewer Rerun đang nghe ở 127.0.0.1:9876; viewer phải cùng phiên bản SDK mà Brush nhúng
    (Brush 0.3.0 → rerun 0.24.1) và phải chạy trước. Ghi toàn bộ splat rất nặng nên mặc định thưa.
    """
    if not (args.rerun or args.rerun_save):
        return ()
    return (
        "--rerun-enabled",
        "--rerun-log-train-stats-every",
        str(args.rerun_stats_every),
        "--rerun-log-splats-every",
        str(args.rerun_splats_every),
        "--rerun-max-img-size",
        str(args.rerun_max_img_size),
    )


@contextmanager
def rerun_receiver(args: argparse.Namespace, work: Path) -> Iterator[None]:
    """Với `--rerun-save`: chạy viewer Rerun không giao diện để hứng luồng ghi của Brush và lưu thành `.rrd`.

    File chỉ được chuyển tới đích khi train xong, để Studio không mở phải bản ghi dở. Nghe ở 127.0.0.1:9876 (cổng
    Brush tự kết nối) nên mỗi máy chỉ chạy được một lượt ghi tại một thời điểm.
    """
    if args.rerun_save is None:
        yield
        return
    partial = work / "train.rrd"
    receiver = subprocess.Popen(
        [str(args.rerun_bin), "--save", str(partial), "--bind", "127.0.0.1", "--port", "9876"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(3)  # chờ cổng gRPC mở trước khi Brush kết nối
        if receiver.poll() is not None:
            raise SystemExit(f"Không chạy được {args.rerun_bin} (cổng 9876 đang bận hoặc sai phiên bản)")
        yield
    finally:
        receiver.terminate()
        receiver.wait(timeout=60)
    args.rerun_save.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(partial, args.rerun_save)


def pose_reference(job_id: str) -> tuple[ProductArtifactRef, dict]:
    """Camera pose REC-03 đã publish của job, kèm cấu hình xử lý của job (để ghi vào kết quả)."""
    registry = get_project_registry()
    job = registry.get_job(job_id)
    stage = next(
        (
            item
            for item in reversed(job.stage_artifacts)
            if item.stage_id == StageId.CAMERA_POSE and item.status == StageStatus.SUCCEEDED and item.artifact_uri
        ),
        None,
    )
    if stage is None or stage.artifact_checksum is None or stage.data_class is None:
        raise SystemExit(f"{job_id} chưa có camera pose REC-03")
    reference = ProductArtifactRef(
        artifact_type=stage.artifact_type or "CameraPoseArtifact",
        schema_version="1.0",
        artifact_uri=stage.artifact_uri,
        artifact_checksum=stage.artifact_checksum,
        data_class=stage.data_class,
        producer_stage=StageId.CAMERA_POSE,
        job_id=job_id,
    )
    processing = registry.runtime_resolver.resolve(f"artifact://jobs/{job_id}/config/processing.json")
    params = json.loads(processing.read_text()).get("params", {}) if processing.is_file() else {}
    return reference, params


def run(args: argparse.Namespace) -> dict:
    """Dựng thư mục train từ pose của job, train Brush có eval split, chấm LPIPS ở mốc cuối."""
    settings = get_settings()
    registry = get_project_registry()
    resolve = registry.runtime_resolver.require
    reference, params = pose_reference(args.job)
    work = args.work / args.label
    poses = CameraPoseResolver(resolve, FrameSetResolver(resolve, resolve))
    config = BrushConfig(
        total_train_iters=args.iters,
        max_resolution=args.max_resolution,
        sh_degree=args.sh_degree,
        seed=0,
        max_splats=args.max_splats,
        refine_every=args.refine_every,
        sog_iterations=1,
    )
    log_path = work / "brush-eval.log"
    if args.resume and log_path.is_file() and EVAL_LINE.search(log_path.read_text()):
        # Lượt trước đã train xong nhưng dừng trước khi ghi kết quả: dùng lại log + ảnh render.
        log = log_path.read_text()
        finished = [json.loads(line) for line in log.splitlines() if line.startswith('{"returncode"')]
        train_seconds = finished[-1]["elapsed_seconds"] if finished else float("nan")
        version = next(
            (
                line.split()[-1]
                for line in (work / "brush-version.log").read_text().splitlines()
                if line.startswith("brush")
            ),
            "unknown",
        )
    else:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        BrushInputAdapter(poses, ColmapProcess(ColmapRuntimeSettings())).prepare(reference, work)
        runtime = BrushRuntimeSettings()
        process = VisualProcess(runtime.model_copy(update={"timeout_seconds": args.timeout}))
        version = process.qualify(work)
        command = (
            *brush_command(config, work, process.iteration_flag),
            "--eval-split-every",
            str(args.eval_split_every),
            "--eval-every",
            str(args.eval_every),
            "--eval-save-to-disk",
            *rerun_flags(args),
        )
        started = time.monotonic()
        with rerun_receiver(args, work):
            log = process.run(Invocation("brush-eval", runtime.command, command), work)
        train_seconds = time.monotonic() - started
    evals = [
        {"iter": int(match[1]), "psnr": float(match[2]), "ssim": float(match[3])} for match in EVAL_LINE.finditer(log)
    ]
    if not evals:
        raise SystemExit("Brush không in kết quả eval; xem brush-eval.log")
    final_iter = max(item["iter"] for item in evals)
    renders = work / "output" / f"eval_{final_iter}"
    lpips = None
    if settings.product_scene_runtime_python and renders.is_dir():
        completed = subprocess.run(
            [
                str(settings.product_scene_runtime_python),
                str(LPIPS_SCRIPT),
                "--renders",
                str(renders),
                "--gt",
                str(work / "training" / "images"),
                "--net",
                args.lpips_net,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            lpips = json.loads(completed.stdout.strip().splitlines()[-1])
        else:
            print("LPIPS lỗi:", completed.stderr[-2000:])
    ply = work / "output" / "visual.ply"
    record = {
        "benchmark": "recon_visual_quality",
        "label": args.label,
        "recorded_at": datetime.now(UTC).isoformat(),
        "job_id": args.job,
        "camera_pose_ref": reference.artifact_uri,
        "registered_images": len(poses.load(reference).poses),
        "eval_split_every": args.eval_split_every,
        "processing_params": params,
        "brush_config": config.model_dump(exclude={"schema_version", "sog_iterations"}),
        "brush_version": version,
        "train_seconds": round(train_seconds, 1),
        "evals": evals,
        "final": {
            **next(item for item in evals if item["iter"] == final_iter),
            "lpips": None if lpips is None else lpips["lpips"],
            "lpips_net": None if lpips is None else lpips["net"],
            "lpips_views": None if lpips is None else lpips["count"],
        },
        "ply_bytes": ply.stat().st_size if ply.is_file() else None,
        "machine": args.machine,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    # Giữ PLY cuối (để import xem) và ảnh render mốc cuối; bỏ ảnh train/undistort nặng.
    for heavy in ("source", "target", "training", "undistorted"):
        shutil.rmtree(work / heavy, ignore_errors=True)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="recon_visual_quality: Brush eval split trên pose của một job")
    parser.add_argument("--job", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iters", type=int, default=30000)
    parser.add_argument("--max-splats", type=int, default=1_500_000)
    parser.add_argument("--max-resolution", type=int, default=1280)
    parser.add_argument("--sh-degree", type=int, default=3)
    parser.add_argument("--refine-every", type=int, default=200)
    parser.add_argument("--eval-split-every", type=int, default=8)
    parser.add_argument("--eval-every", type=int, default=7000)
    parser.add_argument("--rerun", action="store_true", help="ghi quá trình train ra viewer Rerun 0.24.1 đang chạy sẵn")
    parser.add_argument(
        "--rerun-save",
        type=Path,
        help="tự hứng và lưu bản ghi thành file .rrd (vd data/rerun_recordings/<job>.rrd để Studio hiển thị)",
    )
    parser.add_argument("--rerun-bin", type=Path, default=Path("data/tools/rerun-0.24.1/bin/rerun"))
    parser.add_argument("--rerun-stats-every", type=int, default=50)
    parser.add_argument("--rerun-splats-every", type=int, default=2000)
    parser.add_argument("--rerun-max-img-size", type=int, default=512)
    parser.add_argument("--lpips-net", default="vgg", choices=("vgg", "alex"))
    parser.add_argument("--timeout", type=float, default=4 * 3600)
    parser.add_argument("--machine", default="local-t2000")
    parser.add_argument("--resume", action="store_true", help="dùng lại log/ảnh render nếu lượt trước đã train xong")
    args = parser.parse_args()
    record = run(args)
    print(json.dumps(record["final"], ensure_ascii=False), record["train_seconds"], "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
