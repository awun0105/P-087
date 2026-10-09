"""Input, privacy, runtime và job manifest contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from src.models.contracts.artifacts import (
    ArtifactUri,
    Checksum,
    ContractModel,
    Identifier,
    JsonObject,
    ProductDataClass,
    SchemaVersion,
)
from src.models.contracts.video_preparation import ServerVideoPreparationVerification


class SourceType(StrEnum):
    """Nguồn input được TEAM_EXECUTION_CONTRACT cho phép."""

    DATASET = "dataset"
    UPLOAD = "upload"


class InputFile(ContractModel):
    """Một file đầu vào đã được nhận và checksummed."""

    original_name: str
    media_type: str
    size_bytes: int = Field(ge=0)
    checksum: Checksum
    artifact_uri: ArtifactUri
    data_class: ProductDataClass


class InputConfiguration(ContractModel):
    """Các modality có mặt trong một input execution."""

    rgb_present: bool
    depth_present: bool = False
    registered_lidar_present: bool
    declared_same_scene: bool | None = None

    @model_validator(mode="after")
    def _require_modality(self) -> Self:
        if self.depth_present and not self.rgb_present:
            raise ValueError("RGB+Depth configuration requires RGB")
        if not self.rgb_present and not self.registered_lidar_present:
            raise ValueError("at least one input modality is required")
        if self.rgb_present and self.registered_lidar_present and self.declared_same_scene is not True:
            raise ValueError("mixed RGB/LiDAR input must declare the same scene")
        return self


class LidarMetadata(ContractModel):
    """Metadata bắt buộc khi input có registered LiDAR."""

    unit: Identifier
    coordinate_frame: Identifier
    registration_status: Identifier


class InputManifest(ContractModel):
    """Entry contract dùng chung cho dataset và user upload jobs."""

    schema_version: SchemaVersion
    source_type: SourceType
    received_at: datetime
    files: list[InputFile]
    input_configuration: InputConfiguration
    lidar_metadata: LidarMetadata | None = None
    source_rights_attestation: JsonObject
    dataset_manifest_checksum: Checksum | None = None
    preparation_provenance: JsonObject | None = None
    video_preparation: ServerVideoPreparationVerification | None = None
    input_manifest_checksum: Checksum

    @model_validator(mode="after")
    def _bind_lidar_metadata_to_modality(self) -> Self:
        if self.input_configuration.registered_lidar_present and self.lidar_metadata is None:
            raise ValueError("registered LiDAR input requires lidar_metadata")
        if not self.input_configuration.registered_lidar_present and self.lidar_metadata is not None:
            raise ValueError("lidar_metadata requires registered_lidar_present")
        if self.video_preparation is not None:
            videos = [item for item in self.files if item.media_type in {"video/mp4", "video/quicktime"}]
            if len(videos) != 1:
                raise ValueError("video preparation requires exactly one RGB video input")
            video = videos[0]
            if (
                video.checksum != self.video_preparation.uploaded_checksum
                or video.size_bytes != self.video_preparation.uploaded_size_bytes
            ):
                raise ValueError("video preparation verification does not bind the InputManifest video bytes")
        return self

    @model_serializer(mode="wrap")
    def _preserve_legacy_optional_provenance(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Keep omitted preparation provenance absent so old logical checksums remain valid."""
        data = handler(self)
        if "preparation_provenance" not in self.model_fields_set:
            data.pop("preparation_provenance", None)
        if "video_preparation" not in self.model_fields_set:
            data.pop("video_preparation", None)
        return data


class PrivacyInspectionScope(StrEnum):
    """Phạm vi kiểm tra privacy được contract cho phép."""

    SAMPLED = "sampled"
    ALL_SELECTED_FRAMES = "all_selected_frames"
    APPROVED_COPY = "approved_copy"


class PrivacyResult(StrEnum):
    """Kết quả privacy gate chuẩn."""

    PRELIMINARY_SCREENED = "PRELIMINARY_SCREENED"
    VERIFIED_ANONYMIZED = "VERIFIED_ANONYMIZED"
    QUARANTINED = "QUARANTINED"


class PrivacyValidationReport(ContractModel):
    """Kết quả privacy gate gắn với một InputManifest cụ thể."""

    schema_version: SchemaVersion
    input_manifest_checksum: Checksum
    inspection_scope: PrivacyInspectionScope
    selected_frame_count: int = Field(ge=0)
    inspected_frame_count: int = Field(ge=0)
    unresolved_findings: list[JsonObject]
    result: PrivacyResult
    report_checksum: Checksum


