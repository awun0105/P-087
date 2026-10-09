"""Reconstruction artifacts published by EX-REC."""

import hashlib
import math
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import (
    ArtifactDataClass,
    ArtifactRef,
    ArtifactUri,
    Checksum,
    ContractModel,
    Identifier,
    JsonObject,
    ProductArtifactRef,
    SchemaVersion,
)
from src.models.contracts.coordinates import CoordinateSystem, MetricScale, MetricScaleStatus, Transform
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.manifests import InputConfiguration, StageId


class VisualArtifact(ContractModel):
    """Visual representation; production format is determined by its producer."""

    artifact_type: Literal["VisualArtifact"]
    schema_version: SchemaVersion
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    producer_stage: Literal[StageId.VISUAL_RECON]
    job_id: Identifier
    format: Identifier
    producer: Identifier
    producer_version: str
    coordinate_system: CoordinateSystem
    source_input_checksum: Checksum
    provenance: JsonObject


class DependencyOrigin(StrEnum):
    """Nguồn của dependency tiền xử lý, độc lập với dataset/provider."""

    SENSOR_INPUT = "sensor_input"
    ESTIMATED = "estimated"
    EXTERNAL = "external"
    GROUND_TRUTH = "ground_truth"


class PreprocessingDependency(ContractModel):
    """Một dependency đầu vào có vai trò và nguồn gốc truy vết được."""

    role: Identifier
    origin: DependencyOrigin
    source_checksum: Checksum


class PreprocessingProvenance(ContractModel):
    """Dependency lineage chung cho LiDAR ingest và bundle reference."""

    dependencies: list[PreprocessingDependency]
    ground_truth_assisted: bool
    details: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bind_assistance_to_dependencies(self) -> Self:
        uses_ground_truth = any(item.origin == DependencyOrigin.GROUND_TRUTH for item in self.dependencies)
        if self.ground_truth_assisted != uses_ground_truth:
            raise ValueError("ground_truth_assisted must match ground-truth dependencies")
        return self


class LiDARGeometryArtifact(ContractModel):
    """Registered LiDAR geometry before RGB alignment/composition."""

    artifact_type: Literal["LiDARGeometryArtifact"]
    schema_version: SchemaVersion
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    producer_stage: Literal[StageId.LIDAR_INGEST]
    job_id: Identifier
    source_modality: Literal["registered_lidar"]
    source_input_checksum: Checksum
    geometry_format: Identifier
    coordinate_system: CoordinateSystem
    source_frame: Identifier
    declared_transform_to_canonical: Transform | None = None
    preprocessing_provenance: PreprocessingProvenance


class EstimatedTrajectoryPose(ContractModel):
    """One estimated sensor pose bound to the exact source scan and timestamp row."""

    scan_index: int = Field(ge=0)
    source_scan_file_id: Identifier
    source_scan_checksum: Checksum
    timestamp_seconds: FiniteFloat
    map_from_sensor: Transform

    @model_validator(mode="after")
    def _require_finite_translation(self) -> Self:
        if not all(math.isfinite(component) for component in self.map_from_sensor.translation_xyz):
            raise ValueError("trajectory pose translation must be finite")
        return self


class EstimatedTrajectoryExecutionMetrics(ContractModel):
    """Measured per-attempt resource use; metrics describe only the provider child."""

    process_elapsed_seconds: FiniteFloat = Field(ge=0)
    provider_elapsed_seconds: FiniteFloat = Field(ge=0)
    provider_cpu_seconds: FiniteFloat = Field(ge=0)
    provider_peak_rss_bytes: int = Field(gt=0)
    scan_point_counts: list[int] = Field(min_length=2)

    @model_validator(mode="after")
    def _validate_point_counts(self) -> Self:
        if any(count < 1 for count in self.scan_point_counts):
            raise ValueError("odometry point counts must be positive")
        return self


