"""T-043 bước 3 (ObjectGS): pha huấn luyện không ghi log trong cửa sổ treo thì bị dừng; có tiến triển thì không."""

import os
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.services.process_control import ProcessStalledError
from src.services.scene import objectgs


def _runtime(tmp_path: Path, stall_seconds: float) -> objectgs.ObjectGSRuntime:
    return objectgs.ObjectGSRuntime(
        python=tmp_path / "python",
        repository=tmp_path,
        gsplat_repository=tmp_path,
        timeout_seconds=30,
        stall_seconds=stall_seconds,
    )


def _wrapper(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "stage.py"
    script.write_text(body, encoding="utf-8")
    wrapper = tmp_path / "python"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    os.chmod(wrapper, 0o755)
    return wrapper


def test_objectgs_stall_window_default_and_environment_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert Settings(_env_file=None, openai_api_key="test-key").product_objectgs_stall_seconds == 1800
    monkeypatch.setenv("PRODUCT_OBJECTGS_STALL_SECONDS", "77")
    assert Settings(_env_file=None, openai_api_key="test-key").product_objectgs_stall_seconds == 77
    with pytest.raises(ValidationError):
        _runtime(tmp_path, stall_seconds=0)


def test_silent_training_stage_is_stopped_as_stalled(tmp_path: Path) -> None:
    python = _wrapper(tmp_path, "import time\nprint('[ITER 1]', flush=True)\ntime.sleep(60)\n")
    runtime = objectgs.ObjectGSRuntime(
        python=python, repository=tmp_path, gsplat_repository=tmp_path, timeout_seconds=30, stall_seconds=1
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started = time.monotonic()

    with pytest.raises(ProcessStalledError) as error:
        objectgs._run_stage_process(
            [str(python), "train.py"],
            workspace=workspace,
            stage="train",
            runtime=runtime,
            environment={},
            cancel_event=None,
        )

    assert time.monotonic() - started < 20
    assert error.value.code == "PROCESS_STALLED"
    assert "ObjectGS train" in str(error.value) and "không tiến triển" in str(error.value)


def test_training_stage_that_keeps_logging_is_not_stopped(tmp_path: Path) -> None:
    body = (
        "import time\nend = time.monotonic() + 2.5\nwhile time.monotonic() < end:\n"
        "    print('Training progress: step', flush=True)\n    time.sleep(0.2)\n"
    )
    python = _wrapper(tmp_path, body)
    runtime = objectgs.ObjectGSRuntime(
        python=python, repository=tmp_path, gsplat_repository=tmp_path, timeout_seconds=30, stall_seconds=1
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status = objectgs._run_stage_process(
        [str(python), "train.py"],
        workspace=workspace,
        stage="train",
        runtime=runtime,
        environment={},
        cancel_event=None,
    )

    assert status == 0
