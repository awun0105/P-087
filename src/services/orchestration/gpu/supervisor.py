"""Supervise API and CPU control processes in one Railway service."""

import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from threading import Event


def supervise(command: Sequence[str]) -> int:
    commands = [list(command)]
    if os.environ.get("GPU_CONTROLLER_RUN", "false").lower() == "true":
        commands.append([sys.executable, "-m", "scripts.cloud.runpod_controller", "run"])
    if os.environ.get("GPU_CPU_LANE_ENABLED", "false").lower() == "true":
        commands.append([sys.executable, "-m", "src.services.orchestration.gpu.cpu_worker"])
    processes: list[subprocess.Popen] = []
    stop = Event()
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, lambda *_: stop.set())
    try:
        for cmd in commands:
            processes.append(subprocess.Popen(cmd, start_new_session=True))
        while not stop.wait(1):
            for process in processes:
                if process.poll() is not None:
                    return process.returncode or 1  # Fail service so Railway restarts the full supervised group.
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
