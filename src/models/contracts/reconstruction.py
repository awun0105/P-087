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
from src.models.contracts.coordinates import CoordinateSystem, MetricScale, Transform
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
