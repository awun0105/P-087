from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from httpx import AsyncClient

from src.api import auth as auth_api
from src.api.product import registration as registration_api
from src.main import app
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import MetricScale, Transform
from src.models.contracts.identity import artifact_model_checksum, artifact_model_payload, canonical_content_checksum
from src.models.contracts.input_assembly import DistanceUnit, InputAssetFormat, InputRole
from src.models.contracts.manifests import InputConfiguration, StageId
from src.models.contracts.reconstruction import PreprocessingProvenance, ReconstructionBundle
from src.models.contracts.rgb_lidar_registration import (
    RegistrationCandidate,
    RegistrationFindingCode,
    RegistrationInputMode,
    RegistrationOperationState,
    RegistrationOverlayPreview,
    RegistrationProfile,
    RegistrationProposal,
    RegistrationProposalState,
    RegistrationQAReport,
    RegistrationQAStatus,
    RegistrationRequest,
    RegistrationROI,
    RegistrationSourceBinding,
    registration_preflight,
    seal_registration_overlay_preview,
    seal_registration_profile,
    seal_registration_proposal,
    seal_registration_qa_report,
    seal_registration_request,
)
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.auth.models import UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.registration_operations import RegistrationOperationStore
from src.services.orchestration.projects import ProjectRegistry
from src.services.reconstruction.bundle import BundleBuildRequest, ReconstructionBundleService
from src.services.reconstruction.bundle_validation import BundleDependencies
from src.services.reconstruction.rgb.canonical.bundle_metric import _reference as metric_verification_reference
from src.services.reconstruction.rgb.canonical.bundle_metric_models import (
    BundleMetricAcceptance,
    BundleMetricRecord,
    BundleMetricRequest,
)
from src.services.reconstruction.rgb.canonical.metric_models import DistanceAnchor
from src.services.scene.bundle_consumer import load_reconstruction_bundle

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
    include_overlay: bool = False,
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
    overlay_ref: ProductArtifactRef | None = None
    overlay: RegistrationOverlayPreview | None = None
    if include_overlay:
        assert request.target_roi_world is not None
        overlay = seal_registration_overlay_preview(
            {
                "job_id": request.target_job_id,
                "operation_id": request.request_id,
                "input_mode": request.source.mode,
                "request_checksum": request.request_checksum,
                "source_input_checksum": request.source.source_input_checksum,
                "source_geometry_ref": source_ref,
                "target_rgb_geometry_ref": request.target_rgb_geometry_ref,
                "target_scene_revision": request.expected_scene_revision,
                "request_target_roi_world": request.target_roi_world,
                "target_floor_evidence_checksum": request.floor_evidence_refs[0].artifact_checksum,
                "profile_checksum": request.profile_checksum,
                "candidate_id": candidate.candidate_id,
                "source_frame": proposal.source_frame,
                "transform_target_from_source": candidate.transform_target_from_source,
                "rgb_scale_factor": candidate.rgb_scale_factor,
                "bounds_min_xy_m": [-20.0, -20.0],
                "bounds_max_xy_m": [20.0, 20.0],
                "source_in_roi_point_count": 1,
                "target_in_roi_point_count": 1,
                "source_points_xy_world_m": [[1.0, 2.0]],
                "target_points_xy_world_m": [[3.0, 4.0]],
                "sample_cap_per_cloud": 512,
                "diagnostic_only": True,
                "preview_checksum": _ZERO,
            }
        )
        overlay_ref = ProductArtifactRef(
            artifact_type="RegistrationOverlayPreview",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{request.target_job_id}/rgb-lidar-align/inspection/overlay.json",
            artifact_checksum=artifact_model_checksum(overlay),
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
            "evidence_refs": [overlay_ref] if overlay_ref is not None else [],
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
    outputs = [(proposal_ref, proposal), (report_ref, report)]
    if overlay_ref is not None and overlay is not None:
        outputs.append((overlay_ref, overlay))
    for reference, model in outputs:
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


def _persist_proposed_operation(
    database: RuntimeDatabase,
    request: RegistrationRequest,
    proposal_ref: ProductArtifactRef,
    report_ref: ProductArtifactRef,
) -> tuple[RegistrationOperationStore, object]:
    store = RegistrationOperationStore(database)
    store.enqueue(request, f"confirm-{request.request_id}")
    claimed = store.claim_next("registration-confirmation-test", lease_seconds=60)
    assert claimed is not None and claimed.lease_token is not None
    proposed = store.finish(
        claimed.operation_id,
        lease_token=claimed.lease_token,
        fencing_token=claimed.fencing_token,
        state=RegistrationOperationState.PROPOSED,
        proposal_ref=proposal_ref,
        qa_report_ref=report_ref,
    )
    return store, proposed


def _confirmation_inspection(
    scene_revision: str,
    *,
    qa_result: RegistrationQAStatus = RegistrationQAStatus.PASS,
    selected_candidate_id: str = "candidate-inspection-1",
    report_candidate_id: str = "candidate-inspection-1",
    overlay_candidate_id: str | None = "candidate-inspection-1",
    rgb_scale_factor: float | None = None,
    current_scene_revision: str | None = None,
) -> SimpleNamespace:
    proposal = SimpleNamespace(
        state=RegistrationProposalState.PROPOSED,
        selected_candidate_id=selected_candidate_id,
        candidates=[SimpleNamespace(candidate_id=selected_candidate_id, rgb_scale_factor=rgb_scale_factor)],
    )
    qa_report = SimpleNamespace(result=qa_result, candidate_id=report_candidate_id)
    overlays = [] if overlay_candidate_id is None else [SimpleNamespace(candidate_id=overlay_candidate_id)]
    return SimpleNamespace(
        expected_scene_revision=scene_revision,
        current_scene_revision=current_scene_revision or scene_revision,
        proposal=proposal,
        qa_report=qa_report,
        overlay_previews=overlays,
    )


def _seed_user(database: RuntimeDatabase, user_id: str) -> None:
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_users(user_id,email,payload) VALUES (?,?,?)",
            (user_id, f"{user_id}@example.test", "{}"),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["guest", "editor", "reviewer"])
