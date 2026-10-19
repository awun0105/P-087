from __future__ import annotations

from hashlib import sha256

import numpy as np
import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.input_assembly import DistanceUnit, InputAssetFormat, InputRole
from src.models.contracts.manifests import StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationCandidate,
    RegistrationInputMode,
    RegistrationProfile,
    RegistrationProposal,
    RegistrationProposalState,
    RegistrationRequest,
    RegistrationROI,
    RegistrationSourceBinding,
    seal_registration_overlay_preview,
    seal_registration_profile,
    seal_registration_proposal,
    seal_registration_request,
    validate_registration_overlay_binding,
)
from src.services.reconstruction.alignment.bev_search import RegistrationFloorPlane
from src.services.reconstruction.alignment.registration_overlay import build_registration_overlay_preview

JOB_ID = "job-overlay"
PROJECT_ID = "project-overlay"
ZERO_CHECKSUM = "sha256:" + "0" * 64


def _checksum(value: str) -> str:
    return "sha256:" + sha256(value.encode()).hexdigest()


def _ref(artifact_type: str, stage: StageId) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB_ID}/registration/{artifact_type.lower()}.json",
        artifact_checksum=_checksum(artifact_type),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=stage,
        job_id=JOB_ID,
    )


def _request(*, point_count: int, scale_search: bool = False) -> RegistrationRequest:
    profile: RegistrationProfile = seal_registration_profile(
        {
            "profile_id": "overlay-test-profile",
            "qualification_state": "provisional",
            "qualification_record_ref": None,
            "scale_policy": "bounded_rgb_scale_search" if scale_search else "confirmed_metric_only",
            "rgb_scale_factor_bounds": [0.75, 1.25] if scale_search else None,
            "profile_checksum": ZERO_CHECKSUM,
        }
    )
    source = RegistrationSourceBinding(
        mode=RegistrationInputMode.STATIC_CLOUD,
        target_job_id=JOB_ID,
        authorized_project_id=PROJECT_ID,
        source_input_checksum=_checksum("input-cloud"),
        source_frame="lidar-map-frame",
        source_distance_unit=DistanceUnit.METER,
        source_point_count=point_count,
        source_format=InputAssetFormat.POINT_CLOUD_PCD,
        source_header_checksum=_checksum("pcd-header"),
        source_role=InputRole.STATIC_LIDAR_CLOUD,
        input_assembly_id="assembly-overlay",
        input_assembly_revision=1,
        input_assembly_checksum=_checksum("assembly-revision"),
        source_file_ids=["map-file"],
        same_scene_attestation=True,
    )
    return seal_registration_request(
        {
            "request_id": "registration-overlay-operation",
            "requested_by": "reviewer-1",
            "target_project_id": PROJECT_ID,
            "target_job_id": JOB_ID,
            "target_rgb_geometry_ref": _ref("RgbGeometry", StageId.RGB_GEOMETRY),
            "expected_scene_revision": "scene-rev-overlay",
            "source": source,
            "metric_state": "unknown" if scale_search else "confirmed",
            "metric_confirmation_ref": None
            if scale_search
            else _ref("RGBMetricConfirmation", StageId.METRIC_CANONICALIZE),
            "floor_state": "supported",
            "floor_model_refs": [_ref("FloorFitEvidence", StageId.OBJECT_EXTRACT)],
            "target_roi_world": RegistrationROI(min_xyz_m=(-20, -20, -2), max_xyz_m=(20, 20, 8)),
            "profile": profile,
            "profile_checksum": profile.profile_checksum,
            "request_checksum": ZERO_CHECKSUM,
        }
    )


def _proposal(request: RegistrationRequest, *, scale: float | None = None) -> RegistrationProposal:
    source_ref = _ref("LiDARGeometryArtifact", StageId.LIDAR_INGEST)
    candidate = RegistrationCandidate(
        candidate_id="candidate-overlay-1",
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame=request.source.source_frame,
            translation_xyz=(2, 3, 0),
            rotation_quaternion_xyzw=(0, 0, 2**-0.5, 2**-0.5),
        ),
        score=0.9,
        rgb_scale_factor=scale,
    )
    return seal_registration_proposal(
        {
            "job_id": JOB_ID,
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
            "proposal_checksum": ZERO_CHECKSUM,
        }
    )


def _floor(request: RegistrationRequest) -> RegistrationFloorPlane:
    return RegistrationFloorPlane(
        frame="world",
        normal_xyz=(0, 0, 1),
        offset_m=0,
        up_direction_xyz=(0, 0, 1),
        evidence_checksum=request.floor_evidence_refs[0].artifact_checksum,
    )


def test_overlay_uses_candidate_transform_clips_roi_and_scales_target_in_floor_frame() -> None:
    request = _request(point_count=4, scale_search=True)
    proposal = _proposal(request, scale=1.25)
    source = np.asarray([[1, 0, 0], [0, 0, 0], [30, 0, 0], [0, 0, 0]], dtype=float)
    target = np.asarray([[4, 0, 0], [30, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=float)

    preview = build_registration_overlay_preview(
        request,
        proposal,
        proposal.candidates[0],
        request.request_id,
        source,
        target,
        _floor(request),
    )

    assert preview.rgb_scale_factor == 1.25
    assert preview.source_in_roi_point_count == 3
    assert preview.target_in_roi_point_count == 3
    assert preview.source_points_xy_world_m[0] == pytest.approx((2, 4))
    assert preview.target_points_xy_world_m[0] == pytest.approx((5, 0))
    assert preview.bounds_min_xy_m == pytest.approx((-25, -25))
    assert preview.bounds_max_xy_m == pytest.approx((25, 25))
    assert preview.diagnostic_only is True
    validate_registration_overlay_binding(request, proposal, preview, request.request_id)

    another_operation = seal_registration_overlay_preview(
        {**preview.model_dump(mode="json"), "operation_id": "other-operation", "preview_checksum": ZERO_CHECKSUM}
    )
    with pytest.raises(ValueError, match="another operation"):
        validate_registration_overlay_binding(request, proposal, another_operation, request.request_id)


def test_overlay_sampling_is_deterministic_and_capped_per_cloud() -> None:
    point_count = 70_000
    request = _request(point_count=point_count)
    proposal = _proposal(request)
    values = np.linspace(-10, 10, point_count)
    cloud = np.column_stack((values, np.sin(values), np.zeros(point_count)))

    first = build_registration_overlay_preview(
        request, proposal, proposal.candidates[0], request.request_id, cloud, cloud, _floor(request)
    )
    second = build_registration_overlay_preview(
        request, proposal, proposal.candidates[0], request.request_id, cloud, cloud, _floor(request)
    )

    assert first.source_in_roi_point_count == point_count
    assert first.target_in_roi_point_count == point_count
    assert len(first.source_points_xy_world_m) == 512
    assert len(first.target_points_xy_world_m) == 512
    assert first.source_points_xy_world_m == second.source_points_xy_world_m
    assert first.target_points_xy_world_m == second.target_points_xy_world_m


def test_overlay_rejects_nonfinite_or_over_budget_geometry() -> None:
    request = _request(point_count=2)
    proposal = _proposal(request)
    target = np.zeros((2, 3), dtype=float)
    source = np.asarray([[0, 0, 0], [np.nan, 0, 0]], dtype=float)

    with pytest.raises(ValueError, match="source points are invalid"):
        build_registration_overlay_preview(
            request, proposal, proposal.candidates[0], request.request_id, source, target, _floor(request)
        )
