"""Process-group execution shared by long-running product operations."""

import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from math import isfinite
from pathlib import Path
from threading import Event
from typing import TextIO


class ProcessCancelledError(RuntimeError):
    """Raised after cancellation kills and reaps a child process group."""


class ProcessTimeoutError(TimeoutError):
    """Raised after timeout kills and reaps a child process group."""


def run_cancellable_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    output: TextIO,
    cancel_event: Event | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run argv in its own process group; cancel/timeout always kill the group and reap its leader."""
    if not command or any(not argument for argument in command):
        raise ValueError("process command must contain non-empty arguments")
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("process timeout must be positive")
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCancelledError("Process was cancelled before start")

    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=os.environ | dict(environment) if environment is not None else None,
    )
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _kill_and_reap(process)
                raise ProcessCancelledError("Process was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_and_reap(process)
                raise ProcessTimeoutError("Process exceeded its configured timeout")
            try:
                return process.wait(timeout=min(0.1, remaining) if cancel_event is not None else remaining)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            _kill_and_reap(process)


def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
    """Stop owned session groups, including Ninja compiler groups, then reap the leader."""
    if hasattr(os, "killpg"):
        # Ninja starts each compiler command in a new group within our private
        # session. Killing only the leader's group leaves those commands alive.
        for _ in range(2):
            groups = {process.pid}
            proc = Path("/proc")
            if proc.is_dir():
                for entry in proc.iterdir():
                    if not entry.name.isdecimal():
                        continue
                    try:
                        pid = int(entry.name)
                        if os.getsid(pid) == process.pid:
                            groups.add(os.getpgid(pid))
                    except (ProcessLookupError, PermissionError):
                        continue
            for group in groups:
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    else:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()
