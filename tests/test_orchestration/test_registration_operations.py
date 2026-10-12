import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.input_assembly import DistanceUnit, InputAssetFormat, InputRole
from src.models.contracts.manifests import StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationInputMode,
    RegistrationOperationState,
    RegistrationProfile,
    RegistrationRequest,
    RegistrationROI,
    RegistrationSourceBinding,
    seal_registration_profile,
    seal_registration_request,
)
from src.services.orchestration.jobs.database import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    RuntimeDatabase,
    RuntimeStateConflictError,
)
from src.services.orchestration.jobs.registration_operations import (
    RegistrationOperationCancellationRequestedError,
    RegistrationOperationLeaseLostError,
    RegistrationOperationRecord,
    RegistrationOperationStore,
)

_ZERO = "sha256:" + "0" * 64


def _checksum(value: str) -> str:
    return "sha256:" + sha256(value.encode()).hexdigest()


def _ref(job_id: str, artifact_type: str) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/registration/{artifact_type.lower()}.json",
        artifact_checksum=_checksum(artifact_type),
        data_class="derived",
        producer_stage=(StageId.OBJECT_EXTRACT if artifact_type == "FloorFitEvidence" else StageId.RGB_LIDAR_ALIGN),
        job_id=job_id,
    )


def _publication_ref(job_id: str, artifact_type: str, stage_id: StageId) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/registration/{artifact_type.lower()}.json",
        artifact_checksum=_checksum(artifact_type),
        data_class="derived",
        producer_stage=stage_id,
        job_id=job_id,
    )


def _request(request_id: str = "registration-request-1", requester_id: str = "user-a") -> RegistrationRequest:
    job_id, project_id = "job-registration-1", "project-registration-1"
    profile: RegistrationProfile = seal_registration_profile(
        {
            "profile_id": "registration-test-profile",
            "qualification_state": "provisional",
            "qualification_record_ref": None,
            "profile_checksum": _ZERO,
        }
    )
    source = RegistrationSourceBinding(
        mode=RegistrationInputMode.STATIC_CLOUD,
        target_job_id=job_id,
        authorized_project_id=project_id,
        source_input_checksum=_checksum("map-source"),
        source_frame="lidar-map-frame",
        source_distance_unit=DistanceUnit.METER,
        source_point_count=1_000,
        source_format=InputAssetFormat.POINT_CLOUD_PCD,
        source_header_checksum=_checksum("pcd-header"),
        source_role=InputRole.STATIC_LIDAR_CLOUD,
        input_assembly_id="assembly-registration-1",
        input_assembly_revision=1,
        input_assembly_checksum=_checksum("assembly-1"),
        source_file_ids=["map-file-1"],
        same_scene_attestation=True,
    )
    return seal_registration_request(
        {
            "request_id": request_id,
            "requested_by": requester_id,
            "target_project_id": project_id,
            "target_job_id": job_id,
            "target_rgb_geometry_ref": ProductArtifactRef(
                artifact_type="RgbGeometry",
                schema_version="1.0",
                artifact_uri=f"artifact://jobs/{job_id}/rgb/geometry.json",
                artifact_checksum=_checksum("rgb-geometry"),
                data_class="derived",
                producer_stage=StageId.RGB_GEOMETRY,
                job_id=job_id,
            ),
            "expected_scene_revision": "scene-revision-1",
            "source": source,
            "metric_state": "confirmed",
            "metric_confirmation_ref": ProductArtifactRef(
                artifact_type="RGBMetricConfirmation",
                schema_version="1.0",
                artifact_uri=f"artifact://jobs/{job_id}/metric/confirmation.json",
                artifact_checksum=_checksum("metric"),
                data_class="derived",
                producer_stage=StageId.METRIC_CANONICALIZE,
                job_id=job_id,
            ),
            "floor_state": "supported",
            "floor_model_refs": [_ref(job_id, "FloorFitEvidence")],
            "target_roi_world": RegistrationROI(min_xyz_m=(-20, -20, -2), max_xyz_m=(20, 20, 8)),
            "profile": profile,
            "profile_checksum": profile.profile_checksum,
            "request_checksum": _ZERO,
        }
    )


