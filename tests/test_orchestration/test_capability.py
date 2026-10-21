"""Live headroom positive/negative/error proof qua probe fixture, không cần GPU."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.services.orchestration.processing import capability


@pytest.fixture(autouse=True)
def _unpinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mặc định worker không được ghim GPU; test ghim tự đặt biến môi trường."""
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)


def _rows(*rows: tuple[int, str, int, int]) -> SimpleNamespace:
    """Output `nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.free,memory.used` (MiB)."""
    return SimpleNamespace(
        stdout="".join(
            f"{index}, {uuid}, Tesla T4, {total}, {free}, {total - free}\n" for index, uuid, total, free in rows
        )
    )


def test_live_headroom_uses_mem_available_and_gib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    query = Mock(return_value=_rows((0, "GPU-aaaa", 16384, 2048)))
    monkeypatch.setattr(capability.subprocess, "run", query)
    monkeypatch.setattr(
        Path, "read_text", lambda *args: "MemTotal: 16777216 kB\nMemFree: 100 kB\nMemAvailable: 4194304 kB\n"
    )
    monkeypatch.setattr(capability.shutil, "disk_usage", lambda path: SimpleNamespace(free=8 * 1024**3))
    assert capability.measure_live_headroom(tmp_path) == {"vram_free_gb": 2, "ram_available_gb": 4, "disk_free_gb": 8}
    assert query.call_args.kwargs["timeout"] == 2


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "garbage",
        "0, GPU-a, T4, 16384, nan, 1",
        "0, GPU-a, T4, 16384, inf, 1",
        "0, GPU-a, T4, 16384, -1, 1",
        "0, GPU-a, T4, 16384, [N/A], 1",
        "0, GPU-a, T4, 16384, 4096, 1\n1, GPU-b, T4, 16384, 8192, 1\n",  # nhiều GPU, worker chưa ghim
    ],
)
def test_unknown_vram_is_not_zero_or_total(stdout: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=stdout))
    assert capability._live_vram_gb() is None


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError(), subprocess.TimeoutExpired("nvidia-smi", 2), subprocess.CalledProcessError(1, "nvidia-smi")],
)
def test_gpu_failure_isolated(error: Exception, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability.subprocess, "run", Mock(side_effect=error))
    monkeypatch.setattr(capability, "_live_ram_gb", lambda: 3.0)
    assert capability.measure_live_headroom(tmp_path)["vram_free_gb"] is None
    assert capability.measure_live_headroom(tmp_path)["ram_available_gb"] == 3


@pytest.mark.parametrize(
    "content", ["MemTotal: 1048576 kB", "MemAvailable:", "MemAvailable: invalid kB", "MemAvailable: -1 kB"]
)
def test_ram_missing_or_malformed_is_unknown(content: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_text", lambda *args: content)
    assert capability._live_ram_gb() is None


def test_proc_and_disk_errors_are_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_text", Mock(side_effect=PermissionError()))
    monkeypatch.setattr(capability, "_live_vram_gb", lambda: 1.0)
    result = capability.measure_live_headroom(tmp_path / "missing")
    assert result == {"vram_free_gb": 1, "ram_available_gb": None, "disk_free_gb": None}
    assert not (tmp_path / "missing").exists()


TWO = ((0, "GPU-aaaa-1111", 16384, 1024), (1, "GPU-bbbb-2222", 16384, 12288))


@pytest.mark.parametrize(
    ("visible", "free_gb"),
    [("1", 12.0), ("0", 1.0), ("1,0", 12.0), ("GPU-bbbb", 12.0), ("GPU-aaaa-1111", 1.0)],
)
def test_pinned_worker_measures_its_own_gpu(visible: str, free_gb: float, monkeypatch: pytest.MonkeyPatch) -> None:
    """`nvidia-smi` liệt kê mọi GPU bất kể CUDA_VISIBLE_DEVICES: phải chọn đúng dòng của worker."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visible)
    monkeypatch.setattr(capability.subprocess, "run", lambda *args, **kwargs: _rows(*TWO))
    assert capability._live_vram_gb() == free_gb
    gpu = capability.bound_gpu()
    assert gpu is not None and gpu.total_gb == 16 and gpu.used_gb == 16 - free_gb


@pytest.mark.parametrize("visible", ["7", "GPU-zzzz", "GPU-", "", "MIG-123"])
def test_pin_that_matches_no_single_gpu_is_unknown(visible: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visible)
    monkeypatch.setattr(capability.subprocess, "run", lambda *args, **kwargs: _rows(*TWO))
    assert capability.bound_gpu() is None and capability._live_vram_gb() is None


def test_capacity_reports_totals_of_the_pinned_gpu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.setattr(capability.subprocess, "run", lambda *args, **kwargs: _rows((0, "GPU-a", 8192, 1), TWO[1]))
    monkeypatch.setattr(capability, "_ram_gb", lambda: 32.0)
    monkeypatch.setattr(capability.shutil, "disk_usage", lambda path: SimpleNamespace(total=100 * 1024**3, free=1))
    assert capability.measure_capacity(tmp_path) == {"vram": 16, "ram": 32, "disk": 100}


def test_probe_keeps_idle_baseline_while_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mốc rảnh chỉ đổi ở lượt đo lúc rảnh; lúc bận số trống tức thời tụt nhưng mốc giữ nguyên."""
    free = {"mib": 15360}
    monkeypatch.setattr(
        capability.subprocess, "run", lambda *args, **kwargs: _rows((0, "GPU-aaaa", 16384, free["mib"]))
    )
    monkeypatch.setattr(capability, "_live_ram_gb", lambda: 20.0)
    # `subprocess.run` giả chỉ trả bảng nvidia-smi; không để lượt đọc phiên bản COLMAP (có cache theo tiến trình)
    # làm kết quả phụ thuộc thứ tự chạy test.
    monkeypatch.setattr(capability, "colmap_vocab_tree_available", lambda: None)
    first = capability.probe(tmp_path, idle=True)
    assert first.idle_vram_free_gb == 15 and first.idle_measured_at == first.measured_at
    assert first.gpu_uuid == "GPU-aaaa" and first.disk_total_gb is not None and first.vram_total_gb == 16
    free["mib"] = 1024
    busy = capability.probe(tmp_path, idle=False, previous=first)
    assert busy.vram_free_gb == 1 and busy.idle_vram_free_gb == 15
    assert busy.idle_measured_at == first.idle_measured_at
    assert capability.probe(tmp_path, idle=False).idle_measured_at is None  # chưa từng đo lúc rảnh