async def test_confirm_persists_only_the_exact_qa_candidate_without_mutating_scene(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    role: str,
) -> None:
    registry, database, revision, audit = _runtime(tmp_path, monkeypatch)
    assert database is not None
    user = _user(role)
    if user.user_id != "user-guest":
        _seed_user(database, "user-guest")
    _seed_user(database, user.user_id)
    request = _request(registry, revision, "user-guest")
    outputs, _ = _inspection_outputs(registry, request, include_overlay=True)
    store, proposed = _persist_proposed_operation(database, request, outputs.proposal_ref, outputs.qa_report_ref)
    monkeypatch.setattr(
        registration_api,
        "_verified_registration_inspection",
        lambda _registry, _record: _confirmation_inspection(revision),
    )
    # This test owns the S4n confirmation contract; consumer publication has its
    # own integration test below.
    monkeypatch.setattr(
        registration_api,
        "_commit_or_conflict",
        lambda _registry, _store, record: registration_api._public_operation(record),
    )
    before_scene = registry.scene.current(_JOB_ID).scene
    payload = {
        "expected_operation_checksum": proposed.operation_checksum,
        "expected_scene_revision": revision,
        "candidate_id": "candidate-inspection-1",
    }

    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/confirm",
            json=payload,
        )

    assert response.status_code == 200, response.text
    response_payload = response.json()
    assert response_payload["state"] == RegistrationOperationState.CONFIRMED.value
    assert response_payload["confirmed_candidate_id"] == "candidate-inspection-1"
    assert response_payload["confirmed_by_user_id"] == user.user_id
    assert response_payload["operation_checksum"].startswith("sha256:")
    confirmed = store.get(request.request_id)
    assert confirmed.confirmed_from_checksum == proposed.operation_checksum
    assert confirmed.confirmed_candidate_id == "candidate-inspection-1"
    assert confirmed.confirmed_by_user_id == user.user_id
    assert registry.scene.current(_JOB_ID).scene == before_scene
    if role in {"editor", "reviewer"}:
        assert audit.events and audit.events[-1][0] == user.user_id
        assert audit.events[-1][1] == "operator.intervention"

    with _session(user):
        replay = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/confirm",
            json=payload,
        )
    assert replay.status_code == 200, replay.text
    assert replay.json() == response_payload
    assert store.get(request.request_id) == confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inspection_kwargs", "candidate_id"),
    [
        ({"qa_result": RegistrationQAStatus.INCONCLUSIVE}, "candidate-inspection-1"),
        ({"current_scene_revision": "scene-revision-stale"}, "candidate-inspection-1"),
        ({"report_candidate_id": "candidate-other"}, "candidate-inspection-1"),
        ({"overlay_candidate_id": None}, "candidate-inspection-1"),
        ({"rgb_scale_factor": 1.1}, "candidate-inspection-1"),
        ({}, "candidate-other"),
    ],
)
async def test_confirm_rejects_unqualified_stale_or_changed_candidates(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    inspection_kwargs: dict[str, object],
    candidate_id: str,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    user = _user("guest")
    _seed_user(database, user.user_id)
    request = _request(registry, revision, user.user_id)
    outputs, _ = _inspection_outputs(registry, request, include_overlay=True)
    store, proposed = _persist_proposed_operation(database, request, outputs.proposal_ref, outputs.qa_report_ref)
    monkeypatch.setattr(
        registration_api,
        "_verified_registration_inspection",
        lambda _registry, _record: _confirmation_inspection(revision, **inspection_kwargs),
    )

    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/confirm",
            json={
                "expected_operation_checksum": proposed.operation_checksum,
                "expected_scene_revision": revision,
                "candidate_id": candidate_id,
            },
        )

    assert response.status_code == 409, response.text
    persisted = store.get(request.request_id)
    assert persisted.state == RegistrationOperationState.PROPOSED
    assert persisted.operation_checksum == proposed.operation_checksum


