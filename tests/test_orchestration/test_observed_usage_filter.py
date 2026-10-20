"""T-054: the scene list reads only the usage rows of the jobs it shows."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing.observed import load_usages, processing_seconds
from src.services.orchestration.processing.telemetry import ResourceUsage
from src.services.orchestration.processing.usage_recording import record_usage

_T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def _usage(job_id: str, tool: str, minutes: int, outcome: str = "completed") -> ResourceUsage:
    return ResourceUsage(
        job_id=job_id,
        attempt_id="a",
        tool=tool,
        config_checksum="sha256:" + "1" * 64,
        runtime_manifest_checksum="sha256:" + "2" * 64,
        started_at=_T0,
        completed_at=_T0 + timedelta(minutes=minutes),
        outcome=outcome,
        exit_code=0,
        duration_seconds=minutes * 60.0,
        sample_count=0,
        ram_sample_count=0,
        vram_sample_count=0,
        gpu_sample_count=0,
        scratch_sample_count=0,
        headroom_before={},
    )


def test_filtered_usages_give_the_same_processing_time(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    for usage in (
        _usage("job-a", "preview", 10),
        _usage("job-a", "preview", 12),
        _usage("job-a", "scene.geometry", 3),
        _usage("job-a", "scene.geometry", 4),
        _usage("job-a", "finalize", 5, "failed"),
        _usage("job-b", "preview", 30),
    ):
        record_usage(database, usage)
    everything = processing_seconds(load_usages(database))
    only_a = load_usages(database, job_ids=["job-a"])
    assert {usage.job_id for usage in only_a} == {"job-a"}
    assert processing_seconds(only_a) == {"job-a": everything["job-a"]}
    assert load_usages(database, job_ids=[]) == []
