"""T-049: a brief database outage while a tool runs must not kill the tool."""

import sqlite3
import sys
from pathlib import Path

import pytest

from src.models.contracts.retryability import classify_retryability
from src.services.orchestration.jobs import runner
from tests.test_orchestration.test_runner_expected_deadline import _attempt


def test_run_tool_survives_one_get_job_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempt = _attempt(tmp_path)
    monkeypatch.setattr(runner, "_resource_sampler", lambda attempt, tool: None)
    monkeypatch.setattr(runner, "_expected_limit", lambda attempt, name, fixed: (fixed, None))
    real_get_job = attempt.registry.get_job
    calls = {"n": 0}

    def flaky(job_id: str):  # noqa: ANN202
        calls["n"] += 1
        if calls["n"] == 2:
            raise sqlite3.OperationalError("database is locked")
        return real_get_job(job_id)

    monkeypatch.setattr(attempt.registry, "get_job", flaky)
    code, payload = runner._run_tool(
        attempt, "preview", [sys.executable, "-c", "import time; time.sleep(3); print('{}')"], 30
    )
    assert code == 0 and payload == {}
    assert calls["n"] >= 3


def test_persistent_database_errors_are_retryable_failures() -> None:
    assert classify_retryability("PREVIEW_RUNNER_FAILED", {"exception_type": "OperationalError"}) is True
    assert classify_retryability("PREVIEW_RUNNER_FAILED", {"exception_type": "InterfaceError"}) is True
