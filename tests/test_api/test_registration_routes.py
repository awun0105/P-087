from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from src.api import auth as auth_api
from src.api.product import registration as registration_api
from src.main import app
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.identity import artifact_model_checksum, artifact_model_payload
from src.models.contracts.input_assembly import DistanceUnit, InputAssetFormat, InputRole
from src.models.contracts.manifests import StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationCandidate,
    RegistrationFindingCode,
    RegistrationInputMode,
    RegistrationProfile,
    RegistrationProposal,
    RegistrationProposalState,
    RegistrationQAReport,
    RegistrationQAStatus,
    RegistrationRequest,
    RegistrationROI,
    RegistrationSourceBinding,
    registration_preflight,
    seal_registration_profile,
    seal_registration_proposal,
    seal_registration_qa_report,
    seal_registration_request,
)
from src.services.orchestration.auth.models import UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.registration_operations import RegistrationOperationStore
from src.services.orchestration.projects import ProjectRegistry

_ZERO = "sha256:" + "0" * 64
_JOB_ID = "job-fixture-001"


def _checksum(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _user(role: str) -> UserRecord:
    return UserRecord(
        user_id=f"user-{role}",
        email=f"{role}@example.test",
        display_name=role.title(),
        role=role,  # type: ignore[arg-type]
        password_hash="test-only-hash",
        created_at=datetime.now(UTC),
    )


class _AuditRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, dict[str, str]]] = []

    def audit(self, actor_id: str, action: str, target: str, details: dict[str, str]) -> None:
        self.events.append((actor_id, action, target, details))


@contextmanager
def _session(user: UserRecord | None) -> Iterator[None]:
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def _runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner_user_id: str | None = "user-guest",
    persistent: bool = True,
) -> tuple[ProjectRegistry, RuntimeDatabase | None, str, _AuditRecorder]:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.sqlite'}") if persistent else None
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database)
    registry.seed_from_fixtures()
    scene_revision = registry.scene.current(_JOB_ID).scene.scene_revision
    monkeypatch.setattr(registration_api.deps, "registry", lambda: registry)
    monkeypatch.setattr(registry, "get_job_owner_user_id", lambda _job_id: owner_user_id)
    audit = _AuditRecorder()
    monkeypatch.setattr(auth_api, "auth_service", lambda: audit)
    return registry, database, scene_revision, audit


def _request(
    registry: ProjectRegistry,
    scene_revision: str,
    requester_id: str,
    *,
    request_id: str = "registration-request-1",
    target_job_id: str = _JOB_ID,
    target_project_id: str | None = None,
    source_point_count: int | None = 1_000,
) -> RegistrationRequest:
    project_id = target_project_id or registry.get_job(_JOB_ID).project_id
    profile: RegistrationProfile = seal_registration_profile(
        {
            "profile_id": "registration-route-test-profile",
            "qualification_state": "provisional",
            "qualification_record_ref": None,
            "profile_checksum": _ZERO,
        }
    )
    source = RegistrationSourceBinding(
        mode=RegistrationInputMode.STATIC_CLOUD,
        target_job_id=target_job_id,
        authorized_project_id=project_id,
        source_input_checksum=_checksum("map-source"),
        source_frame="lidar-map-frame",
        source_distance_unit=DistanceUnit.METER,
        source_point_count=source_point_count,
        source_format=InputAssetFormat.POINT_CLOUD_PCD,
        source_header_checksum=_checksum("pcd-header"),
        source_role=InputRole.STATIC_LIDAR_CLOUD,
        input_assembly_id="assembly-registration-1",
        input_assembly_revision=1,
        input_assembly_checksum=_checksum("assembly-revision-1"),
        source_file_ids=["map-file-1"],
        same_scene_attestation=True,
    )
    target_ref = ProductArtifactRef(
        artifact_type="RgbGeometry",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{target_job_id}/rgb/geometry.json",
        artifact_checksum=_checksum("rgb-geometry"),
        data_class="derived",
        producer_stage=StageId.RGB_GEOMETRY,
        job_id=target_job_id,
    )
    metric_ref = ProductArtifactRef(
        artifact_type="RGBMetricConfirmation",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{target_job_id}/metric/confirmation.json",
        artifact_checksum=_checksum("metric-confirmation"),
        data_class="derived",
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=target_job_id,
    )
    floor_ref = ProductArtifactRef(
        artifact_type="FloorFitEvidence",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{target_job_id}/registration/floor-fit.json",
        artifact_checksum=_checksum("floor-evidence"),
        data_class="derived",
        producer_stage=StageId.OBJECT_EXTRACT,
        job_id=target_job_id,
    )
    return seal_registration_request(
        {
            "request_id": request_id,
            "requested_by": requester_id,
            "target_project_id": project_id,
            "target_job_id": target_job_id,
            "target_rgb_geometry_ref": target_ref,
            "expected_scene_revision": scene_revision,
            "source": source,
            "metric_state": "confirmed",
            "metric_confirmation_ref": metric_ref,
            "floor_state": "supported",
            "floor_model_refs": [floor_ref],
            "target_roi_world": RegistrationROI(min_xyz_m=(-20, -20, -2), max_xyz_m=(20, 20, 8)),
            "profile": profile,
            "profile_checksum": profile.profile_checksum,
            "request_checksum": _ZERO,
        }
    )


