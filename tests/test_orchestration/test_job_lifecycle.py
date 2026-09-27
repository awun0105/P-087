"""Unit tests for job lifecycle persistence and attempt history (PRODUCT-02).

Covers the DoD items that the pure transition table cannot:
- Only legal transitions persist (revision is written after validation).
- SUCCEEDED requires resolvable artifacts/checksums.
- Retry appends attempt history and never overwrites prior provenance.
"""

from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactRef
from src.models.contracts.manifests import JobStatus, StageId
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs import (
    InvalidTransitionError,
    JobArtifactStore,
    JobNotResolvableError,
    TransitionRequest,
)
from src.services.orchestration.projects.errors import JobNotFoundError
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures"
_FIXTURE_JOB_ID = "job-fixture-001"


@pytest.fixture
def registry(tmp_path) -> ProjectRegistry:
    """Registry seeded from fixtures, writing revisions into tmp_path."""
    instance = ProjectRegistry(_FIXTURE_ROOT, runtime_root=tmp_path / "artifacts")
    instance.seed_from_fixtures()
    return instance


@pytest.fixture
def running_job(registry: ProjectRegistry) -> str:
    """A fresh job moved to RUNNING."""
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    return job.job_id


# ── only legal transitions persist ───────────────────────────────────────────


def test_illegal_transition_does_not_persist(registry: ProjectRegistry) -> None:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    before = registry.get_job(job.job_id)
    with pytest.raises(InvalidTransitionError):
        registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.SUCCEEDED))
    assert registry.get_job(job.job_id) == before
    assert len(registry.list_job_attempts(job.job_id)) == 1


def test_legal_transition_persists_revision(registry: ProjectRegistry, running_job: str) -> None:
    job = registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.FAILED))
    assert job.status == JobStatus.FAILED
    assert job.completed_at is not None


def test_transition_records_a_manifest_revision(registry: ProjectRegistry, running_job: str) -> None:
    registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.FAILED))
    attempts = registry.list_job_attempts(running_job)
    assert attempts[-1].job_manifest_uri is not None
    assert attempts[-1].job_manifest_checksum is not None


def test_published_revision_is_readable_and_verifies(registry: ProjectRegistry, running_job: str) -> None:
    """Revision đã publish phải đọc lại được và khớp checksum byte."""
    registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.FAILED))
    attempt = registry.list_job_attempts(running_job)[-1]
    reference = ArtifactRef(
        artifact_type="JobManifest",
        schema_version="1.0",
        artifact_uri=attempt.job_manifest_uri,
        artifact_checksum=attempt.job_manifest_checksum,
        data_class="derived",
        producer_stage=attempt.current_stage,
        job_id=running_job,
    )
    loaded = JobArtifactStore(registry.lifecycle.resolver).load_manifest(reference)
    assert loaded.status == JobStatus.FAILED
    assert loaded.job_id == running_job


def test_revision_paths_are_distinct_per_transition(registry: ProjectRegistry, running_job: str) -> None:
    registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.FAILED))
    registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.QUEUED))
    uris = [attempt.job_manifest_uri for attempt in registry.list_job_attempts(running_job)]
    assert len(set(uris)) == len(uris), "mỗi revision phải ở URI riêng"


def test_started_at_is_never_overwritten(registry: ProjectRegistry, running_job: str) -> None:
    original = registry.get_job(running_job).started_at
    registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.CANCELLED))
    assert registry.get_job(running_job).started_at == original


def test_current_stage_can_advance(registry: ProjectRegistry, running_job: str) -> None:
    job = registry.transition_job(
        running_job,
        TransitionRequest(target_status=JobStatus.FAILED, current_stage=StageId.FRAME_EXTRACT),
    )
    assert job.current_stage == StageId.FRAME_EXTRACT


# ── SUCCEEDED requires resolvable artifacts ──────────────────────────────────


