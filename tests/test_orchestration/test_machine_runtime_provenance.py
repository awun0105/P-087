"""T-040 bước 7: số đo ghi runtime thật của máy đã chạy job, không phải checksum của job."""

from datetime import UTC, datetime
from pathlib import Path

from src.config import Settings
from src.models.contracts.manifests import RuntimeComponent, RuntimeComponentStatus, RuntimeManifest
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.profile import (
    ExecutionProfile,
    machine_runtime_checksum,
    software_runtime_checksum,
)
from src.services.orchestration.processing.observed import observed_budget
from src.services.orchestration.processing.telemetry import ResourceUsage
from tests.test_orchestration.test_prepared_queue import _registry

_NOW = datetime(2026, 10, 2, tzinfo=UTC)
_JOB = {"frames": 60.0, "splats": 500000.0}


def _manifest(colmap: str) -> RuntimeManifest:
    draft = RuntimeManifest(
        schema_version="1.0",
        components={
            "colmap": RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version=colmap),
            "gpu_model": RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version="NVIDIA A40"),
        },
        runtime_manifest_checksum="sha256:" + "0" * 64,
    )
    return with_canonical_checksum(draft, "runtime_manifest_checksum")


def _usage(runtime: str) -> ResourceUsage:
    return ResourceUsage(
        job_id="job-a",
        attempt_id="attempt-a",
        tool="preview",
        config_checksum="c",
        runtime_manifest_checksum=runtime,
        params=_JOB,
        gpu_name="T4",
        shared_gpu=False,
        started_at=_NOW,
        completed_at=_NOW,
        outcome="completed",
        exit_code=0,
        duration_seconds=1.0,
        sample_count=1,
        ram_sample_count=1,
        vram_sample_count=1,
        gpu_sample_count=1,
        scratch_sample_count=1,
        peak_ram_gb=2.0,
        peak_vram_gb=1.0,
        headroom_before={},
    )


def test_machine_runtime_is_the_worker_software_runtime_even_for_a_legacy_job() -> None:
    manifest = _manifest("3.9.1")
    assert software_runtime_checksum(manifest) != manifest.runtime_manifest_checksum  # GPU nằm ngoài khoá phần mềm
    profile = ExecutionProfile(
        config_checksum="sha256:" + "c" * 64,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software_runtime_checksum(manifest),
        seed=7,
    )

    assert machine_runtime_checksum(profile, manifest.runtime_manifest_checksum) == software_runtime_checksum(manifest)
    assert machine_runtime_checksum(None, "sha256:" + "d" * 64) == "sha256:" + "d" * 64


def test_budget_is_attributed_to_the_machine_that_ran_the_job() -> None:
    manifest = _manifest("3.9.1")
    software = software_runtime_checksum(manifest)
    usages = [_usage(software)]

    def budget(runtime: str):  # noqa: ANN202
        return observed_budget(
            usages, tools=("preview",), params=_JOB, gpu_name="T4", runtime_manifest_checksum=runtime
        )

    assert budget(software) is not None
    assert budget(manifest.runtime_manifest_checksum) is None


def test_runner_sampler_records_the_worker_runtime_not_the_job_checksum(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    registry = _registry(tmp_path)
    manifest = _manifest("3.9.1")
    worker_profile = ExecutionProfile(
        config_checksum=registry.execution_profile.config_checksum,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software_runtime_checksum(manifest),
        seed=7,
    )
    registry.execution_profile = worker_profile
    job = registry.create_job(_job_input())
    legacy = job.model_copy(update={"runtime_manifest_checksum": manifest.runtime_manifest_checksum})
    captured: list = []
    monkeypatch.setattr(runner, "build_sampler", lambda settings, context, workspace: captured.append(context))
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    attempt = runner._Attempt(registry, Settings(_env_file=None, openai_api_key="test-key"), legacy, workspace)

    runner._resource_sampler(attempt, "preview")

    assert captured[0].runtime_manifest_checksum == software_runtime_checksum(manifest)


def _job_input():  # noqa: ANN202
    from src.services.orchestration.projects.models import JobCreateInput

    return JobCreateInput(project_id="project-fixture-001")


def test_objectify_sampler_records_the_worker_runtime_not_the_job_checksum(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from src.services.orchestration.scene import objectify_queue

    registry = _registry(tmp_path)
    manifest = _manifest("3.9.1")
    registry.execution_profile = ExecutionProfile(
        config_checksum=registry.execution_profile.config_checksum,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software_runtime_checksum(manifest),
        seed=7,
    )
    job = registry.create_job(_job_input()).model_copy(
        update={"runtime_manifest_checksum": manifest.runtime_manifest_checksum}
    )
    admission = SimpleNamespace(registry=registry, shares_gpu=lambda: False)
    captured: list = []
    monkeypatch.setattr(objectify_queue, "build_sampler", lambda settings, context, workspace: captured.append(context))

    objectify_queue._scene_sampler(
        Settings(_env_file=None, openai_api_key="test-key"),
        admission,
        job,
        "geometry",
        "op-1",
        job.config_checksum,
        tmp_path / "scene",
    )

    assert captured[0].runtime_manifest_checksum == software_runtime_checksum(manifest)
