"""Đọc giới hạn bộ nhớ (RAM) và CPU từ cgroup v1/v2 hoặc biến môi trường container."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CGROUP_ROOT = Path("/sys/fs/cgroup")
_MAX_BYTES_THRESHOLD = 2**60


def memory_limit_gb(cgroup_root: Path | None = None) -> float | None:
    """Giới hạn bộ nhớ của container (GiB); None khi không giới hạn hoặc không đọc được.

    Đọc `memory.max` (cgroup v2), nếu không có thì đọc `memory/memory.limit_in_bytes` (cgroup v1).
    Giá trị `max`, giá trị không phải số, hoặc số > 2^60 nghĩa là không giới hạn.
    """
    root = cgroup_root or CGROUP_ROOT
    candidates = [
        root / "memory.max",
        root / "memory" / "memory.limit_in_bytes",
    ]
    for path in candidates:
        try:
            if not path.is_file():
                continue
            text = path.read_text().strip()
            if text == "max":
                return None
            bytes_val = int(text)
            if bytes_val <= 0 or bytes_val >= _MAX_BYTES_THRESHOLD:
                return None
            return round(bytes_val / (1024**3), 2)
        except (OSError, ValueError):
            continue
    return None


def memory_usage_gb(cgroup_root: Path | None = None) -> float | None:
    """Bộ nhớ hiện đang dùng của container (GiB); None khi không đọc được."""
    root = cgroup_root or CGROUP_ROOT
    candidates = [
        root / "memory.current",
        root / "memory" / "memory.usage_in_bytes",
    ]
    for path in candidates:
        try:
            if not path.is_file():
                continue
            text = path.read_text().strip()
            bytes_val = int(text)
            if bytes_val < 0:
                return None
            return round(bytes_val / (1024**3), 2)
        except (OSError, ValueError):
            continue
    return None


def memory_reclaimable_gb(cgroup_root: Path | None = None) -> float:
    """Page cache kernel thu hồi được ngay (`inactive_file`), GiB; 0 khi không đọc được.

    `memory.current`/`usage_in_bytes` tính cả page cache: job đọc nhiều ảnh sẽ làm con số này chạm giới hạn dù
    tiến trình không giữ bộ nhớ đó. Trừ `inactive_file` là cách kubelet tính working set.
    """
    root = cgroup_root or CGROUP_ROOT
    for path, key in (
        (root / "memory.stat", "inactive_file"),
        (root / "memory" / "memory.stat", "total_inactive_file"),
    ):
        try:
            if not path.is_file():
                continue
            for line in path.read_text().splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[0] == key:
                    return round(max(0, int(parts[1])) / (1024**3), 2)
        except (OSError, ValueError):
            continue
    return 0.0


def cpu_limit(cgroup_root: Path | None = None) -> float | None:
    """Giới hạn số nhân CPU theo quota CFS; None khi không giới hạn hoặc không đọc được.

    cgroup v2: `cpu.max` chứa `quota period` (ví dụ `600000 100000`); `max` -> None.
    cgroup v1: `cpu.cfs_quota_us` chia `cpu.cfs_period_us`; quota <= 0 -> None.
    """
    root = cgroup_root or CGROUP_ROOT
    # cgroup v2
    v2_path = root / "cpu.max"
    try:
        if v2_path.is_file():
            text = v2_path.read_text().strip()
            parts = text.split()
            if len(parts) >= 2:
                quota_str, period_str = parts[0], parts[1]
                if quota_str == "max":
                    return None
                quota, period = float(quota_str), float(period_str)
                if quota > 0 and period > 0:
                    return round(quota / period, 2)
    except (OSError, ValueError):
        pass

    # cgroup v1
    quota_path = root / "cpu" / "cpu.cfs_quota_us"
    period_path = root / "cpu" / "cpu.cfs_period_us"
    try:
        if quota_path.is_file() and period_path.is_file():
            quota = int(quota_path.read_text().strip())
            period = int(period_path.read_text().strip())
            if quota > 0 and period > 0:
                return round(quota / period, 2)
    except (OSError, ValueError):
        pass

    return None


def effective_cpu_count(cgroup_root: Path | None = None) -> int:
    """Số nhân CPU thực tế mà container/process được dùng.

    Lấy giá trị nhỏ nhất, làm tròn xuống và tối thiểu 1, của:
    - os.cpu_count()
    - len(os.sched_getaffinity(0))
    - cpu_limit(...) nếu có
    - RUNPOD_CPU_COUNT nếu có và là số nguyên dương.
    """
    candidates: list[float] = []

    count = os.cpu_count()
    if count is not None and count > 0:
        candidates.append(float(count))

    if hasattr(os, "sched_getaffinity"):
        try:
            aff = len(os.sched_getaffinity(0))
            if aff > 0:
                candidates.append(float(aff))
        except OSError:
            pass

    cgroup_cpu = cpu_limit(cgroup_root)
    if cgroup_cpu is not None and cgroup_cpu > 0:
        candidates.append(cgroup_cpu)

    runpod_env = os.environ.get("RUNPOD_CPU_COUNT")
    if runpod_env:
        try:
            val = int(runpod_env.strip())
            if val > 0:
                candidates.append(float(val))
        except ValueError:
            pass

    if not candidates:
        return 1

    return max(1, int(math.floor(min(candidates))))
