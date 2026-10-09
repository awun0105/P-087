from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.input_assembly import DistanceUnit, InputAssetFormat, InputRole
from src.models.contracts.manifests import StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationCandidate,
    RegistrationFindingCode,
    RegistrationInputMode,
    RegistrationOperationState,
    RegistrationPreflightState,
    RegistrationProfile,
    RegistrationProposal,
    RegistrationProposalState,
    RegistrationQAReport,
    RegistrationQAStatus,
    RegistrationReferenceError,
    RegistrationRegionMetric,
    RegistrationRequest,
    RegistrationROI,
    RegistrationSourceBinding,
    registration_preflight,
    seal_registration_profile,
    seal_registration_proposal,
    seal_registration_qa_report,
    seal_registration_request,
    validate_registration_proposal_binding,
    validate_registration_qa_binding,
    validate_registration_transition,
)

ZERO_CHECKSUM = "sha256:" + "0" * 64
JOB_ID = "job-rgb-1"
PROJECT_ID = "project-1"


def _checksum(value: str) -> str:
    return "sha256:" + sha256(value.encode()).hexdigest()


def _ref(
    artifact_type: str,
    stage: StageId,
    *,
    job_id: str = JOB_ID,
    checksum: str | None = None,
    data_class: ArtifactDataClass = ArtifactDataClass.DERIVED,
) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/registration/{artifact_type.lower()}.json",
        artifact_checksum=checksum or _checksum(artifact_type),
        data_class=data_class,
        producer_stage=stage,
        job_id=job_id,
    )


def _profile(*, qualified: bool = False, scale_policy: str = "confirmed_metric_only") -> RegistrationProfile:
    qualification_ref = _ref("RegistrationProfileQualification", StageId.RGB_LIDAR_ALIGN) if qualified else None
    return seal_registration_profile(
        {
            "schema_version": "1.0",
            "profile_id": "warehouse-registration-v1",
            "qualification_state": "qualified" if qualified else "provisional",
            "qualification_record_ref": qualification_ref,
            "scale_policy": scale_policy,
            "rgb_scale_factor_bounds": [0.75, 1.25] if scale_policy == "bounded_rgb_scale_search" else None,
            "profile_checksum": ZERO_CHECKSUM,
        }
    )


def _source(
    mode: RegistrationInputMode = RegistrationInputMode.STATIC_CLOUD,
    **overrides: object,
) -> RegistrationSourceBinding:
    if mode == RegistrationInputMode.SENSOR_PACKAGE:
        package = _ref("LidarPackageRecord", StageId.LIDAR_INGEST)
        values: dict[str, object] = {
            "mode": mode,
            "target_job_id": JOB_ID,
            "authorized_project_id": PROJECT_ID,
            "source_input_checksum": package.artifact_checksum,
            "source_frame": "lidar-world",
            "source_distance_unit": DistanceUnit.METER,
            "source_point_count": 12_000,
            "lidar_package_ref": package,
        }
    else:
        role = {
            RegistrationInputMode.REGISTERED_MAP: InputRole.REGISTERED_LIDAR_MAP,
            RegistrationInputMode.STATIC_CLOUD: InputRole.STATIC_LIDAR_CLOUD,
            RegistrationInputMode.RAW_SCAN_SEQUENCE: InputRole.LIDAR_SCAN,
        }[mode]
        values = {
            "mode": mode,
            "target_job_id": JOB_ID,
            "authorized_project_id": PROJECT_ID,
            "source_input_checksum": _checksum("map-source"),
            "source_frame": "lidar-map-frame",
            "source_distance_unit": DistanceUnit.METER,
            "source_point_count": 12_000,
            "source_format": InputAssetFormat.POINT_CLOUD_PCD,
            "source_header_checksum": _checksum("pcd-header"),
            "source_role": role,
            "input_assembly_id": "assembly-1",
            "input_assembly_revision": 2,
            "input_assembly_checksum": _checksum("assembly-2"),
            "source_file_ids": ["map-file-1"]
            if mode != RegistrationInputMode.RAW_SCAN_SEQUENCE
            else ["scan-1", "scan-2"],
            "same_scene_attestation": True if mode != RegistrationInputMode.RAW_SCAN_SEQUENCE else None,
        }
    values.update(overrides)
    return RegistrationSourceBinding(**values)


