"""Regression interruption, mocks không chạy trainer/process thật."""

import io
import signal
from pathlib import Path

import pytest

from src.services.reconstruction import preview_cli
from src.services.reconstruction.adapters import brush_runtime
from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings, Invocation, VisualProcess


def test_visual_interrupt_kills_its_separate_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    class Process:
        pid = 43210
        waits = 0

        def __enter__(self) -> "Process":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise KeyboardInterrupt
            return -9

    process = Process()
    monkeypatch.setattr(brush_runtime.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(brush_runtime.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    runtime = VisualProcess(BrushRuntimeSettings(expected_version="fixture", runtime_identity="fixture"))
    with pytest.raises(KeyboardInterrupt):
        runtime._invoke(Invocation("fixture", ("fixture",), ()), (tmp_path, io.StringIO()))
    assert calls == [(process.pid, signal.SIGKILL)]
    assert process.waits == 2


def test_cli_restores_signal_handler_after_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(args: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(preview_cli, "_execute", interrupt)
    assert preview_cli.main(["--request", "unused", "--store-root", "unused", "--workspace", "unused"]) == 130
    assert signal.getsignal(signal.SIGTERM) == previous
