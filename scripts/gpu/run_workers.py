"""Khởi động các worker theo kế hoạch chia GPU (`gpu_plan`) và giữ chúng chạy.

    set -a; source <file env>; set +a
    python -m scripts.gpu.run_workers                 # số worker tự chọn theo VRAM từng GPU
    python -m scripts.gpu.run_workers --workers 2     # đặt tay tổng số worker

Mỗi worker là một tiến trình `worker_cli` được ghim vào một GPU qua biến môi trường. Nhiều worker cùng đọc
một hàng đợi: mỗi job chỉ một worker nhận được (claim bằng CAS trong DB). SIGTERM/Ctrl+C dừng mọi worker;
một worker chết thì dừng cả nhóm để người vận hành thấy lỗi thay vì chạy thiếu âm thầm.
"""

import argparse
import os
import signal
import subprocess
import sys
import time

from scripts.gpu.gpu_plan import Plan, plan_for_machine

WORKER_COMMAND = [sys.executable, "-m", "src.services.orchestration.jobs.worker_cli"]


def spawn(plan: Plan) -> list[subprocess.Popen[bytes]]:
    """Một tiến trình worker cho mỗi slot, với môi trường ghim GPU của slot đó."""
    return [subprocess.Popen(WORKER_COMMAND, env={**os.environ, **slot.environment}) for slot in plan.slots]


def main(argv: list[str] | None = None) -> int:
    """CLI; trả exit code của worker đầu tiên thoát (0 khi dừng bằng tín hiệu)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", default="auto", help="tổng số worker, hoặc `auto` theo VRAM trống từng GPU")
    args = parser.parse_args(argv)
    jobs = 64 if args.workers == "auto" else max(1, int(args.workers))
    gpus, plan = plan_for_machine(jobs)
    print(f"[workers] {len(gpus)} GPU, {len(plan.slots)} worker — {plan.reason}", flush=True)
    for slot in plan.slots:
        print(f"[workers]   worker {slot.worker} → GPU {slot.gpu_index}", flush=True)
    processes = spawn(plan)

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
