"""Live headroom positive/negative/error proof qua probe fixture, không cần GPU."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.services.orchestration.processing import capability


def test_live_headroom_uses_mem_available_and_gib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    query = Mock(return_value=SimpleNamespace(stdout="2048\n"))
    monkeypatch.setattr(capability.subprocess, "run", query)
    monkeypatch.setattr(
        Path, "read_text", lambda *args: "MemTotal: 16777216 kB\nMemFree: 100 kB\nMemAvailable: 4194304 kB\n"
    )
    monkeypatch.setattr(capability.shutil, "disk_usage", lambda path: SimpleNamespace(free=8 * 1024**3))
    assert capability.measure_live_headroom(tmp_path) == {"vram_free_gb": 2, "ram_available_gb": 4, "disk_free_gb": 8}
    assert query.call_args.kwargs["timeout"] == 2


@pytest.mark.parametrize("stdout", ["", "garbage", "nan", "inf", "-1", "4096\n8192\n", "[N/A]"])
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