def test_succeeded_blocked_without_published_artifacts(registry: ProjectRegistry, running_job: str) -> None:
    """Không được ghi SUCCEEDED khi job chưa có artifact đầu ra nào."""
    with pytest.raises(JobNotResolvableError, match="chưa có artifact"):
        registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.SUCCEEDED))


def test_succeeded_allowed_when_artifacts_resolve(registry: ProjectRegistry) -> None:
    """Job mang artifact của fixture (resolve được, checksum khớp) mới qua được gate."""
    fixture_job = registry.get_job(_FIXTURE_JOB_ID)
    assert fixture_job.stage_artifacts, "fixture job phải có artifact để test này có nghĩa"
    in_flight = fixture_job.model_copy(update={"status": JobStatus.RUNNING, "completed_at": None})

    registry.lifecycle.require_artifacts_resolvable(in_flight)  # must not raise
    for stage in in_flight.stage_artifacts:
        assert (
            ArtifactResolver(_FIXTURE_ROOT / "artifact_store")
            .require(
                ArtifactRef(
                    artifact_type=stage.artifact_type or "unknown",
                    schema_version="1.0",
                    artifact_uri=stage.artifact_uri,
                    artifact_checksum=stage.artifact_checksum,
                    data_class=stage.data_class,
                    producer_stage=stage.stage_id,
                    job_id=_FIXTURE_JOB_ID,
                )
            )
            .is_file()
        )


def test_succeeded_blocked_when_artifact_checksum_is_wrong(registry: ProjectRegistry) -> None:
    """SUCCEEDED fail-closed nếu checksum artifact không khớp byte trên đĩa."""
    fixture_job = registry.get_job(_FIXTURE_JOB_ID)
    broken_stage = fixture_job.stage_artifacts[0].model_copy(
        update={"artifact_checksum": "sha256:" + "f" * 64},
    )
    tampered = fixture_job.model_copy(update={"stage_artifacts": [broken_stage]})

    with pytest.raises(JobNotResolvableError, match="không resolve được"):
        registry.lifecycle.require_artifacts_resolvable(tampered)


# ── retry appends, never overwrites ──────────────────────────────────────────


def test_retry_appends_attempt_and_keeps_history(registry: ProjectRegistry, running_job: str) -> None:
    registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.FAILED))
    before = registry.list_job_attempts(running_job)
    registry.transition_job(running_job, TransitionRequest(target_status=JobStatus.QUEUED))
    after = registry.list_job_attempts(running_job)

    assert after[: len(before)] == before, "attempt cũ không được sửa"
    assert len(after) == len(before) + 1


def test_retry_increments_attempt_number_only_on_retry(registry: ProjectRegistry) -> None:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.FAILED))
    numbers_before = [attempt.attempt for attempt in registry.list_job_attempts(job.job_id)]
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.QUEUED))
    numbers_after = [attempt.attempt for attempt in registry.list_job_attempts(job.job_id)]

    assert numbers_before == [1, 1, 1], "đổi trạng thái trong cùng một lần chạy không tăng số attempt"
    assert numbers_after[-1] == 2, "retry mở lần chạy mới"


def test_fixture_job_has_a_seeded_attempt(registry: ProjectRegistry) -> None:
    attempts = registry.list_job_attempts(_FIXTURE_JOB_ID)
    assert len(attempts) == 1
    assert attempts[0].status == JobStatus.SUCCEEDED


def test_attempts_for_missing_job_raises(registry: ProjectRegistry) -> None:
    with pytest.raises(JobNotFoundError):
        registry.list_job_attempts("no-such-job")


def test_failed_transition_carries_structured_error(registry: ProjectRegistry, running_job: str) -> None:
    error = {
        "error_code": "WORKER_CRASH",
        "stage_id": "ST-FRAME-EXTRACT",
        "human_message": "worker dừng bất ngờ",
        "retryable": True,
    }
    registry.transition_job(
        running_job,
        TransitionRequest(target_status=JobStatus.FAILED, error=error),
    )
    assert registry.list_job_attempts(running_job)[-1].error.error_code == "WORKER_CRASH"