class EstimatedTrajectoryDiagnostics(ContractModel):
    """Observed odometry diagnostics; absolute drift remains unknown without a reference."""

    scan_count: int = Field(ge=2)
    valid_pose_count: int = Field(ge=0)
    coverage_ratio: FiniteFloat = Field(ge=0, le=1)
    timestamp_gap_threshold_seconds: FiniteFloat = Field(gt=0)
    timestamp_gap_count: int = Field(ge=0)
    maximum_timestamp_gap_seconds: FiniteFloat = Field(ge=0)
    converged_scan_count: int | None = Field(default=None, ge=0)
    convergence_method: Identifier | None = None
    degenerate_scan_count: int | None = Field(default=None, ge=0)
    degeneracy_method: Identifier | None = None
    execution_metrics: EstimatedTrajectoryExecutionMetrics | None = None
    absolute_drift_status: Literal["not_measured"] = "not_measured"

    @model_validator(mode="after")
    def _validate_diagnostic_counts(self) -> Self:
        expected_coverage = self.valid_pose_count / self.scan_count
        if self.valid_pose_count > self.scan_count or not math.isclose(
            self.coverage_ratio, expected_coverage, rel_tol=1e-6, abs_tol=1e-6
        ):
            raise ValueError("trajectory coverage must match the valid pose count")
        if self.timestamp_gap_count > self.scan_count - 1:
            raise ValueError("timestamp gap count cannot exceed the scan interval count")
        if self.timestamp_gap_count == 0 and self.maximum_timestamp_gap_seconds > self.timestamp_gap_threshold_seconds:
            raise ValueError("maximum timestamp gap exceeds the threshold but is not counted")
        if self.timestamp_gap_count > 0 and self.maximum_timestamp_gap_seconds <= self.timestamp_gap_threshold_seconds:
            raise ValueError("timestamp gap count requires a maximum gap above the threshold")
        if (self.converged_scan_count is None) != (self.convergence_method is None):
            raise ValueError("convergence count and method must be reported together")
        if self.converged_scan_count is not None and self.converged_scan_count > self.scan_count:
            raise ValueError("converged scan count cannot exceed the scan count")
        if (self.degenerate_scan_count is None) != (self.degeneracy_method is None):
            raise ValueError("degeneracy count and method must be reported together")
        if self.degenerate_scan_count is not None and self.degenerate_scan_count > self.scan_count:
            raise ValueError("degenerate scan count cannot exceed the scan count")
        if self.execution_metrics is not None and len(self.execution_metrics.scan_point_counts) != self.scan_count:
            raise ValueError("execution point counts must match the trajectory scan count")
        return self


class EstimatedTrajectoryArtifact(ContractModel):
    """Immutable local LiDAR odometry result, never equivalent to supplied or GT poses."""

    artifact_type: Literal["EstimatedTrajectoryArtifact"]
    schema_version: Literal["1.0"]
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    job_id: Identifier
    assembly_id: Identifier
    assembly_revision: int = Field(gt=0)
    assembly_checksum: Checksum
    recipe_checksum: Checksum
    provider_id: Identifier
    provider_version: Identifier
    adapter_protocol_version: Identifier
    runtime_qualification_checksum: Checksum
    config_checksum: Checksum
    timestamp_file_checksum: Checksum
    coordinate_unit: Literal["meter"]
    sensor_frame_id: Identifier
    odometry_map_frame_id: Identifier
    world_from_map: Transform | None = None
    trajectory_origin: Literal["estimated"] = "estimated"
    runtime_qualification_status: Literal["wired_unqualified"] = "wired_unqualified"
    poses: list[EstimatedTrajectoryPose] = Field(min_length=2)
    diagnostics: EstimatedTrajectoryDiagnostics

    @model_validator(mode="after")
    def _bind_poses_to_scan_sequence(self) -> Self:
        if self.sensor_frame_id == self.odometry_map_frame_id:
            raise ValueError("sensor and odometry map frame IDs must differ")
        if self.diagnostics.scan_count != len(self.poses):
            raise ValueError("trajectory artifact must contain one pose per source scan")
        if self.diagnostics.valid_pose_count != len(self.poses) or self.diagnostics.coverage_ratio != 1.0:
            raise ValueError("incomplete trajectories cannot be published as complete artifacts")
        scan_ids = [pose.source_scan_file_id for pose in self.poses]
        if len(scan_ids) != len(set(scan_ids)):
            raise ValueError("trajectory source scans must be unique")
        previous_timestamp = -math.inf
        for index, pose in enumerate(self.poses):
            if pose.scan_index != index:
                raise ValueError("trajectory pose order must match the selected scan order")
            if pose.timestamp_seconds <= previous_timestamp:
                raise ValueError("trajectory timestamps must increase strictly")
            previous_timestamp = pose.timestamp_seconds
            if (
                pose.map_from_sensor.parent_frame != self.odometry_map_frame_id
                or pose.map_from_sensor.local_frame != self.sensor_frame_id
            ):
                raise ValueError("trajectory pose transform must be map_from_sensor in the declared frames")
        if self.world_from_map is not None and (
            self.world_from_map.parent_frame != "world" or self.world_from_map.local_frame != self.odometry_map_frame_id
        ):
            raise ValueError("world_from_map must map the declared odometry map into canonical world")
        if self.world_from_map is not None and not all(
            math.isfinite(component) for component in self.world_from_map.translation_xyz
        ):
            raise ValueError("world_from_map translation must be finite")
        return self


