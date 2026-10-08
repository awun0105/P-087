"""Versioned contracts for staged files, input resolution, and accepted recipes.

These types describe the new assembly boundary. They do not change the legacy
InputManifest or make any R1-R6 recipe executable by themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field, FiniteFloat, PositiveInt, field_validator, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import InputFile
from src.models.contracts.video_preparation import ServerVideoPreparationVerification


class InputRole(StrEnum):
    """A semantic role selected for one or more exact staged file references."""

    RGB_VIDEO = "rgb_video"
    REGISTERED_LIDAR_MAP = "registered_lidar_map"
    STATIC_LIDAR_CLOUD = "static_lidar_cloud"
    LIDAR_SCAN = "lidar_scan"
    CAMERA_LIDAR_CALIBRATION = "camera_lidar_calibration"
    SENSOR_TRAJECTORY = "sensor_trajectory"
    CAMERA_TRAJECTORY = "camera_trajectory"
    RGB_FRAME_TIMES = "rgb_frame_times"
    GAUSSIAN_SCENE = "gaussian_scene"


class InputAssetFormat(StrEnum):
    """Content formats distinguishable by the current or planned bounded probes."""

    VIDEO_MP4 = "video_mp4"
    VIDEO_MOV = "video_mov"
    POINT_CLOUD_PLY = "point_cloud_ply"
    POINT_CLOUD_PCD = "point_cloud_pcd"
    GAUSSIAN_PLY = "gaussian_ply"
    GAUSSIAN_PLY_COLMAP = "gaussian_ply_colmap"
    GAUSSIAN_SOG = "gaussian_sog"
    ZIP_UNKNOWN = "zip_unknown"
    CALIBRATION_JSON = "calibration_json"
    TUM_TRAJECTORY = "tum_trajectory"
    RGB_FRAME_TIMES = "rgb_frame_times"
    UNKNOWN = "unknown"


class GaussianViewFormat(StrEnum):
    """Accepted source identity for the separate view/import intent."""

    PLY = "gaussian_ply"
    PLY_COLMAP = "gaussian_ply_colmap"
    SOG = "gaussian_sog"


class InputWorkflowIntent(StrEnum):
    VIDEO_RECONSTRUCTION = "video_reconstruction"
    GAUSSIAN_VIEW_IMPORT = "gaussian_view_import"


class RecipeGroup(StrEnum):
    RGB_ONLY = "R1"
    REGISTERED_MAP = "R2"
    SINGLE_STATIC_CLOUD = "R3"
    SUPPLIED_TRAJECTORY = "R4"
    ESTIMATED_TRAJECTORY = "R5"
    SENSOR_GUIDED = "R6"


class InputResolutionState(StrEnum):
    READY = "ready"
    NEEDS_INPUT = "needs_input"
    PENDING_VERIFICATION = "pending_verification"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class EvidenceProvenance(StrEnum):
    DECLARED = "declared"
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    VERIFIED = "verified"


class CloudObservationState(StrEnum):
    REGISTERED_MAP = "registered_map"
    SINGLE_STATIC_CLOUD = "single_static_cloud"
    RAW_SCAN_SEQUENCE = "raw_scan_sequence"


class DistanceUnit(StrEnum):
    METER = "m"
    CENTIMETER = "cm"
    MILLIMETER = "mm"


class TrajectoryConvention(StrEnum):
    WORLD_FROM_SENSOR = "world_from_sensor"
    WORLD_FROM_CAMERA = "world_from_camera"
    UNKNOWN = "unknown"


class ClockRelation(StrEnum):
    SAME_CLOCK = "same_clock"
    KNOWN_OFFSET = "known_offset"
    UNKNOWN = "unknown"


class TrajectoryOrigin(StrEnum):
    NOT_REQUIRED = "not_required"
    SUPPLIED = "supplied"
    ESTIMATED = "estimated"


class RuntimeCapabilityKey(StrEnum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
    R6 = "R6"
    GAUSSIAN_PLY_VIEW = "gaussian_ply_view"
    GAUSSIAN_SOG_VIEW = "gaussian_sog_view"


class RuntimeQualificationStatus(StrEnum):
    QUALIFIED = "qualified"
    WIRED_UNQUALIFIED = "wired_unqualified"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"


class CandidateState(StrEnum):
    READY = "ready"
    NEEDS_INPUT = "needs_input"
    PENDING_VERIFICATION = "pending_verification"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class ArchiveMemberRef(ContractModel):
    """A member is tied to its unchanged archive bytes and its own content hash."""

    container_checksum: Checksum
    member_path: str = Field(min_length=1, max_length=1024)
    member_checksum: Checksum
    uncompressed_size_bytes: int = Field(ge=0, strict=True)

    @field_validator("member_path")
    @classmethod
    def _safe_member_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        raw_parts = value.split("/")
        if (
            "\\" in value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in raw_parts)
            or path.as_posix() != value
        ):
            raise ValueError("archive member path must be a normalized relative POSIX path")
        return value


class InputRoleEvidence(ContractModel):
    role: InputRole
    provenance: EvidenceProvenance
    method: Identifier | None = None
    evidence_checksum: Checksum | None = None

    @model_validator(mode="after")
    def _require_evidence_source(self) -> InputRoleEvidence:
        if self.provenance in {EvidenceProvenance.OBSERVED, EvidenceProvenance.ESTIMATED} and self.method is None:
            raise ValueError("observed or estimated role evidence requires a method")
        if self.provenance == EvidenceProvenance.VERIFIED and self.evidence_checksum is None:
            raise ValueError("verified role evidence requires an evidence checksum")
        return self


class StagedInputFile(ContractModel):
    """Upload-level source plus an optional exact member inside an archive."""

    file_id: Identifier
    upload_id: Identifier
    source_file: InputFile
    observed_format: InputAssetFormat
    archive_member: ArchiveMemberRef | None = None
    role_evidence: list[InputRoleEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bind_member_to_archive(self) -> StagedInputFile:
        if self.archive_member is not None and self.archive_member.container_checksum != self.source_file.checksum:
            raise ValueError("archive member identity must bind the exact uploaded archive checksum")
        evidence_keys = [(item.role, item.provenance) for item in self.role_evidence]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("staged file has duplicate role evidence")
        return self


ValueT = TypeVar("ValueT")


class EvidenceValue(ContractModel, Generic[ValueT]):
    """Typed evidence keeps a declaration distinct from an observation or verification."""

    value: ValueT
    provenance: EvidenceProvenance
    method: Identifier | None = None
    evidence_checksum: Checksum | None = None

    @model_validator(mode="after")
    def _require_evidence_source(self) -> EvidenceValue[ValueT]:
        if self.provenance in {EvidenceProvenance.OBSERVED, EvidenceProvenance.ESTIMATED} and self.method is None:
            raise ValueError("observed or estimated values require a method")
        if self.provenance == EvidenceProvenance.VERIFIED and self.evidence_checksum is None:
            raise ValueError("verified values require an evidence checksum")
        return self


class InputAssemblyDeclarations(ContractModel):
    same_scene: EvidenceValue[bool] | None = None
    cloud_state: EvidenceValue[CloudObservationState] | None = None
    coordinate_unit: EvidenceValue[DistanceUnit] | None = None
    lidar_frame_id: EvidenceValue[Identifier] | None = None
    world_frame_id: EvidenceValue[Identifier] | None = None
    trajectory_convention: EvidenceValue[TrajectoryConvention] | None = None
    clock_relation: EvidenceValue[ClockRelation] | None = None
    clock_offset_seconds: EvidenceValue[FiniteFloat] | None = None


_SINGLE_FILE_ROLES = {
    InputRole.RGB_VIDEO,
    InputRole.REGISTERED_LIDAR_MAP,
    InputRole.STATIC_LIDAR_CLOUD,
    InputRole.CAMERA_LIDAR_CALIBRATION,
    InputRole.SENSOR_TRAJECTORY,
    InputRole.CAMERA_TRAJECTORY,
    InputRole.RGB_FRAME_TIMES,
    InputRole.GAUSSIAN_SCENE,
}


class InputBinding(ContractModel):
    """An explicit binding; list order is significant for a LiDAR scan sequence."""

    binding_id: Identifier
    role: InputRole
    file_ids: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_cardinality(self) -> InputBinding:
        if len(self.file_ids) != len(set(self.file_ids)):
            raise ValueError("input binding cannot repeat a file ID")
        if self.role in _SINGLE_FILE_ROLES and len(self.file_ids) != 1:
            raise ValueError(f"{self.role.value} binding must select exactly one staged file")
        return self


class InputAssemblySnapshot(ContractModel):
    """One immutable assembly revision; later changes require a new revision/checksum."""

    schema_version: Literal["1.0"]
    assembly_id: Identifier
    revision: PositiveInt
    owner_id: Identifier
    created_at: datetime
    requested_intent: InputWorkflowIntent | None = None
    files: list[StagedInputFile] = Field(min_length=1)
    bindings: list[InputBinding] = Field(default_factory=list)
    declarations: InputAssemblyDeclarations = Field(default_factory=InputAssemblyDeclarations)
    video_preparation_verification: ServerVideoPreparationVerification | None = None
    assembly_checksum: Checksum

    @model_validator(mode="after")
    def _validate_revision_bindings(self) -> InputAssemblySnapshot:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != UTC.utcoffset(self.created_at):
            raise ValueError("assembly timestamps must be timezone-aware UTC")
        file_ids = [item.file_id for item in self.files]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("assembly file IDs must be unique")
        binding_ids = [item.binding_id for item in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("assembly binding IDs must be unique")
        roles = [item.role for item in self.bindings]
        if len(roles) != len(set(roles)):
            raise ValueError("assembly can contain only one selected binding per role")
        unknown_files = {file_id for binding in self.bindings for file_id in binding.file_ids} - set(file_ids)
        if unknown_files:
            raise ValueError("assembly binding references a file outside this revision")
        return self


class RuntimeCapabilityRecord(ContractModel):
    capability_key: RuntimeCapabilityKey
    status: RuntimeQualificationStatus
    runtime_id: Identifier | None = None
    runtime_version: Identifier | None = None
    qualification_evidence_checksum: Checksum | None = None
    reason_codes: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_qualification_claim(self) -> RuntimeCapabilityRecord:
        if self.status == RuntimeQualificationStatus.QUALIFIED:
            if not self.runtime_id or not self.runtime_version or not self.qualification_evidence_checksum:
                raise ValueError("qualified runtime requires exact runtime identity and qualification evidence")
        elif self.status == RuntimeQualificationStatus.WIRED_UNQUALIFIED:
            if not self.runtime_id or not self.runtime_version or not self.reason_codes:
                raise ValueError("wired but unqualified runtime requires its version and qualification gap")
        elif not self.reason_codes:
            raise ValueError("unavailable or incompatible runtime requires a reason code")
        return self


class RuntimeQualificationRegistry(ContractModel):
    schema_version: Literal["1.0"]
    registry_version: Identifier
    capabilities: list[RuntimeCapabilityRecord]
    registry_checksum: Checksum

    @model_validator(mode="after")
    def _unique_capabilities(self) -> RuntimeQualificationRegistry:
        keys = [item.capability_key for item in self.capabilities]
        if len(keys) != len(set(keys)):
            raise ValueError("runtime registry capability keys must be unique")
        return self


class MissingInputFact(ContractModel):
    code: Identifier
    description: str = Field(min_length=1)
    related_file_ids: list[Identifier] = Field(default_factory=list)


class ResolutionDiagnostic(ContractModel):
    code: Identifier
    severity: Literal["info", "warning", "error"]
    description: str = Field(min_length=1)
    related_file_ids: list[Identifier] = Field(default_factory=list)


class RecipeComponentVersion(ContractModel):
    component_id: Identifier
    version: Identifier
    config_checksum: Checksum | None = None


class VideoRecipeCandidate(ContractModel):
    candidate_kind: Literal["video_recipe"]
    candidate_id: Identifier
    recipe_group: RecipeGroup
    state: CandidateState
    bindings: list[InputBinding] = Field(min_length=1)
    excluded_file_ids: list[Identifier] = Field(default_factory=list)
    trajectory_origin: TrajectoryOrigin
    required_facts: list[MissingInputFact] = Field(default_factory=list)
    diagnostics: list[ResolutionDiagnostic] = Field(default_factory=list)
    runtime: RuntimeCapabilityRecord

    @model_validator(mode="after")
    def _validate_recipe_bindings(self) -> VideoRecipeCandidate:
        _validate_recipe_contract(self.recipe_group, self.bindings, self.trajectory_origin)
        if self.runtime.capability_key.value != self.recipe_group.value:
            raise ValueError("runtime capability must match the selected recipe group")
        _validate_candidate_state(self.state, self.required_facts, self.diagnostics, self.runtime)
        return self


class GaussianViewCandidate(ContractModel):
    candidate_kind: Literal["gaussian_view_import"]
    candidate_id: Identifier
    source_file_id: Identifier
    source_format: GaussianViewFormat
    state: CandidateState
    excluded_file_ids: list[Identifier] = Field(default_factory=list)
    required_facts: list[MissingInputFact] = Field(default_factory=list)
    diagnostics: list[ResolutionDiagnostic] = Field(default_factory=list)
    runtime: RuntimeCapabilityRecord

    @model_validator(mode="after")
    def _validate_view_runtime(self) -> GaussianViewCandidate:
        expected = (
            RuntimeCapabilityKey.GAUSSIAN_SOG_VIEW
            if self.source_format == GaussianViewFormat.SOG
            else RuntimeCapabilityKey.GAUSSIAN_PLY_VIEW
        )
        if self.runtime.capability_key != expected:
            raise ValueError("Gaussian view candidate must bind its source-format runtime capability")
        _validate_candidate_state(self.state, self.required_facts, self.diagnostics, self.runtime)
        return self


InputResolutionCandidate = Annotated[
    VideoRecipeCandidate | GaussianViewCandidate,
    Field(discriminator="candidate_kind"),
]


class InputResolutionReport(ContractModel):
    schema_version: Literal["1.0"]
    assembly_id: Identifier
    assembly_revision: PositiveInt
    assembly_checksum: Checksum
    resolver_version: Identifier
    runtime_registry_checksum: Checksum
    state: InputResolutionState
    candidates: list[InputResolutionCandidate] = Field(default_factory=list)
    recommended_candidate_id: Identifier | None = None
    missing_facts: list[MissingInputFact] = Field(default_factory=list)
    diagnostics: list[ResolutionDiagnostic] = Field(default_factory=list)
    report_checksum: Checksum

    @model_validator(mode="after")
    def _validate_resolution_state(self) -> InputResolutionReport:
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("resolution candidate IDs must be unique")
        selected = next((item for item in self.candidates if item.candidate_id == self.recommended_candidate_id), None)
        if self.recommended_candidate_id is not None and selected is None:
            raise ValueError("recommended candidate must exist in this report")
        if self.state == InputResolutionState.READY:
            if selected is None or selected.state != CandidateState.READY:
                raise ValueError("ready resolution requires one recommended ready candidate")
            if selected.runtime.status != RuntimeQualificationStatus.QUALIFIED:
                raise ValueError("ready resolution requires a qualified runtime")
            if sum(item.state == CandidateState.READY for item in self.candidates) != 1:
                raise ValueError("ready resolution must have exactly one runnable candidate")
        elif selected is not None:
            raise ValueError("non-ready resolution cannot recommend a runnable candidate")
        if self.state == InputResolutionState.NEEDS_INPUT and not self.missing_facts:
            raise ValueError("needs_input resolution requires typed missing facts")
        if self.state == InputResolutionState.PENDING_VERIFICATION and not any(
            item.state == CandidateState.PENDING_VERIFICATION for item in self.candidates
        ):
            raise ValueError("pending_verification resolution requires a pending candidate")
        if self.state == InputResolutionState.UNSUPPORTED and (
            not self.candidates or any(item.state != CandidateState.UNSUPPORTED for item in self.candidates)
        ):
            raise ValueError("unsupported resolution requires only unsupported candidates")
        if self.state == InputResolutionState.INVALID and not any(
            item.severity == "error" for item in self.diagnostics
        ):
            raise ValueError("invalid resolution requires an error diagnostic")
        return self


class InputRecipe(ContractModel):
    """Accepted immutable video recipe; retries bind this identity, never latest draft state."""

    schema_version: Literal["1.0"]
    recipe_id: Identifier
    assembly_id: Identifier
    assembly_revision: PositiveInt
    assembly_checksum: Checksum
    resolution_checksum: Checksum
    candidate_id: Identifier
    recipe_group: RecipeGroup
    selected_by: Identifier
    accepted_at: datetime
    bindings: list[InputBinding] = Field(min_length=1)
    excluded_file_ids: list[Identifier] = Field(default_factory=list)
    trajectory_origin: TrajectoryOrigin
    component_versions: list[RecipeComponentVersion] = Field(min_length=1)
    config_checksum: Checksum
    recipe_checksum: Checksum

    @model_validator(mode="after")
    def _validate_accepted_recipe(self) -> InputRecipe:
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() != UTC.utcoffset(self.accepted_at):
            raise ValueError("accepted recipe timestamp must be timezone-aware UTC")
        _validate_recipe_contract(self.recipe_group, self.bindings, self.trajectory_origin)
        component_ids = [item.component_id for item in self.component_versions]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("accepted recipe component versions must be unique")
        return self


class GaussianViewImportIntent(ContractModel):
    """Exact PLY/SOG selection for view import; it never requests reconstruction."""

    schema_version: Literal["1.0"]
    intent_id: Identifier
    assembly_id: Identifier
    assembly_revision: PositiveInt
    assembly_checksum: Checksum
    resolution_checksum: Checksum
    candidate_id: Identifier
    source_file_id: Identifier
    source_format: GaussianViewFormat
    source_checksum: Checksum
    selected_by: Identifier
    selected_at: datetime
    intent_checksum: Checksum

    @model_validator(mode="after")
    def _validate_selected_time(self) -> GaussianViewImportIntent:
        if self.selected_at.tzinfo is None or self.selected_at.utcoffset() != UTC.utcoffset(self.selected_at):
            raise ValueError("Gaussian import selection timestamp must be timezone-aware UTC")
        return self


def _validate_candidate_state(
    state: CandidateState,
    required_facts: list[MissingInputFact],
    diagnostics: list[ResolutionDiagnostic],
    runtime: RuntimeCapabilityRecord,
) -> None:
    if state == CandidateState.READY and runtime.status != RuntimeQualificationStatus.QUALIFIED:
        raise ValueError("ready candidate requires a qualified runtime")
    if state == CandidateState.NEEDS_INPUT and not required_facts:
        raise ValueError("needs_input candidate requires typed missing facts")
    if state == CandidateState.PENDING_VERIFICATION and runtime.status not in {
        RuntimeQualificationStatus.WIRED_UNQUALIFIED,
        RuntimeQualificationStatus.QUALIFIED,
    }:
        raise ValueError("pending candidate requires an implemented runtime or pending QA")
    if state == CandidateState.UNSUPPORTED and runtime.status not in {
        RuntimeQualificationStatus.UNAVAILABLE,
        RuntimeQualificationStatus.INCOMPATIBLE,
    }:
        raise ValueError("unsupported candidate requires an unavailable or incompatible runtime")
    if state == CandidateState.INVALID and not any(item.severity == "error" for item in diagnostics):
        raise ValueError("invalid candidate requires an error diagnostic")


def _validate_recipe_contract(
    recipe_group: RecipeGroup,
    bindings: list[InputBinding],
    trajectory_origin: TrajectoryOrigin,
) -> None:
    roles = {binding.role for binding in bindings}
    required = {InputRole.RGB_VIDEO}
    if recipe_group == RecipeGroup.REGISTERED_MAP:
        required.add(InputRole.REGISTERED_LIDAR_MAP)
    elif recipe_group == RecipeGroup.SINGLE_STATIC_CLOUD:
        required.add(InputRole.STATIC_LIDAR_CLOUD)
    elif recipe_group in {RecipeGroup.SUPPLIED_TRAJECTORY, RecipeGroup.ESTIMATED_TRAJECTORY}:
        required.add(InputRole.LIDAR_SCAN)
    elif recipe_group == RecipeGroup.SENSOR_GUIDED:
        required.update({InputRole.CAMERA_LIDAR_CALIBRATION, InputRole.SENSOR_TRAJECTORY, InputRole.RGB_FRAME_TIMES})
        if not roles.intersection({InputRole.REGISTERED_LIDAR_MAP, InputRole.STATIC_LIDAR_CLOUD, InputRole.LIDAR_SCAN}):
            raise ValueError("R6 requires a registered map, one cloud, or a scan sequence")
    if not required.issubset(roles):
        raise ValueError(f"{recipe_group.value} candidate is missing required role bindings")
    expected_origin = {
        RecipeGroup.RGB_ONLY: TrajectoryOrigin.NOT_REQUIRED,
        RecipeGroup.REGISTERED_MAP: TrajectoryOrigin.NOT_REQUIRED,
        RecipeGroup.SINGLE_STATIC_CLOUD: TrajectoryOrigin.NOT_REQUIRED,
        RecipeGroup.SUPPLIED_TRAJECTORY: TrajectoryOrigin.SUPPLIED,
        RecipeGroup.ESTIMATED_TRAJECTORY: TrajectoryOrigin.ESTIMATED,
    }.get(recipe_group)
    if expected_origin is not None and trajectory_origin != expected_origin:
        raise ValueError(f"{recipe_group.value} trajectory origin does not match its contract")
    if recipe_group == RecipeGroup.SENSOR_GUIDED and trajectory_origin == TrajectoryOrigin.NOT_REQUIRED:
        raise ValueError("R6 requires an explicitly supplied or estimated sensor trajectory")


_CHECKSUM_PLACEHOLDER = "sha256:" + "0" * 64
ContractT = TypeVar("ContractT", bound=ContractModel)


def _seal_contract(value: ContractT | dict[str, object], model_type: type[ContractT], checksum_field: str) -> ContractT:
    payload = value.model_dump(mode="json") if isinstance(value, ContractModel) else dict(value)
    payload[checksum_field] = _CHECKSUM_PLACEHOLDER
    normalized = model_type.model_validate(payload).model_dump(mode="json")
    normalized[checksum_field] = canonical_content_checksum(normalized, checksum_field)
    return model_type.model_validate(normalized)


def seal_input_assembly(value: InputAssemblySnapshot | dict[str, object]) -> InputAssemblySnapshot:
    return _seal_contract(value, InputAssemblySnapshot, "assembly_checksum")


def seal_runtime_registry(value: RuntimeQualificationRegistry | dict[str, object]) -> RuntimeQualificationRegistry:
    return _seal_contract(value, RuntimeQualificationRegistry, "registry_checksum")


def seal_input_resolution(value: InputResolutionReport | dict[str, object]) -> InputResolutionReport:
    return _seal_contract(value, InputResolutionReport, "report_checksum")


def seal_input_recipe(value: InputRecipe | dict[str, object]) -> InputRecipe:
    return _seal_contract(value, InputRecipe, "recipe_checksum")


def seal_gaussian_view_intent(value: GaussianViewImportIntent | dict[str, object]) -> GaussianViewImportIntent:
    return _seal_contract(value, GaussianViewImportIntent, "intent_checksum")


def verify_input_assembly_checksum(value: InputAssemblySnapshot) -> None:
    verify_content_checksum(value, "assembly_checksum")


def verify_runtime_registry_checksum(value: RuntimeQualificationRegistry) -> None:
    verify_content_checksum(value, "registry_checksum")


def verify_input_resolution_checksum(value: InputResolutionReport) -> None:
    verify_content_checksum(value, "report_checksum")


def verify_input_recipe_checksum(value: InputRecipe) -> None:
    verify_content_checksum(value, "recipe_checksum")


def verify_gaussian_view_intent_checksum(value: GaussianViewImportIntent) -> None:
    verify_content_checksum(value, "intent_checksum")


__all__ = [
    "ArchiveMemberRef",
    "CandidateState",
    "ClockRelation",
    "CloudObservationState",
    "DistanceUnit",
    "EvidenceProvenance",
    "EvidenceValue",
    "GaussianViewCandidate",
    "GaussianViewFormat",
    "GaussianViewImportIntent",
    "InputAssetFormat",
    "InputAssemblyDeclarations",
    "InputAssemblySnapshot",
    "InputBinding",
    "InputRecipe",
    "InputResolutionCandidate",
    "InputResolutionReport",
    "InputResolutionState",
    "InputRole",
    "InputRoleEvidence",
    "InputWorkflowIntent",
    "MissingInputFact",
    "RecipeComponentVersion",
    "RecipeGroup",
    "ResolutionDiagnostic",
    "RuntimeCapabilityKey",
    "RuntimeCapabilityRecord",
    "RuntimeQualificationRegistry",
    "RuntimeQualificationStatus",
    "StagedInputFile",
    "TrajectoryConvention",
    "TrajectoryOrigin",
    "VideoRecipeCandidate",
    "seal_gaussian_view_intent",
    "seal_input_assembly",
    "seal_input_recipe",
    "seal_input_resolution",
    "seal_runtime_registry",
    "verify_gaussian_view_intent_checksum",
    "verify_input_assembly_checksum",
    "verify_input_recipe_checksum",
    "verify_input_resolution_checksum",
    "verify_runtime_registry_checksum",
]
