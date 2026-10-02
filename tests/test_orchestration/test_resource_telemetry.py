"""Attribution/error proof cho sampled telemetry; subprocess local không phải GPU acceptance."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import Settings
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.workspace import cleanup_attempt_workspace
from src.services.orchestration.processing import telemetry
from tests.test_orchestration.test_prepared_queue import _registry


def _proc(root: Path, pid: int, group: int, rss: int) -> None:
    """Process comm chứa dấu ngoặc để không thể split stat một cách ngây thơ."""
    path = root / str(pid)
    path.mkdir(parents=True)
    (path / "stat").write_text(f"{pid} (tool (child)) S 1 {group} 0\n")
    (path / "status").write_text(f"Name: test\nVmRSS: {rss} kB\n")


def test_ram_and_vram_attributed_to_process_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _proc(tmp_path, 100, 40, 1048576)
    _proc(tmp_path, 101, 40, 2097152)
    _proc(tmp_path, 200, 50, 999999999)
    memory = telemetry._group_memory(40, tmp_path)
    assert memory == {100: 1.0, 101: 2.0}
    monkeypatch.setattr(
        telemetry.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="100, 1024\n200, 999999\n101, 2048\n"),
    )
    assert telemetry._group_vram(set(memory)) == 3
    assert telemetry._group_memory(90, tmp_path) is None
    assert telemetry._group_memory(40, tmp_path / "missing") is None


@pytest.mark.parametrize("stdout", ["", "200, 99999", "100, [N/A]", "100, nan", "100, -1", "malformed"])
def test_unattributed_or_invalid_vram_is_unknown(stdout: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=stdout))
    assert telemetry._group_vram({100}) is None


def test_vram_timeout_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("nvidia-smi", 2)))
    assert telemetry._group_vram({100}) is None


def test_scratch_measurement_does_not_follow_symlinks(tmp_path: Path) -> None:
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    (workspace / "a.bin").write_bytes(b"1234")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "b.bin").write_bytes(b"123456789")
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    assert telemetry._scratch_gb(workspace) == 4 / 1024**3
    assert telemetry._scratch_gb(tmp_path / "missing") is None


def test_sampled_peaks_duration_and_record_survive_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workers" / "job-a" / ("attempt-" + "a" * 32)
    workspace.mkdir(parents=True)
    (workspace / "scratch.bin").write_bytes(b"scratch")
    monkeypatch.setattr(telemetry, "measure_live_headroom", lambda path: {"vram_free_gb": None, "ram_available_gb": 5})
    clocks = iter([10.0, 15.0])
    monkeypatch.setattr(telemetry.time, "monotonic", lambda: next(clocks))
    context = telemetry.ResourceContext(
        job_id="job-a",
        attempt_id=workspace.name,
        tool="preview",
        config_checksum="sha256:" + "a" * 64,
        runtime_manifest_checksum="sha256:" + "b" * 64,
    )
    collector = telemetry.ResourceSampler(context, workspace=workspace, worker_root=tmp_path / "workers")
    ram = iter([{100: 1.0, 101: 2.0}, {100: 2.0}, None])
    vram = iter([1.0, 4.0, None])
    monkeypatch.setattr(telemetry, "_group_memory", lambda group: next(ram))
    monkeypatch.setattr(telemetry, "_group_vram", lambda pids: next(vram))
    for _ in range(3):
        collector.sample(100)
    usage = collector.finish("completed", 0)
    assert usage.duration_seconds == 5 and usage.sample_count == 3
    assert usage.peak_ram_gb == 3 and usage.peak_vram_gb == 4
    assert usage.ram_sample_count == usage.vram_sample_count == 2
    assert usage.measurement_method == "sampled_process_group"
    cleanup_attempt_workspace(workspace, worker_root=tmp_path / "workers", artifact_root=tmp_path / "artifacts")
    loaded = telemetry.ResourceUsage.model_validate_json((workspace / "resource-usage.jsonl").read_text())
    assert loaded == usage and not (workspace / "scratch.bin").exists()


def _attempt(tmp_path: Path) -> runner._Attempt:
    """Real fixture manifest, fake registry lookup; tool vẫn là subprocess local thật."""
    registry = _registry(tmp_path / "runtime")
    job = registry.get_job("job-fixture-001")
    workspace = tmp_path / "workers" / job.job_id / ("attempt-" + "c" * 32)
    workspace.mkdir(parents=True)
    registry.get_job = Mock(return_value=job)
    return runner._Attempt(registry, Settings(product_worker_root=tmp_path / "workers"), job, workspace)


@pytest.mark.parametrize("case", ["success", "nonzero", "malformed", "timeout", "cancelled", "launch"])
def test_runner_records_local_process_outcomes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    attempt = _attempt(tmp_path)
    monkeypatch.setattr(telemetry, "measure_live_headroom", lambda path: {"vram_free_gb": None})
    monkeypatch.setattr(telemetry, "_group_vram", lambda pids: None)
    code = "print('{}')"
    if case == "nonzero":
        code += "; raise SystemExit(1)"
    elif case == "malformed":
        code = "print('not json')"
    elif case in {"timeout", "cancelled"}:
        code = "import time; time.sleep(30)"
    command = [sys.executable, "-c", code] if case != "launch" else [str(tmp_path / "missing-executable")]
    timeout = 0 if case == "timeout" else 10
    if case == "cancelled":
        attempt.registry.get_job.return_value = attempt.job.model_copy(update={"job_manifest_checksum": "changed"})
    if case in {"success", "nonzero"}:
        exit_code, payload = runner._run_tool(attempt, "test", command, timeout)
        assert exit_code == (0 if case == "success" else 1) and payload == {}
    else:
        errors = {
            "malformed": ValueError,
            "timeout": TimeoutError,
            "cancelled": runner.PreviewCancelledError,
            "launch": FileNotFoundError,
        }
        with pytest.raises(errors[case]):
            runner._run_tool(attempt, "test", command, timeout)
    usage = telemetry.ResourceUsage.model_validate_json((attempt.workspace / "resource-usage.jsonl").read_text())
    expected = {
        "success": "completed",
        "nonzero": "failed",
        "malformed": "failed",
        "timeout": "timeout",
        "cancelled": "cancelled",
        "launch": "failed",
    }
    assert usage.outcome == expected[case] and usage.config_checksum == attempt.job.config_checksum
    assert usage.attempt_id == attempt.workspace.name and usage.peak_vram_gb is None
    assert usage.duration_seconds >= 0
    if case in {"timeout", "cancelled"}:
        assert usage.exit_code is not None and usage.exit_code < 0  # Process đã dừng/reap.


@pytest.mark.parametrize("failure", [False, True])
def test_telemetry_failure_preserves_primary_result_or_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: bool
) -> None:
    attempt = _attempt(tmp_path)
    collector = Mock()
    collector.sample.side_effect = RuntimeError("private path")
    collector.finish.side_effect = PermissionError("secret path")
    monkeypatch.setattr(runner, "_resource_sampler", lambda *args: collector)
    if failure:
        with pytest.raises(FileNotFoundError):
            runner._run_tool(attempt, "test", [str(tmp_path / "missing")], 5)
    else:
        assert runner._run_tool(attempt, "test", [sys.executable, "-c", "print('{}')"], 5) == (0, {})
    assert "secret path" not in caplog.text and "private path" not in caplog.text


def test_sampler_creation_failure_does_not_block_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempt = _attempt(tmp_path)
    monkeypatch.setattr(runner, "ResourceSampler", Mock(side_effect=RuntimeError("unsupported platform")))
    assert runner._run_tool(attempt, "test", [sys.executable, "-c", "print('{}')"], 5) == (0, {})


def test_stop_still_terminates_group_when_leader_already_exited(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock(pid=100, returncode=0)
    process.poll.return_value = 0
    kill = Mock()
    monkeypatch.setattr(runner.os, "killpg", kill)
    runner._stop(process)
    assert [call.args for call in kill.call_args_list] == [(100, runner.signal.SIGTERM), (100, runner.signal.SIGKILL)]
    process.wait.assert_called()