def _request(
    *,
    source: RegistrationSourceBinding | None = None,
    profile: RegistrationProfile | None = None,
    metric_state: str = "confirmed",
    floor_state: str = "supported",
    floor_artifact_type: str = "FloorFitEvidence",
    expected_scene_revision: str = "scene-rev-1",
) -> RegistrationRequest:
    source = source or _source()
    profile = profile or _profile()
    metric_ref = _ref("RGBMetricConfirmation", StageId.METRIC_CANONICALIZE) if metric_state == "confirmed" else None
    floor_stage = StageId.OBJECT_EXTRACT if floor_artifact_type == "FloorFitEvidence" else StageId.RGB_GEOMETRY
    floor_refs = [_ref(floor_artifact_type, floor_stage)] if floor_state == "supported" else []
    return seal_registration_request(
        {
            "schema_version": "1.0",
            "request_id": "registration-request-1",
            "requested_by": "user-1",
            "target_project_id": PROJECT_ID,
            "target_job_id": JOB_ID,
            "target_rgb_geometry_ref": _ref("RgbGeometry", StageId.RGB_GEOMETRY),
            "expected_scene_revision": expected_scene_revision,
            "source": source,
            "metric_state": metric_state,
            "metric_confirmation_ref": metric_ref,
            "floor_state": floor_state,
            "floor_model_refs": floor_refs,
            "target_roi_world": (
                None
                if source.mode == RegistrationInputMode.SENSOR_PACKAGE
                else RegistrationROI(min_xyz_m=(-20.0, -20.0, -2.0), max_xyz_m=(20.0, 20.0, 8.0))
            ),
            "profile": profile,
            "profile_checksum": profile.profile_checksum,
            "request_checksum": ZERO_CHECKSUM,
        }
    )


