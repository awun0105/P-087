"""Crash/retry behavior for the persisted release seal identity."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier
from zipfile import ZipFile

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.release import ApprovalDecision, ReleaseManifest, SceneRevisionStatus
from src.services.orchestration.artifacts.checksum import sha256_bytes
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.review import workflow
from src.services.orchestration.review.release_seals import (
    ReleaseSealError,
    ReleaseSealIntent,
    ReleaseSealRepository,
    ReleaseSealStatus,
)
from src.services.orchestration.review.workflow import (
    ReviewError,
    _verify_release_archive,
    decide,
    release_uri,
    review_state,
    seal_release,
)
from src.services.orchestration.scene.objects import add_box_object
from tests.test_orchestration.test_review_workflow import _install_worker_run, _packaged, _report


def _approve(
    registry: ProjectRegistry,
    job_id: str,
    candidate: str,
    report_checksum: str,
    reviewer_id: str = "u-rev",
    reason: str | None = None,
):
    warnings = review_state(registry, job_id).warning_ids
    return decide(
        registry,
        job_id,
        reviewer_id,
        ApprovalDecision.APPROVE,
        candidate,
        report_checksum,
        warnings,
        reason,
    )


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
    approved = _approve(registry, job.job_id, candidate, report.report_checksum)

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

    released = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert released.record.status == SceneRevisionStatus.RELEASED
    assert registry.persistence is not None
    with registry.persistence.database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_release_seals WHERE job_id=?", (job.job_id,))

    existing = review_state(registry, job.job_id)

    assert existing.record.status == SceneRevisionStatus.RELEASED
    assert existing.release is not None and existing.release_archive is not None


def test_archive_publish_failure_is_persisted_and_retry_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    store = registry.scene.store
    publish = store.publish
    failed = False

    def fail_archive_once(reference, payload):  # noqa: ANN001
        nonlocal failed
        if reference.artifact_type == "ReleaseArchive" and not failed:
            failed = True
            raise OSError("remote store transient detail must not be persisted")
        return publish(reference, payload)

    monkeypatch.setattr(store, "publish", fail_archive_once)
    approved = _approve(registry, job.job_id, candidate, report.report_checksum)

    assert approved.record.status == SceneRevisionStatus.APPROVED
    assert approved.release_seal_error is not None
    assert "remote store transient detail" not in approved.release_seal_error
    assert registry.persistence is not None
    repository = ReleaseSealRepository(registry.persistence.database)
    assert repository.has_failure(job.job_id, candidate, report.report_checksum, approved.approval.record_checksum)

    released = seal_release(registry, job.job_id)

    assert released.record.status == SceneRevisionStatus.RELEASED
    assert released.release_seal_error is None
    assert not repository.has_failure(job.job_id, candidate, report.report_checksum, approved.approval.record_checksum)


def test_crash_after_manifest_before_seal_marker_reuses_all_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    mark_sealed = ReleaseSealRepository.mark_sealed
    failed = False

    def fail_marker_once(repository, intent):  # noqa: ANN001
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("crash before commit marker")
        return mark_sealed(repository, intent)

    monkeypatch.setattr(ReleaseSealRepository, "mark_sealed", fail_marker_once)
    approved = _approve(registry, job.job_id, candidate, report.report_checksum)
    manifest_path = registry.runtime_resolver.locate(release_uri(job.job_id, candidate))
    archive_uri = f"artifact://jobs/{job.job_id}/release/{candidate.removeprefix('sha256:')}/release.zip"
    archive_path = registry.runtime_resolver.locate(archive_uri)
    assert approved.record.status == SceneRevisionStatus.APPROVED
    assert manifest_path is not None and archive_path is not None
    manifest_bytes = manifest_path.read_bytes()
    archive_bytes = archive_path.read_bytes()
    assert review_state(registry, job.job_id).release is None

    monkeypatch.setattr(ReleaseSealRepository, "mark_sealed", mark_sealed)
    released = seal_release(registry, job.job_id)

    assert released.record.status == SceneRevisionStatus.RELEASED
    assert manifest_path.read_bytes() == manifest_bytes
    assert archive_path.read_bytes() == archive_bytes
    assert released.release_seal_error is None


def test_missing_archive_is_rebuilt_from_frozen_identity(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    released = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert released.record.status == SceneRevisionStatus.RELEASED
    archive_uri = f"artifact://jobs/{job.job_id}/release/{candidate.removeprefix('sha256:')}/release.zip"
    archive_path = registry.runtime_resolver.locate(archive_uri)
    assert archive_path is not None
    archive_path.unlink()

    damaged = review_state(registry, job.job_id)
    assert damaged.record.status == SceneRevisionStatus.APPROVED
    assert damaged.release is None and damaged.release_seal_error is not None

    recovered = seal_release(registry, job.job_id)

    assert recovered.record.status == SceneRevisionStatus.RELEASED
    assert archive_path.is_file()


def test_corrupt_existing_archive_fails_closed_and_is_never_overwritten(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    released = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert released.record.status == SceneRevisionStatus.RELEASED
    archive_uri = f"artifact://jobs/{job.job_id}/release/{candidate.removeprefix('sha256:')}/release.zip"
    archive_path = registry.runtime_resolver.locate(archive_uri)
    assert archive_path is not None
    corrupt = archive_path.read_bytes() + b"mutated immutable release"
    archive_path.write_bytes(corrupt)

    damaged = review_state(registry, job.job_id)

    assert damaged.record.status == SceneRevisionStatus.APPROVED
    assert damaged.release is None and damaged.release_archive is None
    assert damaged.release_seal_error is not None
    with pytest.raises(ReviewError):
        seal_release(registry, job.job_id)
    assert archive_path.read_bytes() == corrupt


def test_api_manifest_bytes_must_match_the_frozen_zip_payload(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    released = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert released.record.status == SceneRevisionStatus.RELEASED
    manifest_path = registry.runtime_resolver.locate(release_uri(job.job_id, candidate))
    assert manifest_path is not None
    changed_bytes = manifest_path.read_bytes() + b"\n"
    manifest_path.write_bytes(changed_bytes)

    changed = review_state(registry, job.job_id)

    assert changed.record.status == SceneRevisionStatus.APPROVED
    assert changed.release is None and changed.release_seal_error is not None
    with pytest.raises(ReviewError):
        seal_release(registry, job.job_id)
    assert manifest_path.read_bytes() == changed_bytes


def test_release_archive_rejects_unexpected_zip_members(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    released = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert released.record.status == SceneRevisionStatus.RELEASED
    assert released.package is not None and released.package.package_ref is not None
    assert released.release is not None and released.release_archive is not None
    package_zip = registry.runtime_resolver.require(released.package.package_ref).read_bytes()
    archive_path = registry.runtime_resolver.require(released.release_archive)
    with ZipFile(archive_path) as source:
        members = [(info, source.read(info.filename)) for info in source.infolist()]
    tampered = BytesIO()
    with ZipFile(tampered, "w") as destination:
        for info, content in members:
            destination.writestr(info, content)
        destination.writestr("unexpected.txt", b"not in the candidate package")
    manifest_path = registry.runtime_resolver.locate(release_uri(job.job_id, candidate))
    assert manifest_path is not None

    with pytest.raises(ValueError, match="missing or unexpected"):
        _verify_release_archive(
            package_zip,
            tampered.getvalue(),
            manifest_path.read_bytes(),
            released.validation,
            released.approval,
        )


def test_pre_intent_partial_archive_is_adopted_without_changing_manifest_bytes(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    released = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert released.record.status == SceneRevisionStatus.RELEASED
    manifest_path = registry.runtime_resolver.locate(release_uri(job.job_id, candidate))
    archive_uri = f"artifact://jobs/{job.job_id}/release/{candidate.removeprefix('sha256:')}/release.zip"
    archive_path = registry.runtime_resolver.locate(archive_uri)
    assert registry.persistence is not None and manifest_path is not None and archive_path is not None
    with ZipFile(BytesIO(archive_path.read_bytes())) as archive:
        embedded_manifest = archive.read("release_manifest.json")
    manifest_path.unlink()
    with registry.persistence.database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_release_seals WHERE job_id=?", (job.job_id,))

    recovered = seal_release(registry, job.job_id)

    assert recovered.record.status == SceneRevisionStatus.RELEASED
    assert manifest_path.read_bytes() == embedded_manifest


def test_two_registries_concurrently_seal_the_same_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)

    # Persist approval without starting its automatic seal; both independent registry instances
    # then enter the release protocol together, each opening its own SQLite connections.
    monkeypatch.setattr(
        workflow, "seal_release", lambda current_registry, _job_id: review_state(current_registry, _job_id)
    )
    approved = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert approved.record.status == SceneRevisionStatus.APPROVED
    assert registry.execution_profile is not None
    second_registry = ProjectRegistry(
        fixture_root=registry.fixture_root,
        runtime_root=tmp_path / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}"),
        execution_profile=registry.execution_profile,
    )

    barrier = Barrier(2)
    original_seal = workflow._seal_release

    def synchronized_seal(current_registry, state, repository):  # noqa: ANN001
        barrier.wait(timeout=10)
        return original_seal(current_registry, state, repository)

    monkeypatch.setattr(workflow, "_seal_release", synchronized_seal)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(seal_release, registry, job.job_id)
        second = executor.submit(seal_release, second_registry, job.job_id)
        first_state = first.result(timeout=30)
        second_state = second.result(timeout=30)

    assert first_state.record.status == second_state.record.status == SceneRevisionStatus.RELEASED
    assert first_state.release == second_state.release
    assert first_state.release_archive == second_state.release_archive
    assert first_state.release_archive is not None
    first_bytes = registry.runtime_resolver.require(first_state.release_archive).read_bytes()
    second_bytes = second_registry.runtime_resolver.require(second_state.release_archive).read_bytes()
    assert first_bytes == second_bytes
    assert registry.persistence is not None and first_state.approval is not None
    repository = ReleaseSealRepository(registry.persistence.database)
    sealed = repository.get(job.job_id, candidate, report.report_checksum, first_state.approval.record_checksum)
    assert sealed is not None and sealed.status == ReleaseSealStatus.SEALED


def test_stale_candidate_cannot_be_sealed_after_scene_revision_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    monkeypatch.setattr(
        workflow, "seal_release", lambda current_registry, _job_id: review_state(current_registry, _job_id)
    )
    approved = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert approved.record.status == SceneRevisionStatus.APPROVED

    scene = registry.scene.current(job.job_id).scene
    add_box_object(
        registry.scene,
        job.job_id,
        scene.scene_revision,
        "New revision obstacle",
        (0.2, 0.2, 0.2),
        (2.0, 2.0, 0.2),
    )

    with pytest.raises(ReviewError, match="Chỉ phát hành"):
        seal_release(registry, job.job_id)
    assert registry.runtime_resolver.locate(release_uri(job.job_id, candidate)) is None


def test_stale_candidate_change_during_publish_stays_uncommitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    monkeypatch.setattr(
        workflow, "seal_release", lambda current_registry, _job_id: review_state(current_registry, _job_id)
    )
    approved = _approve(registry, job.job_id, candidate, report.report_checksum)
    assert approved.record.status == SceneRevisionStatus.APPROVED
    assert approved.approval is not None

    publish = workflow._publish_release_once
    changed_revision = False

    def publish_then_change_scene(current_registry, reference, payload):  # noqa: ANN001
        nonlocal changed_revision
        publish(current_registry, reference, payload)
        if reference.artifact_type == "ReleaseManifest" and not changed_revision:
            changed_revision = True
            scene = current_registry.scene.current(job.job_id).scene
            add_box_object(
                current_registry.scene,
                job.job_id,
                scene.scene_revision,
                "Concurrent revision obstacle",
                (0.2, 0.2, 0.2),
                (2.0, 2.0, 0.2),
            )

    monkeypatch.setattr(workflow, "_publish_release_once", publish_then_change_scene)

    with pytest.raises(ReviewError, match="changed while release was sealing"):
        seal_release(registry, job.job_id)

    assert changed_revision
    manifest_path = registry.runtime_resolver.locate(release_uri(job.job_id, candidate))
    assert manifest_path is not None  # immutable bytes may be present, but are not a committed release
    assert registry.persistence is not None
    repository = ReleaseSealRepository(registry.persistence.database)
    intent = repository.get(job.job_id, candidate, report.report_checksum, approved.approval.record_checksum)
    assert intent is not None and intent.status == ReleaseSealStatus.PENDING
    assert repository.has_failure(job.job_id, candidate, report.report_checksum, approved.approval.record_checksum)
    current = review_state(registry, job.job_id)
    assert current.record.status != SceneRevisionStatus.RELEASED
    assert current.release is None
