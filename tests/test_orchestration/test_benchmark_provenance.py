"""Runtime benchmarks retain the executing worker and compatible legacy telemetry."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import Settings
from src.services.orchestration import benchmark
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.profile import ExecutionProfile, software_runtime_checksum
from src.services.orchestration.processing.capability import record
from src.services.orchestration.processing.models import MachineCapability
from src.services.orchestration.projects.models import JobCreateInput
from tests.test_orchestration.test_machine_runtime_provenance import _manifest, _usage
from tests.test_orchestration.test_prepared_queue import _registry


@pytest.mark.parametrize("probe_fails", [False, True])
def test_snapshot_never_uses_another_workers_newer_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe_fails: bool
) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    now = datetime.now(UTC)
    own = MachineCapability(
        worker_id="worker-A",
        measured_at=now - timedelta(seconds=1),
        gpu_name="T4",
        cpu_count=4,
        ram_total_gb=16,
        disk_free_gb=20,
    )
    other = own.model_copy(update={"worker_id": "worker-B", "measured_at": now, "gpu_name": "A40"})
    record(registry.persistence.database, own)
    record(registry.persistence.database, other)
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        product_worker_root=tmp_path / "workers",
    )
    probe = Mock(side_effect=OSError("probe unavailable")) if probe_fails else Mock(return_value=own)
    monkeypatch.setattr(runner, "probe_capability", probe, raising=False)
    build = Mock(return_value=object())
    monkeypatch.setattr(runner, "build_benchmark", build)
    monkeypatch.setattr(runner, "publish_benchmark", Mock())

    runner._record_benchmark(runner._Attempt(registry, settings, job, tmp_path))

    assert build.call_count == 1
    assert build.call_args.kwargs["machine"] == (None if probe_fails else own)
    probe.assert_called_once_with(settings.product_worker_root)


@pytest.mark.parametrize("legacy", [True, False])
def test_timings_accept_the_worker_software_runtime_without_accepting_unrelated_records(
    monkeypatch: pytest.MonkeyPatch, legacy: bool
) -> None:
    manifest = _manifest("3.9.1")
    software = software_runtime_checksum(manifest)
    profile = ExecutionProfile(
        config_checksum="sha256:" + "c" * 64,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software,
    )
    runtime = manifest.runtime_manifest_checksum if legacy else software
    usage = _usage(software)
    variants = [
        usage,
        usage.model_copy(update={"runtime_manifest_checksum": "sha256:" + "b" * 64}),
        usage.model_copy(update={"config_checksum": "sha256:" + "a" * 64}),
        usage.model_copy(update={"job_id": "another-job"}),
        usage.model_copy(update={"started_at": usage.started_at - timedelta(days=2)}),
        usage.model_copy(update={"completed_at": usage.completed_at + timedelta(days=2)}),
    ]
    monkeypatch.setattr(benchmark, "load_usages", lambda database: variants)
    registry = SimpleNamespace(persistence=SimpleNamespace(database=None), execution_profile=profile)
    timings = benchmark._tool_timings(
        registry,
        usage.job_id,
        usage.config_checksum,
        runtime,
        usage.started_at - timedelta(seconds=1),
        None,
        usage.completed_at + timedelta(seconds=1),
    )
    assert len(timings) == 1
    assert timings[0].duration_seconds == usage.duration_seconds


def test_incompatible_worker_profile_does_not_authorize_its_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest("3.9.1")
    profile = ExecutionProfile(
        config_checksum="sha256:" + "c" * 64,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software_runtime_checksum(manifest),
    )
    usage = _usage(profile.job_runtime_checksum)
    monkeypatch.setattr(benchmark, "load_usages", lambda database: [usage])
    registry = SimpleNamespace(persistence=SimpleNamespace(database=None), execution_profile=profile)
    assert (
        benchmark._tool_timings(
            registry,
            usage.job_id,
            usage.config_checksum,
            "sha256:" + "f" * 64,
            usage.started_at - timedelta(seconds=1),
            None,
            usage.completed_at + timedelta(seconds=1),
        )
        == []
    )