def _proposal(
    request: RegistrationRequest,
    *,
    target_scene_revision: str = "scene-rev-1",
    scale_factor: float | None = None,
) -> RegistrationProposal:
    source_ref = _ref("LiDARGeometryArtifact", StageId.LIDAR_INGEST)
    target_ref = request.target_rgb_geometry_ref
    candidate = RegistrationCandidate(
        candidate_id="candidate-1",
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame=request.source.source_frame or "lidar-map-frame",
            translation_xyz=(1.0, 2.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        score=0.95,
        rgb_scale_factor=scale_factor,
    )
    return seal_registration_proposal(
        {
            "job_id": JOB_ID,
            "input_mode": request.source.mode,
            "request_checksum": request.request_checksum,
            "source_input_checksum": request.source.source_input_checksum,
            "source_geometry_ref": source_ref,
            "target_rgb_geometry_ref": target_ref,
            "target_scene_revision": target_scene_revision,
            "profile_checksum": request.profile_checksum,
            "tool_checksum": _checksum("registration-tool-v1"),
            "source_frame": request.source.source_frame or "lidar-map-frame",
            "state": RegistrationProposalState.PROPOSED,
            "candidates": [candidate],
            "selected_candidate_id": candidate.candidate_id,
            "findings": [],
            "proposal_checksum": ZERO_CHECKSUM,
        }
    )


def _pass_report(request: RegistrationRequest, proposal: RegistrationProposal) -> RegistrationQAReport:
    proposal_ref = _ref(
        "RegistrationProposalArtifact",
        StageId.RGB_LIDAR_ALIGN,
        checksum=proposal.proposal_checksum,
    )
    qualification_ref = request.profile.qualification_record_ref
    evidence_refs = [proposal_ref, proposal.source_geometry_ref, proposal.target_rgb_geometry_ref]
    if request.metric_confirmation_ref is not None:
        evidence_refs.append(request.metric_confirmation_ref)
    evidence_refs.extend(request.floor_model_refs)
    if qualification_ref is not None:
        evidence_refs.append(qualification_ref)
    return seal_registration_qa_report(
        {
            "job_id": JOB_ID,
            "input_mode": request.source.mode,
            "request_checksum": request.request_checksum,
            "proposal_ref": proposal_ref,
            "proposal_checksum": proposal.proposal_checksum,
            "source_input_checksum": request.source.source_input_checksum,
            "source_geometry_checksum": proposal.source_geometry_ref.artifact_checksum,
            "target_geometry_checksum": request.target_rgb_geometry_ref.artifact_checksum,
            "target_scene_revision": request.expected_scene_revision,
            "profile": request.profile,
            "profile_checksum": request.profile_checksum,
            "metric_state": request.metric_state,
            "floor_state": request.floor_state,
            "same_scene_attestation": request.source.same_scene_attestation,
            "result": RegistrationQAStatus.PASS,
            "candidate_id": proposal.selected_candidate_id,
            "source_coverage_ratio": 0.9,
            "target_coverage_ratio": 0.9,
            "overlap_ratio": 0.8,
            "bidirectional_p95_residual_m": 0.02,
            "floor_difference_m": 0.01,
            "observable_dof": 3,
            "candidate_margin": 0.5,
            "regions": [
                RegistrationRegionMetric(
                    region_id="warehouse-aisle-1",
                    source_coverage_ratio=0.9,
                    target_coverage_ratio=0.9,
                    correspondence_count=1_200,
                    p95_residual_m=0.02,
                )
            ],
            "evidence_refs": evidence_refs,
            "findings": [],
            "report_checksum": ZERO_CHECKSUM,
        }
    )


def test_static_cloud_request_binds_metric_source_and_returns_ready_preflight() -> None:
    request = _request()

    result = registration_preflight(request)

    assert result.state == RegistrationPreflightState.READY
    assert result.findings == []
    assert request.source.source_distance_unit == DistanceUnit.METER
    assert request.source.source_header_checksum == _checksum("pcd-header")


def test_registered_map_and_static_cloud_roles_are_not_interchangeable() -> None:
    with pytest.raises(ValidationError, match="mode does not match"):
        _source(RegistrationInputMode.REGISTERED_MAP, source_role=InputRole.STATIC_LIDAR_CLOUD)


def test_missing_map_metadata_blocks_preflight_and_invalid_units_are_rejected() -> None:
    source = _source(
        source_distance_unit=None,
        source_frame=None,
        source_format=None,
        source_header_checksum=None,
        same_scene_attestation=None,
    )
    result = registration_preflight(_request(source=source))

    assert result.state == RegistrationPreflightState.INSUFFICIENT
    assert {
        RegistrationFindingCode.SOURCE_UNITS_REQUIRED,
        RegistrationFindingCode.SOURCE_FRAME_REQUIRED,
        RegistrationFindingCode.SOURCE_FORMAT_REQUIRED,
        RegistrationFindingCode.SOURCE_HEADER_REQUIRED,
        RegistrationFindingCode.SAME_SCENE_CONTEXT_MISSING,
    }.issubset(set(result.findings))
    with pytest.raises(ValidationError):
        _source(source_distance_unit="yards")


def test_map_binding_requires_pcd_or_point_cloud_ply_and_exactly_one_file() -> None:
    with pytest.raises(ValidationError, match="supports only parsed PCD/PLY"):
        _source(source_format=InputAssetFormat.GAUSSIAN_PLY)
    with pytest.raises(ValidationError, match="exactly one staged file"):
        _source(source_file_ids=["map-a", "map-b"])
    with pytest.raises(ValidationError, match="distinct from the canonical target world"):
        _source(source_frame="world")


def test_unknown_metric_can_propose_bounded_scale_search_but_not_pass_qa() -> None:
    request = _request(
        profile=_profile(qualified=True, scale_policy="bounded_rgb_scale_search"),
        metric_state="unknown",
    )

    assert registration_preflight(request).state == RegistrationPreflightState.READY
    validate_registration_proposal_binding(request, _proposal(request, scale_factor=1.1))
    with pytest.raises(ValueError, match="frozen RGB scale bounds"):
        validate_registration_proposal_binding(request, _proposal(request, scale_factor=1.3))
    with pytest.raises(ValidationError, match="confirmed metric scale"):
        _pass_report(request, _proposal(request))


def test_raw_scan_sequence_is_routed_to_odometry_before_map_registration() -> None:
    request = _request(source=_source(RegistrationInputMode.RAW_SCAN_SEQUENCE))

    result = registration_preflight(request)

    assert result.state == RegistrationPreflightState.INSUFFICIENT
    assert RegistrationFindingCode.RAW_SCANS_REQUIRE_TRAJECTORY in result.findings


def test_false_same_scene_context_blocks_map_registration() -> None:
    request = _request(source=_source(same_scene_attestation=False))

    result = registration_preflight(request)

    assert result.state == RegistrationPreflightState.INSUFFICIENT
    assert RegistrationFindingCode.DIFFERENT_SCENE in result.findings


@pytest.mark.parametrize(
    ("point_count", "expected_finding"),
    [
        (0, RegistrationFindingCode.EMPTY_CLOUD),
        (20_000_001, RegistrationFindingCode.POINT_BUDGET_EXCEEDED),
    ],
)
def test_empty_and_over_budget_clouds_do_not_enter_registration(
    point_count: int, expected_finding: RegistrationFindingCode
) -> None:
    request = _request(source=_source(source_point_count=point_count))

    result = registration_preflight(request)

    assert result.state == RegistrationPreflightState.INSUFFICIENT
    assert expected_finding in result.findings


@pytest.mark.parametrize("floor_state", ["uncertain", "unsupported"])
def test_uncertain_or_unsupported_floor_blocks_automatic_qa(floor_state: str) -> None:
    request = _request(floor_state=floor_state)

    result = registration_preflight(request)

    expected = (
        RegistrationFindingCode.FLOOR_UNCERTAIN
        if floor_state == "uncertain"
        else RegistrationFindingCode.FLOOR_UNSUPPORTED
    )
    assert result.state == RegistrationPreflightState.INSUFFICIENT
    assert expected in result.findings


def test_legacy_unbound_floor_model_ref_is_readable_but_blocks_map_preflight() -> None:
    request = _request(floor_artifact_type="FloorModel")

    result = registration_preflight(request)

    assert result.state == RegistrationPreflightState.INSUFFICIENT
    assert RegistrationFindingCode.TARGET_FLOOR_EVIDENCE_REQUIRED in result.findings


def test_sensor_package_mode_preserves_existing_metric_ingest_binding() -> None:
    request = _request(source=_source(RegistrationInputMode.SENSOR_PACKAGE))

    assert registration_preflight(request).state == RegistrationPreflightState.READY

    package_ref = _ref("LidarPackageRecord", StageId.LIDAR_INGEST, job_id="other-job")
    with pytest.raises(ValidationError, match="target job"):
        _source(
            RegistrationInputMode.SENSOR_PACKAGE,
            lidar_package_ref=package_ref,
            source_input_checksum=package_ref.artifact_checksum,
        )


def test_cross_project_source_binding_and_oversized_roi_are_rejected() -> None:
    with pytest.raises(ValidationError, match="not authorized"):
        _request(source=_source(authorized_project_id="other-project"))
    with pytest.raises(ValidationError, match="ROI exceeds"):
        _request(
            source=_source(),
            profile=seal_registration_profile(
                {
                    "schema_version": "1.0",
                    "profile_id": "small-roi",
                    "max_roi_extent_m": 10.0,
                    "profile_checksum": ZERO_CHECKSUM,
                }
            ),
        )


def test_profile_requires_ordered_scale_bounds_and_server_qualification_ref() -> None:
    with pytest.raises(ValidationError, match="positive and ordered"):
        seal_registration_profile(
            {
                "schema_version": "1.0",
                "profile_id": "bad-bounds",
                "scale_policy": "bounded_rgb_scale_search",
                "rgb_scale_factor_bounds": [2.0, 1.0],
                "profile_checksum": ZERO_CHECKSUM,
            }
        )
    with pytest.raises(ValidationError, match="qualification record"):
        seal_registration_profile(
            {
                "schema_version": "1.0",
                "profile_id": "unqualified-claim",
                "qualification_state": "qualified",
                "qualification_record_ref": _ref("FakeQualification", StageId.RGB_LIDAR_ALIGN),
                "profile_checksum": ZERO_CHECKSUM,
            }
        )


def test_proposal_binding_rejects_stale_scene_revision() -> None:
    request = _request()
    current = _proposal(request)
    validate_registration_proposal_binding(request, current)

    stale = _proposal(request, target_scene_revision="scene-rev-old")
    with pytest.raises(ValueError, match="stale or bound"):
        validate_registration_proposal_binding(request, stale)


def test_proposal_rejects_cross_job_geometry_refs() -> None:
    request = _request()
    with pytest.raises(ValidationError, match="belong to the target job"):
        seal_registration_proposal(
            {
                "job_id": JOB_ID,
                "input_mode": RegistrationInputMode.STATIC_CLOUD,
                "request_checksum": request.request_checksum,
                "source_input_checksum": request.source.source_input_checksum,
                "source_geometry_ref": _ref("LiDARGeometryArtifact", StageId.LIDAR_INGEST, job_id="other-job"),
                "target_rgb_geometry_ref": request.target_rgb_geometry_ref,
                "target_scene_revision": request.expected_scene_revision,
                "profile_checksum": request.profile_checksum,
                "tool_checksum": _checksum("tool"),
                "source_frame": "lidar-map-frame",
                "state": RegistrationProposalState.FAILED,
                "findings": [RegistrationFindingCode.LOW_OVERLAP],
                "proposal_checksum": ZERO_CHECKSUM,
            }
        )


def test_qa_pass_requires_qualified_profile_and_exact_bound_evidence() -> None:
    request = _request(profile=_profile(qualified=True))
    proposal = _proposal(request)
    report = _pass_report(request, proposal)

    validate_registration_qa_binding(request, proposal, report)

    missing_source = report.model_copy(
        update={"evidence_refs": [ref for ref in report.evidence_refs if ref != proposal.source_geometry_ref]}
    )
    from src.models.contracts.identity import canonical_content_checksum

    payload = missing_source.model_dump(mode="json")
    payload["report_checksum"] = canonical_content_checksum(payload, "report_checksum")
    missing_source = RegistrationQAReport.model_validate(payload)
    with pytest.raises(ValueError, match="exact proposal, geometry, metric, floor and profile refs"):
        validate_registration_qa_binding(request, proposal, missing_source)


def test_qa_failure_and_inconclusive_results_need_explicit_findings() -> None:
    request = _request(profile=_profile(qualified=True))
    proposal = _proposal(request)
    base = _pass_report(request, proposal).model_dump(mode="json")
    base.update(result=RegistrationQAStatus.FAIL, findings=[], report_checksum=ZERO_CHECKSUM)

    with pytest.raises(ValidationError, match="explicit finding codes"):
        seal_registration_qa_report(base)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_coverage_ratio", 0.05),
        ("target_coverage_ratio", 0.05),
        ("overlap_ratio", 0.1),
        ("bidirectional_p95_residual_m", 0.11),
        ("floor_difference_m", 0.11),
        ("observable_dof", 2),
        ("candidate_margin", 0.01),
    ],
)
def test_qa_pass_rejects_metrics_outside_provisional_profile(field: str, value: float) -> None:
    request = _request(profile=_profile(qualified=True))
    proposal = _proposal(request)
    payload = _pass_report(request, proposal).model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError, match="registration QA"):
        seal_registration_qa_report(payload)


