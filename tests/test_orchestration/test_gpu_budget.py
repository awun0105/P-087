"""T-043 bước 5: trần giờ GPU mỗi scene. Không đặt thì không chặn; vượt trước khi chạy hoặc khi đang chạy thì dừng."""

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.config import Settings
from src.models.contracts.manifests import JobStatus
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.processing.expected_duration import Estimate
from src.services.orchestration.processing.gpu_budget import GpuBudgetExceededError, spent_gpu_hours
from src.services.orchestration.processing.telemetry import ResourceUsage
from src.services.orchestration.projects.models import JobCreateInput
from tests.test_orchestration.test_prepared_queue import _registry

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def _usage(job_id: str, seconds: float, **changes: object) -> ResourceUsage:
    fields: dict[str, object] = {
        "job_id": job_id,
        "attempt_id": "attempt-a",
        "tool": "preview",
        "config_checksum": "c",
        "runtime_manifest_checksum": "runtime-1",
        "params": {"brush.total_train_iters": 1000.0},
        "gpu_name": "NVIDIA A40",
        "shared_gpu": False,
        "started_at": NOW,
        "completed_at": NOW,
        "outcome": "completed",
        "exit_code": 0,
        "duration_seconds": seconds,
        "sample_count": 1,
        "ram_sample_count": 1,
        "vram_sample_count": 1,
        "gpu_sample_count": 1,
        "scratch_sample_count": 1,
        "peak_ram_gb": 2.0,
        "peak_vram_gb": 1.0,
        "headroom_before": {},
    }
    return ResourceUsage(**{**fields, **changes})


def test_spent_hours_count_only_this_jobs_completed_billed_runs() -> None:
    usages = [
        _usage("job-a", 3600),
        _usage("job-a", 1800, outcome="failed"),
        _usage("job-b", 7200),
        _usage("job-a", 1800, tool="scene.objectify"),
    ]

    assert spent_gpu_hours(usages, "job-a") == pytest.approx(1.5)


def _attempt(tmp_path: Path, cap: float | None) -> runner._Attempt:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    job = registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    settings = Settings(_env_file=None, openai_api_key="test-key", product_job_gpu_hours_max=cap)
    return runner._Attempt(registry, settings, job, workspace)


def _quiet(monkeypatch: pytest.MonkeyPatch, usages: list[ResourceUsage], deadline: float = 30) -> None:
    monkeypatch.setattr(runner, "_resource_sampler", lambda attempt, tool: None)
    monkeypatch.setattr(runner, "load_usages", lambda database: usages)
    monkeypatch.setattr(runner, "_expected_limit", lambda attempt, name, fixed: (deadline, None))


def test_no_cap_never_blocks_a_gpu_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempt = _attempt(tmp_path, cap=None)
    _quiet(monkeypatch, [_usage(attempt.job.job_id, 10 * 3600)])

    exit_code, payload = runner._run_tool(attempt, "preview", [sys.executable, "-c", "print('{}')"], 30)

    assert (exit_code, payload) == (0, {})


def test_cap_blocks_a_gpu_tool_before_it_starts_when_the_projected_run_exceeds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = _attempt(tmp_path, cap=1.0)
    _quiet(monkeypatch, [_usage(attempt.job.job_id, 0.9 * 3600)])
    monkeypatch.setattr(
        runner,
        "_expected_limit",
        lambda attempt, name, fixed: (
            600,
            Estimate("preview", 0.2 * 3600, 0.0002, 1000, 3, "NVIDIA A40", "cùng runtime"),
        ),
    )

    with pytest.raises(GpuBudgetExceededError) as error:
        runner._run_tool(attempt, "preview", [sys.executable, "-c", "print('{}')"], 30)

    assert error.value.code == "GPU_BUDGET_EXCEEDED"
    assert "đã dùng 0.90 giờ GPU" in str(error.value) and "vượt mức tối đa 1 giờ" in str(error.value)
    assert not (attempt.workspace / "preview.stdout.json").exists()


def test_cap_stops_a_running_gpu_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempt = _attempt(tmp_path, cap=0.0002)
    _quiet(monkeypatch, [])
    started = time.monotonic()

    with pytest.raises(GpuBudgetExceededError) as error:
        runner._run_tool(attempt, "finalize", [sys.executable, "-c", "import time; time.sleep(30)"], 30)

    assert time.monotonic() - started < 15
    assert "đang chạy" in str(error.value) and "đã dừng" in str(error.value)


def test_budget_failure_is_recorded_as_not_retryable(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path, cap=1.0)

    runner._record_runner_failure(attempt, GpuBudgetExceededError("Scene này đã dùng 1.00 giờ GPU; đã dừng."))

    error = attempt.registry.list_job_attempts(attempt.job.job_id)[-1].error
    assert error is not None
    assert error.error_code == "GPU_BUDGET_EXCEEDED"
    assert error.retryable is False


def test_cap_is_read_from_the_environment_and_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None, openai_api_key="test-key").product_job_gpu_hours_max is None
    monkeypatch.setenv("PRODUCT_JOB_GPU_HOURS_MAX", "2.5")
    assert Settings(_env_file=None, openai_api_key="test-key").product_job_gpu_hours_max == 2.5
