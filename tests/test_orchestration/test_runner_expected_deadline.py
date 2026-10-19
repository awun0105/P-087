"""T-043 bước 4 (nối vào runner): hạn tự tính của một công cụ, thông báo khi vượt, và rơi về giới hạn cố định."""

import sys
import time
from pathlib import Path

import pytest

from src.config import Settings
from src.models.contracts.manifests import JobStatus
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.processing.expected_duration import Estimate
from src.services.orchestration.projects.models import JobCreateInput
from tests.test_orchestration.test_prepared_queue import _registry

_ESTIMATE = Estimate(
    tool="preview",
    seconds=0.1,
    seconds_per_unit=0.0001,
    units=1000,
    samples=3,
    gpu_name="NVIDIA A40",
    scope="cùng runtime",
)


def _attempt(tmp_path: Path) -> runner._Attempt:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    job = registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    settings = Settings(_env_file=None, openai_api_key="test-key")
    return runner._Attempt(registry, settings, job, workspace)


def test_tool_is_stopped_at_its_expected_deadline_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = _attempt(tmp_path)
    monkeypatch.setattr(runner, "_resource_sampler", lambda attempt, tool: None)
    monkeypatch.setattr(runner, "_expected_limit", lambda attempt, name, fixed: (0.5, _ESTIMATE))
    started = time.monotonic()

    with pytest.raises(runner.ExpectedDurationError) as error:
        runner._run_tool(attempt, "preview", [sys.executable, "-c", "import time; time.sleep(30)"], 30)

    assert time.monotonic() - started < 15
    assert error.value.code == "EXPECTED_DURATION_EXCEEDED"
    message = str(error.value)
    assert "chạy quá" in message and "NVIDIA A40" in message and "gấp" in message and "đã dừng" in message
    record = (attempt.workspace / "preview.expected.json").read_text(encoding="utf-8")
    assert '"deadline_seconds": 0.5' in record and '"samples": 3' in record


def test_without_an_estimate_the_plain_timeout_message_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempt = _attempt(tmp_path)
    monkeypatch.setattr(runner, "_resource_sampler", lambda attempt, tool: None)
    monkeypatch.setattr(runner, "_expected_limit", lambda attempt, name, fixed: (0.5, None))

    with pytest.raises(TimeoutError) as error:
        runner._run_tool(attempt, "preview", [sys.executable, "-c", "import time; time.sleep(30)"], 30)

    assert not isinstance(error.value, runner.ExpectedDurationError)
    assert str(error.value) == "preview worker quá thời gian cấu hình"


def test_expected_duration_failure_is_recorded_with_its_own_retryable_code(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)

    runner._record_runner_failure(attempt, runner.ExpectedDurationError("preview chạy quá 40 phút; đã dừng."))

    failed = attempt.registry.get_job(attempt.job.job_id)
    assert failed.status == JobStatus.FAILED
    error = attempt.registry.list_job_attempts(attempt.job.job_id)[-1].error
    assert error is not None
    assert error.error_code == "EXPECTED_DURATION_EXCEEDED"
    assert error.retryable is True
    assert error.human_message == "preview chạy quá 40 phút; đã dừng."


def test_expected_limit_falls_back_to_the_fixed_limit_without_measurements(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)

    limit, estimate = runner._expected_limit(attempt, "preview", 1800)

    assert limit == 1800
    assert estimate is None
