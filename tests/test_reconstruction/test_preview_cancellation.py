"""Regression process cleanup; real-child coverage uses only a fixture-owned sleeper."""

import io
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TextIO

import pytest

from src.services.reconstruction import preview_cli
from src.services.reconstruction.adapters import brush_runtime
from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings, Invocation, VisualProcess


class FakeProcess:
    """Popen surface used by polling-path tests; wait reaps a terminated child."""

    def __init__(self, polls: list[int | None]) -> None:
        self.pid = 43210
        self._polls = iter(polls)
        self.returncode: int | None = None
        self.reaped = False

    def __enter__(self) -> "FakeProcess":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        try:
            result = next(self._polls)
        except StopIteration:
            return None
        if result is not None:
            self.returncode = result
        return result

    def wait(self, timeout: float | None = None) -> int:
        self.reaped = True
        if self.returncode is None:
            self.returncode = -signal.SIGKILL
        return self.returncode


def _runtime(timeout_seconds: float = 10.0) -> VisualProcess:
    return VisualProcess(
        BrushRuntimeSettings(
            expected_version="fixture",
            runtime_identity="fixture",
            timeout_seconds=timeout_seconds,
            hang_timeout_seconds=0,
        )
    )


def _use_fake_process(monkeypatch: pytest.MonkeyPatch, process: FakeProcess) -> None:
    monkeypatch.setattr(brush_runtime.subprocess, "Popen", lambda *args, **kwargs: process)


def test_visual_interrupt_kills_its_separate_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess([None])
    calls: list[tuple[int, int]] = []
    _use_fake_process(monkeypatch, process)
    monkeypatch.setattr(brush_runtime.os, "killpg", lambda pid, sig: calls.append((pid, sig)))

    def interrupt_polling(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(brush_runtime, "time", SimpleNamespace(monotonic=time.monotonic, sleep=interrupt_polling))
    with pytest.raises(KeyboardInterrupt):
        _runtime()._invoke(Invocation("fixture", ("fixture",), ()), (tmp_path, io.StringIO()))

    assert calls == [(process.pid, signal.SIGKILL)]
    assert process.returncode == -signal.SIGKILL
    assert process.reaped


def test_visual_timeout_kills_and_reaps_fake_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess([None])
    _use_fake_process(monkeypatch, process)
    monkeypatch.setattr(brush_runtime.os, "killpg", lambda pid, sig: None)
    monkeypatch.setattr(
        brush_runtime,
        "time",
        SimpleNamespace(monotonic=iter((0.0, 0.0, 2.0)).__next__, sleep=time.sleep),
    )

    with pytest.raises(brush_runtime.VisualError, match="timeout") as error:
        _runtime(timeout_seconds=1.0)._invoke(Invocation("fixture", ("fixture",), ()), (tmp_path, io.StringIO()))

    assert error.value.code == "VISUAL_TIMEOUT"
    assert process.returncode == -signal.SIGKILL
    assert process.reaped


def test_visual_fatal_log_kills_and_reaps_fake_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess([None])
    _use_fake_process(monkeypatch, process)
    monkeypatch.setattr(brush_runtime.os, "killpg", lambda pid, sig: None)
    monkeypatch.setattr(
        brush_runtime,
        "time",
        SimpleNamespace(monotonic=iter((0.0, 0.0, 0.0)).__next__, sleep=time.sleep),
    )
    (tmp_path / "fixture.log").write_text("CUDA out of memory while allocating\n")

    with pytest.raises(brush_runtime.VisualError) as error:
        _runtime()._invoke(Invocation("fixture", ("fixture",), ()), (tmp_path, io.StringIO()))

    assert error.value.code == "VISUAL_OUT_OF_MEMORY"
    assert process.returncode == -signal.SIGKILL
    assert process.reaped


def test_visual_success_returns_child_exit_without_killing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess([None, 0])
    calls: list[tuple[int, int]] = []
    _use_fake_process(monkeypatch, process)
    monkeypatch.setattr(brush_runtime.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr(brush_runtime, "time", SimpleNamespace(monotonic=time.monotonic, sleep=lambda _: None))

    result = _runtime()._invoke(Invocation("fixture", ("fixture",), ()), (tmp_path, io.StringIO()))

    assert result == 0
    assert process.returncode == 0
    assert not calls


def test_visual_interrupt_tolerates_already_exited_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = FakeProcess([None])
    _use_fake_process(monkeypatch, process)

    def exited_before_signal(pid: int, sig: int) -> None:
        raise ProcessLookupError(pid, "process group already exited")

    def interrupt_after_exit(_: float) -> None:
        process.returncode = 0
        raise KeyboardInterrupt

    monkeypatch.setattr(brush_runtime.os, "killpg", exited_before_signal)
    monkeypatch.setattr(brush_runtime, "time", SimpleNamespace(monotonic=time.monotonic, sleep=interrupt_after_exit))
    with pytest.raises(KeyboardInterrupt):
        _runtime()._invoke(Invocation("fixture", ("fixture",), ()), (tmp_path, io.StringIO()))

    assert process.returncode == 0
    assert process.reaped


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process-group cleanup requires POSIX")
def test_real_fixture_child_is_killed_and_reaped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def track_child(
        args: list[str],
        cwd: Path,
        stdin: int,
        stdout: TextIO,
        stderr: int,
        start_new_session: bool,
        env: dict[str, str],
    ) -> subprocess.Popen[bytes]:
        assert start_new_session
        child = original_popen(
            args,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            start_new_session=start_new_session,
            env=env,
        )
        children.append(child)
        assert os.getpgid(child.pid) == child.pid
        return child

    def interrupt_sleep(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(brush_runtime.subprocess, "Popen", track_child)
    monkeypatch.setattr(brush_runtime, "time", SimpleNamespace(monotonic=time.monotonic, sleep=interrupt_sleep))
    try:
        with pytest.raises(KeyboardInterrupt):
            VisualProcess(
                BrushRuntimeSettings(
                    command=(sys.executable,),
                    expected_version="fixture",
                    runtime_identity="fixture",
                    timeout_seconds=2.0,
                    hang_timeout_seconds=0,
                )
            ).run(Invocation("fixture-child", (sys.executable, "-c", "import time; time.sleep(60)"), ()), tmp_path)
    finally:
        for child in children:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            child.wait(timeout=5)

    assert len(children) == 1
    assert children[0].returncode == -signal.SIGKILL
    assert children[0].wait(timeout=0) == -signal.SIGKILL


def test_cli_restores_signal_handler_after_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(args: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(preview_cli, "_execute", interrupt)
    assert preview_cli.main(["--request", "unused", "--store-root", "unused", "--workspace", "unused"]) == 130
    assert signal.getsignal(signal.SIGTERM) == previous