class EstimatedTrajectoryIngestBinding(ContractModel):
    """Verified scan-to-pose lineage awaiting an explicit world-frame bridge."""

    schema_version: Literal["1.0"] = "1.0"
    trajectory_ref: ArtifactRef
    timestamp_file_ref: ArtifactRef
    assembly_checksum: Checksum
    recipe_checksum: Checksum
    source_scan_file_ids: list[Identifier] = Field(min_length=2)
    source_scan_checksums: list[Checksum] = Field(min_length=2)
    sensor_frame_id: Identifier
    odometry_map_frame_id: Identifier
    world_frame_status: Literal["pending_world_from_map_confirmation"] = "pending_world_from_map_confirmation"

    @model_validator(mode="after")
    def _validate_ingest_binding(self) -> Self:
        if self.trajectory_ref.artifact_type != "EstimatedTrajectoryArtifact":
            raise ValueError("ingest binding must reference an estimated trajectory artifact")
        if self.trajectory_ref.data_class != ArtifactDataClass.DERIVED:
            raise ValueError("estimated trajectory reference must be derived data")
        if self.timestamp_file_ref.data_class != ArtifactDataClass.PRODUCT_INPUT:
            raise ValueError("ingest binding timestamp reference must be a product input")
        provenance = self.trajectory_ref.source_provenance or {}
        if (
            provenance.get("assembly_checksum") != self.assembly_checksum
            or provenance.get("recipe_checksum") != self.recipe_checksum
            or provenance.get("timestamp_file_checksum") != self.timestamp_file_ref.artifact_checksum
        ):
            raise ValueError("ingest binding checksums must match the trajectory reference")
        if len(self.source_scan_file_ids) != len(self.source_scan_checksums):
            raise ValueError("scan file IDs and checksums must have equal lengths")
        if len(self.source_scan_file_ids) != len(set(self.source_scan_file_ids)):
            raise ValueError("ingest binding scan file IDs must be unique")
        if self.sensor_frame_id == self.odometry_map_frame_id:
            raise ValueError("sensor and odometry map frame IDs must differ")
        return self


class VoxelGridSummary(ContractModel):
    """Lưới voxel đã dùng, đủ để EX-SIM kiểm clearance mà không cần payload upstream.

    Chỉ giữ phần canonical đã quy đổi; octree native của pinned splat-transform không
    phải shared contract và không được nhân bản vào đây.
    """

    resolution_m: FiniteFloat = Field(gt=0)
    grid_bounds_min_xyz_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    grid_bounds_max_xyz_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    scene_bounds_min_xyz_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    scene_bounds_max_xyz_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]

    @model_validator(mode="after")
    def _require_positive_extent(self) -> Self:
        if any(low >= high for low, high in zip(self.grid_bounds_min_xyz_m, self.grid_bounds_max_xyz_m)):
            raise ValueError("voxel grid bounds must have positive extent")
        if any(low >= high for low, high in zip(self.scene_bounds_min_xyz_m, self.scene_bounds_max_xyz_m)):
            raise ValueError("voxel scene bounds must have positive extent")
        return self


