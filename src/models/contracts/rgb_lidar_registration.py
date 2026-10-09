"""Contracts for automatic RGB and LiDAR map registration proposals and QA."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self, TypeVar

from pydantic import Field, FiniteFloat, PositiveInt, model_validator

from src.models.contracts.artifacts import (
    ArtifactRef,
    Checksum,
    ContractModel,
    Identifier,
    ProductArtifactRef,
)
from src.models.contracts.coordinates import Transform
from src.models.contracts.identity import (
    artifact_model_checksum,
    canonical_content_checksum,
    verify_content_checksum,
)
from src.models.contracts.input_assembly import DistanceUnit, InputAssetFormat, InputRole
from src.models.contracts.manifests import StageId

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
_CHECKSUM_PLACEHOLDER = "sha256:" + "0" * 64
ContractT = TypeVar("ContractT", bound=ContractModel)


class RegistrationInputMode(StrEnum):
    SENSOR_PACKAGE = "sensor_package"
    REGISTERED_MAP = "registered_map"
    STATIC_CLOUD = "static_cloud"
    RAW_SCAN_SEQUENCE = "raw_scan_sequence"


class RegistrationOperationState(StrEnum):
    REQUESTED = "REQUESTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_RESOURCES = "WAITING_RESOURCES"
    PROPOSED = "PROPOSED"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT = "INSUFFICIENT"
    FAILED = "FAILED"
    REVIEWED = "REVIEWED"
    CONFIRMED = "CONFIRMED"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"


class RegistrationProposalState(StrEnum):
    PROPOSED = "PROPOSED"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT = "INSUFFICIENT"
    FAILED = "FAILED"


class RegistrationQAStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class RegistrationPreflightState(StrEnum):
    READY = "READY"
    INSUFFICIENT = "INSUFFICIENT"


class RegistrationFindingCode(StrEnum):
    SOURCE_FORMAT_REQUIRED = "SOURCE_FORMAT_REQUIRED"
    SOURCE_HEADER_REQUIRED = "SOURCE_HEADER_REQUIRED"
    SOURCE_UNITS_REQUIRED = "SOURCE_UNITS_REQUIRED"
    SOURCE_FRAME_REQUIRED = "SOURCE_FRAME_REQUIRED"
    SAME_SCENE_CONTEXT_MISSING = "SAME_SCENE_CONTEXT_MISSING"
    DIFFERENT_SCENE = "DIFFERENT_SCENE"
    EMPTY_CLOUD = "EMPTY_CLOUD"
    POINT_COUNT_UNAVAILABLE = "POINT_COUNT_UNAVAILABLE"
    POINT_BUDGET_EXCEEDED = "POINT_BUDGET_EXCEEDED"
    RAW_SCANS_REQUIRE_TRAJECTORY = "RAW_SCANS_REQUIRE_TRAJECTORY"
    METRIC_SCALE_UNKNOWN = "METRIC_SCALE_UNKNOWN"
    FLOOR_UNSUPPORTED = "FLOOR_UNSUPPORTED"
    FLOOR_UNCERTAIN = "FLOOR_UNCERTAIN"
    TARGET_FLOOR_EVIDENCE_REQUIRED = "TARGET_FLOOR_EVIDENCE_REQUIRED"
    LOW_OVERLAP = "LOW_OVERLAP"
    LOW_COVERAGE = "LOW_COVERAGE"
    HIGH_RESIDUAL = "HIGH_RESIDUAL"
    AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"
    UNOBSERVABLE = "UNOBSERVABLE"
    SEARCH_BUDGET_EXCEEDED = "SEARCH_BUDGET_EXCEEDED"
    ICP_NOT_CONVERGED = "ICP_NOT_CONVERGED"
    STALE_TARGET = "STALE_TARGET"
    UNQUALIFIED_PROFILE = "UNQUALIFIED_PROFILE"
    METRIC_CONFIRMATION_REQUIRED = "METRIC_CONFIRMATION_REQUIRED"


class RegistrationROI(ContractModel):
    """Bounded target-world search region in canonical meters."""

    frame: Literal["world"] = "world"
    distance_unit: Literal["m"] = "m"
    min_xyz_m: Vector3
    max_xyz_m: Vector3

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Self:
        extents = [high - low for low, high in zip(self.min_xyz_m, self.max_xyz_m, strict=True)]
        if any(extent <= 0 for extent in extents):
            raise ValueError("registration ROI bounds must be ordered")
        return self


class RegistrationProfile(ContractModel):
    """Versioned search limits and provisional QA thresholds for one registration run."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: Identifier
    algorithm: Literal["bev_multicandidate_constrained_icp_v1"] = "bev_multicandidate_constrained_icp_v1"
    distance_unit: Literal["m"] = "m"
    qualification_state: Literal["provisional", "qualified"] = "provisional"
    qualification_record_ref: ProductArtifactRef | None = None
    scale_policy: Literal["confirmed_metric_only", "bounded_rgb_scale_search"] = "confirmed_metric_only"
    rgb_scale_factor_bounds: tuple[FiniteFloat, FiniteFloat] | None = None
    max_source_points: int = Field(default=20_000_000, ge=1, le=20_000_000, strict=True)
    max_points_per_map: int = Field(default=250_000, ge=1_000, le=1_000_000, strict=True)
    max_roi_extent_m: FiniteFloat = Field(default=100.0, gt=0, le=1_000)
    bev_cell_resolution_m: FiniteFloat = Field(default=0.25, ge=0.025, le=2.0)
    max_bev_grid_cells: int = Field(default=65_536, ge=1_024, le=262_144, strict=True)
    bev_height_edges_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat] = (
        0.15,
        0.6,
        1.5,
        3.0,
        6.0,
    )
    search_seed: int = Field(default=0, ge=0, le=4_294_967_295, strict=True)
    rgb_scale_hypotheses: int = Field(default=5, ge=2, le=9, strict=True)
    yaw_hypotheses: int = Field(default=180, ge=1, le=720, strict=True)
    translation_hypotheses: int = Field(default=2_500, ge=1, le=100_000, strict=True)
    max_refinement_points: int = Field(default=50_000, ge=1_000, le=250_000, strict=True)
    max_refinement_candidates: int = Field(default=8, ge=1, le=32, strict=True)
    top_k_candidates: int = Field(default=8, ge=1, le=32, strict=True)
    icp_iterations: int = Field(default=50, ge=1, le=200, strict=True)
    icp_voxel_sizes_m: tuple[FiniteFloat, ...] = (0.8, 0.4, 0.2)
    icp_max_correspondence_distance_m: FiniteFloat = Field(default=1.0, gt=0, le=10)
    icp_trim_fraction: FiniteFloat = Field(default=0.7, ge=0.1, le=1.0)
    icp_min_correspondences: int = Field(default=24, ge=6, le=100_000, strict=True)
    icp_max_translation_step_m: FiniteFloat = Field(default=0.5, gt=0, le=5)
    icp_max_yaw_step_rad: FiniteFloat = Field(default=0.174533, gt=0, le=0.785398)
    icp_convergence_translation_m: FiniteFloat = Field(default=0.002, gt=0, le=0.1)
    icp_convergence_yaw_rad: FiniteFloat = Field(default=0.002, gt=0, le=0.1)
    icp_min_singular_ratio: FiniteFloat = Field(default=0.001, gt=0, le=0.1)
    runtime_budget_seconds: PositiveInt = Field(default=300, le=3_600)
    minimum_source_coverage_ratio: FiniteFloat = Field(default=0.1, gt=0, le=1)
    minimum_target_coverage_ratio: FiniteFloat = Field(default=0.1, gt=0, le=1)
    minimum_overlap_ratio: FiniteFloat = Field(default=0.2, gt=0, le=1)
    maximum_bidirectional_p95_residual_m: FiniteFloat = Field(default=0.1, gt=0, le=2)
    maximum_floor_difference_m: FiniteFloat = Field(default=0.1, gt=0, le=2)
    minimum_candidate_margin: FiniteFloat = Field(default=0.05, ge=0, le=1)
    minimum_observable_dof: int = Field(default=3, ge=3, le=6, strict=True)
    profile_checksum: Checksum

    @model_validator(mode="after")
    def _profile_policy(self) -> Self:
        if self.bev_height_edges_m[0] <= 0 or any(
            lower >= upper for lower, upper in zip(self.bev_height_edges_m, self.bev_height_edges_m[1:])
        ):
            raise ValueError("BEV height edges must be strictly increasing")
        if not 1 <= len(self.icp_voxel_sizes_m) <= 4 or any(size <= 0 for size in self.icp_voxel_sizes_m):
            raise ValueError("ICP voxel sizes must contain one to four positive meter values")
        if any(coarse <= fine for coarse, fine in zip(self.icp_voxel_sizes_m, self.icp_voxel_sizes_m[1:])):
            raise ValueError("ICP voxel sizes must be strictly decreasing from coarse to fine")
        if self.qualification_state == "qualified":
            if (
                self.qualification_record_ref is None
                or self.qualification_record_ref.artifact_type != "RegistrationProfileQualification"
                or self.qualification_record_ref.data_class != "derived"
            ):
                raise ValueError("qualified profile requires its server-owned qualification record")
        elif self.qualification_record_ref is not None:
            raise ValueError("provisional profile cannot claim a qualification record")
        if self.scale_policy == "bounded_rgb_scale_search":
            if self.rgb_scale_factor_bounds is None:
                raise ValueError("bounded scale search requires RGB scale factor bounds")
            lower, upper = self.rgb_scale_factor_bounds
            if lower <= 0 or lower >= upper:
                raise ValueError("RGB scale factor bounds must be positive and ordered")
        elif self.rgb_scale_factor_bounds is not None:
            raise ValueError("confirmed-metric profile cannot carry scale search bounds")
        return self

    def checksum(self) -> Checksum:
        """Content identity for every search budget, metric threshold, and qualification state."""
        return canonical_content_checksum(self, "profile_checksum")


