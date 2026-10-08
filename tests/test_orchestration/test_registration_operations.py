import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

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
    RegistrationOperationLeaseLostError,
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
    assert LATEST_SCHEMA_VERSION == 18
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
