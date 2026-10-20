"""T-048: a failure right after the runner claims a job must be recorded, not leave the job RUNNING."""

from pathlib import Path

import pytest

from src.config import Settings
from src.services.orchestration.jobs import runner
from tests.test_orchestration.test_worker_cleanup import _confirmed


def test_finalize_failure_right_after_claim_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, confirmation = _confirmed(tmp_path / "runtime")
    settings = Settings(product_worker_root=tmp_path / "workers")
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_project_registry", lambda: registry)
    monkeypatch.setattr(runner, "_authorized_decision", lambda *args: (confirmation, "sha256:" + "a" * 64))

    def broken(*args: object) -> str:
        raise OSError("disk unavailable")

    monkeypatch.setattr(runner, "_attempt_log_id", broken)

    with pytest.raises(OSError):
        runner.run_finalize_job(job.job_id)

    after = registry.get_job(job.job_id)
    assert after.status == runner.JobStatus.FAILED
    error = registry.list_job_attempts(job.job_id)[-1].error
    assert error is not None and error.stage_id == runner.StageId.RGB_GEOMETRY