class RegistrationSourceBinding(ContractModel):
    """Exact source inventory bound to a target job after project authorization.

    For an independent map, the assembly checksum binds the staged-file inventory;
    source_input_checksum identifies selected source bytes (or a server-derived
    ordered inventory digest for a scan sequence). The header checksum identifies
    the exact parsed PCD/PLY header used to interpret its point fields.
    """

    mode: RegistrationInputMode
    target_job_id: Identifier
    authorized_project_id: Identifier
    source_input_checksum: Checksum
    source_frame: Identifier | None = None
    source_distance_unit: DistanceUnit | None = None
    source_point_count: int | None = Field(default=None, ge=0, strict=True)
    source_format: InputAssetFormat | None = None
    source_header_checksum: Checksum | None = None
    source_role: InputRole | None = None
    input_assembly_id: Identifier | None = None
    input_assembly_revision: PositiveInt | None = None
    input_assembly_checksum: Checksum | None = None
    source_file_ids: list[Identifier] = Field(default_factory=list)
    lidar_package_ref: ProductArtifactRef | None = None
    same_scene_attestation: bool | None = None

    @model_validator(mode="after")
    def _source_mode_fields(self) -> Self:
        assembly_fields = (
            self.input_assembly_id,
            self.input_assembly_revision,
            self.input_assembly_checksum,
        )
        if len(self.source_file_ids) != len(set(self.source_file_ids)):
            raise ValueError("registration source cannot repeat a staged file ID")
        if self.source_frame == "world":
            raise ValueError("registration source frame must be distinct from the canonical target world")
        if self.mode == RegistrationInputMode.SENSOR_PACKAGE:
            if self.lidar_package_ref is None or self.lidar_package_ref.artifact_type != "LidarPackageRecord":
                raise ValueError("sensor-package mode requires an exact LidarPackageRecord reference")
            if self.lidar_package_ref.job_id != self.target_job_id:
                raise ValueError("sensor package must be ingested into the target job")
            if not self.lidar_package_ref.artifact_uri.startswith(f"artifact://jobs/{self.target_job_id}/"):
                raise ValueError("sensor package URI must belong to the target job")
            if self.source_input_checksum != self.lidar_package_ref.artifact_checksum:
                raise ValueError("sensor package source checksum must match the bound package record")
            if (
                self.source_distance_unit != DistanceUnit.METER
                or self.source_role is not None
                or any(value is not None for value in assembly_fields)
                or self.source_file_ids
                or self.source_format is not None
                or self.source_header_checksum is not None
            ):
                raise ValueError("sensor-package mode cannot use staged-map bindings or non-metric units")
            if self.same_scene_attestation is not None:
                raise ValueError("sensor-package same-scene evidence is not a user checkbox")
            return self

        if self.lidar_package_ref is not None or any(value is None for value in assembly_fields):
            raise ValueError("map/cloud modes require one exact staged-file assembly binding")
        if not self.source_file_ids:
            raise ValueError("map/cloud modes require exact staged file IDs")
        expected_role = {
            RegistrationInputMode.REGISTERED_MAP: InputRole.REGISTERED_LIDAR_MAP,
            RegistrationInputMode.STATIC_CLOUD: InputRole.STATIC_LIDAR_CLOUD,
            RegistrationInputMode.RAW_SCAN_SEQUENCE: InputRole.LIDAR_SCAN,
        }[self.mode]
        if self.source_role != expected_role:
            raise ValueError("registration mode does not match the selected input assembly role")
        if self.mode in {RegistrationInputMode.REGISTERED_MAP, RegistrationInputMode.STATIC_CLOUD}:
            if len(self.source_file_ids) != 1:
                raise ValueError("registered maps and static clouds must bind exactly one staged file")
        if self.source_format is not None and self.source_format not in {
            InputAssetFormat.POINT_CLOUD_PCD,
            InputAssetFormat.POINT_CLOUD_PLY,
        }:
            raise ValueError("map registration supports only parsed PCD/PLY point-cloud inputs")
        if self.source_header_checksum is not None and self.source_format is None:
            raise ValueError("parsed point-cloud header requires an observed PCD/PLY format")
        if self.mode == RegistrationInputMode.RAW_SCAN_SEQUENCE and self.same_scene_attestation is not None:
            raise ValueError("raw scan sequence is not a registered-map same-scene assertion")
        return self