def _store(tmp_path: Path) -> tuple[RuntimeDatabase, RegistrationOperationStore]:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.sqlite'}")
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_users(user_id,email,payload) VALUES (?,?,?)",
            ("user-a", "user-a@example.test", "{}"),
        )
        tx.execute("INSERT INTO r2s_projects(project_id,payload) VALUES (?,?)", ("project-registration-1", "{}"))
        tx.execute(
            "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES (?,?,?,?)",
            ("job-registration-1", "project-registration-1", 1, "artifact://jobs/job-registration-1/manifest.json"),
        )
    return database, RegistrationOperationStore(database)


def test_registration_operation_migration_is_latest_and_additive(tmp_path: Path) -> None:
    path = tmp_path / "schema-v17.sqlite"
    with sqlite3.connect(path) as legacy:
        legacy.execute("CREATE TABLE r2s_schema (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)")
        legacy.execute("INSERT INTO r2s_schema VALUES (1, 0)")
        for version, statements in MIGRATIONS:
            if version > 17:
                continue
            for statement in statements:
                legacy.execute(statement)
            legacy.execute("UPDATE r2s_schema SET version=? WHERE id=1", (version,))
        legacy.execute("INSERT INTO r2s_projects(project_id,payload) VALUES ('preserved-project','{}')")

    database = RuntimeDatabase(f"sqlite:///{path}")
    assert LATEST_SCHEMA_VERSION == 19
    assert database.schema_version() == LATEST_SCHEMA_VERSION
    with database.transaction() as tx:
        assert tx.execute("SELECT project_id FROM r2s_projects").fetchall() == [("preserved-project",)]
        assert tx.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='r2s_registration_operations'"
        ).fetchone() == ("r2s_registration_operations",)


