from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationCandidate,
    RegistrationFindingCode,
    RegistrationInputMode,
    RegistrationProposalState,
    RegistrationQAStatus,
    RegistrationSourceCloudManifest,
    seal_registration_proposal,
)
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore, sha256_bytes, sha256_file
from src.services.orchestration.jobs import registration_worker as worker_module
from src.services.orchestration.jobs.admission import OperationResourceProfile
from src.services.orchestration.jobs.registration_sources import VerifiedRegistrationSource
from src.services.orchestration.jobs.registration_worker import RegistrationOperationWorker
from src.services.reconstruction.alignment.bev_search import (
    CoarseRegistrationCandidate,
    CoarseRegistrationSearchResult,
    RegistrationFloorPlane,
    RegistrationSearchDiagnostics,
)
from src.services.reconstruction.alignment.constrained_icp import (
    ConstrainedICPDiagnostics,
    ConstrainedICPResult,
    RefinedRegistrationCandidate,
)
from src.services.reconstruction.alignment.source_planes import SourcePlaneHypothesis, SourcePlaneHypothesisReport


def _checksum(payload: bytes) -> str:
    return "sha256:" + sha256(payload).hexdigest()


def _worker() -> RegistrationOperationWorker:
    return object.__new__(RegistrationOperationWorker)


