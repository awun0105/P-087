"""T-043 bước 3 (MoGe): trình chạy không ghi tiến độ trong cửa sổ treo thì bị dừng; có tiến độ thì không."""

import os
import sys
import time
from pathlib import Path

import pytest

from src.services.reconstruction.metric_proposal import MogeSettings, _run_moge


def _wrapper(tmp_path: Path, body: str) -> Path:
    """Trình thông dịch giả: shell script gọi Python với script `body` (nhận đúng argv của runner thật)."""
    script = tmp_path / "fake_moge.py"
    script.write_text(body, encoding="utf-8")
    wrapper = tmp_path / "fake-python"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    os.chmod(wrapper, 0o755)
    return wrapper


def test_stall_window_default_and_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert MogeSettings().stall_seconds == 300
    monkeypatch.setenv("R2S_MOGE_STALL_SECONDS", "9")
    assert MogeSettings().stall_seconds == 9


def test_silent_moge_runner_is_stopped_as_stalled(tmp_path: Path) -> None:
    python = _wrapper(tmp_path, "import time\nprint('loading model', flush=True)\ntime.sleep(60)\n")
    settings = MogeSettings(python=python, model=tmp_path / "model.pt", timeout_seconds=30, stall_seconds=1)
    workspace = tmp_path / "workspace"
    started = time.monotonic()

    with pytest.raises(ValueError) as error:
        _run_moge({"frames": []}, workspace, settings)

    assert time.monotonic() - started < 20
    assert "không tiến triển" in str(error.value)
    assert "R2S_MOGE_STALL_SECONDS" in str(error.value)


def test_moge_runner_that_reports_each_frame_is_not_stopped(tmp_path: Path) -> None:
    body = (
        "import json,sys,time\nimport numpy as np\n"
        "args=sys.argv[1:]\nresult=args[args.index('--result')+1]\n"
        "end=time.monotonic()+2.5\nwhile time.monotonic()<end:\n"
        "    print(json.dumps({'frame': 1, 'of': 1}), flush=True)\n    time.sleep(0.2)\n"
        "np.savez(result, **{'0_depth': np.ones(2, dtype=np.float32)})\n"
    )
    python = _wrapper(tmp_path, body)
    settings = MogeSettings(python=python, model=tmp_path / "model.pt", timeout_seconds=30, stall_seconds=1)

    arrays = _run_moge({"frames": []}, tmp_path / "workspace", settings)

    assert set(arrays) == {"0_depth"}