def test_enqueue_is_idempotent_and_rejects_key_reuse_for_other_request(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()

    accepted = store.enqueue(request, "request-key-1")
    replay = store.enqueue(request, "request-key-1")

    assert accepted.operation_id == replay.operation_id == request.request_id
    assert accepted.state == RegistrationOperationState.QUEUED
    with pytest.raises(RuntimeStateConflictError, match="Idempotency-Key"):
        store.enqueue(_request("registration-request-2"), "request-key-1")


def test_legacy_operation_payload_without_additive_fields_keeps_its_checksum(tmp_path: Path) -> None:
    database, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")

    with database.transaction(write=True) as tx:
        row = tx.execute(
            "SELECT payload FROM r2s_registration_operations WHERE operation_id=?", (request.request_id,)
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        assert payload.pop("cancellation_requested") is False
        assert payload.pop("resource_wait_reason") is None
        tx.execute(
            "UPDATE r2s_registration_operations SET payload=? WHERE operation_id=?",
            (json.dumps(payload), request.request_id),
        )

    restored = store.get(request.request_id)
    assert restored.cancellation_requested is False
    assert restored.state == RegistrationOperationState.QUEUED


def test_confirmation_persists_exact_decision_and_replays_after_reload(tmp_path: Path) -> None:
    database, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=60, now=now)
    assert claimed is not None and claimed.lease_token is not None
    proposed = store.finish(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        state=RegistrationOperationState.PROPOSED,
        proposal_ref=_ref(claimed.target_job_id, "RegistrationProposalArtifact"),
        qa_report_ref=_ref(claimed.target_job_id, "RegistrationQAReport"),
        now=now + timedelta(seconds=1),
    )

    confirmed = store.confirm(
        proposed.operation_id,
        expected_operation_checksum=proposed.operation_checksum,
        expected_scene_revision=request.expected_scene_revision,
        candidate_id="candidate-qualified-1",
        user_id="user-a",
        now=now + timedelta(seconds=2),
    )
    replay = store.confirm(
        proposed.operation_id,
        expected_operation_checksum=proposed.operation_checksum,
        expected_scene_revision=request.expected_scene_revision,
        candidate_id="candidate-qualified-1",
        user_id="user-a",
        now=now + timedelta(seconds=30),
    )

    assert confirmed.state == RegistrationOperationState.CONFIRMED
    assert confirmed.confirmed_candidate_id == "candidate-qualified-1"
    assert confirmed.confirmed_by_user_id == "user-a"
    assert confirmed.confirmed_at == now + timedelta(seconds=2)
    assert confirmed.confirmed_from_checksum == proposed.operation_checksum
    assert confirmed.operation_checksum != proposed.operation_checksum
    assert replay == confirmed
    assert store.get(proposed.operation_id) == confirmed
    assert store.get(proposed.operation_id).request.expected_scene_revision == request.expected_scene_revision
    assert database.schema_version() == LATEST_SCHEMA_VERSION


def test_confirmed_operation_commits_exact_bundle_and_alignment_once(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-commit")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=60, now=now)
    assert claimed is not None and claimed.lease_token is not None
    proposed = store.finish(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        state=RegistrationOperationState.PROPOSED,
        proposal_ref=_ref(claimed.target_job_id, "RegistrationProposalArtifact"),
        qa_report_ref=_ref(claimed.target_job_id, "RegistrationQAReport"),
        now=now + timedelta(seconds=1),
    )
    confirmed = store.confirm(
        proposed.operation_id,
        expected_operation_checksum=proposed.operation_checksum,
        expected_scene_revision=request.expected_scene_revision,
        candidate_id="candidate-qualified-1",
        user_id="user-a",
        now=now + timedelta(seconds=2),
    )
    bundle_ref = _publication_ref(request.target_job_id, "ReconstructionBundle", StageId.METRIC_CANONICALIZE)
    alignment_ref = _publication_ref(request.target_job_id, "AlignmentRecord", StageId.RGB_LIDAR_ALIGN)
    manifest_checksum = _checksum("published-job-manifest")

    committed = store.commit(
        confirmed.operation_id,
        expected_operation_checksum=confirmed.operation_checksum,
        expected_scene_revision=request.expected_scene_revision,
        bundle_ref=bundle_ref,
        alignment_ref=alignment_ref,
        manifest_checksum=manifest_checksum,
        now=now + timedelta(seconds=3),
    )
    replay = store.commit(
        confirmed.operation_id,
        expected_operation_checksum=confirmed.operation_checksum,
        expected_scene_revision=request.expected_scene_revision,
        bundle_ref=bundle_ref,
        alignment_ref=alignment_ref,
        manifest_checksum=manifest_checksum,
        now=now + timedelta(seconds=4),
    )

    assert committed.state == RegistrationOperationState.COMMITTED
    assert committed.committed_bundle_ref == bundle_ref
    assert committed.committed_alignment_ref == alignment_ref
    assert committed.committed_manifest_checksum == manifest_checksum
    assert replay == committed
    assert store.get(confirmed.operation_id) == committed
    with pytest.raises(RuntimeStateConflictError, match="different outputs"):
        store.commit(
            confirmed.operation_id,
            expected_operation_checksum=confirmed.operation_checksum,
            expected_scene_revision=request.expected_scene_revision,
            bundle_ref=bundle_ref,
            alignment_ref=alignment_ref,
            manifest_checksum=_checksum("different-job-manifest"),
        )


def test_confirmation_rejects_stale_checksum_and_conflicting_replay(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=60, now=now)
    assert claimed is not None and claimed.lease_token is not None
    proposed = store.finish(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        state=RegistrationOperationState.PROPOSED,
        proposal_ref=_ref(claimed.target_job_id, "RegistrationProposalArtifact"),
        qa_report_ref=_ref(claimed.target_job_id, "RegistrationQAReport"),
        now=now + timedelta(seconds=1),
    )

    with pytest.raises(RuntimeStateConflictError, match="changed before confirmation"):
        store.confirm(
            proposed.operation_id,
            expected_operation_checksum=_checksum("stale operation"),
            expected_scene_revision=request.expected_scene_revision,
            candidate_id="candidate-qualified-1",
            user_id="user-a",
        )

    confirmed = store.confirm(
        proposed.operation_id,
        expected_operation_checksum=proposed.operation_checksum,
        expected_scene_revision=request.expected_scene_revision,
        candidate_id="candidate-qualified-1",
        user_id="user-a",
        now=now + timedelta(seconds=2),
    )
    assert store.get(proposed.operation_id) == confirmed

    for candidate_id, user_id, scene_revision in (
        ("candidate-other", "user-a", request.expected_scene_revision),
        ("candidate-qualified-1", "user-b", request.expected_scene_revision),
        ("candidate-qualified-1", "user-a", "scene-revision-other"),
    ):
        with pytest.raises(RuntimeStateConflictError, match="different confirmation"):
            store.confirm(
                proposed.operation_id,
                expected_operation_checksum=proposed.operation_checksum,
                expected_scene_revision=scene_revision,
                candidate_id=candidate_id,
                user_id=user_id,
            )


def test_concurrent_candidate_confirmations_have_one_compare_and_swap_winner(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=60, now=now)
    assert claimed is not None and claimed.lease_token is not None
    proposed = store.finish(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        state=RegistrationOperationState.PROPOSED,
        proposal_ref=_ref(claimed.target_job_id, "RegistrationProposalArtifact"),
        qa_report_ref=_ref(claimed.target_job_id, "RegistrationQAReport"),
        now=now + timedelta(seconds=1),
    )
    barrier = Barrier(2)

    def confirm(candidate_id: str) -> str:
        barrier.wait()
        try:
            result = store.confirm(
                proposed.operation_id,
                expected_operation_checksum=proposed.operation_checksum,
                expected_scene_revision=request.expected_scene_revision,
                candidate_id=candidate_id,
                user_id="user-a",
            )
        except RuntimeStateConflictError:
            return "conflict"
        return result.confirmed_candidate_id or "missing"

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(confirm, ("candidate-a", "candidate-b")))

    assert outcomes.count("conflict") == 1
    assert sum(outcome.startswith("candidate-") for outcome in outcomes) == 1
    persisted = store.get(proposed.operation_id)
    assert persisted.state == RegistrationOperationState.CONFIRMED
    assert persisted.confirmed_candidate_id in {"candidate-a", "candidate-b"}


def test_queued_registration_cancellation_is_terminal_and_idempotent(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)

    cancelled = store.cancel(request.request_id, now=now)
    replay = store.cancel(request.request_id, now=now + timedelta(seconds=1))

    assert cancelled.state == replay.state == RegistrationOperationState.CANCELLED
    assert cancelled.operation_checksum == replay.operation_checksum
    assert store.claim_next("worker-a", lease_seconds=60, now=now + timedelta(seconds=2)) is None


def test_resource_wait_releases_lease_and_can_be_claimed_again(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=30, now=now)
    assert claimed is not None and claimed.lease_token is not None

    waiting = store.wait_for_resources(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        reason="RAM: busy",
        now=now + timedelta(seconds=1),
    )

    assert waiting.state == RegistrationOperationState.WAITING_RESOURCES
    assert waiting.resource_wait_reason == "RAM: busy"
    assert waiting.worker_id is waiting.lease_token is waiting.lease_expires_at is waiting.heartbeat_at is None
    assert waiting.attempt == claimed.attempt
    with pytest.raises(RegistrationOperationLeaseLostError):
        store.finish(
            claimed.operation_id,
            lease_token=claimed.lease_token,
            fencing_token=claimed.fencing_token,
            state=RegistrationOperationState.FAILED,
            error="stale worker",
            now=now + timedelta(seconds=2),
        )

    resumed = store.claim_next("worker-b", lease_seconds=30, now=now + timedelta(seconds=3))

    assert resumed is not None and resumed.operation_id == claimed.operation_id
    assert resumed.state == RegistrationOperationState.RUNNING
    assert resumed.lease_token != claimed.lease_token
    assert resumed.fencing_token == claimed.fencing_token + 1
    assert resumed.attempt == claimed.attempt + 1
    assert resumed.resource_wait_reason is None


def test_requeued_resource_wait_does_not_starve_another_queued_operation(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    first = store.enqueue(_request("registration-request-first"), "request-key-first")
    second = store.enqueue(_request("registration-request-second"), "request-key-second")
    now = max(first.created_at, second.created_at) + timedelta(seconds=1)
    claimed = store.claim_next("worker-a", lease_seconds=30, now=now)
    assert claimed is not None and claimed.operation_id == first.operation_id

    store.wait_for_resources(
        claimed.operation_id,
        lease_token=claimed.lease_token or "",
        fencing_token=claimed.fencing_token,
        reason="RAM: busy",
        now=now + timedelta(seconds=1),
    )

    next_claim = store.claim_next("worker-b", lease_seconds=30, now=now + timedelta(seconds=2))

    assert next_claim is not None and next_claim.operation_id == second.operation_id


def test_resource_wait_reason_is_required_only_in_the_waiting_state(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    claimed = store.claim_next("worker-a", lease_seconds=30)
    assert claimed is not None

    running_payload = claimed.model_dump(mode="python")
    running_payload["resource_wait_reason"] = "RAM: busy"
    with pytest.raises(ValidationError, match="only valid while waiting for resources"):
        RegistrationOperationRecord.model_validate(running_payload)

    waiting_payload = claimed.model_dump(mode="python")
    waiting_payload.update(
        state=RegistrationOperationState.WAITING_RESOURCES,
        worker_id=None,
        lease_token=None,
        lease_expires_at=None,
        heartbeat_at=None,
    )
    with pytest.raises(ValidationError, match="requires a wait reason"):
        RegistrationOperationRecord.model_validate(waiting_payload)


def test_resource_wait_reason_must_be_nonempty_and_bounded(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    claimed = store.claim_next("worker-a", lease_seconds=30)
    assert claimed is not None and claimed.lease_token is not None

    for reason in ("  ", "x" * 501):
        with pytest.raises(ValueError, match="resource wait reason"):
            store.wait_for_resources(
                claimed.operation_id,
                lease_token=claimed.lease_token,
                fencing_token=claimed.fencing_token,
                reason=reason,
            )

    assert store.get(claimed.operation_id).state == RegistrationOperationState.RUNNING


def test_resource_wait_reason_is_checksum_bound(tmp_path: Path) -> None:
    database, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=30, now=now)
    assert claimed is not None and claimed.lease_token is not None
    store.wait_for_resources(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        reason="RAM: busy",
        now=now + timedelta(seconds=1),
    )

    with database.transaction(write=True) as tx:
        row = tx.execute(
            "SELECT payload FROM r2s_registration_operations WHERE operation_id=?", (request.request_id,)
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["resource_wait_reason"] = "RAM: available"
        tx.execute(
            "UPDATE r2s_registration_operations SET payload=? WHERE operation_id=?",
            (json.dumps(payload), request.request_id),
        )

    with pytest.raises(RuntimeStateConflictError, match="checksum mismatch"):
        store.get(request.request_id)


def test_waiting_resource_registration_can_be_cancelled_without_claim(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=30, now=now)
    assert claimed is not None and claimed.lease_token is not None
    waiting = store.wait_for_resources(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        reason="disk: external",
        now=now + timedelta(seconds=1),
    )

    cancelled = store.cancel(waiting.operation_id, now=now + timedelta(seconds=2))

    assert cancelled.state == RegistrationOperationState.CANCELLED
    assert cancelled.resource_wait_reason is None
    assert store.cancel(waiting.operation_id, now=now + timedelta(seconds=3)) == cancelled
    assert store.claim_next("worker-b", lease_seconds=30, now=now + timedelta(seconds=4)) is None


def test_running_cancel_is_acknowledged_if_worker_requeues_for_resources(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=30, now=now)
    assert claimed is not None and claimed.lease_token is not None
    requested = store.cancel(claimed.operation_id, now=now + timedelta(seconds=1))
    assert requested.cancellation_requested is True

    cancelled = store.wait_for_resources(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        reason="RAM: busy",
        now=now + timedelta(seconds=2),
    )

    assert cancelled.state == RegistrationOperationState.CANCELLED
    assert cancelled.cancellation_requested is True
    assert cancelled.resource_wait_reason is None
    assert cancelled.lease_token is None


def test_running_cancel_racing_resource_requeue_always_ends_cancelled(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=30, now=now)
    assert claimed is not None and claimed.lease_token is not None
    gate = Barrier(3)

    def cancel() -> RegistrationOperationRecord:
        gate.wait()
        return store.cancel(claimed.operation_id, now=now + timedelta(seconds=1))

    def wait() -> RegistrationOperationRecord:
        gate.wait()
        return store.wait_for_resources(
            claimed.operation_id,
            lease_token=claimed.lease_token or "",
            fencing_token=claimed.fencing_token,
            reason="RAM: busy",
            now=now + timedelta(seconds=2),
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        cancelled_future = workers.submit(cancel)
        waiting_future = workers.submit(wait)
        gate.wait()
        cancel_result = cancelled_future.result()
        wait_result = waiting_future.result()

    final = store.get(claimed.operation_id)
    assert final.state == RegistrationOperationState.CANCELLED
    assert final.resource_wait_reason is None
    if cancel_result.state == RegistrationOperationState.RUNNING:
        assert cancel_result.cancellation_requested is True
        assert wait_result.state == RegistrationOperationState.CANCELLED
    else:
        assert cancel_result.state == RegistrationOperationState.CANCELLED
        assert wait_result.state == RegistrationOperationState.WAITING_RESOURCES


def test_queued_cancel_racing_worker_claim_is_never_lost(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    gate = Barrier(3)

    def cancel() -> RegistrationOperationRecord:
        gate.wait()
        return store.cancel(request.request_id, now=now)

    def claim() -> RegistrationOperationRecord | None:
        gate.wait()
        return store.claim_next("worker-a", lease_seconds=60, now=now)

    with ThreadPoolExecutor(max_workers=2) as workers:
        cancelled_future = workers.submit(cancel)
        claimed_future = workers.submit(claim)
        gate.wait()
        cancelled = cancelled_future.result()
        claimed = claimed_future.result()

    current = store.get(request.request_id)
    if current.state == RegistrationOperationState.CANCELLED:
        assert claimed is None
        assert cancelled.state == RegistrationOperationState.CANCELLED
    else:
        assert current.state == RegistrationOperationState.RUNNING
        assert current.cancellation_requested is True
        assert claimed is not None and claimed.operation_id == request.request_id
        assert cancelled.cancellation_requested is True


def test_running_cancel_racing_proposal_is_linearized(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=60, now=now)
    assert claimed is not None and claimed.lease_token is not None
    gate = Barrier(3)

    def cancel() -> RegistrationOperationRecord:
        gate.wait()
        return store.cancel(claimed.operation_id, now=now + timedelta(seconds=1))

    def finish() -> RegistrationOperationRecord | Exception:
        gate.wait()
        try:
            return store.finish(
                claimed.operation_id,
                lease_token=claimed.lease_token or "",
                fencing_token=claimed.fencing_token,
                state=RegistrationOperationState.PROPOSED,
                proposal_ref=_ref(claimed.target_job_id, "RegistrationProposalArtifact"),
                qa_report_ref=_ref(claimed.target_job_id, "RegistrationQAReport"),
                now=now + timedelta(seconds=2),
            )
        except (RegistrationOperationCancellationRequestedError, RegistrationOperationLeaseLostError) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as workers:
        cancelled_future = workers.submit(cancel)
        finished_future = workers.submit(finish)
        gate.wait()
        cancelled = cancelled_future.result()
        finished = finished_future.result()

    current = store.get(claimed.operation_id)
    if current.state == RegistrationOperationState.PROPOSED:
        assert isinstance(finished, RegistrationOperationRecord)
        assert cancelled.state == RegistrationOperationState.PROPOSED
    else:
        assert current.state == RegistrationOperationState.RUNNING
        assert current.cancellation_requested is True
        assert isinstance(
            finished,
            (RegistrationOperationCancellationRequestedError, RegistrationOperationLeaseLostError),
        )
        assert cancelled.cancellation_requested is True


def test_running_registration_cancellation_waits_for_worker_ack_and_fences_proposal(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=30, now=now)
    assert claimed is not None and claimed.lease_token is not None

    pending = store.cancel(claimed.operation_id, now=now + timedelta(seconds=1))
    assert pending.state == RegistrationOperationState.RUNNING
    assert pending.cancellation_requested is True
    assert pending.lease_token == claimed.lease_token
    assert pending.fencing_token == claimed.fencing_token
    assert store.cancel(claimed.operation_id, now=now + timedelta(seconds=2)) == pending
    observed = store.heartbeat(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        lease_seconds=30,
        now=now + timedelta(seconds=2),
    )
    assert observed.cancellation_requested is True

    with pytest.raises(RegistrationOperationCancellationRequestedError, match="acknowledge cancellation"):
        store.finish(
            observed.operation_id,
            lease_token=observed.lease_token or "",
            fencing_token=observed.fencing_token,
            state=RegistrationOperationState.PROPOSED,
            proposal_ref=_ref(claimed.target_job_id, "RegistrationProposalArtifact"),
            qa_report_ref=_ref(claimed.target_job_id, "RegistrationQAReport"),
            now=now + timedelta(seconds=3),
        )

    cancelled = store.finish(
        observed.operation_id,
        lease_token=observed.lease_token or "",
        fencing_token=observed.fencing_token,
        state=RegistrationOperationState.CANCELLED,
        now=now + timedelta(seconds=4),
    )
    assert cancelled.state == RegistrationOperationState.CANCELLED
    assert cancelled.cancellation_requested is True
    assert cancelled.lease_token is None


def test_running_cancellation_flag_is_bound_by_operation_checksum(tmp_path: Path) -> None:
    database, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=30, now=now)
    assert claimed is not None
    store.cancel(claimed.operation_id, now=now + timedelta(seconds=1))

    with database.transaction(write=True) as tx:
        row = tx.execute(
            "SELECT payload FROM r2s_registration_operations WHERE operation_id=?", (request.request_id,)
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["cancellation_requested"] = False
        tx.execute(
            "UPDATE r2s_registration_operations SET payload=? WHERE operation_id=?",
            (json.dumps(payload), request.request_id),
        )

    with pytest.raises(RuntimeStateConflictError, match="checksum mismatch"):
        store.get(request.request_id)


def test_expired_running_cancellation_fails_instead_of_claiming_cancel_success(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=1, now=now)
    assert claimed is not None
    pending = store.cancel(claimed.operation_id, now=now + timedelta(seconds=2))
    assert pending.state == RegistrationOperationState.RUNNING
    assert pending.cancellation_requested is True

    assert store.claim_next("worker-b", lease_seconds=10, now=now + timedelta(seconds=3)) is None
    expired = store.get(claimed.operation_id)
    assert expired.state == RegistrationOperationState.FAILED
    assert expired.error == "Worker lease expired before cancellation was acknowledged; submit a new request to retry."


def test_database_columns_cannot_diverge_from_the_sealed_operation_payload(tmp_path: Path) -> None:
    database, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")

    with database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_registration_operations SET state=? WHERE operation_id=?",
            (RegistrationOperationState.FAILED.value, request.request_id),
        )

    with pytest.raises(RuntimeStateConflictError, match="columns differ"):
        store.get(request.request_id)


def test_mutated_operation_payload_fails_its_content_checksum(tmp_path: Path) -> None:
    database, store = _store(tmp_path)
    request = _request()
    store.enqueue(request, "request-key-1")

    with database.transaction(write=True) as tx:
        row = tx.execute(
            "SELECT payload FROM r2s_registration_operations WHERE operation_id=?", (request.request_id,)
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["error"] = "tampered"
        tx.execute(
            "UPDATE r2s_registration_operations SET payload=? WHERE operation_id=?",
            (json.dumps(payload), request.request_id),
        )

    with pytest.raises(RuntimeStateConflictError, match="checksum mismatch"):
        store.get(request.request_id)


def test_two_workers_cannot_claim_the_same_registration_operation(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    store.enqueue(_request(), "request-key-1")

    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = list(workers.map(lambda worker: store.claim_next(worker, lease_seconds=60), ("worker-a", "worker-b")))

    assert sum(claim is not None for claim in claims) == 1
    assert store.get("registration-request-1").attempt == 1


def test_heartbeat_and_finish_require_current_lease_and_bind_outputs(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    store.enqueue(_request(), "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=10, now=now)
    assert claimed is not None and claimed.lease_token is not None

    with pytest.raises(RegistrationOperationLeaseLostError):
        store.heartbeat(
            claimed.operation_id,
            lease_token="stale-token",
            fencing_token=claimed.fencing_token,
            lease_seconds=10,
            now=now + timedelta(seconds=1),
        )
    renewed = store.heartbeat(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        lease_seconds=20,
        now=now + timedelta(seconds=5),
    )
    finished = store.finish(
        renewed.operation_id,
        lease_token=renewed.lease_token or "",
        fencing_token=renewed.fencing_token,
        state=RegistrationOperationState.PROPOSED,
        proposal_ref=_ref(renewed.target_job_id, "RegistrationProposalArtifact"),
        qa_report_ref=_ref(renewed.target_job_id, "RegistrationQAReport"),
        now=now + timedelta(seconds=6),
    )

    assert finished.state == RegistrationOperationState.PROPOSED
    assert store.get(finished.operation_id).qa_report_ref == finished.qa_report_ref


def test_finish_rejects_proposal_artifacts_from_another_job(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    store.enqueue(_request(), "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=10, now=now)
    assert claimed is not None and claimed.lease_token is not None

    with pytest.raises(ValidationError, match="target job"):
        store.finish(
            claimed.operation_id,
            lease_token=claimed.lease_token,
            fencing_token=claimed.fencing_token,
            state=RegistrationOperationState.PROPOSED,
            proposal_ref=_ref("other-job", "RegistrationProposalArtifact"),
            qa_report_ref=_ref(claimed.target_job_id, "RegistrationQAReport"),
            now=now + timedelta(seconds=1),
        )
    assert store.get(claimed.operation_id).state == RegistrationOperationState.RUNNING


def test_expired_lease_fails_closed_and_old_worker_cannot_publish(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    store.enqueue(_request(), "request-key-1")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    claimed = store.claim_next("worker-a", lease_seconds=5, now=now)
    assert claimed is not None and claimed.lease_token is not None

    assert store.claim_next("worker-b", lease_seconds=5, now=now + timedelta(seconds=6)) is None
    expired = store.get(claimed.operation_id)
    assert expired.state == RegistrationOperationState.FAILED
    assert expired.error and "lease expired" in expired.error
    with pytest.raises(RegistrationOperationLeaseLostError):
        store.finish(
            claimed.operation_id,
            lease_token=claimed.lease_token,
            fencing_token=claimed.fencing_token,
            state=RegistrationOperationState.FAILED,
            error="late result",
            now=now + timedelta(seconds=7),
        )
