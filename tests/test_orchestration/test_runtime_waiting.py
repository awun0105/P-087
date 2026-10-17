"""T-040 bước 4: job chờ GPU đúng runtime được báo là `waiting_for="runtime"`."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.models.contracts.manifests import JobStatus, RuntimeComponent, RuntimeComponentStatus, RuntimeManifest, StageId
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.profile import ExecutionProfile, software_runtime_checksum
from src.services.orchestration.jobs.progress import job_progress
from src.services.orchestration.jobs.worker_runtimes import has_live_runtime, publish
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry

_T0 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
_NOW = datetime.now(UTC)
_CONFIG = "sha256:" + "c" * 64


def _manifest(gpu: str = "NVIDIA A40") -> RuntimeManifest:
    draft = RuntimeManifest(
        schema_version="1.0",
        components={
            "colmap": RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version="3.9.1"),
            "gpu_model": RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version=gpu),
        },
        runtime_manifest_checksum="sha256:" + "0" * 64,
    )
    return with_canonical_checksum(draft, "runtime_manifest_checksum")


def _profile(manifest: RuntimeManifest) -> ExecutionProfile:
    return ExecutionProfile(
        config_checksum=_CONFIG,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software_runtime_checksum(manifest),
        seed=7,
    )


def _queued_job(root: Path, **update: object):  # noqa: ANN202
    probe = ProjectRegistry(runtime_root=root / "artifacts")
    registry = ProjectRegistry(
        runtime_root=root / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}"),
        execution_profile=ExecutionProfile(
            config_checksum=probe._fixture_config_checksum(),
            runtime_manifest_checksum=probe._fixture_runtime_checksum(),
            seed=7,
        ),
    )
    registry.seed_from_fixtures()
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    return job.model_copy(update={"job_id": "job-r", "started_at": _T0, **update})


def _event(attempt: int, status: JobStatus, stage: StageId, minutes: int) -> JobAttemptRecord:
    return JobAttemptRecord(
        attempt=attempt, status=status, current_stage=stage, recorded_at=_T0 + timedelta(minutes=minutes)
    )


def test_queued_job_without_a_live_runtime_waits_for_gpu(tmp_path: Path) -> None:
    job = _queued_job(tmp_path)
    attempts = [_event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0)]

    assert job_progress(job, attempts, preview_ready=False, runtime_wait=True).waiting_for == "runtime"
    assert job_progress(job, attempts, preview_ready=False, runtime_wait=False).waiting_for is None


def test_running_job_is_not_reported_as_waiting_for_runtime(tmp_path: Path) -> None:
    job = _queued_job(tmp_path, status=JobStatus.RUNNING, current_stage=StageId.FRAME_EXTRACT)
    attempts = [
        _event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, 0),
        _event(1, JobStatus.RUNNING, StageId.FRAME_EXTRACT, 1),
    ]

    assert job_progress(job, attempts, preview_ready=False, runtime_wait=True).waiting_for is None


def test_human_waits_keep_precedence_over_runtime(tmp_path: Path) -> None:
    job = _queued_job(tmp_path, status=JobStatus.RUNNING, current_stage=StageId.METRIC_CANONICALIZE)
    attempts = [_event(1, JobStatus.RUNNING, StageId.METRIC_CANONICALIZE, 9)]

    progress = job_progress(job, attempts, preview_ready=True, runtime_wait=True)

    assert progress.waiting_for == "metric_confirmation"


def test_has_live_runtime_matches_software_and_legacy_full_checksum(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    manifest = _manifest()
    publish(database, _profile(manifest), manifest)

    assert has_live_runtime(database, software_runtime_checksum(manifest))
    assert has_live_runtime(database, manifest.runtime_manifest_checksum)
    assert not has_live_runtime(database, "sha256:" + "e" * 64)


def test_has_live_runtime_ignores_a_worker_that_went_away(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    manifest = _manifest()
    publish(database, _profile(manifest), manifest, now=_NOW - timedelta(hours=2))

    assert not has_live_runtime(database, software_runtime_checksum(manifest))