class RegistrationSourceCloudManifest(ContractModel):
    """Exact staged point-cloud bytes copied into a job without claiming a world up axis."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["RegistrationSourceCloudManifest"] = "RegistrationSourceCloudManifest"
    producer_stage: Literal[StageId.LIDAR_INGEST] = StageId.LIDAR_INGEST
    job_id: Identifier
    source_geometry_ref: ProductArtifactRef
    input_mode: Literal[RegistrationInputMode.REGISTERED_MAP, RegistrationInputMode.STATIC_CLOUD]
    source_input_checksum: Checksum
    input_assembly_id: Identifier
    input_assembly_revision: PositiveInt
    input_assembly_checksum: Checksum
    source_file_id: Identifier
    source_format: Literal["pcd", "ply"]
    source_header_checksum: Checksum
    source_point_count: PositiveInt
    source_distance_unit: DistanceUnit
    source_frame: Identifier
    same_scene_lineage_verified: bool
    manifest_checksum: Checksum

    @model_validator(mode="after")
    def _bind_source_cloud(self) -> Self:
        reference = self.source_geometry_ref
        if (
            reference.artifact_type != "RegistrationSourcePointCloud"
            or reference.producer_stage != StageId.LIDAR_INGEST
            or reference.job_id != self.job_id
            or not reference.artifact_uri.startswith(f"artifact://jobs/{self.job_id}/")
            or reference.artifact_checksum != self.source_input_checksum
        ):
            raise ValueError("registration source manifest must bind exact copied bytes in its target job")
        if not self.source_frame.strip() or self.source_frame == "world":
            raise ValueError("registration source frame must be explicit and distinct from world")
        return self


class RegistrationRequest(ContractModel):
    """Immutable request for a proposal against one exact RGB geometry revision."""

    schema_version: Literal["1.0"] = "1.0"
    request_id: Identifier
    requested_by: Identifier
    target_project_id: Identifier
    target_job_id: Identifier
    target_rgb_geometry_ref: ProductArtifactRef
    expected_scene_revision: Identifier
    source: RegistrationSourceBinding
    metric_state: Literal["confirmed", "unknown"]
    metric_confirmation_ref: ProductArtifactRef | None = None
    floor_state: Literal["supported", "uncertain", "unsupported"]
    # Keep the schema-1.0 wire name; new refs point to the published FloorFitEvidence envelope.
    floor_model_refs: list[ProductArtifactRef] = Field(default_factory=list)
    target_roi_world: RegistrationROI | None = None
    profile: RegistrationProfile
    profile_checksum: Checksum
    request_checksum: Checksum

    @model_validator(mode="after")
    def _bind_request(self) -> Self:
        if self.target_rgb_geometry_ref.artifact_type != "RgbGeometry":
            raise ValueError("registration target must be canonical RGB geometry")
        if (
            self.target_rgb_geometry_ref.job_id != self.target_job_id
            or not self.target_rgb_geometry_ref.artifact_uri.startswith(f"artifact://jobs/{self.target_job_id}/")
        ):
            raise ValueError("RGB target reference must belong to the target job")
        if self.target_rgb_geometry_ref.producer_stage != StageId.RGB_GEOMETRY:
            raise ValueError("registration target must come from the RGB geometry stage")
        if self.source.target_job_id != self.target_job_id:
            raise ValueError("source binding target job differs from the registration target")
        if self.source.authorized_project_id != self.target_project_id:
            raise ValueError("source binding is not authorized in the target project")
        if self.source.mode != RegistrationInputMode.SENSOR_PACKAGE and self.target_roi_world is None:
            raise ValueError("independent-map registration requires a bounded target-world ROI")
        if self.target_roi_world is not None:
            extents = [
                high - low
                for low, high in zip(self.target_roi_world.min_xyz_m, self.target_roi_world.max_xyz_m, strict=True)
            ]
            if any(extent > self.profile.max_roi_extent_m for extent in extents):
                raise ValueError("registration ROI exceeds the profile search extent")
        if self.profile_checksum != self.profile.profile_checksum or self.profile.checksum() != self.profile_checksum:
            raise ValueError("request profile checksum does not match the embedded profile")
        if self.metric_state == "confirmed":
            if self.metric_confirmation_ref is None:
                raise ValueError("confirmed metric state requires its exact confirmation artifact")
            if (
                self.metric_confirmation_ref.artifact_type != "RGBMetricConfirmation"
                or self.metric_confirmation_ref.job_id != self.target_job_id
                or not self.metric_confirmation_ref.artifact_uri.startswith(f"artifact://jobs/{self.target_job_id}/")
            ):
                raise ValueError("metric confirmation must belong to the target job")
        elif self.metric_confirmation_ref is not None:
            raise ValueError("unknown metric state cannot carry a confirmation reference")
        if self.floor_state == "supported" and not self.floor_model_refs:
            raise ValueError("supported floor state requires exact floor-evidence references")
        if self.floor_state == "unsupported" and self.floor_model_refs:
            raise ValueError("unsupported floor state cannot bind supported floor evidence")
        for reference in self.floor_model_refs:
            if (
                reference.artifact_type not in {"FloorFitEvidence", "FloorModel"}
                or reference.job_id != self.target_job_id
                or not reference.artifact_uri.startswith(f"artifact://jobs/{self.target_job_id}/")
            ):
                raise ValueError("floor evidence reference must belong to the target job")
            if reference.artifact_type == "FloorFitEvidence" and reference.producer_stage != StageId.OBJECT_EXTRACT:
                raise ValueError("floor-fit evidence must come from the object-extraction stage")
        return self

    @property
    def floor_evidence_refs(self) -> list[ProductArtifactRef]:
        """FloorFitEvidence refs under the schema-1.0 field name retained for compatibility."""
        return self.floor_model_refs


class RegistrationPreflight(ContractModel):
    request_checksum: Checksum
    state: RegistrationPreflightState
    findings: list[RegistrationFindingCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _state_has_findings(self) -> Self:
        if (self.state == RegistrationPreflightState.READY) == bool(self.findings):
            raise ValueError("ready preflight has no findings; insufficient preflight requires findings")
        return self


def registration_preflight(request: RegistrationRequest) -> RegistrationPreflight:
    """Reject unsupported or unobservable input before worker admission."""
    verify_content_checksum(request, "request_checksum")
    if request.profile.checksum() != request.profile_checksum:
        raise ValueError("registration profile changed after request sealing")
    findings: list[RegistrationFindingCode] = []
    source = request.source
    if source.mode == RegistrationInputMode.RAW_SCAN_SEQUENCE:
        findings.append(RegistrationFindingCode.RAW_SCANS_REQUIRE_TRAJECTORY)
    if source.mode != RegistrationInputMode.SENSOR_PACKAGE:
        if source.source_format is None:
            findings.append(RegistrationFindingCode.SOURCE_FORMAT_REQUIRED)
        if source.source_header_checksum is None:
            findings.append(RegistrationFindingCode.SOURCE_HEADER_REQUIRED)
        if source.source_distance_unit is None:
            findings.append(RegistrationFindingCode.SOURCE_UNITS_REQUIRED)
        if source.source_frame is None:
            findings.append(RegistrationFindingCode.SOURCE_FRAME_REQUIRED)
        if source.same_scene_attestation is None:
            findings.append(RegistrationFindingCode.SAME_SCENE_CONTEXT_MISSING)
        elif source.same_scene_attestation is False:
            findings.append(RegistrationFindingCode.DIFFERENT_SCENE)
    elif source.source_frame is None:
        findings.append(RegistrationFindingCode.SOURCE_FRAME_REQUIRED)
    if source.source_point_count is None:
        findings.append(RegistrationFindingCode.POINT_COUNT_UNAVAILABLE)
    elif source.source_point_count == 0:
        findings.append(RegistrationFindingCode.EMPTY_CLOUD)
    elif source.source_point_count > request.profile.max_source_points:
        findings.append(RegistrationFindingCode.POINT_BUDGET_EXCEEDED)
    if request.metric_state == "unknown" and request.profile.scale_policy == "confirmed_metric_only":
        findings.append(RegistrationFindingCode.METRIC_SCALE_UNKNOWN)
    if request.source.mode in {RegistrationInputMode.REGISTERED_MAP, RegistrationInputMode.STATIC_CLOUD} and (
        len(request.floor_evidence_refs) != 1
        or any(reference.artifact_type != "FloorFitEvidence" for reference in request.floor_evidence_refs)
    ):
        findings.append(RegistrationFindingCode.TARGET_FLOOR_EVIDENCE_REQUIRED)
    if request.floor_state == "unsupported":
        findings.append(RegistrationFindingCode.FLOOR_UNSUPPORTED)
    elif request.floor_state == "uncertain":
        findings.append(RegistrationFindingCode.FLOOR_UNCERTAIN)
    return RegistrationPreflight(
        request_checksum=request.request_checksum,
        state=RegistrationPreflightState.INSUFFICIENT if findings else RegistrationPreflightState.READY,
        findings=findings,
    )


class RegistrationCandidate(ContractModel):
    candidate_id: Identifier
    transform_target_from_source: Transform
    score: FiniteFloat = Field(ge=0, le=1)
    rgb_scale_factor: FiniteFloat | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _rigid_transform(self) -> Self:
        if self.transform_target_from_source.parent_frame != "world":
            raise ValueError("candidate transform target must be canonical world")
        return self


class RegistrationProposal(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["RegistrationProposalArtifact"] = "RegistrationProposalArtifact"
    producer_stage: Literal[StageId.RGB_LIDAR_ALIGN] = StageId.RGB_LIDAR_ALIGN
    job_id: Identifier
    input_mode: RegistrationInputMode
    request_checksum: Checksum
    source_input_checksum: Checksum
    source_geometry_ref: ProductArtifactRef
    target_rgb_geometry_ref: ProductArtifactRef
    target_scene_revision: Identifier
    profile_checksum: Checksum
    tool_checksum: Checksum
    source_frame: Identifier
    state: RegistrationProposalState
    candidates: list[RegistrationCandidate] = Field(default_factory=list)
    selected_candidate_id: Identifier | None = None
    findings: list[RegistrationFindingCode] = Field(default_factory=list)
    proposal_checksum: Checksum

    @model_validator(mode="after")
    def _proposal_shape(self) -> Self:
        if (
            self.source_geometry_ref.artifact_type not in {"LiDARGeometryArtifact", "RegistrationSourcePointCloud"}
            or self.source_geometry_ref.producer_stage != StageId.LIDAR_INGEST
        ):
            raise ValueError("proposal source must be ingested LiDAR geometry or a bound registration source cloud")
        if (
            self.target_rgb_geometry_ref.artifact_type != "RgbGeometry"
            or self.target_rgb_geometry_ref.producer_stage != StageId.RGB_GEOMETRY
        ):
            raise ValueError("proposal target must be canonical RGB geometry")
        for reference in (self.source_geometry_ref, self.target_rgb_geometry_ref):
            if reference.job_id != self.job_id or not reference.artifact_uri.startswith(
                f"artifact://jobs/{self.job_id}/"
            ):
                raise ValueError("proposal geometry references must belong to the target job")
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("registration candidate IDs must be unique")
        if any(
            candidate.transform_target_from_source.local_frame != self.source_frame for candidate in self.candidates
        ):
            raise ValueError("candidate transform source frame differs from the registered LiDAR map")
        if self.state == RegistrationProposalState.PROPOSED:
            if self.selected_candidate_id not in ids or self.findings:
                raise ValueError("proposed registration must select one listed candidate")
        elif self.state == RegistrationProposalState.AMBIGUOUS:
            if (
                len(ids) < 2
                or self.selected_candidate_id is not None
                or RegistrationFindingCode.AMBIGUOUS_CANDIDATES not in self.findings
            ):
                raise ValueError("ambiguous registration needs multiple candidates and no selected candidate")
        elif self.candidates or not self.findings:
            raise ValueError("insufficient/failed registration requires findings and no candidates")
        return self


class RegistrationRegionMetric(ContractModel):
    region_id: Identifier
    source_coverage_ratio: FiniteFloat = Field(ge=0, le=1)
    target_coverage_ratio: FiniteFloat = Field(ge=0, le=1)
    correspondence_count: int = Field(ge=0, strict=True)
    p95_residual_m: FiniteFloat | None = Field(default=None, ge=0)


class RegistrationReferenceError(ContractModel):
    reference_ref: ArtifactRef
    translation_error_m: FiniteFloat = Field(ge=0)
    rotation_error_degrees: FiniteFloat = Field(ge=0)

    @model_validator(mode="after")
    def _evaluation_only_reference(self) -> Self:
        if self.reference_ref.data_class not in {"ground_truth", "evaluation_only"}:
            raise ValueError("registration reference error must use held-out/evaluation data")
        return self


class RegistrationQAReport(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["RegistrationQAReport"] = "RegistrationQAReport"
    producer_stage: Literal[StageId.RGB_LIDAR_ALIGN] = StageId.RGB_LIDAR_ALIGN
    job_id: Identifier
    input_mode: RegistrationInputMode
    request_checksum: Checksum
    proposal_ref: ProductArtifactRef
    proposal_checksum: Checksum
    source_input_checksum: Checksum
    source_geometry_checksum: Checksum
    target_geometry_checksum: Checksum
    target_scene_revision: Identifier
    profile: RegistrationProfile
    profile_checksum: Checksum
    metric_state: Literal["confirmed", "unknown"]
    floor_state: Literal["supported", "uncertain", "unsupported"]
    same_scene_attestation: bool | None = None
    result: RegistrationQAStatus
    candidate_id: Identifier | None = None
    source_coverage_ratio: FiniteFloat | None = Field(default=None, ge=0, le=1)
    target_coverage_ratio: FiniteFloat | None = Field(default=None, ge=0, le=1)
    overlap_ratio: FiniteFloat | None = Field(default=None, ge=0, le=1)
    bidirectional_p95_residual_m: FiniteFloat | None = Field(default=None, ge=0)
    floor_difference_m: FiniteFloat | None = Field(default=None, ge=0)
    observable_dof: int | None = Field(default=None, ge=0, le=6, strict=True)
    candidate_margin: FiniteFloat | None = Field(default=None, ge=0, le=1)
    regions: list[RegistrationRegionMetric] = Field(default_factory=list)
    evidence_refs: list[ProductArtifactRef] = Field(default_factory=list)
    findings: list[RegistrationFindingCode] = Field(default_factory=list)
    independent_reference_error: RegistrationReferenceError | None = None
    report_checksum: Checksum

    @model_validator(mode="after")
    def _report_shape(self) -> Self:
        if (
            self.proposal_ref.artifact_type != "RegistrationProposalArtifact"
            or self.proposal_ref.producer_stage != StageId.RGB_LIDAR_ALIGN
            or self.proposal_ref.job_id != self.job_id
            or not self.proposal_ref.artifact_uri.startswith(f"artifact://jobs/{self.job_id}/")
        ):
            raise ValueError("QA report must bind a proposal from the same target job")
        if self.profile_checksum != self.profile.profile_checksum or self.profile.checksum() != self.profile_checksum:
            raise ValueError("QA report profile checksum mismatch")
        region_ids = [region.region_id for region in self.regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("registration QA region IDs must be unique")
        if self.result == RegistrationQAStatus.PASS:
            if self.profile.qualification_state != "qualified":
                raise ValueError("registration QA PASS requires a qualified frozen profile")
            if self.metric_state != "confirmed" or self.floor_state != "supported":
                raise ValueError("registration QA PASS requires confirmed metric scale and supported floor")
            if self.input_mode != RegistrationInputMode.SENSOR_PACKAGE and self.same_scene_attestation is not True:
                raise ValueError("independent-map QA PASS requires same-scene context evidence")
            if self.candidate_id is None or self.findings or not self.evidence_refs:
                raise ValueError("registration QA PASS requires one candidate and observed evidence")
            if not self.regions:
                raise ValueError("registration QA PASS requires measured per-region evidence")
            required_refs = [self.proposal_ref]
            if self.profile.qualification_record_ref is not None:
                required_refs.append(self.profile.qualification_record_ref)
            if any(reference not in self.evidence_refs for reference in required_refs):
                raise ValueError("registration QA evidence must include exact proposal and qualification refs")
            metrics = (
                self.source_coverage_ratio,
                self.target_coverage_ratio,
                self.overlap_ratio,
                self.bidirectional_p95_residual_m,
                self.floor_difference_m,
                self.observable_dof,
                self.candidate_margin,
            )
            if any(value is None for value in metrics):
                raise ValueError("registration QA PASS requires all observed metrics")
            if self.source_coverage_ratio < self.profile.minimum_source_coverage_ratio:
                raise ValueError("registration QA source coverage is below profile")
            if self.target_coverage_ratio < self.profile.minimum_target_coverage_ratio:
                raise ValueError("registration QA target coverage is below profile")
            if self.overlap_ratio < self.profile.minimum_overlap_ratio:
                raise ValueError("registration QA overlap is below profile")
            if self.bidirectional_p95_residual_m > self.profile.maximum_bidirectional_p95_residual_m:
                raise ValueError("registration QA residual is above profile")
            if self.floor_difference_m > self.profile.maximum_floor_difference_m:
                raise ValueError("registration QA floor consistency is above profile")
            if self.observable_dof < self.profile.minimum_observable_dof:
                raise ValueError("registration QA observability is below profile")
            if self.candidate_margin < self.profile.minimum_candidate_margin:
                raise ValueError("registration QA candidate separation is below profile")
            for region in self.regions:
                if region.correspondence_count == 0 or region.p95_residual_m is None:
                    raise ValueError("registration QA PASS requires residual evidence in every observed region")
                if region.source_coverage_ratio < self.profile.minimum_source_coverage_ratio:
                    raise ValueError("registration QA region source coverage is below profile")
                if region.target_coverage_ratio < self.profile.minimum_target_coverage_ratio:
                    raise ValueError("registration QA region target coverage is below profile")
                if region.p95_residual_m > self.profile.maximum_bidirectional_p95_residual_m:
                    raise ValueError("registration QA region residual is above profile")
        elif not self.findings:
            raise ValueError("FAIL/INCONCLUSIVE registration QA requires explicit finding codes")
        return self


def _seal_contract(value: ContractT | dict[str, object], model_type: type[ContractT], checksum_field: str) -> ContractT:
    payload = value.model_dump(mode="json") if isinstance(value, ContractModel) else dict(value)
    payload[checksum_field] = _CHECKSUM_PLACEHOLDER
    normalized = model_type.model_validate(payload).model_dump(mode="json")
    normalized[checksum_field] = canonical_content_checksum(normalized, checksum_field)
    return model_type.model_validate(normalized)


def seal_registration_profile(value: RegistrationProfile | dict[str, object]) -> RegistrationProfile:
    return _seal_contract(value, RegistrationProfile, "profile_checksum")


def seal_registration_request(value: RegistrationRequest | dict[str, object]) -> RegistrationRequest:
    return _seal_contract(value, RegistrationRequest, "request_checksum")


def seal_registration_proposal(value: RegistrationProposal | dict[str, object]) -> RegistrationProposal:
    return _seal_contract(value, RegistrationProposal, "proposal_checksum")


def seal_registration_source_cloud_manifest(
    value: RegistrationSourceCloudManifest | dict[str, object],
) -> RegistrationSourceCloudManifest:
    return _seal_contract(value, RegistrationSourceCloudManifest, "manifest_checksum")


def seal_registration_qa_report(value: RegistrationQAReport | dict[str, object]) -> RegistrationQAReport:
    return _seal_contract(value, RegistrationQAReport, "report_checksum")


def validate_registration_proposal_binding(request: RegistrationRequest, proposal: RegistrationProposal) -> None:
    """Reject stale target, changed source/profile, or cross-job proposal refs."""
    verify_content_checksum(request, "request_checksum")
    verify_content_checksum(proposal, "proposal_checksum")
    if (
        proposal.request_checksum != request.request_checksum
        or proposal.job_id != request.target_job_id
        or proposal.input_mode != request.source.mode
        or proposal.source_input_checksum != request.source.source_input_checksum
        or proposal.target_rgb_geometry_ref != request.target_rgb_geometry_ref
        or proposal.target_scene_revision != request.expected_scene_revision
        or proposal.profile_checksum != request.profile_checksum
        or proposal.source_frame != request.source.source_frame
    ):
        raise ValueError("registration proposal is stale or bound to different source/target/config")
    if proposal.state == RegistrationProposalState.PROPOSED:
        selected = next(item for item in proposal.candidates if item.candidate_id == proposal.selected_candidate_id)
    else:
        selected = None
    if request.metric_state == "unknown" and proposal.state in {
        RegistrationProposalState.PROPOSED,
        RegistrationProposalState.AMBIGUOUS,
    }:
        if (
            request.profile.scale_policy != "bounded_rgb_scale_search"
            or request.profile.rgb_scale_factor_bounds is None
        ):
            raise ValueError("unknown RGB metric scale requires an enabled bounded scale search")
        lower, upper = request.profile.rgb_scale_factor_bounds
        if any(
            candidate.rgb_scale_factor is None or not lower <= candidate.rgb_scale_factor <= upper
            for candidate in proposal.candidates
        ):
            raise ValueError("every unknown-scale candidate must stay inside the frozen RGB scale bounds")
        if selected is not None and selected.rgb_scale_factor is None:
            raise ValueError("selected unknown-scale candidate requires an explicit scale hypothesis")
    elif request.metric_state == "confirmed" and any(
        candidate.rgb_scale_factor is not None for candidate in proposal.candidates
    ):
        raise ValueError("metric-confirmed registration cannot rescale the RGB scene silently")


def validate_registration_qa_binding(
    request: RegistrationRequest, proposal: RegistrationProposal, report: RegistrationQAReport
) -> None:
    """Require the QA report to describe the exact request, candidate, source, and target revision."""
    validate_registration_proposal_binding(request, proposal)
    verify_content_checksum(report, "report_checksum")
    if (
        report.request_checksum != request.request_checksum
        or report.proposal_checksum != proposal.proposal_checksum
        or report.source_input_checksum != request.source.source_input_checksum
        or report.source_geometry_checksum != proposal.source_geometry_ref.artifact_checksum
        or report.target_geometry_checksum != request.target_rgb_geometry_ref.artifact_checksum
        or report.target_scene_revision != request.expected_scene_revision
        or report.profile_checksum != request.profile_checksum
        or report.job_id != request.target_job_id
        or report.input_mode != request.source.mode
        or report.metric_state != request.metric_state
        or report.floor_state != request.floor_state
        or report.same_scene_attestation != request.source.same_scene_attestation
    ):
        raise ValueError("registration QA report is stale or bound to different evidence")
    if report.proposal_ref.artifact_checksum != artifact_model_checksum(proposal):
        raise ValueError("registration QA proposal ref checksum mismatch")
    if report.result == RegistrationQAStatus.PASS:
        required_refs = [proposal.source_geometry_ref, proposal.target_rgb_geometry_ref]
        if request.metric_confirmation_ref is not None:
            required_refs.append(request.metric_confirmation_ref)
        required_refs.extend(request.floor_evidence_refs)
        if request.profile.qualification_record_ref is not None:
            required_refs.append(request.profile.qualification_record_ref)
        if any(reference not in report.evidence_refs for reference in required_refs):
            raise ValueError(
                "registration QA PASS must include exact proposal, geometry, metric, floor and profile refs"
            )
    if report.result == RegistrationQAStatus.PASS and (
        proposal.state != RegistrationProposalState.PROPOSED or report.candidate_id != proposal.selected_candidate_id
    ):
        raise ValueError("registration QA PASS must bind the selected, unambiguous proposal candidate")


_ALLOWED_TRANSITIONS: dict[RegistrationOperationState, frozenset[RegistrationOperationState]] = {
    RegistrationOperationState.REQUESTED: frozenset(
        {RegistrationOperationState.QUEUED, RegistrationOperationState.INSUFFICIENT, RegistrationOperationState.FAILED}
    ),
    RegistrationOperationState.QUEUED: frozenset(
        {RegistrationOperationState.RUNNING, RegistrationOperationState.FAILED, RegistrationOperationState.CANCELLED}
    ),
    RegistrationOperationState.RUNNING: frozenset(
        {
            RegistrationOperationState.WAITING_RESOURCES,
            RegistrationOperationState.PROPOSED,
            RegistrationOperationState.AMBIGUOUS,
            RegistrationOperationState.INSUFFICIENT,
            RegistrationOperationState.FAILED,
            RegistrationOperationState.CANCELLED,
        }
    ),
    RegistrationOperationState.WAITING_RESOURCES: frozenset(
        {
            RegistrationOperationState.RUNNING,
            RegistrationOperationState.FAILED,
            RegistrationOperationState.CANCELLED,
        }
    ),
    RegistrationOperationState.PROPOSED: frozenset(
        {RegistrationOperationState.REVIEWED, RegistrationOperationState.FAILED, RegistrationOperationState.CANCELLED}
    ),
    RegistrationOperationState.AMBIGUOUS: frozenset(
        {RegistrationOperationState.REVIEWED, RegistrationOperationState.FAILED, RegistrationOperationState.CANCELLED}
    ),
    RegistrationOperationState.REVIEWED: frozenset(
        {RegistrationOperationState.CONFIRMED, RegistrationOperationState.FAILED, RegistrationOperationState.CANCELLED}
    ),
    RegistrationOperationState.CONFIRMED: frozenset(
        {RegistrationOperationState.COMMITTED, RegistrationOperationState.FAILED, RegistrationOperationState.CANCELLED}
    ),
    RegistrationOperationState.INSUFFICIENT: frozenset(),
    RegistrationOperationState.FAILED: frozenset(),
    RegistrationOperationState.COMMITTED: frozenset(),
    RegistrationOperationState.CANCELLED: frozenset(),
}


def validate_registration_transition(
    current: RegistrationOperationState, following: RegistrationOperationState
) -> None:
    """Guard the persisted state machine; retries that change inputs use a new request identity."""
    if following not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid registration state transition: {current.value} -> {following.value}")
