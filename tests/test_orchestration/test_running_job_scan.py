"""Startup and sweeper scans must run on PostgreSQL, not only SQLite (json_extract is SQLite-only)."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.worker_cli import latest_running_job_ids


def _databases(tmp_path: Path) -> list[RuntimeDatabase]:
    found = [RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")]
    url = os.environ.get("R2S_GPU_TEST_DATABASE_URL")
    if url:
        parsed = urlsplit(url)
        assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.path == "/r2s_gpu_test"
        found.append(RuntimeDatabase(url))
    return found


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_latest_running_job_ids_reads_only_the_newest_event(tmp_path: Path, backend: str) -> None:
    databases = {"sqlite": 0, "postgres": 1}
    candidates = _databases(tmp_path)
    if databases[backend] >= len(candidates):
        pytest.skip("R2S_GPU_TEST_DATABASE_URL is not configured")
    database = candidates[databases[backend]]
    events = [
        ("scan-a", 1, "QUEUED"),
        ("scan-a", 2, "RUNNING"),
        ("scan-b", 1, "RUNNING"),
        ("scan-b", 2, "SUCCEEDED"),
        ("scan-c", 1, "RUNNING"),
    ]
    with database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_job_events WHERE job_id LIKE ?", ("scan-%",))
        tx.execute("DELETE FROM r2s_jobs WHERE job_id LIKE ?", ("scan-%",))
        tx.execute("DELETE FROM r2s_projects WHERE project_id = 'scan-project'")
        tx.execute("INSERT INTO r2s_projects(project_id, payload) VALUES ('scan-project', '{}')")
        for job_id in ("scan-a", "scan-b", "scan-c"):
            tx.execute(
                "INSERT INTO r2s_jobs(job_id, project_id, version, manifest_ref) VALUES (?, 'scan-project', 1, '{}')",
                (job_id,),
            )
        for job_id, version, status in events:
            tx.execute(
                "INSERT INTO r2s_job_events(job_id, version, payload) VALUES (?, ?, ?)",
                (job_id, version, json.dumps({"status": status})),
            )
    with database.transaction() as tx:
        running = sorted(job for job in latest_running_job_ids(tx) if job.startswith("scan-"))
    assert running == ["scan-a", "scan-c"]
