"""Process-group execution shared by long-running product operations."""

import os
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from math import isfinite
from pathlib import Path
from threading import Event
from typing import TextIO


class ProcessCancelledError(RuntimeError):
    """Raised after cancellation kills and reaps a child process group."""


class ProcessTimeoutError(TimeoutError):
    """Raised after timeout kills and reaps a child process group."""


class ProcessStalledError(RuntimeError):
    """Raised after the process made no progress for too long; its group was killed and reaped.

    Khác `ProcessTimeoutError`: tiến trình vẫn đang chạy nhưng không ghi thêm gì, nên hết giờ cố định không phân biệt được
    với một lượt chỉ chậm. `code` là mã lỗi của công cụ (mặc định `PROCESS_STALLED`).
    """

    def __init__(self, message: str, *, code: str = "PROCESS_STALLED") -> None:
        super().__init__(message)
        self.code = code


#: Một dấu hiệu tiến triển rẻ: trả giá trị; giá trị đổi so với lần trước nghĩa là vừa có tiến triển.
ProgressMarker = Callable[[], object]


class ProgressWatchdog:
    """Đồng hồ tiến triển: không dấu hiệu nào đổi trong `stall_seconds` thì coi như treo.

    Không đọc đầu ra của tiến trình, nên dùng được cho mọi công cụ. Lỗi khi đọc một dấu hiệu được coi là không đổi.
    """

    def __init__(
        self,
        stall_seconds: float,
        markers: Sequence[ProgressMarker],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isfinite(stall_seconds) or stall_seconds <= 0:
            raise ValueError("stall window must be positive")
        self.stall_seconds = stall_seconds
        self._markers = tuple(markers)
        self._clock = clock
        self._seen = self._read()
        self._last_progress = clock()

    def _read(self) -> tuple[object, ...]:
        values: list[object] = []
        for marker in self._markers:
            try:
                values.append(marker())
            except OSError:
                values.append(None)
        return tuple(values)

    def poll(self) -> bool:
        """True nếu có dấu hiệu đổi từ lần gọi trước; khi đổi thì mốc tiến triển được làm mới."""
        current = self._read()
        if current == self._seen:
            return False
        self._seen = current
        self._last_progress = self._clock()
        return True

    def stalled(self) -> bool:
        return self._clock() - self._last_progress > self.stall_seconds


def file_size_marker(path: Path) -> ProgressMarker:
    """Log/file tăng kích thước là có tiến triển; file chưa có thì -1."""

    def marker() -> int:
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return -1

    return marker


def tree_marker(root: Path, *, depth: int = 3) -> ProgressMarker:
    """Số file và mtime mới nhất trong cây thư mục (giới hạn độ sâu): thư mục kết quả đổi là có tiến triển."""

    def marker() -> tuple[int, int]:
        count = 0
        newest = 0
        pending = [(root, 0)]
        while pending:
            directory, level = pending.pop()
            try:
                entries = list(os.scandir(directory))
            except FileNotFoundError:
                continue
            for entry in entries:
                try:
                    newest = max(newest, entry.stat(follow_symlinks=False).st_mtime_ns)
                except OSError:
                    continue
                count += 1
                if entry.is_dir(follow_symlinks=False) and level + 1 < depth:
                    pending.append((Path(entry.path), level + 1))
        return count, newest

    return marker


def _human_duration(seconds: float) -> str:
    if seconds >= 120:
        return f"{round(seconds / 60)} phút"
    return f"{round(seconds)} giây"


def run_cancellable_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    output: TextIO,
    cancel_event: Event | None = None,
    environment: Mapping[str, str] | None = None,
    stall_seconds: float | None = None,
    progress: Sequence[ProgressMarker] = (),
    stall_code: str = "PROCESS_STALLED",
    label: str = "Tiến trình",
) -> int:
    """Run argv in its own process group; cancel, timeout and stall always kill the group and reap its leader.

    `stall_seconds` bật canh tiến độ: không dấu hiệu nào trong `progress` đổi quá lâu thì ném `ProcessStalledError`.
    """
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
    watchdog = ProgressWatchdog(stall_seconds, progress) if stall_seconds is not None else None
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _kill_and_reap(process)
                raise ProcessCancelledError("Process was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_and_reap(process)
                raise ProcessTimeoutError("Process exceeded its configured timeout")
            if watchdog is not None:
                watchdog.poll()
                if watchdog.stalled():
                    _kill_and_reap(process)
                    raise ProcessStalledError(
                        f"{label} không tiến triển trong {_human_duration(watchdog.stall_seconds)} và đã bị dừng.",
                        code=stall_code,
                    )
            if cancel_event is not None or watchdog is not None:
                wait_for = min(0.1, remaining)
            else:
                wait_for = remaining
            try:
                return process.wait(timeout=wait_for)
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
