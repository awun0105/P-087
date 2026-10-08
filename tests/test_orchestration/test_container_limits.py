"""Kiểm tra đọc giới hạn cgroup v1/v2, biến môi trường và tính RAM/CPU hiệu dụng."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.orchestration.processing.capability import _live_ram_gb, _ram_gb
from src.services.orchestration.processing.container_limits import (
    cpu_limit,
    effective_cpu_count,
    memory_limit_gb,
    memory_usage_gb,
)


def test_cgroup_v2_memory_limit(tmp_path: Path) -> None:
    # memory.max = 44023414784 bytes -> 41.0 GiB
    (tmp_path / "memory.max").write_text("44023414784\n")
    assert memory_limit_gb(tmp_path) == 41.0

    # memory.max = max -> None (không giới hạn)
    (tmp_path / "memory.max").write_text("max\n")
    assert memory_limit_gb(tmp_path) is None

    # memory.current = 1073741824 bytes -> 1.0 GiB
    (tmp_path / "memory.current").write_text("1073741824\n")
    assert memory_usage_gb(tmp_path) == 1.0


def test_cgroup_v1_memory_limit(tmp_path: Path) -> None:
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir(parents=True)

    # 44023414784 -> 41.0 GiB
    (mem_dir / "memory.limit_in_bytes").write_text("44023414784\n")
    assert memory_limit_gb(tmp_path) == 41.0

    # Giá trị không giới hạn của Linux v1 (LONG_MAX / page-aligned) -> None
    (mem_dir / "memory.limit_in_bytes").write_text("9223372036854771712\n")
    assert memory_limit_gb(tmp_path) is None

    # usage_in_bytes
    (mem_dir / "memory.usage_in_bytes").write_text("2147483648\n")
    assert memory_usage_gb(tmp_path) == 2.0


def test_cpu_limit_v2_and_v1(tmp_path: Path) -> None:
    # cgroup v2: "600000 100000" -> 6.0
    (tmp_path / "cpu.max").write_text("600000 100000\n")
    assert cpu_limit(tmp_path) == 6.0

    # cgroup v2: "max 100000" -> None
    (tmp_path / "cpu.max").write_text("max 100000\n")
    assert cpu_limit(tmp_path) is None

    # cgroup v1 fallback
    (tmp_path / "cpu.max").unlink()
    cpu_dir = tmp_path / "cpu"
    cpu_dir.mkdir(parents=True)
    (cpu_dir / "cpu.cfs_quota_us").write_text("400000\n")
    (cpu_dir / "cpu.cfs_period_us").write_text("100000\n")
    assert cpu_limit(tmp_path) == 4.0

    # cgroup v1: quota = -1 (không giới hạn) -> None
    (cpu_dir / "cpu.cfs_quota_us").write_text("-1\n")
    assert cpu_limit(tmp_path) is None


def test_empty_or_missing_cgroup_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty_cgroup"
    empty.mkdir()
    assert memory_limit_gb(empty) is None
    assert memory_usage_gb(empty) is None
    assert cpu_limit(empty) is None

    non_existent = tmp_path / "missing"
    assert memory_limit_gb(non_existent) is None
    assert memory_usage_gb(non_existent) is None
    assert cpu_limit(non_existent) is None

    # effective_cpu_count không cgroup trả ít nhất 1
    assert effective_cpu_count(empty) >= 1


def test_effective_cpu_count_with_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock máy có 12 nhân
    monkeypatch.setattr("os.cpu_count", lambda: 12)
    monkeypatch.delenv("RUNPOD_CPU_COUNT", raising=False)
    # Giả lập sched_getaffinity không giới hạn (hoặc trả 12)
    if hasattr(os, "sched_getaffinity"):
        monkeypatch.setattr("os.sched_getaffinity", lambda _: set(range(12)))

    assert effective_cpu_count(tmp_path) == 12

    # RUNPOD_CPU_COUNT=6 -> 6
    monkeypatch.setenv("RUNPOD_CPU_COUNT", "6")
    assert effective_cpu_count(tmp_path) == 6

    # RUNPOD_CPU_COUNT=abc -> bỏ qua, vẫn dùng 12
    monkeypatch.setenv("RUNPOD_CPU_COUNT", "abc")
    assert effective_cpu_count(tmp_path) == 12

    # Quota cgroup = 4.0 -> min(12, 4.0) = 4
    (tmp_path / "cpu.max").write_text("400000 100000\n")
    assert effective_cpu_count(tmp_path) == 4


def test_ram_gb_and_live_ram_respect_container_limit(tmp_path: Path) -> None:
    # Mock /proc/meminfo báo host có 125 GB (131072000 kB)
    meminfo_content = "MemTotal:       131072000 kB\nMemAvailable:   104857600 kB\n"

    orig_read_text = Path.read_text

    def selective_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if str(self) == "/proc/meminfo":
            return meminfo_content
        return orig_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", autospec=True, side_effect=selective_read_text):
        # Không có cgroup limit -> dùng host 125 GB
        assert _ram_gb(tmp_path) == 125.0

        # Có cgroup limit 41 GB -> min(125, 41) = 41 GB
        (tmp_path / "memory.max").write_text("44023414784\n")
        assert _ram_gb(tmp_path) == 41.0

        # Live RAM: memory.current = 10 GB (10737418240 bytes)
        # cgroup_free = 41 - 10 = 31 GB < host available 100 GB -> 31 GB
        (tmp_path / "memory.current").write_text("10737418240\n")
        assert _live_ram_gb(tmp_path) == 31.0