class StageId(StrEnum):
    """Registry duy nhất cho product/runtime stage identifiers."""

    INPUT_VALIDATE = "ST-INPUT-VALIDATE"
    PRIVACY_GATE = "ST-PRIVACY-GATE"
    FRAME_EXTRACT = "ST-FRAME-EXTRACT"
    CAMERA_POSE = "ST-CAMERA-POSE"
    VISUAL_RECON = "ST-VISUAL-RECON"
    RGB_GEOMETRY = "ST-RGB-GEOMETRY"
    LIDAR_INGEST = "ST-LIDAR-INGEST"
    LIDAR_ODOMETRY = "ST-LIDAR-ODOMETRY"
    LIDAR_CALIBRATION_QA = "ST-LIDAR-CALIBRATION-QA"
    RGB_LIDAR_ALIGN = "ST-RGB-LIDAR-ALIGN"
    METRIC_CANONICALIZE = "ST-METRIC-CANONICALIZE"
    OBJECT_EXTRACT = "ST-OBJECT-EXTRACT"
    OBJECT_ASSOC = "ST-OBJECT-ASSOC"
    OBJECT_CONFIRM = "ST-OBJECT-CONFIRM"
    SCENE_DECOMPOSE = "ST-SCENE-DECOMPOSE"
    COLLIDER = "ST-COLLIDER"
    EDIT = "ST-EDIT"
    PREFLIGHT = "ST-PREFLIGHT"
    CANDIDATE_BUILD = "ST-CANDIDATE-BUILD"
    ISAAC_VALIDATE = "ST-ISAAC-VALIDATE"
    REVIEW = "ST-REVIEW"
    RELEASE = "ST-RELEASE"


class JobStatus(StrEnum):
    """Top-level job lifecycle states."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StageStatus(StrEnum):
    """Per-stage execution states."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionError(ContractModel):
    """Structured worker/stage failure passed across track boundaries."""

    error_code: Identifier
    stage_id: StageId
    human_message: str
    retryable: bool
    details: JsonObject | None = None


class StageArtifact(ContractModel):
    """Execution record của một stage trong JobManifest."""

    stage_id: StageId
    status: StageStatus
    artifact_type: Identifier | None = None
    artifact_uri: ArtifactUri | None = None
    artifact_checksum: Checksum | None = None
    data_class: ProductDataClass | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: ExecutionError | None = None

    @model_validator(mode="after")
    def _validate_terminal_state(self) -> Self:
        if (self.artifact_uri is None) != (self.data_class is None):
            raise ValueError("stage artifact URI and data_class must be declared together")
        if self.status == StageStatus.SUCCEEDED:
            if not self.artifact_uri or not self.artifact_checksum or not self.completed_at:
                raise ValueError("SUCCEEDED stage requires artifact URI, checksum and completed_at")
        if self.status == StageStatus.FAILED and self.error is None:
            raise ValueError("FAILED stage requires structured error")
        if self.error is not None and self.error.stage_id != self.stage_id:
            raise ValueError("stage error must bind the same stage_id")
        return self


class RuntimeComponentStatus(StrEnum):
    """Verification state for a runtime component version."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class RuntimeComponent(ContractModel):
    """Runtime component version captured when its machine is available."""

    status: RuntimeComponentStatus
    version: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _require_verified_version(self) -> Self:
        if self.status == RuntimeComponentStatus.VERIFIED and not self.version:
            raise ValueError("VERIFIED runtime component requires a version")
        return self


class RuntimeManifest(ContractModel):
    """Version inventory for local, GPU and simulator workers."""

    schema_version: SchemaVersion
    components: dict[Identifier, RuntimeComponent]
    runtime_manifest_checksum: Checksum


class JobManifest(ContractModel):
    """Manifest lưu execution state và provenance của một job."""

    schema_version: SchemaVersion
    job_id: Identifier
    project_id: Identifier
    scene_revision: Identifier
    status: JobStatus
    input_manifest_checksum: Checksum
    config_checksum: Checksum
    runtime_manifest_checksum: Checksum
    seed: int | None = None
    started_at: datetime
    completed_at: datetime | None = None
    current_stage: StageId
    stage_artifacts: list[StageArtifact]
    job_manifest_checksum: Checksum