def _inspection_outputs(
    registry: ProjectRegistry,
    request: RegistrationRequest,
    *,
    include_proposal_ref: bool = True,
) -> tuple[SimpleNamespace, ProductArtifactRef]:
    source_ref = ProductArtifactRef(
        artifact_type="LiDARGeometryArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{request.target_job_id}/lidar/geometry.json",
        artifact_checksum=_checksum("lidar-geometry"),
        data_class="derived",
        producer_stage=StageId.LIDAR_INGEST,
        job_id=request.target_job_id,
    )
    candidate = RegistrationCandidate(
        candidate_id="candidate-inspection-1",
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame=request.source.source_frame,
            translation_xyz=(1.0, 2.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        score=0.95,
    )
    proposal: RegistrationProposal = seal_registration_proposal(
        {
            "job_id": request.target_job_id,
            "input_mode": request.source.mode,
            "request_checksum": request.request_checksum,
            "source_input_checksum": request.source.source_input_checksum,
            "source_geometry_ref": source_ref,
            "target_rgb_geometry_ref": request.target_rgb_geometry_ref,
            "target_scene_revision": request.expected_scene_revision,
            "profile_checksum": request.profile_checksum,
            "tool_checksum": _checksum("registration-tool"),
            "source_frame": request.source.source_frame,
            "state": RegistrationProposalState.PROPOSED,
            "candidates": [candidate],
            "selected_candidate_id": candidate.candidate_id,
            "findings": [],
            "proposal_checksum": _ZERO,
        }
    )
    provenance = {
        "operation_id": request.request_id,
        "registration_request_checksum": request.request_checksum,
    }
    proposal_ref = ProductArtifactRef(
        artifact_type="RegistrationProposalArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{request.target_job_id}/rgb-lidar-align/inspection/proposal.json",
        artifact_checksum=artifact_model_checksum(proposal),
        data_class="derived",
        producer_stage=StageId.RGB_LIDAR_ALIGN,
        job_id=request.target_job_id,
        source_provenance=provenance,
    )
    report: RegistrationQAReport = seal_registration_qa_report(
        {
            "job_id": request.target_job_id,
            "input_mode": request.source.mode,
            "request_checksum": request.request_checksum,
            "proposal_ref": proposal_ref,
            "proposal_checksum": proposal.proposal_checksum,
            "source_input_checksum": request.source.source_input_checksum,
            "source_geometry_checksum": source_ref.artifact_checksum,
            "target_geometry_checksum": request.target_rgb_geometry_ref.artifact_checksum,
            "target_scene_revision": request.expected_scene_revision,
            "profile": request.profile,
            "profile_checksum": request.profile_checksum,
            "metric_state": request.metric_state,
            "floor_state": request.floor_state,
            "same_scene_attestation": request.source.same_scene_attestation,
            "result": RegistrationQAStatus.INCONCLUSIVE,
            "findings": [RegistrationFindingCode.UNQUALIFIED_PROFILE],
            "report_checksum": _ZERO,
        }
    )
    report_ref = ProductArtifactRef(
        artifact_type="RegistrationQAReport",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{request.target_job_id}/rgb-lidar-align/inspection/qa.json",
        artifact_checksum=artifact_model_checksum(report),
        data_class="derived",
        producer_stage=StageId.RGB_LIDAR_ALIGN,
        job_id=request.target_job_id,
        source_provenance=provenance,
    )
    for reference, model in ((proposal_ref, proposal), (report_ref, report)):
        path = registry.runtime_resolver.resolve(reference.artifact_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact_model_payload(model))
    record = SimpleNamespace(
        operation_id=request.request_id,
        target_job_id=request.target_job_id,
        request=request,
        request_checksum=request.request_checksum,
        proposal_ref=proposal_ref if include_proposal_ref else None,
        qa_report_ref=report_ref,
    )
    return record, proposal_ref


def _seed_user(database: RuntimeDatabase, user_id: str) -> None:
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_users(user_id,email,payload) VALUES (?,?,?)",
            (user_id, f"{user_id}@example.test", "{}"),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "owner_user_id", "expected_status"),
    [
        ("guest", "user-guest", 202),
        ("guest", "user-another", 403),
        ("editor", "user-guest", 202),
        ("reviewer", "user-guest", 202),
    ],
)
async def test_enqueue_enforces_job_ownership_and_preserves_operator_intervention(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    role: str,
    owner_user_id: str,
    expected_status: int,
) -> None:
    registry, database, revision, audit = _runtime(tmp_path, monkeypatch, owner_user_id=owner_user_id)
    assert database is not None
    user = _user(role)
    _seed_user(database, user.user_id)
    request = _request(registry, revision, user.user_id)

    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations",
            json=request.model_dump(mode="json"),
            headers={"Idempotency-Key": f"registration-{role}"},
        )

    assert response.status_code == expected_status, response.text
    with database.transaction() as tx:
        count = tx.execute("SELECT COUNT(*) FROM r2s_registration_operations").fetchone()[0]
    assert count == (1 if expected_status == 202 else 0)
    if role in {"editor", "reviewer"}:
        assert audit.events[0][0] == user.user_id
        assert audit.events[0][1] == "operator.intervention"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_status"),
    [("stale_scene", 409), ("wrong_requester", 403), ("wrong_project", 409), ("insufficient", 422)],
)
async def test_enqueue_rejects_stale_identity_or_insufficient_preflight_without_queueing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
    expected_status: int,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    user = _user("guest")
    _seed_user(database, user.user_id)
    request = _request(registry, revision, user.user_id)
    if case == "stale_scene":
        request = _request(registry, "stale-revision", user.user_id)
    elif case == "wrong_requester":
        request = _request(registry, revision, "user-someone-else")
    elif case == "wrong_project":
        request = _request(registry, revision, user.user_id, target_project_id="project-other")
    else:
        request = _request(registry, revision, user.user_id, source_point_count=None)

    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations",
            json=request.model_dump(mode="json"),
            headers={"Idempotency-Key": "registration-invalid"},
        )

    assert response.status_code == expected_status, response.text
    with database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_registration_operations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_enqueue_replays_idempotently_and_rejects_key_reuse_for_another_request(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    user = _user("guest")
    _seed_user(database, user.user_id)
    first = _request(registry, revision, user.user_id)
    second = _request(registry, revision, user.user_id, request_id="registration-request-2")
    url = f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations"
    headers = {"Idempotency-Key": "registration-once"}

    with _session(user):
        accepted = await client.post(url, json=first.model_dump(mode="json"), headers=headers)
        replay = await client.post(url, json=first.model_dump(mode="json"), headers=headers)
        conflict = await client.post(url, json=second.model_dump(mode="json"), headers=headers)

    assert accepted.status_code == replay.status_code == 202
    assert accepted.json()["operation_id"] == replay.json()["operation_id"] == first.request_id
    assert conflict.status_code == 409
    with database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_registration_operations").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_status_and_cancel_are_job_bound_and_hide_worker_internal_fields(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    user = _user("guest")
    _seed_user(database, user.user_id)
    request = _request(registry, revision, user.user_id)
    other_job_id = "job-registration-other"
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES (?,?,?,?)",
            (other_job_id, registry.get_job(_JOB_ID).project_id, 1, f"artifact://jobs/{other_job_id}/manifest.json"),
        )
    other_request = _request(
        registry,
        revision,
        user.user_id,
        request_id="registration-request-other-job",
        target_job_id=other_job_id,
    )
    store = RegistrationOperationStore(database)
    store.enqueue(request, "registration-status")
    store.enqueue(other_request, "registration-other-job")
    base = f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}"
    mismatched_path = f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{other_request.request_id}"

    with _session(user):
        status_response = await client.get(base)
        cancelled = await client.post(f"{base}/cancel")
        cancelled_again = await client.post(f"{base}/cancel")
        wrong_job = await client.get(
            f"/api/v1/jobs/job-not-this-one/rgb-lidar-registration/operations/{request.request_id}"
        )
        mismatched_operation = await client.get(mismatched_path)
        mismatched_cancel = await client.post(f"{mismatched_path}/cancel")

    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["state"] == "QUEUED"
    assert {"request", "idempotency_key", "lease_token", "worker_id", "error"}.isdisjoint(status_response.json())
    assert cancelled.status_code == cancelled_again.status_code == 200
    assert cancelled.json()["state"] == cancelled_again.json()["state"] == "CANCELLED"
    assert wrong_job.status_code == 404
    assert mismatched_operation.status_code == mismatched_cancel.status_code == 404
    assert store.get(request.request_id).state.value == "CANCELLED"
    assert store.get(other_request.request_id).state.value == "QUEUED"