def test_qa_pass_requires_residuals_in_every_region() -> None:
    request = _request(profile=_profile(qualified=True))
    proposal = _proposal(request)
    payload = _pass_report(request, proposal).model_dump(mode="json")
    payload["regions"][0]["p95_residual_m"] = 0.11

    with pytest.raises(ValidationError, match="region residual"):
        seal_registration_qa_report(payload)


def test_reference_error_is_only_valid_for_held_out_or_evaluation_data() -> None:
    with pytest.raises(ValidationError, match="held-out/evaluation"):
        RegistrationReferenceError(
            reference_ref=ArtifactRef(
                artifact_type="GroundTruthTransform",
                schema_version="1.0",
                artifact_uri="artifact://jobs/job-rgb-1/gt/transform.json",
                artifact_checksum=_checksum("gt"),
                data_class=ArtifactDataClass.DERIVED,
                producer_stage=StageId.RGB_LIDAR_ALIGN,
                job_id=JOB_ID,
            ),
            translation_error_m=0.01,
            rotation_error_degrees=0.2,
        )


def test_registration_state_machine_blocks_terminal_and_skipped_transitions() -> None:
    validate_registration_transition(RegistrationOperationState.REQUESTED, RegistrationOperationState.QUEUED)
    validate_registration_transition(RegistrationOperationState.RUNNING, RegistrationOperationState.WAITING_RESOURCES)
    validate_registration_transition(RegistrationOperationState.WAITING_RESOURCES, RegistrationOperationState.RUNNING)
    validate_registration_transition(RegistrationOperationState.CONFIRMED, RegistrationOperationState.COMMITTED)

    with pytest.raises(ValueError, match="invalid registration state transition"):
        validate_registration_transition(RegistrationOperationState.COMMITTED, RegistrationOperationState.RUNNING)
    with pytest.raises(ValueError, match="invalid registration state transition"):
        validate_registration_transition(RegistrationOperationState.REQUESTED, RegistrationOperationState.CONFIRMED)
    with pytest.raises(ValueError, match="invalid registration state transition"):
        validate_registration_transition(
            RegistrationOperationState.WAITING_RESOURCES, RegistrationOperationState.PROPOSED
        )


