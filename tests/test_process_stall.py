"""T-043 bước 1: canh tiến độ dùng chung. Tiến trình đang ghi tiến triển không bị cắt; tiến trình im quá ngưỡng bị dừng."""

import os
import signal
import sys
import time
from pathlib import Path
from threading import Event

import pytest

from src.services.process_control import (
    ProcessCancelledError,
    ProcessStalledError,
    ProcessTimeoutError,
    ProgressWatchdog,
    file_size_marker,
    run_cancellable_process,
    tree_marker,
)
from src.services.reconstruction.adapters.brush_runtime import (
    BrushRuntimeSettings,
    Invocation,
    VisualError,
    VisualProcess,
)


def _printer(seconds: float, interval: float) -> str:
    return (
        "import sys,time\n"
        f"end=time.monotonic()+{seconds}\n"
        "while time.monotonic()<end:\n"
        "    print('step', flush=True)\n"
        f"    time.sleep({interval})\n"
    )


def test_process_that_keeps_writing_is_not_stopped_even_past_the_stall_window(tmp_path: Path) -> None:
    log = tmp_path / "process.log"
    with log.open("w") as output:
        code = run_cancellable_process(
            [sys.executable, "-c", _printer(seconds=2.0, interval=0.1)],
            cwd=tmp_path,
            timeout_seconds=30,
            output=output,
            stall_seconds=0.6,
            progress=[file_size_marker(log)],
        )
    assert code == 0


def test_silent_process_is_stopped_as_stalled_and_its_group_is_reaped(tmp_path: Path) -> None:
    pid_file = tmp_path / "compiler.pid"
    child = f"import os,time,pathlib; os.setpgrp(); pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    leader = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
    log = tmp_path / "process.log"
    started = time.monotonic()
    try:
        with log.open("w") as output, pytest.raises(ProcessStalledError) as error:
            run_cancellable_process(
                [sys.executable, "-c", leader],
                cwd=tmp_path,
                timeout_seconds=30,
                output=output,
                stall_seconds=0.5,
                progress=[file_size_marker(log)],
                stall_code="TEST_STALLED",
                label="Công cụ thử",
            )
        assert time.monotonic() - started < 10
        assert error.value.code == "TEST_STALLED"
        assert "không tiến triển" in str(error.value) and "đã bị dừng" in str(error.value)
        pid = int(pid_file.read_text())
        stat = Path(f"/proc/{pid}/stat")
        assert not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_timeout_still_applies_to_a_process_that_keeps_progressing(tmp_path: Path) -> None:
    log = tmp_path / "process.log"
    with log.open("w") as output, pytest.raises(ProcessTimeoutError):
        run_cancellable_process(
            [sys.executable, "-c", _printer(seconds=30, interval=0.1)],
            cwd=tmp_path,
            timeout_seconds=1,
            output=output,
            stall_seconds=5,
            progress=[file_size_marker(log)],
        )


def test_cancel_still_stops_a_stall_guarded_process(tmp_path: Path) -> None:
    cancel = Event()
    cancel.set()
    log = tmp_path / "process.log"
    with log.open("w") as output, pytest.raises(ProcessCancelledError):
        run_cancellable_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            timeout_seconds=30,
            output=output,
            cancel_event=cancel,
            stall_seconds=5,
            progress=[file_size_marker(log)],
        )


def test_watchdog_reports_stall_only_after_markers_stop_changing() -> None:
    now = [0.0]
    value = [0]
    dog = ProgressWatchdog(10, [lambda: value[0]], clock=lambda: now[0])

    now[0] = 9.0
    assert not dog.poll() and not dog.stalled()
    value[0] = 1
    now[0] = 15.0
    assert dog.poll()  # đổi giá trị: mốc tiến triển làm mới tại t=15
    now[0] = 24.0
    assert not dog.stalled()
    now[0] = 26.0
    assert dog.stalled()


def test_watchdog_treats_an_unreadable_marker_as_unchanged(tmp_path: Path) -> None:
    missing = tmp_path / "absent.log"
    dog = ProgressWatchdog(5, [file_size_marker(missing), tree_marker(tmp_path / "absent-dir")])
    assert dog.poll() is False


def test_tree_marker_moves_when_a_result_file_appears(tmp_path: Path) -> None:
    results = tmp_path / "sparse"
    results.mkdir()
    marker = tree_marker(results)
    before = marker()
    (results / "cameras.bin").write_bytes(b"x")
    assert marker() != before


def test_brush_train_still_reports_a_hang_with_the_previous_code(tmp_path: Path) -> None:
    """Brush đi qua lớp canh chung; mã lỗi và ngưỡng treo giữ nguyên (VISUAL_HANG_TIMEOUT)."""
    script = tmp_path / "silent_brush.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    settings = BrushRuntimeSettings(
        command=(sys.executable, str(script)),
        expected_version="0.0.0",
        runtime_identity="fixture",
        timeout_seconds=30,
        hang_timeout_seconds=1,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    invocation = Invocation("brush-train", (sys.executable, str(script)), ("--unused",))
    with pytest.raises(VisualError) as error:
        VisualProcess(settings).run(invocation, workspace)
    assert error.value.code == "VISUAL_HANG_TIMEOUT"
