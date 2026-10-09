from dataclasses import replace
from hashlib import sha256

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
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
    RegistrationRegionMetric,
    RegistrationRequest,
    RegistrationROI,
    RegistrationSourceBinding,
    seal_registration_profile,
    seal_registration_proposal,
    seal_registration_request,
)
from src.services.reconstruction.alignment.constrained_icp import RefinedRegistrationCandidate
from src.services.reconstruction.alignment.registration_qa import build_registration_qa_report

_JOB = "job-registration-qa"
_PROJECT = "project-registration-qa"
_ZERO = "sha256:" + "0" * 64


def _checksum(value: str) -> str:
    return "sha256:" + sha256(value.encode()).hexdigest()


def _artifact_checksum(value: RegistrationProposal) -> str:
    payload = value.model_dump_json(indent=2).encode("utf-8") + b"\n"
    return "sha256:" + sha256(payload).hexdigest()


def _ref(artifact_type: str, stage: StageId, *, checksum: str | None = None) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB}/registration/{artifact_type.lower()}.json",
        artifact_checksum=checksum or _checksum(artifact_type),
        data_class="derived",
        producer_stage=stage,
        job_id=_JOB,
    )


def _profile(*, qualified: bool) -> RegistrationProfile:
    qualification = _ref("RegistrationProfileQualification", StageId.RGB_LIDAR_ALIGN) if qualified else None
    return seal_registration_profile(
        {
            "profile_id": "warehouse-registration-test",
            "qualification_state": "qualified" if qualified else "provisional",
            "qualification_record_ref": qualification,
            "profile_checksum": _ZERO,
        }
    )


def _request(*, qualified: bool, same_scene: bool = True) -> RegistrationRequest:
    profile = _profile(qualified=qualified)
    source = RegistrationSourceBinding(
        mode=RegistrationInputMode.STATIC_CLOUD,
        target_job_id=_JOB,
        authorized_project_id=_PROJECT,
        source_input_checksum=_checksum("map-source"),
        source_frame="lidar-map-frame",
        source_distance_unit=DistanceUnit.METER,
        source_point_count=12_000,
        source_format=InputAssetFormat.POINT_CLOUD_PCD,
        source_header_checksum=_checksum("pcd-header"),
        source_role=InputRole.STATIC_LIDAR_CLOUD,
        input_assembly_id="assembly-registration-qa",
        input_assembly_revision=2,
        input_assembly_checksum=_checksum("assembly-2"),
        source_file_ids=["map-file-1"],
        same_scene_attestation=same_scene,
    )
    return seal_registration_request(
        {
            "request_id": "registration-request-qa",
            "requested_by": "reviewer-qa",
            "target_project_id": _PROJECT,
            "target_job_id": _JOB,
            "target_rgb_geometry_ref": _ref("RgbGeometry", StageId.RGB_GEOMETRY),
            "expected_scene_revision": "scene-rev-2",
            "source": source,
            "metric_state": "confirmed",
            "metric_confirmation_ref": _ref("RGBMetricConfirmation", StageId.METRIC_CANONICALIZE),
            "floor_state": "supported",
            "floor_model_refs": [_ref("FloorFitEvidence", StageId.OBJECT_EXTRACT)],
            "target_roi_world": RegistrationROI(min_xyz_m=(-20, -20, -2), max_xyz_m=(20, 20, 8)),
            "profile": profile,
            "profile_checksum": profile.profile_checksum,
            "request_checksum": _ZERO,
        }
    )


