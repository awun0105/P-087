"""Crash/retry behavior for the persisted release seal identity."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.release import ApprovalDecision, ReleaseManifest, SceneRevisionStatus
from src.services.orchestration.artifacts.checksum import sha256_bytes
from src.services.orchestration.review import workflow
from src.services.orchestration.review.release_seals import (
    ReleaseSealError,
    ReleaseSealIntent,
    ReleaseSealRepository,
    ReleaseSealStatus,
)
from src.services.orchestration.review.workflow import decide, release_uri, review_state, seal_release
from tests.test_orchestration.test_review_workflow import _install_worker_run, _packaged, _report


def test_retry_after_archive_publish_failure_reuses_frozen_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)

    class Clock:
        value = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)

        @classmethod
        def now(cls, _timezone):
            return cls.value

    monkeypatch.setattr(workflow, "datetime", Clock)
    store = registry.scene.store
    publish = store.publish
    failed_manifest = False

    def publish_with_manifest_failure(reference, payload):  # noqa: ANN001
        nonlocal failed_manifest
        if reference.artifact_type == "ReleaseManifest" and not failed_manifest:
            failed_manifest = True
            raise OSError("crash after release ZIP publication")
        return publish(reference, payload)

    monkeypatch.setattr(store, "publish", publish_with_manifest_failure)
    approved = decide(
        registry,
        job.job_id,
        "u-rev",
        ApprovalDecision.APPROVE,
        candidate,
        report.report_checksum,
        [],
        None,
    )

    assert approved.record.status == SceneRevisionStatus.APPROVED
    assert approved.approval is not None
    archive_uri = f"artifact://jobs/{job.job_id}/release/{candidate.removeprefix('sha256:')}/release.zip"
    archive_path = registry.runtime_resolver.locate(archive_uri)
    assert archive_path is not None
    with ZipFile(BytesIO(archive_path.read_bytes())) as archive:
        original_manifest_bytes = archive.read("release_manifest.json")
    assert registry.runtime_resolver.locate(release_uri(job.job_id, candidate)) is None

    assert registry.persistence is not None
    repository = ReleaseSealRepository(registry.persistence.database)
    intent = repository.get(job.job_id, candidate, report.report_checksum, approved.approval.record_checksum)
    assert intent is not None
    assert intent.status == ReleaseSealStatus.PENDING and intent.archive_ref is not None
    assert intent.manifest_payload.encode("utf-8") == original_manifest_bytes
    assert intent.manifest_byte_checksum == sha256_bytes(original_manifest_bytes)

    same = repository.get_or_create(
        job.job_id,
        candidate,
        report.report_checksum,
        approved.approval.record_checksum,
        lambda: pytest.fail("same seal identity must reuse its frozen intent"),
    )
    assert same.seal_id == intent.seal_id and same.manifest_payload == intent.manifest_payload

    original_manifest = ReleaseManifest.model_validate_json(intent.manifest_payload)
    for new_report, new_approval in (
        (report.report_checksum, "sha256:" + "a" * 64),
        ("sha256:" + "b" * 64, approved.approval.record_checksum),
    ):
        approval_projection = original_manifest.approval_record.model_copy(update={"record_checksum": new_approval})
        variant_draft = original_manifest.model_copy(
            update={
                "validation_report_checksum": new_report,
                "approval_record": approval_projection,
                "release_timestamp": original_manifest.release_timestamp + timedelta(seconds=1),
                "release_manifest_checksum": "sha256:" + "0" * 64,
            }
        )
        variant_manifest = variant_draft.model_copy(
            update={"release_manifest_checksum": canonical_content_checksum(variant_draft, "release_manifest_checksum")}
        )
        variant = ReleaseSealIntent.freeze(
            job_id=job.job_id,
            candidate_checksum=candidate,
            validation_report_checksum=new_report,
            approval_record_checksum=new_approval,
            manifest=variant_manifest,
        )
        persisted = repository.get_or_create(job.job_id, candidate, new_report, new_approval, lambda: variant)
        assert persisted.seal_id != intent.seal_id

    corrupted = repository.get(job.job_id, candidate, report.report_checksum, "sha256:" + "a" * 64)
    assert corrupted is not None
    with registry.persistence.database.transaction(write=True) as tx:
        tx.execute(
            """UPDATE r2s_release_seals SET payload=? WHERE job_id=? AND candidate_checksum=?
               AND validation_report_checksum=? AND approval_record_checksum=?""",
            ("{}", job.job_id, candidate, report.report_checksum, "sha256:" + "a" * 64),
        )
    with pytest.raises(ReleaseSealError, match="Invalid persisted release seal intent"):
        repository.get(job.job_id, candidate, report.report_checksum, "sha256:" + "a" * 64)

    Clock.value += timedelta(hours=1)
    released = seal_release(registry, job.job_id)

    assert released.record.status == SceneRevisionStatus.RELEASED
    assert released.release is not None
    manifest_path = registry.runtime_resolver.locate(release_uri(job.job_id, candidate))
    assert manifest_path is not None
    published_manifest_bytes = manifest_path.read_bytes()
    with ZipFile(BytesIO(archive_path.read_bytes())) as archive:
        embedded_manifest_bytes = archive.read("release_manifest.json")

    assert embedded_manifest_bytes == original_manifest_bytes
    assert published_manifest_bytes == original_manifest_bytes
    manifest = ReleaseManifest.model_validate_json(published_manifest_bytes)
    assert manifest.release_timestamp == Clock.value - timedelta(hours=1)
    assert manifest.release_manifest_checksum == released.release.release_manifest_checksum
    sealed = repository.get(job.job_id, candidate, report.report_checksum, approved.approval.record_checksum)
    assert sealed is not None and sealed.status == ReleaseSealStatus.SEALED and sealed.generation == 3


def test_existing_release_without_seal_intent_remains_readable(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)

    released = decide(
        registry,
        job.job_id,
        "u-rev",
        ApprovalDecision.APPROVE,
        candidate,
        report.report_checksum,
        [],
        None,
    )
    assert released.record.status == SceneRevisionStatus.RELEASED
    assert registry.persistence is not None
    with registry.persistence.database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_release_seals WHERE job_id=?", (job.job_id,))

    existing = review_state(registry, job.job_id)

    assert existing.record.status == SceneRevisionStatus.RELEASED
    assert existing.release is not None and existing.release_archive is not None
