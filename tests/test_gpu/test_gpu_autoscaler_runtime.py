"""T-040 bước 8: autoscaler chỉ bật GPU cho việc máy mới chạy được (quy tắc Q6)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts.cloud.gpu_autoscaler import runnable_waiting
from src.models.contracts.manifests import (
    JobStatus,
    RuntimeComponent,
    RuntimeComponentStatus,
    RuntimeManifest,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile, software_runtime_checksum
from src.services.orchestration.jobs.worker_runtimes import RUNTIME_TTL, live_runtime_checksums, publish

_LIVE = "sha256:" + "1" * 64
_DEAD = "sha256:" + "2" * 64
_NOW = datetime.now(UTC)


def _job(runtime: str, *, stages: bool = False):  # noqa: ANN202
    artifacts = (
        [
            StageArtifact(
                stage_id=StageId.FRAME_EXTRACT,
                status=StageStatus.SUCCEEDED,
                artifact_type="NormalizedRGBFrameSet",
                artifact_uri="artifact://jobs/job-x/rec02a/frame_set.json",
                artifact_checksum="sha256:" + "a" * 64,
                data_class="derived",
                completed_at=_NOW,
            )
        ]
        if stages
        else []
    )
    return SimpleNamespace(
        job_id="job-x",
        status=JobStatus.QUEUED,
        current_stage=StageId.INPUT_VALIDATE,
        runtime_manifest_checksum=runtime,
        stage_artifacts=artifacts,
    )


def test_job_on_a_live_runtime_is_worth_a_gpu() -> None:
    assert runnable_waiting(_job(_LIVE), frozenset({_LIVE}))
    assert runnable_waiting(_job(_LIVE, stages=True), frozenset({_LIVE}))


def test_job_without_stages_is_worth_a_gpu_because_it_can_be_rebound() -> None:
    assert runnable_waiting(_job(_DEAD), frozenset({_LIVE}))
    assert runnable_waiting(_job(_DEAD), frozenset())


def test_job_with_stages_on_a_gone_runtime_is_not_counted() -> None:
    """Cần chạy lại từ đầu do người dùng; bật GPU lúc này không giúp gì."""
    assert not runnable_waiting(_job(_DEAD, stages=True), frozenset({_LIVE}))


def test_live_runtime_checksums_keeps_only_workers_seen_within_the_ttl(tmp_path) -> None:  # noqa: ANN001
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")

    def manifest(colmap: str) -> RuntimeManifest:
        draft = RuntimeManifest(
            schema_version="1.0",
            components={"colmap": RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version=colmap)},
            runtime_manifest_checksum="sha256:" + "0" * 64,
        )
        return with_canonical_checksum(draft, "runtime_manifest_checksum")

    config = "sha256:" + "c" * 64
    live, stale = manifest("3.9.1"), manifest("3.8.0")
    for item, when in ((live, _NOW), (stale, _NOW - RUNTIME_TTL - timedelta(minutes=1))):
        profile = ExecutionProfile(
            config_checksum=config,
            runtime_manifest_checksum=item.runtime_manifest_checksum,
            software_runtime_checksum=software_runtime_checksum(item),
            seed=7,
        )
        publish(database, profile, item, now=when)

    checksums = live_runtime_checksums(database, now=_NOW)

    assert software_runtime_checksum(live) in checksums
    assert live.runtime_manifest_checksum in checksums
    assert software_runtime_checksum(stale) not in checksums
    assert stale.runtime_manifest_checksum not in checksums
