"""Reconstruction artifacts published by EX-REC."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import (
    ArtifactUri,
    Checksum,
    ContractModel,
    Identifier,
    JsonObject,
    ProductArtifactRef,
    SchemaVersion,
)
from src.models.contracts.coordinates import CoordinateSystem, MetricScale, MetricScaleStatus, Transform
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
        return self


class CapsuleFootprint(ContractModel):
    """Hình trụ đại diện robot; consumer phải tự kiểm seed theo đúng footprint này.

    `length_m` là phần hình trụ, không phải tổng chiều cao, để physics engine dựng
    đúng capsule mà không phải tự suy ra từ hai số còn lại.
    """

    height_m: FiniteFloat = Field(gt=0)
    radius_m: FiniteFloat = Field(gt=0)
    length_m: FiniteFloat = Field(ge=0)

    @model_validator(mode="after")
    def _bind_length_to_cylinder(self) -> Self:
        if abs(self.height_m - (self.length_m + 2 * self.radius_m)) > 1e-9:
            raise ValueError("capsule length must be height minus two radii")
        return self


class GeometryArtifact(ContractModel):
    """Collision mesh canonical từ RGB 3DGS; EX-REC produce, EX-SIM consume làm collider.

    Bắt buộc bind `applied_confirmation_checksum` để downstream từ chối scale hai lần,
    và `seed` để không có consumer nào phải tin lời producer rằng seed đã hợp lệ.
    """

    artifact_type: Literal["GeometryArtifact"]
    schema_version: SchemaVersion
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    producer_stage: Literal[StageId.RGB_GEOMETRY]
    job_id: Identifier
    source_modality: Literal["rgb_3dgs"]
    geometry_format: Literal["glb"]
    coordinate_system: CoordinateSystem
    metric_scale: MetricScale
    applied_confirmation_checksum: Checksum
    applied_transform: Transform
    source_master_checksum: Checksum
    voxel: VoxelGridSummary
    seed: SeedDecision
    capsule: CapsuleFootprint
    provenance: PreprocessingProvenance

    @model_validator(mode="after")
    def _require_confirmed_metric_scale(self) -> Self:
        if self.metric_scale.status != MetricScaleStatus.CONFIRMED:
            raise ValueError("collision geometry requires a CONFIRMED metric scale")
        if any(item.origin == DependencyOrigin.GROUND_TRUTH for item in self.provenance.dependencies):
            raise ValueError("product collision geometry must not depend on evaluation ground truth")
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