def _proposal(request: RegistrationRequest) -> RegistrationProposal:
    candidate = RegistrationCandidate(
        candidate_id="candidate-1",
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame=request.source.source_frame or "lidar-map-frame",
            translation_xyz=(1.0, 2.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        score=0.95,
    )
    return seal_registration_proposal(
        {
            "job_id": _JOB,
            "input_mode": request.source.mode,
            "request_checksum": request.request_checksum,
            "source_input_checksum": request.source.source_input_checksum,
            "source_geometry_ref": _ref("LiDARGeometryArtifact", StageId.LIDAR_INGEST),
            "target_rgb_geometry_ref": request.target_rgb_geometry_ref,
            "target_scene_revision": request.expected_scene_revision,
            "profile_checksum": request.profile_checksum,
            "tool_checksum": _checksum("registration-tool-v1"),
            "source_frame": request.source.source_frame,
            "state": RegistrationProposalState.PROPOSED,
            "candidates": [candidate],
            "selected_candidate_id": candidate.candidate_id,
            "findings": [],
            "proposal_checksum": _ZERO,
        }
    )


def _refined(
    proposal: RegistrationProposal, *, residual_m: float = 0.02, overlap: float = 0.8
) -> RefinedRegistrationCandidate:
    candidate = proposal.candidates[0]
    region = RegistrationRegionMetric(
        region_id="aisle-a",
        source_coverage_ratio=0.9,
        target_coverage_ratio=0.9,
        correspondence_count=1_200,
        p95_residual_m=residual_m,
    )
    return RefinedRegistrationCandidate(
        candidate=candidate,
        coarse_score=0.9,
        source_coverage_ratio=0.9,
        target_coverage_ratio=0.9,
        overlap_ratio=overlap,
        correspondence_count=1_200,
        rejected_correspondence_count=12,
        observable_dof=3,
        point_to_plane_p95_residual_m=residual_m,
        bidirectional_p95_residual_m=residual_m,
        bidirectional_max_residual_m=residual_m * 2,
        iterations=18,
        converged=True,
        regions=(region,),
    )


def _run(
    request: RegistrationRequest,
    *,
    residual_m: float = 0.02,
    overlap: float = 0.8,
    verified: bool | None = True,
    qualification_verified: bool = False,
) -> tuple[RegistrationProposal, RegistrationQAReport]:
    proposal = _proposal(request)
    proposal_ref = _ref(
        "RegistrationProposalArtifact",
        StageId.RGB_LIDAR_ALIGN,
        checksum=_artifact_checksum(proposal),
    )
    report = build_registration_qa_report(
        request,
        proposal,
        proposal_ref,
        _refined(proposal, residual_m=residual_m, overlap=overlap),
        candidate_margin=0.5,
        floor_difference_m=0.01,
        same_scene_verified=verified,
        server_qualification_verified=qualification_verified,
    )
    return proposal, report


def test_provisional_profile_keeps_good_synthetic_fit_inconclusive() -> None:
    request = _request(qualified=False)

    _, report = _run(request)

    assert report.result == RegistrationQAStatus.INCONCLUSIVE
    assert RegistrationFindingCode.UNQUALIFIED_PROFILE in report.findings
    assert report.bidirectional_p95_residual_m == pytest.approx(0.02)


def test_proposal_artifact_reference_uses_exact_serialized_bytes_checksum() -> None:
    request = _request(qualified=False)
    proposal = _proposal(request)
    wrong_ref = _ref(
        "RegistrationProposalArtifact",
        StageId.RGB_LIDAR_ALIGN,
        checksum=proposal.proposal_checksum,
    )

    with pytest.raises(ValueError, match="does not identify the exact proposal"):
        build_registration_qa_report(
            request,
            proposal,
            wrong_ref,
            _refined(proposal),
            candidate_margin=0.5,
            floor_difference_m=0.01,
            same_scene_verified=True,
        )


def test_same_scene_requires_server_resolved_context() -> None:
    request = _request(qualified=True)

    _, report = _run(request, verified=None, qualification_verified=True)

    assert report.result == RegistrationQAStatus.INCONCLUSIVE
    assert RegistrationFindingCode.SAME_SCENE_CONTEXT_MISSING in report.findings


def test_qualified_measured_fit_fails_when_residual_or_overlap_miss_profile() -> None:
    request = _request(qualified=True)

    _, report = _run(request, residual_m=0.2, overlap=0.1, qualification_verified=True)

    assert report.result == RegistrationQAStatus.FAIL
    assert RegistrationFindingCode.HIGH_RESIDUAL in report.findings
    assert RegistrationFindingCode.LOW_OVERLAP in report.findings


def test_qualified_fit_pass_binds_exact_proposal_geometry_and_profile_evidence() -> None:
    request = _request(qualified=True)

    proposal, report = _run(request, qualification_verified=True)

    assert report.result == RegistrationQAStatus.PASS
    assert report.candidate_id == proposal.selected_candidate_id
    assert proposal.source_geometry_ref in report.evidence_refs
    assert proposal.target_rgb_geometry_ref in report.evidence_refs
    assert request.profile.qualification_record_ref in report.evidence_refs


def test_client_supplied_qualified_profile_is_not_server_qualification() -> None:
    request = _request(qualified=True)

    _, report = _run(request)

    assert report.result == RegistrationQAStatus.INCONCLUSIVE
    assert RegistrationFindingCode.UNQUALIFIED_PROFILE in report.findings


def test_measurements_cannot_be_reused_for_a_different_candidate() -> None:
    request = _request(qualified=True)
    proposal = _proposal(request)
    wrong_candidate = replace(
        _refined(proposal), candidate=proposal.candidates[0].model_copy(update={"candidate_id": "other"})
    )

    with pytest.raises(ValueError, match="do not belong to the selected"):
        build_registration_qa_report(
            request,
            proposal,
            _ref(
                "RegistrationProposalArtifact",
                StageId.RGB_LIDAR_ALIGN,
                checksum=_artifact_checksum(proposal),
            ),
            wrong_candidate,
            candidate_margin=0.5,
            floor_difference_m=0.01,
            same_scene_verified=True,
        )
