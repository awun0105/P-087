"""Cancellation/timeout must stop compiler children which create separate process groups."""

import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from src.services.process_control import ProcessCancelledError, ProcessTimeoutError, run_cancellable_process


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="Linux session ownership regression")
@pytest.mark.parametrize("interrupt", ["cancel", "timeout"])
def test_interrupt_kills_child_in_separate_group_of_owned_session(tmp_path, interrupt):
    pid_file = tmp_path / "compiler.pid"
    child = (
        "import os,time,pathlib; os.setpgrp(); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    leader = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
    cancel = Event()
    pid = None
    try:
        with (tmp_path / "process.log").open("w") as log, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                run_cancellable_process,
                [sys.executable, "-c", leader],
                cwd=tmp_path,
                timeout_seconds=1 if interrupt == "timeout" else 5,
                output=log,
                cancel_event=cancel,
            )
            deadline = time.monotonic() + 3
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert pid_file.exists()
            pid = int(pid_file.read_text())
            if interrupt == "cancel":
                cancel.set()
            expected = ProcessCancelledError if interrupt == "cancel" else ProcessTimeoutError
            with pytest.raises(expected):
                future.result(timeout=6)
        stat = Path(f"/proc/{pid}/stat")
        assert not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"
    finally:
        if pid is not None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
