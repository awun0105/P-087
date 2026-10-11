"""AUD-18: job chọn che frame dừng trước COLMAP cho tới khi người dùng chấp nhận bản đã che."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import JobStatus, StageArtifact, StageId, StageStatus
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes, with_canonical_checksum
from src.services.orchestration.jobs.anonymization_review import (
    AnonymizationReviewError,
    SanitizationAcceptance,
    accept,
    accept_when_nothing_redacted,
    redacted_frame,
    review,
)
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.models import JobAttemptRecord, TransitionRequest
from src.services.orchestration.jobs.progress import (
    ANONYMIZATION_ACCEPTANCE_TYPE,
    awaiting_anonymization_review,
    awaiting_reviewed_preview,
    job_progress,
)
from src.services.orchestration.jobs.queue import waiting_jobs
from src.services.orchestration.jobs.worker_cli import dispatch_next, recover_interrupted_jobs
from src.services.orchestration.projects.models import JobCreateInput
from tests.test_orchestration.test_job_progress import _registry
from tests.test_reconstruction.test_frame_sanitization import REDACTED, _fake_anonymizer, _setup


def _publish(registry, job_id: str, path: str, artifact_type: str, stage: StageId) -> ProductArtifactRef:  # noqa: ANN001
    payload = f'{{"path": "{path}"}}'.encode()
    reference = ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/{path}",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=stage,
        job_id=job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)
    return reference


def _after_prepare(root: Path, *, sanitized: bool = True, prepare=None):  # noqa: ANN001, ANN202
    """Job RUNNING ngay sau bước tách frame, với frame set đã che (hoặc frame set thường).

    `prepare(job_id)` trả ref của một frame set thật; không truyền thì dùng một artifact giữ chỗ.
    """
    registry = _registry(root)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    job = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.RUNNING), expected_checksum=job.job_manifest_checksum
    )
    job = registry.record_stage_progress(job, StageId.FRAME_EXTRACT)
    path = "rec02a/sanitized/frame_set.json" if sanitized else "rec02a/frame_set.json"
    frames = (
        prepare(job.job_id)
        if prepare is not None
        else _publish(registry, job.job_id, path, "NormalizedRGBFrameSet", StageId.FRAME_EXTRACT)
    )
    stage = StageArtifact(
        stage_id=StageId.FRAME_EXTRACT,
        status=StageStatus.SUCCEEDED,
        completed_at=datetime.now(UTC),
        artifact_type=frames.artifact_type,
        artifact_uri=frames.artifact_uri,
        artifact_checksum=frames.artifact_checksum,
        data_class=frames.data_class,
    )
    updated = with_canonical_checksum(
        job.model_copy(update={"stage_artifacts": [*job.stage_artifacts, stage]}), "job_manifest_checksum"
    )
    reference = registry.lifecycle.store.publish_manifest(updated)
    history = registry.persistence.list_attempts(job.job_id)
    event = JobAttemptRecord(
        attempt=history[-1].attempt,
        status=updated.status,
        current_stage=updated.current_stage,
        recorded_at=datetime.now(UTC),
        job_manifest_uri=reference.artifact_uri,
        job_manifest_checksum=reference.artifact_checksum,
    )
    registry.persistence.save_job(updated, reference, event, expected=job)
    return registry, updated


def _acceptance(  # noqa: ANN001
    registry, job_id: str, artifact_type: str = ANONYMIZATION_ACCEPTANCE_TYPE, name: str = "acceptance"
) -> ProductArtifactRef:
    return _publish(registry, job_id, f"rec02a/sanitized/{name}.json", artifact_type, StageId.PRIVACY_GATE)


def _refuse(*_: object, **__: object) -> None:
    raise AssertionError("runner này không được gọi")


def test_sanitized_job_waits_for_the_user_and_is_not_dispatched(tmp_path: Path) -> None:
    registry, job = _after_prepare(tmp_path)

    assert awaiting_anonymization_review(job) and not awaiting_reviewed_preview(job)
    assert [item.job_id for item in waiting_jobs(registry)] == []
    assert not dispatch_next(
        registry, runner=_refuse, video_runner=_refuse, finalize_runner=_refuse, reviewed_runner=_refuse
    )
    progress = job_progress(job, registry.list_job_attempts(job.job_id), preview_ready=False)
    assert progress.waiting_for == "anonymization_review" and progress.queue is None
    assert {stage.stage_id: stage.state for stage in progress.stages}[StageId.FRAME_EXTRACT] == "waiting"


def test_acceptance_is_recorded_once_and_releases_the_job_to_the_reviewed_runner(tmp_path: Path) -> None:
    registry, job = _after_prepare(tmp_path)
    reference = _acceptance(registry, job.job_id)
    accepted = registry.record_anonymization_acceptance(job, reference)

    assert accepted.status == JobStatus.RUNNING and accepted.current_stage == StageId.FRAME_EXTRACT
    assert not awaiting_anonymization_review(accepted) and awaiting_reviewed_preview(accepted)
    assert [(item.job_id, item.phase) for item in waiting_jobs(registry)] == [(job.job_id, "preview")]
    progress = job_progress(accepted, registry.list_job_attempts(job.job_id), preview_ready=False)
    assert progress.waiting_for is None
    assert {stage.stage_id: stage.state for stage in progress.stages}[StageId.FRAME_EXTRACT] == "succeeded"
    with pytest.raises(RuntimeStateConflictError):
        registry.record_anonymization_acceptance(accepted, reference)

    calls: list[tuple[str, str]] = []
    assert dispatch_next(
        registry,
        runner=_refuse,
        video_runner=_refuse,
        finalize_runner=_refuse,
        reviewed_runner=lambda job_id, *, expected_checksum: calls.append((job_id, expected_checksum)),
    )
    assert calls == [(job.job_id, accepted.job_manifest_checksum)]


def test_acceptance_must_belong_to_the_job_and_have_the_right_type(tmp_path: Path) -> None:
    registry, job = _after_prepare(tmp_path)
    with pytest.raises(ValueError, match="không thuộc job"):
        registry.record_anonymization_acceptance(job, _acceptance(registry, job.job_id, "SomethingElse"))
    foreign = _acceptance(registry, job.job_id, name="other").model_copy(update={"job_id": "job-other"})
    with pytest.raises(ValueError, match="không thuộc job"):
        registry.record_anonymization_acceptance(job, foreign)


def test_job_without_redaction_is_unaffected(tmp_path: Path) -> None:
    registry, job = _after_prepare(tmp_path, sanitized=False)
    assert not awaiting_anonymization_review(job) and not awaiting_reviewed_preview(job)
    with pytest.raises(RuntimeStateConflictError):
        registry.record_anonymization_acceptance(job, _acceptance(registry, job.job_id))
    progress = job_progress(job, registry.list_job_attempts(job.job_id), preview_ready=False)
    assert progress.waiting_for is None


def test_paused_job_is_not_treated_as_an_interrupted_process(tmp_path: Path) -> None:
    registry, job = _after_prepare(tmp_path)
    root = tmp_path / "workers"
    (root / job.job_id / "attempt-finished").mkdir(parents=True)
    settings = SimpleNamespace(product_worker_root=root)
    assert recover_interrupted_jobs(registry, settings) == 0
    assert registry.get_job(job.job_id).status == JobStatus.RUNNING
    accepted = registry.record_anonymization_acceptance(job, _acceptance(registry, job.job_id))
    assert recover_interrupted_jobs(registry, settings) == 0
    assert registry.get_job(job.job_id).job_manifest_checksum == accepted.job_manifest_checksum


def _clean_anonymizer():  # noqa: ANN202
    """Bộ che không phát hiện gì: mọi frame là bản sao nguyên byte."""
    inner = _fake_anonymizer()

    def run(source: Path, target: Path, names: list[str]) -> dict:
        result = inner(source, target, names)
        for frame in result["frames"]:
            frame["regions"], frame["sanitized_checksum"] = [], frame["source_checksum"]
        return result

    return run


def _prepared(root: Path, anonymizer=None):  # noqa: ANN001, ANN202
    """Job chờ xem với bộ frame đã che thật (ffmpeg tách frame, bộ che giả che frame đầu)."""

    def prepare(job_id: str) -> ProductArtifactRef:
        preparer, _, request = _setup(root, anonymizer or _fake_anonymizer())
        result = preparer.run(request.model_copy(update={"job_id": job_id}))
        assert result.error is None and result.frame_set_ref is not None
        return result.frame_set_ref

    return _after_prepare(root, prepare=prepare)


def test_review_lists_only_redacted_frames_and_accept_binds_the_viewed_frame_set(tmp_path: Path) -> None:
    registry, job = _prepared(tmp_path)

    view = review(registry, job.job_id)
    assert view.state == "awaiting" and view.frame_count > 1
    assert [[region.kind for region in frame.regions] for frame in view.frames] == [["face"]]
    name = view.frames[0].frame_name
    image = redacted_frame(registry, job.job_id, name)
    assert registry.runtime_resolver.require(image).read_bytes() == REDACTED
    for other in ("999999.png", "../frame_set.json", "manifest.json"):
        with pytest.raises(AnonymizationReviewError):
            redacted_frame(registry, job.job_id, other)

    with pytest.raises(RuntimeStateConflictError, match="đã thay đổi"):
        accept(registry, job.job_id, "sha256:" + "0" * 64, "user-1")
    assert awaiting_anonymization_review(registry.get_job(job.job_id))

    reference = accept(registry, job.job_id, view.frame_set_checksum, "user-1")
    record = SanitizationAcceptance.model_validate_json(registry.runtime_resolver.require(reference).read_bytes())
    assert (record.accepted_by, record.frame_set_checksum, record.redacted_frame_count) == (
        "user-1",
        view.frame_set_checksum,
        1,
    )
    assert awaiting_reviewed_preview(registry.get_job(job.job_id))
    assert review(registry, job.job_id).state == "accepted"
    with pytest.raises(RuntimeStateConflictError):
        accept(registry, job.job_id, view.frame_set_checksum, "user-1")


def test_review_refuses_a_manifest_that_does_not_belong_to_the_frame_set(tmp_path: Path) -> None:
    registry, job = _prepared(tmp_path)
    stage = next(stage for stage in job.stage_artifacts if stage.stage_id == StageId.FRAME_EXTRACT)
    manifest = registry.runtime_resolver.resolve(stage.artifact_uri.rsplit("/", 1)[0] + "/manifest.json")
    manifest.chmod(0o644)
    manifest.write_text(manifest.read_text().replace('"face"', '"license_plate"'))
    with pytest.raises((AnonymizationReviewError, ValueError)):
        review(registry, job.job_id)


def test_job_without_redaction_has_nothing_to_review(tmp_path: Path) -> None:
    registry, job = _after_prepare(tmp_path, sanitized=False)
    with pytest.raises(AnonymizationReviewError):
        review(registry, job.job_id)


@pytest.mark.asyncio
async def test_routes_show_the_review_serve_the_frame_and_accept(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from httpx import ASGITransport, AsyncClient

    from src.api.studio import deps
    from src.main import app

    registry, job = _prepared(tmp_path)
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(auth_required=False))
    base = f"/api/v1/jobs/{job.job_id}/anonymization"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        shown = await client.get(base)
        assert shown.status_code == 200 and shown.json()["state"] == "awaiting"
        image = await client.get(f"{base}/frames/{shown.json()['frames'][0]['frame_name']}")
        assert image.status_code == 200 and image.content == REDACTED
        assert image.headers["content-type"] == "image/png"
        assert (await client.get(f"{base}/frames/999999.png")).status_code == 404
        assert (await client.get("/api/v1/jobs/job-missing/anonymization")).status_code == 404
        stale = await client.post(f"{base}/accept", json={"frame_set_checksum": "sha256:" + "0" * 64})
        assert stale.status_code == 409
        done = await client.post(f"{base}/accept", json={"frame_set_checksum": shown.json()["frame_set_checksum"]})
        assert done.status_code == 200
        assert done.json()["acceptance"]["artifact_type"] == ANONYMIZATION_ACCEPTANCE_TYPE
        assert (await client.post(f"{base}/accept", json={"frame_set_checksum": "x"})).status_code == 409


def test_worker_keeps_going_only_when_no_frame_was_redacted(tmp_path: Path) -> None:
    registry, job = _prepared(tmp_path / "redacted")
    assert accept_when_nothing_redacted(registry, job.job_id) is None
    assert awaiting_anonymization_review(registry.get_job(job.job_id))

    registry, job = _prepared(tmp_path / "clean", _clean_anonymizer())
    assert review(registry, job.job_id).frames == []
    claimed = accept_when_nothing_redacted(registry, job.job_id)
    assert claimed is not None and claimed.current_stage == StageId.CAMERA_POSE
    # Ghi nhận và nhận job trong một lần ghi: không worker nào khác thấy job để nhận lại.
    assert not awaiting_anonymization_review(claimed) and not awaiting_reviewed_preview(claimed)
    assert [item.job_id for item in waiting_jobs(registry)] == []
    stage = next(stage for stage in claimed.stage_artifacts if stage.stage_id == StageId.PRIVACY_GATE)
    record = SanitizationAcceptance.model_validate_json(
        registry.runtime_resolver.require_uri(stage.artifact_uri, stage.artifact_checksum).read_bytes()
    )
    assert record.accepted_by is None and record.redacted_frame_count == 0


def test_worker_masks_every_qa_verified_video_whatever_the_job_config_says() -> None:
    from src.services.orchestration.jobs.runner import must_anonymize

    plain, enforced = SimpleNamespace(), SimpleNamespace(product_anonymize_input=True)
    assert must_anonymize(False, plain, "qa_verified"), "job thiếu cờ anonymize vẫn phải bị che ở qa_verified"
    assert not must_anonymize(False, plain, "self_attested")
    assert must_anonymize(True, plain, "self_attested") and must_anonymize(False, enforced, "self_attested")
