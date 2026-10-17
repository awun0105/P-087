"""T-043 bước 2: COLMAP dừng khi treo (không có tiến triển), không dừng khi vẫn ghi tiến triển."""

import sys
import time
from pathlib import Path

import pytest

from src.models.contracts.retryability import classify_retryability
from src.services.reconstruction.adapters.colmap_runtime import ColmapError, ColmapProcess, ColmapRuntimeSettings


def test_stall_window_default_and_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ColmapRuntimeSettings(runtime_identity="fixture").stall_seconds == 600
    monkeypatch.setenv("R2S_COLMAP_STALL_SECONDS", "42")
    assert ColmapRuntimeSettings(runtime_identity="fixture").stall_seconds == 42


def test_silent_colmap_is_stopped_as_stalled_long_before_the_hard_timeout(tmp_path: Path) -> None:
    fake = tmp_path / "fake_colmap.py"
    fake.write_text("import time\nprint('Loading database', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    settings = ColmapRuntimeSettings(
        command=(sys.executable, str(fake)),
        runtime_identity="fixture",
        timeout_seconds=30,
        stall_seconds=1,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started = time.monotonic()

    with pytest.raises(ColmapError) as error:
        ColmapProcess(settings).run(["mapper"], workspace)

    assert time.monotonic() - started < 20
    assert error.value.code == "PROCESS_STALLED"
    message = str(error.value)
    assert "không tiến triển" in message and "đã bị dừng" in message
    assert "R2S_COLMAP_STALL_SECONDS" in message
    assert str(workspace) not in message and str(workspace) not in str(error.value.details)
    assert any("Loading database" in line for line in error.value.details["log_excerpt"])
    assert classify_retryability("PROCESS_STALLED") is True


def test_colmap_that_keeps_logging_is_not_stopped(tmp_path: Path) -> None:
    fake = tmp_path / "chatty_colmap.py"
    fake.write_text(
        "import time\nend = time.monotonic() + 2.5\nwhile time.monotonic() < end:\n"
        "    print('Registering image', flush=True)\n    time.sleep(0.2)\n",
        encoding="utf-8",
    )
    settings = ColmapRuntimeSettings(
        command=(sys.executable, str(fake)),
        runtime_identity="fixture",
        timeout_seconds=30,
        stall_seconds=1,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    text = ColmapProcess(settings).run(["mapper"], workspace)

    assert text.count("Registering image") >= 5