def test_mutating_a_sealed_request_is_detected_before_preflight() -> None:
    request = _request()
    mutated = request.model_copy(update={"expected_scene_revision": "scene-rev-changed"})

    with pytest.raises(ValueError, match="does not match canonical content"):
        registration_preflight(mutated)


def test_profile_checksum_binds_bev_search_limits() -> None:
    profile = _profile()
    changed = seal_registration_profile(
        {
            **profile.model_dump(mode="json"),
            "bev_cell_resolution_m": 0.4,
            "search_seed": profile.search_seed + 1,
            "max_refinement_points": 40_000,
            "max_refinement_candidates": 4,
        }
    )

    assert changed.profile_checksum != profile.profile_checksum
    assert changed.bev_cell_resolution_m == 0.4
    assert changed.search_seed == profile.search_seed + 1
    assert changed.max_refinement_points == 40_000
    assert changed.max_refinement_candidates == 4


def test_profile_rejects_unordered_height_bands() -> None:
    profile = _profile()
    payload = profile.model_dump(mode="json")
    payload["bev_height_edges_m"] = [0.15, 0.6, 0.5, 3.0, 6.0]
    with pytest.raises(ValidationError, match="height edges"):
        seal_registration_profile(payload)


def test_profile_checksum_binds_constrained_icp_limits() -> None:
    profile = _profile()
    changed = seal_registration_profile(
        {
            **profile.model_dump(mode="json"),
            "icp_voxel_sizes_m": [1.0, 0.5, 0.1],
            "icp_trim_fraction": 0.6,
            "icp_max_correspondence_distance_m": 0.75,
        }
    )

    assert changed.profile_checksum != profile.profile_checksum
    assert changed.icp_voxel_sizes_m == (1.0, 0.5, 0.1)
    assert changed.icp_trim_fraction == 0.6
    assert changed.icp_max_correspondence_distance_m == 0.75


def test_profile_rejects_non_descending_icp_voxel_schedule() -> None:
    profile = _profile()
    payload = profile.model_dump(mode="json")
    payload["icp_voxel_sizes_m"] = [0.2, 0.4]

    with pytest.raises(ValidationError, match="strictly decreasing"):
        seal_registration_profile(payload)
