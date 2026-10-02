"""Attribution/error proof cho sampled telemetry; subprocess local không phải GPU acceptance."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import Settings
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.workspace import cleanup_attempt_workspace
from src.services.orchestration.processing import telemetry
from tests.test_orchestration.test_prepared_queue import _registry


def _proc(root: Path, pid: int, parent: int, group: int, rss: int, started: int = 1) -> None:
    """Process comm chứa dấu ngoặc để không thể split stat một cách ngây thơ."""
    path = root / str(pid)
    path.mkdir(parents=True, exist_ok=True)
    filler = " ".join(["0"] * 16)  # field 6..21 của /proc/<pid>/stat; starttime là field 22
    (path / "stat").write_text(f"{pid} (tool (child)) S {parent} {group} {filler} {started}\n")
    (path / "status").write_text(f"Name: test\nVmRSS: {rss} kB\n")


def test_ram_and_vram_attributed_to_process_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Con tự mở session (group khác) như Brush vẫn thuộc cây; tiến trình không liên quan thì không."""
    _proc(tmp_path, 100, 1, 100, 1048576)
    _proc(tmp_path, 101, 100, 101, 2097152)  # start_new_session: group riêng, cha vẫn là 100
    _proc(tmp_path, 102, 101, 101, 1048576)
    _proc(tmp_path, 200, 1, 200, 999999999)
    tracked: dict[int, int] = {}
    memory = telemetry._tree_memory(100, tracked, tmp_path)
    assert memory == {100: 1.0, 101: 2.0, 102: 1.0} and set(tracked) == {100, 101, 102}
    monkeypatch.setattr(
        telemetry.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="100, 1024\n200, 999999\n101, 2048\n"),
    )
    assert telemetry._tree_vram(set(memory)) == 3
    assert telemetry._tree_memory(90, {}, tmp_path) is None
    assert telemetry._tree_memory(100, {}, tmp_path / "missing") is None


def test_orphaned_descendants_stay_tracked_but_reused_pids_do_not(tmp_path: Path) -> None:
    _proc(tmp_path, 100, 1, 100, 1048576)
    _proc(tmp_path, 101, 100, 101, 2097152, started=50)
    tracked: dict[int, int] = {}
    telemetry._tree_memory(100, tracked, tmp_path)
    # CLI cha thoát, con bị gán lại cho init: vẫn là tiến trình của lần chạy này.
    for name in ("stat", "status"):
        (tmp_path / "100" / name).unlink()
    (tmp_path / "100").rmdir()
    _proc(tmp_path, 101, 1, 101, 3145728, started=50)
    assert telemetry._tree_memory(100, tracked, tmp_path) == {101: 3.0}
    # PID 101 được hệ điều hành cấp lại cho tiến trình khác (thời điểm khởi động khác).
    _proc(tmp_path, 101, 1, 101, 9999999, started=77)
    assert telemetry._tree_memory(100, tracked, tmp_path) is None and tracked == {}


def test_real_child_in_its_own_session_is_measured() -> None:
    """Tiến trình thật: con 200 MB chạy start_new_session như Brush phải nằm trong số đo."""
    child = "b=bytearray(200*1024*1024); import time; time.sleep(20)"
    leader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True);time.sleep(20)",
        ],
        start_new_session=True,
    )
    try:
        tracked: dict[int, int] = {}
        total = 0.0
        for _ in range(100):
            memory = telemetry._tree_memory(leader.pid, tracked)
            total = sum((memory or {}).values())
            if total > 0.15:
                break
            time.sleep(0.05)
        assert total > 0.15 and len(tracked) == 2
    finally:
        for pid in tracked:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        leader.wait()


@pytest.mark.parametrize("stdout", ["", "200, 99999", "100, [N/A]", "100, nan", "100, -1", "malformed"])
def test_unattributed_or_invalid_vram_is_unknown(stdout: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=stdout))
    assert telemetry._tree_vram({100}) is None


