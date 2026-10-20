"""T-056: recorded step marks, derived from each committed job revision."""

from datetime import timedelta
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobStatus, StageArtifact, StageId
from src.services.orchestration.jobs.step_marks import MarkWrite, marks_for_revision
from tests.test_orchestration.test_pipeline_timing import _T0, _event, _registry, _stage


@pytest.fixture
def job(tmp_path: Path):  # noqa: ANN201
    registry, job_id = _registry(tmp_path)
    return registry.get_job(job_id)


def _artifact(
    stage: StageId, artifact_type: str, uri: str, completed_minutes: int, status: str = "SUCCEEDED"
) -> StageArtifact:
    return StageArtifact(
        stage_id=stage,
        status=status,
        artifact_type=artifact_type,
        artifact_uri=uri,
        artifact_checksum="sha256:" + "b" * 64,
        data_class="derived",
        started_at=None,
        completed_at=_T0 + timedelta(minutes=completed_minutes),
    )


def test_claim_starts_current_stage(job) -> None:  # noqa: ANN001
    current = job.model_copy(update={"status": JobStatus.RUNNING, "current_stage": StageId.INPUT_VALIDATE})
    writes = marks_for_revision(job, current, _event(1, JobStatus.RUNNING, StageId.INPUT_VALIDATE, _T0))
    assert writes == [MarkWrite("start", StageId.INPUT_VALIDATE.value, _T0)]


def test_stage_change_starts_new_stage_with_worker_time(job) -> None:  # noqa: ANN001
    previous = job.model_copy(update={"status": JobStatus.RUNNING, "current_stage": StageId.FRAME_EXTRACT})
    current = previous.model_copy(update={"current_stage": StageId.CAMERA_POSE})
    worker_time = _T0 + timedelta(minutes=4)
    event = _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, _T0 + timedelta(minutes=5)).model_copy(
        update={"stage_started_at": worker_time}
    )
    assert MarkWrite("start", StageId.CAMERA_POSE.value, worker_time) in marks_for_revision(previous, current, event)


def test_new_succeeded_artifact_finishes_stage(job) -> None:  # noqa: ANN001
    previous = job.model_copy(update={"status": JobStatus.RUNNING, "current_stage": StageId.CAMERA_POSE})
    stage = _stage(StageId.CAMERA_POSE, _T0 + timedelta(minutes=1), _T0 + timedelta(minutes=9))
    current = previous.model_copy(update={"stage_artifacts": [stage]})
    writes = marks_for_revision(previous, current, _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, _T0))
    assert MarkWrite("start", StageId.CAMERA_POSE.value, stage.started_at) in writes
    assert MarkWrite("finish", StageId.CAMERA_POSE.value, stage.completed_at, "succeeded") in writes


def test_existing_artifact_is_not_written_again(job) -> None:  # noqa: ANN001
    stage = _stage(StageId.CAMERA_POSE, _T0, _T0 + timedelta(minutes=9))
    previous = job.model_copy(
        update={"status": JobStatus.RUNNING, "current_stage": StageId.CAMERA_POSE, "stage_artifacts": [stage]}
    )
    assert marks_for_revision(previous, previous, _event(1, JobStatus.RUNNING, StageId.CAMERA_POSE, _T0)) == []


def test_sanitization_acceptance_finishes_anonymization_review(job) -> None:  # noqa: ANN001
    frames = _artifact(
        StageId.FRAME_EXTRACT, "NormalizedRGBFrameSet", "artifact://jobs/x/rec02a/sanitized/frame_set.json", 3
    )
    previous = job.model_copy(
        update={"status": JobStatus.RUNNING, "current_stage": StageId.FRAME_EXTRACT, "stage_artifacts": [frames]}
    )
    accepted = _artifact(StageId.PRIVACY_GATE, "SanitizationAcceptance", "artifact://jobs/x/acceptance.json", 20)
    current = previous.model_copy(update={"stage_artifacts": [frames, accepted]})
    writes = marks_for_revision(previous, current, _event(1, JobStatus.RUNNING, StageId.FRAME_EXTRACT, _T0))
    assert MarkWrite("finish", StageId.ANONYMIZATION_REVIEW.value, accepted.completed_at, "succeeded") in writes
    assert all(write.step_id != StageId.PRIVACY_GATE.value for write in writes)