def test_registration_source_cloud_copy_is_exact_bounded_and_idempotent(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    worker = _worker()
    worker.resolver = resolver
    worker.writer = FilesystemArtifactStore(resolver)
    worker.max_source_bytes = 1024
    source_path = tmp_path / "source.pcd"
    source_path.write_bytes(b"VERSION .7\nFIELDS x y z\nDATA ascii\n0 0 0\n")
    source_checksum = sha256_file(source_path)
    reference = ProductArtifactRef(
        artifact_type="RegistrationSourcePointCloud",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-1/rec08/registration-source/input.pcd",
        artifact_checksum=source_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_INGEST,
        job_id="job-1",
        source_provenance={"source_input_checksum": source_checksum},
    )

    worker._copy_exact_source(source_path, reference, Event())
    worker._copy_exact_source(source_path, reference, Event())

    copied = resolver.require_uri(reference.artifact_uri, reference.artifact_checksum)
    assert copied.read_bytes() == source_path.read_bytes()
    assert sha256_bytes(copied.read_bytes()) == source_checksum


def test_worker_publishes_estimated_map_manifest_with_ordered_scan_lineage(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    worker = _worker()
    worker.resolver = resolver
    worker.writer = FilesystemArtifactStore(resolver)
    worker.max_source_bytes = 1024
    source_path = tmp_path / "estimated-map.ply"
    source_path.write_bytes(b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nend_header\n0\n")
    source_checksum = sha256_file(source_path)
    product_ref = ProductArtifactRef(
        artifact_type="EstimatedTrajectoryProductEvidence",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-1/attempts/attempt-1/lidar-odometry/product-evidence.json",
        artifact_checksum=_checksum(b"odometry-product"),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id="job-1",
    )
    map_ref = ProductArtifactRef(
        artifact_type="EstimatedTrajectoryMapCloud",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-1/attempts/attempt-1/lidar-odometry/estimated-map.ply",
        artifact_checksum=source_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id="job-1",
        source_provenance={"map_frame_id": "odometry-map-frame"},
    )
    source = VerifiedRegistrationSource(
        path=source_path,
        file_id=None,
        input_assembly_id="assembly-1",
        input_assembly_revision=1,
        input_assembly_checksum=_checksum(b"assembly"),
        source_checksum=source_checksum,
        header_checksum=_checksum(b"ply-header"),
        point_count=1,
        geometry_format="ply",
        distance_unit="m",
        source_frame="odometry-map-frame",
        same_scene_lineage_verified=True,
        source_scan_file_ids=("scan-2", "scan-1"),
        source_scan_checksums=(_checksum(b"scan-2"), _checksum(b"scan-1")),
        estimated_trajectory_product_ref=product_ref,
        estimated_map_cloud_ref=map_ref,
        odometry_runtime_qualification_status="wired_unqualified",
    )
    request = SimpleNamespace(
        target_job_id="job-1",
        source=SimpleNamespace(mode=RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP),
    )

    cloud_ref, manifest_ref = worker._publish_source_cloud(request, source, Event())  # type: ignore[arg-type]
    manifest_path = resolver.require_uri(manifest_ref.artifact_uri, manifest_ref.artifact_checksum)
    manifest = RegistrationSourceCloudManifest.model_validate_json(manifest_path.read_bytes())

    assert manifest.schema_version == "1.1"
    assert manifest.source_geometry_ref == cloud_ref
    assert manifest.source_scan_file_ids == ["scan-2", "scan-1"]
    assert manifest.source_scan_checksums == [_checksum(b"scan-2"), _checksum(b"scan-1")]
    assert manifest.estimated_trajectory_product_ref == product_ref
    assert manifest.estimated_map_cloud_ref == map_ref


def test_registration_worker_publishes_model_using_exact_artifact_bytes_checksum(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    worker = _worker()
    worker.resolver = resolver
    worker.writer = FilesystemArtifactStore(resolver)
    source_ref = ProductArtifactRef(
        artifact_type="LiDARGeometryArtifact",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-1/lidar/geometry.json",
        artifact_checksum=_checksum(b"source-geometry"),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_INGEST,
        job_id="job-1",
    )
    target_ref = ProductArtifactRef(
        artifact_type="RgbGeometry",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-1/rgb/geometry.glb",
        artifact_checksum=_checksum(b"target-geometry"),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.RGB_GEOMETRY,
        job_id="job-1",
    )
    proposal = seal_registration_proposal(
        {
            "job_id": "job-1",
            "input_mode": RegistrationInputMode.STATIC_CLOUD,
            "request_checksum": _checksum(b"request"),
            "source_input_checksum": _checksum(b"source-input"),
            "source_geometry_ref": source_ref,
            "target_rgb_geometry_ref": target_ref,
            "target_scene_revision": "scene-rev-1",
            "profile_checksum": _checksum(b"profile"),
            "tool_checksum": _checksum(b"tool"),
            "source_frame": "lidar-map-frame",
            "state": RegistrationProposalState.INSUFFICIENT,
            "candidates": [],
            "selected_candidate_id": None,
            "findings": [RegistrationFindingCode.LOW_OVERLAP],
            "proposal_checksum": "sha256:" + "0" * 64,
        }
    )
    operation = SimpleNamespace(
        operation_id="registration-1",
        target_job_id="job-1",
        request_checksum=_checksum(b"request"),
        attempt=1,
        fencing_token=1,
    )

    reference = worker._publish_model_artifact(operation, proposal, "proposal.json")

    payload = proposal.model_dump_json(indent=2).encode("utf-8") + b"\n"
    assert reference.artifact_checksum == _checksum(payload)
    assert reference.artifact_checksum != proposal.proposal_checksum
    published = resolver.require_uri(reference.artifact_uri, reference.artifact_checksum)
    assert published.read_bytes() == payload


def test_registration_resource_profile_accounts_for_point_and_target_bounds() -> None:
    worker = _worker()
    worker.registry = MagicMock()
    worker.registry.get_job.return_value = SimpleNamespace(project_id="project-1")
    worker.admission = MagicMock()
    worker.admission.operation_profile_for_job.return_value = OperationResourceProfile(
        required_gb={"vram": 0.0, "ram": 0.25, "disk": 0.05},
        danger_ratio=0.8,
        measured=True,
        gpu_required=False,
    )
    operation = SimpleNamespace(
        target_job_id="job-1",
        request=SimpleNamespace(target_project_id="project-1"),
    )
    source = SimpleNamespace(point_count=2_000)

    profile = worker._resource_profile(operation, source, 10_000, 10_000)

    assert profile.gpu_required is False
    assert profile.required_gb["vram"] == 0.0
    assert profile.required_gb["ram"] >= 0.5
    assert profile.required_gb["disk"] >= 0.1
    assert profile.measured is False


def test_registration_worker_persists_resource_wait_without_holding_reservation(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pcd"
    source_path.write_bytes(b"x")
    target_path = tmp_path / "target.glb"
    target_path.write_bytes(b"target")
    request = SimpleNamespace(
        source=SimpleNamespace(mode="static_cloud"),
        request_checksum=_checksum(b"request"),
        profile_checksum=_checksum(b"profile"),
        target_job_id="job-1",
        target_project_id="project-1",
        expected_scene_revision="scene-rev-1",
        target_rgb_geometry_ref=SimpleNamespace(
            artifact_uri="artifact://jobs/job-1/rgb/geometry.glb",
            artifact_checksum=_checksum(b"target"),
        ),
    )
    operation = SimpleNamespace(
        operation_id="registration-1",
        target_job_id="job-1",
        request_checksum=request.request_checksum,
        request=request,
        lease_token="lease-token",
        fencing_token=1,
        attempt=1,
    )
    worker = _worker()
    worker.store = MagicMock()
    worker.store.claim_next.return_value = operation
    worker.admission = MagicMock()
    worker.admission.worker_id = "worker-1"
    worker.admission.operation_profile_for_job.return_value = OperationResourceProfile(
        required_gb={"vram": 0.0, "ram": None, "disk": None},
        danger_ratio=None,
        measured=False,
        gpu_required=False,
    )
    worker.admission.admit_operation.return_value = SimpleNamespace(
        status="waiting_resources",
        waiting_on=["ram", "disk"],
        reasons={"ram": "unmeasured", "disk": "unmeasured"},
    )
    worker.registry = MagicMock()
    worker.registry.get_job.return_value = SimpleNamespace(project_id="project-1")
    worker.registry.scene.current.return_value.scene.scene_revision = "scene-rev-1"
    worker.source_resolver = MagicMock()
    worker.source_resolver.resolve.return_value = SimpleNamespace(path=source_path, point_count=1)
    worker.resolver = MagicMock()
    worker.resolver.require_uri.return_value = target_path
    worker.workspace_root = tmp_path / "worker"
    worker.max_source_bytes = 1024
    assert worker.process_next() is False

    worker.store.wait_for_resources.assert_called_once()
    assert "waiting_resources" in worker.store.wait_for_resources.call_args.kwargs["reason"]
    worker.admission.release_operation.assert_not_called()


def test_worker_searches_both_signs_of_every_source_plane_and_preserves_ambiguity(monkeypatch) -> None:
    request = SimpleNamespace(
        source=SimpleNamespace(same_scene_attestation=True),
        metric_state="confirmed",
        profile_checksum=_checksum(b"profile"),
        profile=SimpleNamespace(
            runtime_budget_seconds=300,
            top_k_candidates=8,
            max_refinement_candidates=8,
            minimum_candidate_margin=0.05,
            bev_cell_resolution_m=0.25,
        ),
        target_roi_world=object(),
    )
    planes = (
        SourcePlaneHypothesis(
            candidate_id="plane-a",
            frame="lidar-map-frame",
            normal_xyz=(0.0, 0.0, 1.0),
            offset_m=0.0,
            support_points=500,
            support_ratio=0.5,
            median_residual_m=0.002,
            p95_residual_m=0.01,
            major_span_m=5.0,
            minor_span_m=3.0,
            evidence_checksum=_checksum(b"plane-a"),
        ),
        SourcePlaneHypothesis(
            candidate_id="plane-b",
            frame="lidar-map-frame",
            normal_xyz=(0.0, 1.0, 0.0),
            offset_m=0.0,
            support_points=400,
            support_ratio=0.4,
            median_residual_m=0.003,
            p95_residual_m=0.02,
            major_span_m=4.0,
            minor_span_m=2.0,
            evidence_checksum=_checksum(b"plane-b"),
        ),
    )
    report = SourcePlaneHypothesisReport(
        status="hypotheses",
        reason="orientation_unclassified",
        source_checksum=_checksum(b"cloud"),
        source_frame="lidar-map-frame",
        profile_checksum=_checksum(b"source-plane-profile"),
        input_point_count=1_000,
        sampled_point_count=1_000,
        candidates=planes,
        evidence_checksum=_checksum(b"hypotheses"),
    )
    target_floor = RegistrationFloorPlane(
        frame="world",
        normal_xyz=(0.0, 0.0, 1.0),
        offset_m=0.0,
        up_direction_xyz=(0.0, 0.0, 1.0),
        evidence_checksum=_checksum(b"target-floor"),
    )
    target = SimpleNamespace(
        collision_surface_points_world_m=np.zeros((3, 3)),
        collision_surface_normals_world=np.tile([0.0, 0.0, 1.0], (3, 1)),
        target_floor=target_floor,
    )
    worker = _worker()
    source_up_vectors: list[tuple[float, float, float]] = []
    search_options: list[dict[str, object]] = []
    refine_options: list[dict[str, object]] = []

    def search_stub(*args, **kwargs):
        index = len(source_up_vectors)
        search_options.append(kwargs)
        floor = kwargs["source_floor"]
        source_up_vectors.append(floor.up_direction_xyz)
        transform = Transform(
            parent_frame="world",
            local_frame="lidar-map-frame",
            translation_xyz=(float(index * 2), 0.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        )
        candidate = CoarseRegistrationCandidate(
            candidate_id="coarse-candidate",
            transform_target_from_source=transform,
            score=0.9,
            source_coverage_ratio=0.8,
            target_coverage_ratio=0.8,
            overlap_ratio=0.7,
            yaw_radians=0.0,
            translation_xy_m=(float(index * 2), 0.0),
            rgb_scale_factor=None,
        )
        diagnostics = RegistrationSearchDiagnostics(
            profile_checksum=request.profile_checksum,
            source_floor_evidence_checksum=floor.evidence_checksum,
            target_floor_evidence_checksum=target_floor.evidence_checksum,
            source_point_count=1_000,
            target_point_count=3,
            source_sample_count=1_000,
            target_sample_count=3,
            source_structural_cells=10,
            target_structural_cells=10,
            source_cells_by_height=(1, 2, 3, 4, 5, 6),
            target_cells_by_height=(1, 2, 3, 4, 5, 6),
            bev_resolution_m=0.25,
            fine_resolution_m=0.125,
            search_seed=0,
            yaw_hypotheses_evaluated=1,
            scale_hypotheses_evaluated=1,
            translation_hypotheses_evaluated=1,
            fine_hypotheses_evaluated=1,
            candidate_margin=None,
            elapsed_seconds=0.01,
            budget_exhausted=False,
            source_cropped_points=0,
            target_cropped_points=0,
        )
        return CoarseRegistrationSearchResult(
            state=RegistrationProposalState.PROPOSED,
            candidates=(candidate,),
            findings=(),
            diagnostics=diagnostics,
        )

    def refine_stub(coarse, *args, **kwargs):
        refine_options.append(kwargs)
        coarse_candidate = coarse.candidates[0]
        candidate = RegistrationCandidate(
            candidate_id=coarse_candidate.candidate_id,
            transform_target_from_source=coarse_candidate.transform_target_from_source,
            score=coarse_candidate.score,
        )
        refined = RefinedRegistrationCandidate(
            candidate=candidate,
            coarse_score=0.9,
            source_coverage_ratio=0.8,
            target_coverage_ratio=0.8,
            overlap_ratio=0.7,
            correspondence_count=100,
            rejected_correspondence_count=0,
            observable_dof=3,
            point_to_plane_p95_residual_m=0.01,
            bidirectional_p95_residual_m=0.02,
            bidirectional_max_residual_m=0.03,
            iterations=3,
            converged=True,
            regions=(),
        )
        diagnostics = ConstrainedICPDiagnostics(
            profile_checksum=request.profile_checksum,
            source_point_count=1_000,
            target_point_count=3,
            source_sample_count=1_000,
            target_sample_count=3,
            candidates_considered=1,
            candidates_refined=1,
            iterations=3,
            elapsed_seconds=0.01,
            budget_exhausted=False,
            candidate_margin=None,
            candidate_findings=(),
        )
        return ConstrainedICPResult(
            state=RegistrationProposalState.PROPOSED,
            qa_status=RegistrationQAStatus.INCONCLUSIVE,
            candidates=(refined,),
            findings=(),
            diagnostics=diagnostics,
        )

    monkeypatch.setattr(worker_module, "search_independent_map_registration", search_stub)
    monkeypatch.setattr(worker_module, "refine_registration_candidates", refine_stub)

    cancel_event = Event()
    measured, _, state, findings, margin = worker._solve(
        request,
        np.zeros((1_000, 3)),
        target,
        report,
        True,
        cancel_event,
    )

    assert len(source_up_vectors) == 4
    assert source_up_vectors == [
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
    ]
    assert len(measured) == 4
    assert state == RegistrationProposalState.AMBIGUOUS
    assert findings == [RegistrationFindingCode.AMBIGUOUS_CANDIDATES]
    assert margin == 0.0
    assert len(search_options) == len(refine_options) == 4
    assert all(
        1 <= options["runtime_budget_seconds"] < request.profile.runtime_budget_seconds for options in search_options
    )
    assert all(options["cancel_event"] is cancel_event for options in search_options + refine_options)
    assert all(options["runtime_budget_seconds"] < request.profile.runtime_budget_seconds for options in refine_options)
    assert all(options["maximum_candidates"] <= request.profile.top_k_candidates for options in refine_options)


@pytest.mark.parametrize(
    ("runtime_budget", "maximum_refinement_candidates", "diagnostic_key", "diagnostic_value"),
    [
        (3, 8, "minimum_solver_budget_seconds", 4),
        (300, 1, "maximum_refinement_candidates", 1),
    ],
)
def test_worker_fails_closed_when_profile_cannot_budget_all_floor_orientations(
    monkeypatch,
    runtime_budget: int,
    maximum_refinement_candidates: int,
    diagnostic_key: str,
    diagnostic_value: int,
) -> None:
    request = SimpleNamespace(
        source=SimpleNamespace(same_scene_attestation=True),
        metric_state="confirmed",
        profile_checksum=_checksum(b"profile"),
        profile=SimpleNamespace(
            runtime_budget_seconds=runtime_budget,
            top_k_candidates=8,
            max_refinement_candidates=maximum_refinement_candidates,
            minimum_candidate_margin=0.05,
            bev_cell_resolution_m=0.25,
        ),
        target_roi_world=object(),
    )
    plane = SourcePlaneHypothesis(
        candidate_id="plane-a",
        frame="lidar-map-frame",
        normal_xyz=(0.0, 0.0, 1.0),
        offset_m=0.0,
        support_points=500,
        support_ratio=0.5,
        median_residual_m=0.002,
        p95_residual_m=0.01,
        major_span_m=5.0,
        minor_span_m=3.0,
        evidence_checksum=_checksum(b"plane-a"),
    )
    report = SourcePlaneHypothesisReport(
        status="hypotheses",
        reason="orientation_unclassified",
        source_checksum=_checksum(b"cloud"),
        source_frame="lidar-map-frame",
        profile_checksum=_checksum(b"source-plane-profile"),
        input_point_count=1_000,
        sampled_point_count=1_000,
        candidates=(plane,),
        evidence_checksum=_checksum(b"hypotheses"),
    )
    worker = _worker()

    def unexpected_search(*args, **kwargs):
        raise AssertionError("solver must not run when every orientation cannot receive both phase budgets")

    monkeypatch.setattr(worker_module, "search_independent_map_registration", unexpected_search)
    measured, diagnostics, state, findings, margin = worker._solve(
        request,
        np.zeros((1_000, 3)),
        SimpleNamespace(),
        report,
        True,
        Event(),
    )

    assert measured == []
    assert diagnostics["orientation_hypotheses"] == 2
    assert diagnostics[diagnostic_key] == diagnostic_value
    assert diagnostics["budget_exhausted"] is True
    assert state == RegistrationProposalState.INSUFFICIENT
    assert findings == [RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED]
    assert margin is None
