"""Bảng tiến trình Linux đọc từ `/proc`, dùng chung cho telemetry, giữ chỗ và dọn scratch.

Định danh tiến trình bằng cặp (PID, thời điểm khởi động) như `psutil` làm, vì PID được
tái sử dụng. Không thêm dependency: lock runtime không có `psutil`.
"""

import os
from dataclasses import dataclass
from pathlib import Path

PROC_ROOT = Path("/proc")


@dataclass(frozen=True)
class ProcessEntry:
    """Một dòng `/proc/<pid>/stat`: cha, process group và thời điểm khởi động (clock tick)."""

    pid: int
    parent: int
    group: int
    started: int


def process_table(proc_root: Path = PROC_ROOT) -> dict[int, ProcessEntry] | None:
    """Mọi tiến trình đọc được; None khi không có `/proc` (không phải Linux hoặc bị chặn)."""
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return None
    table: dict[int, ProcessEntry] = {}
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            # comm có thể chứa dấu cách/ngoặc: chỉ tách phần sau dấu ')' cuối cùng.
            # Sau đó: state, ppid, pgrp, ... và starttime là field thứ 22 của cả dòng (index 19).
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            pid = int(entry.name)
            started = int(fields[19]) if len(fields) > 19 else 0
            table[pid] = ProcessEntry(pid=pid, parent=int(fields[1]), group=int(fields[2]), started=started)
        except (OSError, ValueError, IndexError):
            continue  # Tiến trình thoát giữa lúc liệt kê và lúc đọc.
    return table


def process_tree(table: dict[int, ProcessEntry], roots: set[int]) -> set[int]:
    """`roots` còn sống cùng toàn bộ con cháu theo PPID, kể cả con tự mở session/process group riêng."""
    children: dict[int, list[int]] = {}
    for entry in table.values():
        children.setdefault(entry.parent, []).append(entry.pid)
    found: set[int] = set()
    pending = [pid for pid in roots if pid in table]
    while pending:
        pid = pending.pop()
        if pid in found:
            continue
        found.add(pid)
        pending.extend(children.get(pid, ()))
    return found


def resident_gb(pid: int, proc_root: Path = PROC_ROOT) -> float | None:
    """RSS của một PID (GiB); None khi tiến trình đã thoát hoặc là kernel thread."""
    try:
        for line in (proc_root / str(pid) / "status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                value = int(line.split()[1]) / 1024**2
                return value if value >= 0 else None
    except (OSError, ValueError, IndexError):
        return None
    return None


def process_alive(pid: int, proc_root: Path = PROC_ROOT) -> bool:
    """Tiến trình cùng máy còn tồn tại hay không (dùng để bỏ giữ chỗ của worker đã chết)."""
    return (proc_root / str(pid)).is_dir()


def any_process_inside(directory: Path, proc_root: Path = PROC_ROOT) -> bool | None:
    """Có tiến trình nào đang lấy `directory` (hoặc thư mục con) làm thư mục làm việc không.

    Brush và splat-transform chạy với cwd là workspace của attempt. None khi không đọc
    được `/proc`: nơi gọi phải coi là "không chắc", không phải "không có".
    """
    try:
        entries = [entry for entry in proc_root.iterdir() if entry.name.isdecimal()]
    except OSError:
        return None
    target = directory.resolve()
    for entry in entries:
        try:
            current = Path(os.readlink(entry / "cwd"))
        except OSError:
            continue  # Tiến trình của user khác hoặc vừa thoát.
        if current == target or target in current.parents:
            return True
    return False