def test_entering_anonymization_wait_starts_review_at_frame_completion(job) -> None:  # noqa: ANN001
    previous = job.model_copy(update={"status": JobStatus.RUNNING, "current_stage": StageId.FRAME_EXTRACT})
    frames = _artifact(
        StageId.FRAME_EXTRACT, "NormalizedRGBFrameSet", "artifact://jobs/x/rec02a/sanitized/frame_set.json", 3
    )
    current = previous.model_copy(update={"stage_artifacts": [frames]})
    writes = marks_for_revision(previous, current, _event(1, JobStatus.RUNNING, StageId.FRAME_EXTRACT, _T0))
    assert MarkWrite("start", StageId.ANONYMIZATION_REVIEW.value, frames.completed_at) in writes


def test_metric_wait_starts_when_stage_becomes_metric(job) -> None:  # noqa: ANN001
    previous = job.model_copy(update={"status": JobStatus.RUNNING, "current_stage": StageId.VISUAL_RECON})
    current = previous.model_copy(update={"current_stage": StageId.METRIC_CANONICALIZE})
    at = _T0 + timedelta(minutes=30)
    writes = marks_for_revision(previous, current, _event(1, JobStatus.RUNNING, StageId.METRIC_CANONICALIZE, at))
    assert MarkWrite("start", StageId.METRIC_CANONICALIZE.value, at) in writes


def test_failed_revision_closes_open_marks(job) -> None:  # noqa: ANN001
    previous = job.model_copy(update={"status": JobStatus.RUNNING, "current_stage": StageId.CAMERA_POSE})
    current = previous.model_copy(update={"status": JobStatus.FAILED})
    at = _T0 + timedelta(minutes=12)
    writes = marks_for_revision(previous, current, _event(1, JobStatus.FAILED, StageId.CAMERA_POSE, at))
    assert writes == [MarkWrite("close", None, at, "failed")]


# ── storage ──────────────────────────────────────────────────────────────────


def _db(tmp_path: Path):  # noqa: ANN202
    from src.services.orchestration.jobs.database import RuntimeDatabase

    return RuntimeDatabase(f"sqlite:///{tmp_path / 'marks.db'}")


def test_start_keeps_earliest_time(tmp_path: Path) -> None:
    from src.services.orchestration.jobs.step_marks import list_marks, record_marks

    database = _db(tmp_path)
    record_marks(database, "job-a", "pipeline", "1", [MarkWrite("start", "ST-CAMERA-POSE", _T0)])
    record_marks(database, "job-a", "pipeline", "1", [MarkWrite("start", "ST-CAMERA-POSE", _T0 + timedelta(minutes=2))])
    (mark,) = list_marks(database, "job-a")
    assert mark.started_at == _T0


def test_finish_keeps_first_completion(tmp_path: Path) -> None:
    from src.services.orchestration.jobs.step_marks import list_marks, record_marks

    database = _db(tmp_path)
    first = _T0 + timedelta(minutes=5)
    record_marks(database, "job-a", "pipeline", "1", [MarkWrite("finish", "ST-METRIC-CANONICALIZE", first, "succeeded")])
    record_marks(
        database, "job-a", "pipeline", "1", [MarkWrite("finish", "ST-METRIC-CANONICALIZE", first + timedelta(hours=1), "failed")]
    )
    (mark,) = list_marks(database, "job-a")
    assert (mark.completed_at, mark.outcome) == (first, "succeeded")


def test_close_only_touches_open_started_marks(tmp_path: Path) -> None:
    from src.services.orchestration.jobs.step_marks import list_marks, record_marks

    database = _db(tmp_path)
    done = _T0 + timedelta(minutes=3)
    record_marks(
        database,
        "job-a",
        "pipeline",
        "1",
        [
            MarkWrite("start", "ST-FRAME-EXTRACT", _T0),
            MarkWrite("finish", "ST-FRAME-EXTRACT", done, "succeeded"),
            MarkWrite("start", "ST-CAMERA-POSE", done),
            MarkWrite("close", None, _T0 + timedelta(minutes=9), "failed"),
        ],
    )
    marks = {mark.step_id: mark for mark in list_marks(database, "job-a")}
    assert marks["ST-FRAME-EXTRACT"].outcome == "succeeded"
    assert marks["ST-CAMERA-POSE"].outcome == "failed"


def test_record_marks_logs_and_swallows_database_errors(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from src.services.orchestration.jobs.step_marks import record_marks

    class Broken:
        def transaction(self, write: bool = False):  # noqa: ANN202
            raise RuntimeError("db down")

    record_marks(Broken(), "job-a", "pipeline", "1", [MarkWrite("start", "x", _T0)])  # type: ignore[arg-type]
    assert "job-a" in caplog.text