@pytest.mark.asyncio
async def test_durable_registration_routes_fail_closed_without_persistence(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch, persistent=False)
    assert database is None
    user = _user("guest")
    request = _request(registry, revision, user.user_id)

    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations",
            json=request.model_dump(mode="json"),
            headers={"Idempotency-Key": "registration-no-db"},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_enqueue_requires_authenticated_requester_identity(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    request = _request(registry, revision, "user-guest")

    with _session(None):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations",
            json=request.model_dump(mode="json"),
            headers={"Idempotency-Key": "registration-anonymous"},
        )

    assert response.status_code == 401
    with database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_registration_operations").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "owner_user_id", "expected_status"),
    [
        ("guest", "user-guest", 200),
        ("guest", "user-another", 403),
        ("editor", "user-guest", 200),
        ("reviewer", "user-guest", 200),
    ],
)
async def test_prepare_uses_job_mutation_policy_and_does_not_enqueue(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    role: str,
    owner_user_id: str,
    expected_status: int,
) -> None:
    registry, database, revision, audit = _runtime(tmp_path, monkeypatch, owner_user_id=owner_user_id)
    assert database is not None
    user = _user(role)
    _seed_user(database, user.user_id)
    request = _request(registry, revision, user.user_id)
    prepared = SimpleNamespace(request=request, preflight=registration_preflight(request))

    class _Preparer:
        def prepare(self, job, *, requested_by: str, expected_scene_revision: str):
            assert job.job_id == _JOB_ID
            assert requested_by == user.user_id
            assert expected_scene_revision == revision
            return prepared

    monkeypatch.setattr(registration_api, "_request_preparer", lambda _registry: _Preparer())
    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/prepare",
            json={"expected_scene_revision": revision},
        )

    assert response.status_code == expected_status, response.text
    with database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_registration_operations").fetchone()[0] == 0
    if expected_status == 200:
        assert response.json()["request"]["request_checksum"] == request.request_checksum
        assert response.json()["preflight"]["state"] == "READY"
        if role in {"editor", "reviewer"}:
            assert audit.events[0][0] == user.user_id
            assert audit.events[0][1] == "operator.intervention"