def test_vram_timeout_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("nvidia-smi", 2)))
    assert telemetry._tree_vram({100}) is None


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
    monkeypatch.setattr(telemetry, "_gpu_used", lambda: 0.5)
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
    monkeypatch.setattr(telemetry, "_tree_memory", lambda root, tracked: next(ram))
    monkeypatch.setattr(telemetry, "_tree_vram", lambda pids: next(vram))
    gpu = iter([2.0, 5.0, 1.0])
    monkeypatch.setattr(telemetry, "_gpu_used", lambda: next(gpu))
    for _ in range(3):
        collector.sample(100)
    usage = collector.finish("completed", 0)
    assert usage.duration_seconds == 5 and usage.sample_count == 3
    assert usage.peak_ram_gb == 3 and usage.peak_vram_gb == 4
    assert usage.ram_sample_count == usage.vram_sample_count == 2
    assert usage.measurement_method == "sampled_process_tree" and not usage.includes_runner_process
    # Mức GPU của cả máy là số riêng, không gộp vào VRAM theo PID.
    assert usage.gpu_used_before_gb == 0.5 and usage.peak_gpu_used_gb == 5 and usage.gpu_sample_count == 3
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
    monkeypatch.setattr(telemetry, "_tree_vram", lambda pids: None)
    monkeypatch.setattr(telemetry, "_gpu_used", lambda: None)
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
    # Bản ghi cũng nằm trong runtime DB: đĩa của máy thuê mất khi trả máy.
    with attempt.registry.persistence.database.transaction() as tx:
        rows = tx.execute("SELECT job_id, payload FROM r2s_resource_usage").fetchall()
    assert [(row[0], telemetry.ResourceUsage.model_validate_json(row[1])) for row in rows] == [(usage.job_id, usage)]


def test_worker_interrupt_is_not_recorded_as_tool_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempt = _attempt(tmp_path)
    monkeypatch.setattr(telemetry, "measure_live_headroom", lambda path: {"vram_free_gb": None})
    monkeypatch.setattr(telemetry, "_gpu_used", lambda: None)
    attempt.registry.get_job.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        runner._run_tool(attempt, "test", [sys.executable, "-c", "import time; time.sleep(30)"], 10)
    usage = telemetry.ResourceUsage.model_validate_json((attempt.workspace / "resource-usage.jsonl").read_text())
    assert usage.outcome == "interrupted" and usage.exit_code is not None and usage.exit_code < 0


def test_step_inside_the_worker_is_sampled_and_never_broken_by_sampling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bước tách vật thể chạy subprocess ngay trong worker: đo cây của chính worker."""
    attempt = _attempt(tmp_path)
    monkeypatch.setattr(telemetry, "measure_live_headroom", lambda path: {"vram_free_gb": None})
    monkeypatch.setattr(telemetry, "_tree_vram", lambda pids: None)
    monkeypatch.setattr(telemetry, "_gpu_used", lambda: None)
    with runner._sampled(attempt, "scene_extract"):
        subprocess.run([sys.executable, "-c", "b=bytearray(64*1024*1024); import time; time.sleep(0.5)"], check=True)
    usage = telemetry.ResourceUsage.model_validate_json((attempt.workspace / "resource-usage.jsonl").read_text())
    assert usage.tool == "scene_extract" and usage.outcome == "completed" and usage.includes_runner_process
    assert usage.sample_count >= 1 and usage.peak_ram_gb is not None and usage.peak_ram_gb > 0.06
    # Bước lỗi vẫn có bản ghi; lỗi của bộ đo không thay lỗi của bước.
    monkeypatch.setattr(telemetry, "_tree_memory", Mock(side_effect=RuntimeError("private path")))
    with pytest.raises(ValueError, match="step failed"), runner._sampled(attempt, "scene_extract"):
        raise ValueError("step failed")
    lines = (attempt.workspace / "resource-usage.jsonl").read_text().splitlines()
    assert telemetry.ResourceUsage.model_validate_json(lines[-1]).outcome == "failed"


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
