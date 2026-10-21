"""Khởi động các worker theo kế hoạch chia GPU (`gpu_plan`) và giữ chúng chạy.

    set -a; source <file env>; set +a
    python -m scripts.gpu.run_workers                 # số worker tự chọn theo VRAM từng GPU
    python -m scripts.gpu.run_workers --workers 2     # đặt tay tổng số worker
    python -m scripts.gpu.run_workers --cpu-workers 0 # không chạy worker làn CPU

Mỗi worker là một tiến trình `worker_cli` được ghim vào một GPU qua biến môi trường. Nhiều worker cùng đọc
một hàng đợi: mỗi bước chỉ một worker nhận được (claim bằng CAS trong DB). SIGTERM/Ctrl+C dừng mọi worker;
một worker chết thì dừng cả nhóm để người vận hành thấy lỗi thay vì chạy thiếu âm thầm.

T-073: thêm `STUDIO_CPU_WORKERS` (mặc định 1) worker chỉ nhận bước CPU của pipeline (chuẩn bị video, hình học), để
bước CPU của job này chạy song song với bước GPU của job khác. Mỗi worker GPU biết tổng số worker GPU qua
`R2S_GPU_WORKERS` để khai số luồng CPU của bước GPU.
"""

import argparse
import os
import signal
import subprocess
import sys
import time

from scripts.gpu.gpu_plan import Plan, plan_for_machine

WORKER_COMMAND = [sys.executable, "-m", "src.services.orchestration.jobs.worker_cli"]
CPU_WORKER_COMMAND = [*WORKER_COMMAND, "--lanes", "cpu"]
#: Mặc định một worker làn CPU: đủ để bước CPU không phải chờ worker GPU rảnh, mà không thêm nhiều tiến trình cùng
#: hỏi DB. Tăng khi số đo cho thấy bước CPU xếp hàng.
DEFAULT_CPU_WORKERS = 1


def cpu_worker_count(value: str | None) -> int:
    """`STUDIO_CPU_WORKERS`: số nguyên ≥ 0; trống hoặc sai thì dùng mặc định."""
    try:
        return max(0, int(value)) if value not in (None, "") else DEFAULT_CPU_WORKERS
    except ValueError:
        return DEFAULT_CPU_WORKERS


def commands(plan: Plan, cpu_workers: int) -> list[tuple[list[str], dict[str, str]]]:
    """(lệnh, môi trường) của từng tiến trình: một worker GPU mỗi slot, rồi các worker làn CPU.

    Worker làn CPU dùng môi trường của slot đầu (cùng máy, cùng runtime) nhưng chỉ nhận bước CPU.
    """
    shared = {"R2S_GPU_WORKERS": str(len(plan.slots))}
    result = [(WORKER_COMMAND, {**shared, **slot.environment}) for slot in plan.slots]
    first = plan.slots[0].environment if plan.slots else {}
    result += [(CPU_WORKER_COMMAND, {**shared, **first, "R2S_WORKER_LANES": "cpu"}) for _ in range(cpu_workers)]
    return result


def spawn(plan: Plan, cpu_workers: int = 0) -> list[subprocess.Popen[bytes]]:
    """Một tiến trình worker cho mỗi slot (môi trường ghim GPU của slot đó), cộng các worker làn CPU."""
    return [
        subprocess.Popen(command, env={**os.environ, **environment})
        for command, environment in commands(plan, cpu_workers)
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI; trả exit code của worker đầu tiên thoát (0 khi dừng bằng tín hiệu)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", default="auto", help="tổng số worker, hoặc `auto` theo VRAM trống từng GPU")
    parser.add_argument(
        "--cpu-workers",
        default=os.environ.get("STUDIO_CPU_WORKERS"),
        help=f"số worker chỉ nhận bước CPU của pipeline (mặc định {DEFAULT_CPU_WORKERS})",
    )
    args = parser.parse_args(argv)
    cpu_workers = cpu_worker_count(args.cpu_workers)
    jobs = 64 if args.workers == "auto" else max(1, int(args.workers))
    gpus, plan = plan_for_machine(jobs)
    print(f"[workers] {len(gpus)} GPU, {len(plan.slots)} worker — {plan.reason}", flush=True)
    for slot in plan.slots:
        print(f"[workers]   worker {slot.worker} → GPU {slot.gpu_index}", flush=True)
    if cpu_workers:
        print(f"[workers]   {cpu_workers} worker làn CPU (bước chuẩn bị video, hình học)", flush=True)
    processes = spawn(plan, cpu_workers)

    def stop(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    code = 0
    try:
        while True:
            for process in processes:
                if process.poll() is not None:
                    code = process.returncode
                    raise KeyboardInterrupt
            time.sleep(2.0)
    except KeyboardInterrupt:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                process.kill()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