@pytest.mark.asyncio
async def test_prepare_requires_auth_current_revision_and_accepted_input_run(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, database, revision, _ = _runtime(tmp_path, monkeypatch)
    user = _user("guest")
    assert database is not None
    _seed_user(database, user.user_id)

    with _session(None):
        anonymous = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/prepare",
            json={"expected_scene_revision": revision},
        )
    with _session(user):
        stale = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/prepare",
            json={"expected_scene_revision": "stale-revision"},
        )
        missing_run = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/prepare",
            json={"expected_scene_revision": revision},
        )

    assert anonymous.status_code == 401
    assert stale.status_code == 409
    assert missing_run.status_code == 422
    with database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_registration_operations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_prepare_requires_persistent_runtime_database(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, database, revision, _ = _runtime(tmp_path, monkeypatch, persistent=False)
    assert database is None

    with _session(_user("guest")):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/prepare",
            json={"expected_scene_revision": revision},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_inspection_loads_verified_outputs_and_marks_stale_scene_revision(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _, current_revision, _ = _runtime(tmp_path, monkeypatch)
    user = _user("guest")
    request = _request(registry, "scene-revision-before-edit", user.user_id)
    record, proposal_ref = _inspection_outputs(registry, request, include_proposal_ref=False)
    monkeypatch.setattr(
        registration_api,
        "_operation_store",
        lambda _registry: SimpleNamespace(get=lambda _operation_id: record),
    )

    with _session(user):
        response = await client.get(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/inspection"
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["operation_id"] == request.request_id
    assert payload["expected_scene_revision"] == "scene-revision-before-edit"
    assert payload["current_scene_revision"] == current_revision
    assert payload["proposal"]["proposal_checksum"] == payload["qa_report"]["proposal_checksum"]
    assert payload["qa_report"]["proposal_ref"]["artifact_checksum"] == proposal_ref.artifact_checksum
    assert payload["qa_report"]["result"] == "INCONCLUSIVE"
    assert registry.scene.current(_JOB_ID).scene.scene_revision == current_revision


@pytest.mark.asyncio
async def test_inspection_rejects_corrupt_output_bytes(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _, revision, _ = _runtime(tmp_path, monkeypatch)
    user = _user("guest")
    request = _request(registry, revision, user.user_id)
    record, _ = _inspection_outputs(registry, request)
    proposal_path = registry.runtime_resolver.resolve(record.proposal_ref.artifact_uri)
    proposal_path.write_bytes(b"tampered")
    monkeypatch.setattr(
        registration_api,
        "_operation_store",
        lambda _registry: SimpleNamespace(get=lambda _operation_id: record),
    )

    with _session(user):
        response = await client.get(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/inspection"
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Registration outputs are missing, corrupt, or bound to different evidence"


@pytest.mark.asyncio
async def test_inspection_rejects_output_reference_from_another_operation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _, revision, _ = _runtime(tmp_path, monkeypatch)
    user = _user("guest")
    request = _request(registry, revision, user.user_id)
    record, _ = _inspection_outputs(registry, request)
    record.proposal_ref = record.proposal_ref.model_copy(
        update={
            "source_provenance": {
                **record.proposal_ref.source_provenance,
                "operation_id": "another-registration-operation",
            }
        }
    )
    monkeypatch.setattr(
        registration_api,
        "_operation_store",
        lambda _registry: SimpleNamespace(get=lambda _operation_id: record),
    )

    with _session(user):
        response = await client.get(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/inspection"
        )

    assert response.status_code == 409


@pytest.mark.parametrize(
    ("reference_name", "updates"),
    [
        ("proposal_ref", {"producer_stage": "FRAME_EXTRACT"}),
        ("qa_report_ref", {"data_class": "product_input"}),
        ("proposal_ref", {"artifact_uri": "artifact://jobs/job-another/rgb-lidar-align/proposal.json"}),
        ("proposal_ref", {"source_provenance": None}),
    ],
)
@pytest.mark.asyncio
async def test_inspection_rejects_output_reference_outside_verified_scope(
    reference_name: str,
    updates: dict[str, object],
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _, revision, _ = _runtime(tmp_path, monkeypatch)
    user = _user("guest")
    request = _request(registry, revision, user.user_id)
    record, _ = _inspection_outputs(registry, request)
    reference = getattr(record, reference_name)
    setattr(record, reference_name, reference.model_copy(update=updates))
    monkeypatch.setattr(
        registration_api,
        "_operation_store",
        lambda _registry: SimpleNamespace(get=lambda _operation_id: record),
    )

    with _session(user):
        response = await client.get(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/inspection"
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_inspection_hides_operation_bound_to_another_job(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _, revision, _ = _runtime(tmp_path, monkeypatch)
    user = _user("guest")
    request = _request(registry, revision, user.user_id)
    record, _ = _inspection_outputs(registry, request)
    record.target_job_id = "job-another"
    monkeypatch.setattr(
        registration_api,
        "_operation_store",
        lambda _registry: SimpleNamespace(get=lambda _operation_id: record),
    )

    with _session(user):
        response = await client.get(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/inspection"
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_inspection_requires_an_authenticated_contributor(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _runtime(tmp_path, monkeypatch)

    with _session(None):
        response = await client.get(f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/unknown/inspection")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_enqueue_keeps_sensor_package_on_existing_finalize_path(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    user = _user("guest")
    _seed_user(database, user.user_id)
    request = _request(registry, revision, user.user_id)
    package_checksum = _checksum("lidar-package-record")
    package_ref = ProductArtifactRef(
        artifact_type="LidarPackageRecord",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB_ID}/lidar/package.json",
        artifact_checksum=package_checksum,
        data_class="derived",
        producer_stage=StageId.LIDAR_INGEST,
        job_id=_JOB_ID,
    )
    package_source = RegistrationSourceBinding(
        mode=RegistrationInputMode.SENSOR_PACKAGE,
        target_job_id=_JOB_ID,
        authorized_project_id=registry.get_job(_JOB_ID).project_id,
        source_input_checksum=package_checksum,
        source_frame="lidar-sensor-frame",
        source_distance_unit=DistanceUnit.METER,
        source_point_count=1_000,
        lidar_package_ref=package_ref,
    )
    request = seal_registration_request(
        request.model_copy(
            update={"source": package_source, "target_roi_world": None, "request_checksum": _ZERO}
        ).model_dump(mode="json")
    )

    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations",
            json=request.model_dump(mode="json"),
            headers={"Idempotency-Key": "registration-sensor-package"},
        )

    assert response.status_code == 422, response.text
    with database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_registration_operations").fetchone()[0] == 0