@pytest.mark.asyncio
async def test_confirm_rejects_stale_operation_checksum_and_scene_revision(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    user = _user("guest")
    _seed_user(database, user.user_id)
    request = _request(registry, revision, user.user_id)
    outputs, _ = _inspection_outputs(registry, request, include_overlay=True)
    store, proposed = _persist_proposed_operation(database, request, outputs.proposal_ref, outputs.qa_report_ref)
    monkeypatch.setattr(
        registration_api,
        "_verified_registration_inspection",
        lambda _registry, _record: _confirmation_inspection(revision),
    )
    endpoint = f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/{request.request_id}/confirm"
    requests = (
        {
            "expected_operation_checksum": _checksum("stale operation checksum"),
            "expected_scene_revision": revision,
            "candidate_id": "candidate-inspection-1",
        },
        {
            "expected_operation_checksum": proposed.operation_checksum,
            "expected_scene_revision": "scene-revision-other",
            "candidate_id": "candidate-inspection-1",
        },
    )

    with _session(user):
        responses = [await client.post(endpoint, json=payload) for payload in requests]

    assert [response.status_code for response in responses] == [409, 409]
    persisted = store.get(request.request_id)
    assert persisted.state == RegistrationOperationState.PROPOSED
    assert persisted.operation_checksum == proposed.operation_checksum


@pytest.mark.asyncio
async def test_guest_cannot_confirm_another_users_registration_operation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, revision, _ = _runtime(tmp_path, monkeypatch, owner_user_id="user-another")
    user = _user("guest")

    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations/registration-request-1/confirm",
            json={
                "expected_operation_checksum": _checksum("no operation"),
                "expected_scene_revision": revision,
                "candidate_id": "candidate-inspection-1",
            },
        )

    assert response.status_code == 403


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
    ("runtime_status", "expected_status"),
    [("qualified", 202), ("wired_unqualified", 422)],
)
async def test_enqueue_accepts_estimated_map_only_after_runtime_qualification(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime_status: Literal["qualified", "wired_unqualified"],
    expected_status: int,
) -> None:
    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    user = _user("guest")
    _seed_user(database, user.user_id)
    request = _request(registry, revision, user.user_id)
    trajectory_ref = ProductArtifactRef(
        artifact_type="EstimatedTrajectoryProductEvidence",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB_ID}/attempts/attempt-registration/rec06/product.json",
        artifact_checksum=_checksum("estimated-trajectory"),
        data_class="derived",
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id=_JOB_ID,
    )
    map_ref = ProductArtifactRef(
        artifact_type="EstimatedTrajectoryMapCloud",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB_ID}/attempts/attempt-registration/rec06/map.ply",
        artifact_checksum=_checksum("estimated-map"),
        data_class="derived",
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id=_JOB_ID,
        source_provenance={"map_frame_id": "lidar-map-frame"},
    )
    source = RegistrationSourceBinding(
        mode=RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP,
        target_job_id=_JOB_ID,
        authorized_project_id=registry.get_job(_JOB_ID).project_id,
        source_input_checksum=map_ref.artifact_checksum,
        source_frame="lidar-map-frame",
        source_distance_unit=DistanceUnit.METER,
        source_point_count=1_000,
        source_format=InputAssetFormat.POINT_CLOUD_PLY,
        source_header_checksum=_checksum("estimated-map-header"),
        source_role=InputRole.LIDAR_SCAN,
        input_assembly_id="assembly-estimated-registration",
        input_assembly_revision=1,
        input_assembly_checksum=_checksum("estimated-assembly"),
        source_file_ids=["scan-1", "scan-2"],
        same_scene_attestation=True,
        estimated_trajectory_product_ref=trajectory_ref,
        estimated_map_cloud_ref=map_ref,
        odometry_runtime_qualification_status=runtime_status,
    )
    request = seal_registration_request(
        request.model_copy(update={"source": source, "request_checksum": _ZERO}).model_dump(mode="json")
    )
    expected_preflight = "READY" if runtime_status == "qualified" else "INSUFFICIENT"
    assert registration_preflight(request).state.value == expected_preflight

    with _session(user):
        response = await client.post(
            f"/api/v1/jobs/{_JOB_ID}/rgb-lidar-registration/operations",
            json=request.model_dump(mode="json"),
            headers={"Idempotency-Key": f"estimated-registration-{runtime_status}"},
        )

    assert response.status_code == expected_status, response.text
    with database.transaction() as tx:
        count = tx.execute("SELECT COUNT(*) FROM r2s_registration_operations").fetchone()[0]
    assert count == (1 if expected_status == 202 else 0)


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
async def test_inspection_returns_exact_candidate_overlay_from_qa_evidence(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _, revision, _ = _runtime(tmp_path, monkeypatch)
    user = _user("reviewer")
    request = _request(registry, revision, user.user_id)
    record, _ = _inspection_outputs(registry, request, include_overlay=True)
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
    previews = response.json()["overlay_previews"]
    assert len(previews) == 1
    assert previews[0]["candidate_id"] == "candidate-inspection-1"
    assert previews[0]["operation_id"] == request.request_id
    assert previews[0]["diagnostic_only"] is True
    assert previews[0]["source_points_xy_world_m"] == [[1.0, 2.0]]


@pytest.mark.asyncio
async def test_inspection_rejects_corrupt_overlay_bytes(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _, revision, _ = _runtime(tmp_path, monkeypatch)
    user = _user("reviewer")
    request = _request(registry, revision, user.user_id)
    record, _ = _inspection_outputs(registry, request, include_overlay=True)
    overlay_ref = next(
        reference
        for reference in registry.runtime_resolver.load_model(record.qa_report_ref, RegistrationQAReport).evidence_refs
        if reference.artifact_type == "RegistrationOverlayPreview"
    )
    registry.runtime_resolver.resolve(overlay_ref.artifact_uri).write_bytes(b"tampered")
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


def test_confirmed_registration_publishes_and_reloads_exact_mixed_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic publication exercises REC-09/10, manifest CAS and replay, not field QA."""
    from src.services.orchestration.jobs import registration_commit as commit_module
    from src.services.orchestration.jobs.registration_commit import RegistrationBundleCommitter

    registry, database, revision, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    _seed_user(database, "user-guest")
    writer = FilesystemArtifactStore(registry.runtime_resolver)
    request = _request(registry, revision, "user-guest", request_id="registration-commit-test")

    def publish_ref(
        artifact_type: str,
        stage: StageId,
        path: str,
        payload: bytes,
        source_provenance: dict[str, object] | None = None,
    ) -> ProductArtifactRef:
        reference = ProductArtifactRef(
            artifact_type=artifact_type,
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{_JOB_ID}/{path}",
            artifact_checksum=sha256_bytes(payload),
            data_class="derived",
            producer_stage=stage,
            job_id=_JOB_ID,
            source_provenance=source_provenance,
        )
        writer.publish(reference, payload)
        return reference

    writer.publish(request.target_rgb_geometry_ref, b"rgb-geometry")
    frame_ref = publish_ref("RGBFrame", StageId.FRAME_EXTRACT, "rec02/frame.bin", b"frame")
    pose_ref = publish_ref("CameraPoseArtifact", StageId.CAMERA_POSE, "rec03/pose.json", b"pose")
    visual_ref = publish_ref("VisualArtifact", StageId.VISUAL_RECON, "rec04/visual.json", b"visual")
    base_request = BundleBuildRequest(
        job_id=_JOB_ID,
        source_input_checksum=request.source.source_input_checksum,
        input_configuration=InputConfiguration(
            rgb_present=True,
            registered_lidar_present=False,
            declared_same_scene=True,
        ),
        metric_scale=MetricScale(status="CONFIRMED", meters_per_unit=1.0),
        rgb_frame_refs=[frame_ref],
        camera_pose_refs=[pose_ref],
        visual_artifact_ref=visual_ref,
        rgb_geometry_ref=request.target_rgb_geometry_ref,
        canonical_geometry_ref=request.target_rgb_geometry_ref,
        provenance={"evidence_kind": "synthetic_fixture"},
    )

    writer.publish(request.metric_confirmation_ref, b"metric-confirmation")
    decision_ref = publish_ref("SyntheticMetricEvidence", StageId.METRIC_CANONICALIZE, "metric/review.json", b"review")
    metric_request = BundleMetricRequest(
        execution_scope="synthetic_fixture",
        bundle=base_request,
        confirmation_ref=request.metric_confirmation_ref,
        canonical_visual_ref=visual_ref,
        independent_sample=DistanceAnchor(
            anchor_id="synthetic-independent-distance",
            source_master=visual_ref,
            point_a=(0.0, 0.0, 0.0),
            point_b=(0.0, 0.0, 1.0),
            distance_m=1.0,
            measurement_ref=visual_ref,
        ),
        tolerance_m=0.02,
    )
    acceptance = BundleMetricAcceptance(
        request_checksum=metric_request.checksum(),
        evidence_kind="synthetic_fixture",
        decision_ref=decision_ref,
    )
    metric_record_data = {
        "schema_version": "1.0",
        "artifact_type": "ReconstructionMetricVerification",
        "scope": "canonical_rgb_bundle_metric",
        "status": "VERIFIED",
        "request": metric_request.model_dump(mode="json"),
        "acceptance": acceptance.model_dump(mode="json"),
        "independent_distance_error_m": 0.0,
        "record_checksum": _ZERO,
    }
    metric_record_data["record_checksum"] = canonical_content_checksum(metric_record_data, "record_checksum")
    metric_record = BundleMetricRecord.model_validate(metric_record_data)
    metric_payload = metric_record.model_dump_json(indent=2).encode() + b"\n"
    proof_ref = metric_verification_reference(metric_record, metric_payload)
    writer.publish(proof_ref, metric_payload)
    base_request_with_proof = base_request.model_copy(update={"verification_ref": proof_ref})
    base_dependencies = BundleDependencies(
        resolve=registry.runtime_resolver.require,
        verify_metric=lambda candidate: (
            candidate.verification_ref == proof_ref
            and candidate.model_copy(update={"verification_ref": None}) == base_request
        ),
    )
    base_bundle, _ = ReconstructionBundleService(writer, base_dependencies).build_and_publish(base_request_with_proof)
    monkeypatch.setattr(commit_module, "job_bundle", lambda _registry, _job: base_bundle)

    outputs, _ = _inspection_outputs(registry, request, include_overlay=True)
    store, proposed = _persist_proposed_operation(database, request, outputs.proposal_ref, outputs.qa_report_ref)
    confirmed = store.confirm(
        request.request_id,
        expected_operation_checksum=proposed.operation_checksum,
        expected_scene_revision=revision,
        candidate_id="candidate-inspection-1",
        user_id="user-editor",
    )
    proposal = registry.runtime_resolver.load_model(confirmed.proposal_ref, RegistrationProposal)
    report = registry.runtime_resolver.load_model(confirmed.qa_report_ref, RegistrationQAReport)
    overlay_ref = report.evidence_refs[0]
    overlay = registry.runtime_resolver.load_model(overlay_ref, RegistrationOverlayPreview)
    source_ref = proposal.source_geometry_ref
    writer.publish(source_ref, b"lidar-geometry")
    writer.publish(request.floor_evidence_refs[0], b"floor-evidence")
    lidar_payload = b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n"
    lidar_lineage = PreprocessingProvenance(dependencies=[], ground_truth_assisted=False, details={"fixture": True})
    lidar_geometry_ref = publish_ref(
        "LiDARGeometryArtifact",
        StageId.LIDAR_INGEST,
        "registration/meter-cloud.ply",
        lidar_payload,
        source_provenance=lidar_lineage.model_dump(mode="json"),
    )
    lidar_metadata_ref = publish_ref(
        "LiDARGeometryMetadata", StageId.LIDAR_INGEST, "registration/meter-cloud.json", b"{}"
    )
    source_manifest = SimpleNamespace(
        source_geometry_ref=source_ref,
        estimated_trajectory_product_ref=None,
        estimated_map_cloud_ref=None,
    )
    committer = RegistrationBundleCommitter(registry, store)
    verified_fixture = (proposal, report, overlay, overlay_ref, source_manifest, lidar_geometry_ref, lidar_metadata_ref)
    monkeypatch.setattr(committer, "_verified_inputs", lambda _operation: verified_fixture)

    before_scene = registry.scene.current(_JOB_ID).scene
    committed = committer.commit(confirmed)

    assert committed.state == RegistrationOperationState.COMMITTED
    assert committed.confirmed_by_user_id == "user-editor"
    assert committed.committed_bundle_ref is not None
    assert committed.committed_alignment_ref is not None
    bundle_view = registry.runtime_resolver.load_model(committed.committed_bundle_ref, ReconstructionBundle)
    assert bundle_view.canonical_geometry_ref == request.target_rgb_geometry_ref
    assert bundle_view.lidar_geometry_ref == lidar_geometry_ref
    assert bundle_view.alignment_record is not None
    assert (
        bundle_view.alignment_record.transform_target_from_source == proposal.candidates[0].transform_target_from_source
    )
    assert load_reconstruction_bundle(committed.committed_bundle_ref, registry.runtime_resolver).bundle == bundle_view
    assert registry.scene.current(_JOB_ID).scene == before_scene
    assert registry.get_job(_JOB_ID).job_manifest_checksum == committed.committed_manifest_checksum

    replay = committer.commit(confirmed)
    assert replay == committed
    assert store.get(request.request_id) == committed


def test_registration_commit_rejects_stale_scene_without_advancing_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A confirmation for an old SceneIR revision cannot publish artifacts or mutate the manifest."""
    from src.services.orchestration.jobs.registration_commit import RegistrationBundleCommitter

    registry, database, _, _ = _runtime(tmp_path, monkeypatch)
    assert database is not None
    _seed_user(database, "user-guest")
    current_revision = registry.scene.current(_JOB_ID).scene.scene_revision
    stale_revision = "rev-000"
    request = _request(registry, stale_revision, "user-guest", request_id="stale-registration-commit")
    outputs, _ = _inspection_outputs(registry, request)
    store, proposed = _persist_proposed_operation(database, request, outputs.proposal_ref, outputs.qa_report_ref)
    confirmed = store.confirm(
        request.request_id,
        expected_operation_checksum=proposed.operation_checksum,
        expected_scene_revision=stale_revision,
        candidate_id="candidate-inspection-1",
        user_id="user-editor",
    )
    before_job = registry.get_job(_JOB_ID)

    with pytest.raises(
        RuntimeStateConflictError, match="Scene revision changed before registration bundle publication"
    ):
        RegistrationBundleCommitter(registry, store).commit(confirmed)

    after = store.get(request.request_id)
    assert after.state == RegistrationOperationState.CONFIRMED
    assert after.committed_bundle_ref is None and after.committed_alignment_ref is None
    assert registry.get_job(_JOB_ID) == before_job
    assert registry.scene.current(_JOB_ID).scene.scene_revision == current_revision
    assert registry.runtime_resolver.list_uris(f"artifact://jobs/{_JOB_ID}/rec09/registration-confirmations/") == []


def test_registration_commit_artifact_writer_accepts_concurrent_identical_publication(tmp_path: Path) -> None:
    """Racing publishers converge on the same immutable bytes and ref."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from src.services.orchestration.artifacts import ArtifactResolver
    from src.services.orchestration.jobs.registration_commit import _IdempotentArtifactWriter

    resolver = ArtifactResolver(tmp_path)
    writer = _IdempotentArtifactWriter(resolver)
    payload = b"same immutable payload"
    reference = ProductArtifactRef(
        artifact_type="AlignmentRecord",
        schema_version="1.0",
        artifact_uri="artifact://jobs/writer-race/rec09/alignment.json",
        artifact_checksum=sha256_bytes(payload),
        data_class="derived",
        producer_stage=StageId.RGB_LIDAR_ALIGN,
        job_id="writer-race",
    )
    barrier = Barrier(2)
    publish = writer.store.publish

    def start_together(current_ref: ProductArtifactRef, current_payload: bytes) -> ProductArtifactRef:
        barrier.wait(timeout=5)
        return publish(current_ref, current_payload)

    writer.store.publish = start_together  # type: ignore[method-assign]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(writer.publish, reference, payload) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]

    assert results == [reference, reference]
    assert resolver.require(reference).read_bytes() == payload


def test_registration_bundle_manifest_cas_rejects_stale_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the first publication from a captured job manifest can advance the head."""
    registry, _, scene_revision, _ = _runtime(tmp_path, monkeypatch)
    job = registry.get_job(_JOB_ID)
    assert job.status.value == "SUCCEEDED"
    writer = FilesystemArtifactStore(registry.runtime_resolver)
    alignment_payload = b"alignment evidence"
    alignment_ref = ProductArtifactRef(
        artifact_type="AlignmentRecord",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB_ID}/cas/alignment.json",
        artifact_checksum=sha256_bytes(alignment_payload),
        data_class="derived",
        producer_stage=StageId.RGB_LIDAR_ALIGN,
        job_id=_JOB_ID,
    )
    bundle_payload = b"registered reconstruction bundle"
    bundle_ref = ProductArtifactRef(
        artifact_type="ReconstructionBundle",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB_ID}/cas/bundle.json",
        artifact_checksum=sha256_bytes(bundle_payload),
        data_class="derived",
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=_JOB_ID,
    )
    writer.publish(alignment_ref, alignment_payload)
    writer.publish(bundle_ref, bundle_payload)

    published = registry.record_registration_bundle(
        job,
        alignment_ref=alignment_ref,
        bundle_ref=bundle_ref,
        expected_scene_revision=scene_revision,
    )
    with pytest.raises(RuntimeStateConflictError, match="Job đã thay đổi"):
        registry.record_registration_bundle(
            job,
            alignment_ref=alignment_ref,
            bundle_ref=bundle_ref,
            expected_scene_revision=scene_revision,
        )

    assert registry.get_job(_JOB_ID) == published
    assert registry.scene.current(_JOB_ID).scene.scene_revision == scene_revision