class SeedDecision(ContractModel):
    """Seed đã yêu cầu và seed được chấp nhận; relocation phải hiện diện, không được giấu."""

    requested_world_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    accepted_world_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    relocates: bool
    relocation_distance_m: FiniteFloat = Field(default=0.0, ge=0)
    relocation_bound_m: FiniteFloat = Field(gt=0)
    occupancy_checksum: Checksum
    clearance_evidence_checksum: Checksum

    @model_validator(mode="after")
    def _bind_relocation_to_seed(self) -> Self:
        if self.relocates != (self.requested_world_m != self.accepted_world_m):
            raise ValueError("relocates must match whether requested and accepted seed differ")
        if self.relocates and self.relocation_distance_m > self.relocation_bound_m:
            raise ValueError("seed relocation exceeds the configured bound")
        if not self.relocates and self.relocation_distance_m:
            raise ValueError("a seed accepted in place cannot report a relocation distance")
        actual = math.dist(self.requested_world_m, self.accepted_world_m)
        if not math.isclose(actual, self.relocation_distance_m, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("relocation distance differs from the two seed points")
        return self


class CapsuleFootprint(ContractModel):
    """Footprint clearance khác capsule physics; consumer phải đọc discriminator.

    Với `capsule`, length là chiều dài phần trụ, height = length + 2*radius.
    Với `clearance_cylinder`, length bằng height; không dựng thành capsule physics.
    """

    shape: Literal["capsule", "clearance_cylinder"] = "capsule"
    height_m: FiniteFloat = Field(gt=0)
    radius_m: FiniteFloat = Field(gt=0)
    length_m: FiniteFloat = Field(ge=0)

    @model_validator(mode="after")
    def _bind_length_to_cylinder(self) -> Self:
        if self.shape == "clearance_cylinder":
            if self.length_m != self.height_m:
                raise ValueError("clearance cylinder length must equal its height")
            return self
        if abs(self.height_m - (self.length_m + 2 * self.radius_m)) > 1e-9:
            raise ValueError("capsule length must be height minus two radii")
        return self


class GeometryStatisticalFilterEvidence(ContractModel):
    """Exact diagnostic evidence for an opt-in pre-mesh Gaussian SOR pass."""

    schema_version: Literal["1.0"] = "1.0"
    algorithm: Literal["statistical_outlier_v1"] = "statistical_outlier_v1"
    input_checksum: Checksum
    output_checksum: Checksum
    input_gaussian_count: int = Field(gt=0)
    retained_gaussian_count: int = Field(gt=0)
    removed_gaussian_count: int = Field(ge=0)
    neighbors: int = Field(ge=2, le=64, strict=True)
    standard_deviation_ratio: FiniteFloat = Field(gt=0)
    max_gaussians: int = Field(ge=3, le=5_000_000, strict=True)
    mean_neighbor_distance_m: FiniteFloat = Field(ge=0)
    standard_deviation_m: FiniteFloat = Field(ge=0)
    threshold_m: FiniteFloat = Field(ge=0)
    quality_status: Literal["diagnostic_only"] = "diagnostic_only"

    @model_validator(mode="after")
    def _conserve_gaussian_rows(self) -> Self:
        if self.input_gaussian_count != self.retained_gaussian_count + self.removed_gaussian_count:
            raise ValueError("statistical filter Gaussian counts must conserve input records")
        if self.input_gaussian_count > self.max_gaussians or self.max_gaussians <= self.neighbors:
            raise ValueError("statistical filter evidence exceeds its configured resource bound")
        if not math.isclose(
            self.threshold_m,
            self.mean_neighbor_distance_m + self.standard_deviation_ratio * self.standard_deviation_m,
            rel_tol=1e-6,
            abs_tol=1e-9,
        ):
            raise ValueError("statistical filter threshold differs from its recorded criteria")
        return self


class GeometryCleanupEvidence(ContractModel):
    """Measured Gaussian removal and exact cleanup configuration for one RGB collision mesh."""

    schema_version: Literal["1.0"] = "1.0"
    job_id: Identifier
    mode: Literal["cluster", "floaters"]
    source_checksum: Checksum
    metric_input_checksum: Checksum
    retained_gaussian_checksum: Checksum
    collision_mesh_checksum: Checksum
    effective_config: JsonObject
    config_checksum: Checksum
    statistical_filter_evidence: GeometryStatisticalFilterEvidence | None = None
    input_gaussian_count: int = Field(gt=0)
    retained_gaussian_count: int = Field(gt=0)
    removed_gaussian_count: int = Field(ge=0)
    qualification_status: Literal["diagnostic_only"] = "diagnostic_only"

    @model_validator(mode="after")
    def _bind_counts_and_config(self) -> Self:
        if self.input_gaussian_count != self.retained_gaussian_count + self.removed_gaussian_count:
            raise ValueError("cleanup Gaussian counts must conserve input records")
        if self.effective_config.get("cleanup") != self.mode:
            raise ValueError("cleanup mode differs from effective configuration")
        filter_config = self.effective_config.get("statistical_outlier_removal")
        if (filter_config is None) != (self.statistical_filter_evidence is None):
            raise ValueError("statistical filter evidence must match the effective cleanup configuration")
        if self.statistical_filter_evidence is not None:
            evidence = self.statistical_filter_evidence
            if evidence.input_checksum != self.metric_input_checksum:
                raise ValueError("statistical filter source differs from metric input")
            if evidence.input_gaussian_count != self.input_gaussian_count:
                raise ValueError("statistical filter count differs from the inspected metric input")
            if evidence.retained_gaussian_count < self.retained_gaussian_count:
                raise ValueError("cluster cleanup cannot retain more Gaussians than the SOR stage")
            if filter_config != {
                "neighbors": evidence.neighbors,
                "standard_deviation_ratio": evidence.standard_deviation_ratio,
                "max_gaussians": evidence.max_gaussians,
            }:
                raise ValueError("statistical filter evidence differs from the effective configuration")
        digest = hashlib.sha256(canonical_json_bytes(self.effective_config)).hexdigest()
        if self.config_checksum != f"sha256:{digest}":
            raise ValueError("cleanup configuration checksum mismatch")
        return self


class GeometryArtifact(ContractModel):
    """Collision mesh canonical từ RGB 3DGS; EX-REC produce, EX-SIM consume làm collider.

    Bắt buộc bind `applied_confirmation_checksum` để downstream từ chối scale hai lần,
    và `seed` để không có consumer nào phải tin lời producer rằng seed đã hợp lệ.
    """

    artifact_type: Literal["GeometryArtifact"]
    schema_version: Literal["1.0", "1.1", "1.2"]
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    producer_stage: Literal[StageId.RGB_GEOMETRY]
    job_id: Identifier
    source_modality: Literal["rgb_3dgs"]
    geometry_format: Literal["glb"]
    coordinate_system: CoordinateSystem
    metric_scale: MetricScale
    applied_scale_m_per_source_unit: FiniteFloat = Field(default=1.0, gt=0)
    applied_confirmation_checksum: Checksum
    applied_transform: Transform
    source_master_checksum: Checksum
    voxel: VoxelGridSummary
    seed: SeedDecision
    capsule: CapsuleFootprint
    provenance: PreprocessingProvenance
    cleanup_evidence: GeometryCleanupEvidence | None = None

    @model_validator(mode="after")
    def _require_confirmed_metric_scale(self) -> Self:
        if self.metric_scale.status != MetricScaleStatus.CONFIRMED:
            raise ValueError("collision geometry requires a CONFIRMED metric scale")
        if self.metric_scale.meters_per_unit != 1.0:
            raise ValueError("canonical collision geometry must use meters_per_unit=1")
        if any(item.origin == DependencyOrigin.GROUND_TRUTH for item in self.provenance.dependencies):
            raise ValueError("product collision geometry must not depend on evaluation ground truth")
        if self.schema_version == "1.2" and self.cleanup_evidence is None:
            raise ValueError("GeometryArtifact 1.2 requires cleanup evidence")
        if self.cleanup_evidence is not None:
            if self.schema_version != "1.2":
                raise ValueError("cleanup evidence requires GeometryArtifact 1.2")
            if self.cleanup_evidence.job_id != self.job_id:
                raise ValueError("cleanup evidence belongs to a different job")
            if self.cleanup_evidence.source_checksum != self.source_master_checksum:
                raise ValueError("cleanup evidence source differs from geometry source")
            if self.cleanup_evidence.collision_mesh_checksum != self.artifact_checksum:
                raise ValueError("cleanup evidence mesh differs from geometry artifact")
        return self


class DepthFrameSet(ContractModel):
    """Metadata for optional sensor depth; it is not evaluation ground truth."""

    storage_dtype: Identifier
    storage_format: Identifier
    scale_to_meter: FiniteFloat = Field(gt=0)
    frame_refs: list[ProductArtifactRef] = Field(min_length=1)
    provenance: JsonObject


class AlignmentStatus(StrEnum):
    """Alignment lifecycle states used by mixed-modality reconstruction."""

    DECLARED = "DECLARED"
    CONFIRMED = "CONFIRMED"


class AlignmentRecord(ContractModel):
    """Immutable evidence binding a LiDAR geometry to its RGB geometry target."""

    artifact_type: Literal["AlignmentRecord"]
    schema_version: SchemaVersion
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    producer_stage: Literal[StageId.RGB_LIDAR_ALIGN]
    job_id: Identifier
    source_lidar_checksum: Checksum
    target_rgb_geometry_checksum: Checksum
    transform_target_from_source: Transform
    status: AlignmentStatus
    method: Identifier
    evidence_refs: list[ProductArtifactRef]
    provenance: JsonObject


class ReconstructionBundle(ContractModel):
    """Modality-aware EX-REC handoff consumed directly by EX-SCENE."""

    artifact_type: Literal["ReconstructionBundle"]
    schema_version: SchemaVersion
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    producer_stage: Literal[StageId.METRIC_CANONICALIZE]
    job_id: Identifier
    source_input_checksum: Checksum
    input_configuration: InputConfiguration
    coordinate_system: CoordinateSystem
    metric_scale: MetricScale
    rgb_frame_refs: list[ProductArtifactRef] = Field(default_factory=list)
    depth_frame_set: DepthFrameSet | None = None
    camera_pose_refs: list[ProductArtifactRef] = Field(default_factory=list)
    visual_artifact_ref: ProductArtifactRef | None = None
    rgb_geometry_ref: ProductArtifactRef | None = None
    lidar_geometry_ref: ProductArtifactRef | None = None
    alignment_record: AlignmentRecord | None = None
    canonical_geometry_ref: ProductArtifactRef
    provenance: JsonObject

    @model_validator(mode="after")
    def _validate_modalities(self) -> Self:
        if self.input_configuration.depth_present != (self.depth_frame_set is not None):
            raise ValueError("depth_present must match depth_frame_set presence")
        if self.input_configuration.rgb_present:
            if not self.rgb_frame_refs or not self.camera_pose_refs:
                raise ValueError("RGB bundle requires frame and camera-pose references")
            if self.visual_artifact_ref is None or self.rgb_geometry_ref is None:
                raise ValueError("RGB bundle requires visual and RGB geometry artifacts")
        if self.input_configuration.registered_lidar_present and self.lidar_geometry_ref is None:
            raise ValueError("LiDAR bundle requires lidar_geometry_ref")
        if self._is_mixed() and not self._has_confirmed_alignment():
            raise ValueError("mixed RGB/LiDAR bundle requires confirmed alignment")
        if self.input_configuration.registered_lidar_present:
            self._validate_lidar_dependency()
        return self

    def _validate_lidar_dependency(self) -> None:
        reference = self.lidar_geometry_ref
        source = reference.source_provenance if reference is not None else None
        if source is None:
            raise ValueError("LiDAR reference requires preprocessing provenance")
        lineage = PreprocessingProvenance.model_validate(source)
        if lineage.ground_truth_assisted and self.provenance.get("ground_truth_assisted") is not True:
            raise ValueError("GT-assisted LiDAR bundle requires ground_truth_assisted provenance")

    def _is_mixed(self) -> bool:
        return self.input_configuration.rgb_present and self.input_configuration.registered_lidar_present

    def _has_confirmed_alignment(self) -> bool:
        record = self.alignment_record
        if record is None or record.status != AlignmentStatus.CONFIRMED:
            return False
        if self.rgb_geometry_ref is None or self.lidar_geometry_ref is None:
            return False
        return (
            record.target_rgb_geometry_checksum == self.rgb_geometry_ref.artifact_checksum
            and record.source_lidar_checksum == self.lidar_geometry_ref.artifact_checksum
        )
