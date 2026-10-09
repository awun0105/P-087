"""Preflight, candidate, validation and evaluation contracts."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, FiniteFloat, JsonValue, model_validator

from src.models.contracts.artifacts import (
    ArtifactRef,
    Checksum,
    ContractModel,
    Identifier,
    ProductArtifactRef,
    SchemaVersion,
)
from src.models.contracts.coordinates import CoordinateSystem, Transform


def _artifact_job_id(reference: ProductArtifactRef) -> str:
    """Read the job identity from a validated logical artifact URI and check optional metadata."""
    job_id = reference.artifact_uri.removeprefix("artifact://jobs/").partition("/")[0]
    if reference.job_id is not None and reference.job_id != job_id:
        raise ValueError("candidate artifact job_id must match its logical URI")
    return job_id


class RuleResult(StrEnum):
    """Result of a preflight or simulator validation rule."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class CollisionObservationState(StrEnum):
    """Evidence state for the space traversed by one configured validation pair."""

    OBSERVED_STATIC = "observed_static"
    UNOBSERVED = "unobserved"
    INFERRED = "inferred"
    MOTION_SUSPECTED = "motion_suspected"


class PreflightRuleId(StrEnum):
    """Stable blocking-rule identifiers shared with EX-SIM."""

    METRIC_SCALE_MISSING = "METRIC_SCALE_MISSING"
    COLLIDER_MISSING = "COLLIDER_MISSING"
    TRANSFORM_INVALID = "TRANSFORM_INVALID"
    OBJECT_OUT_OF_BOUNDS = "OBJECT_OUT_OF_BOUNDS"
    REQUIRED_ARTIFACT_MISSING = "REQUIRED_ARTIFACT_MISSING"
    OBJECT_CONFIRMATION_INCOMPLETE = "OBJECT_CONFIRMATION_INCOMPLETE"
    COLLISION_SOURCE_COVERAGE = "COLLISION_SOURCE_COVERAGE"


class PreflightRule(ContractModel):
    """One deterministic result in a PreflightReport."""

    rule_id: PreflightRuleId
    severity: Identifier
    result: RuleResult
    affected_object_ids: list[Identifier]
    evidence_refs: list[ProductArtifactRef]
    remediation: str | None = None


class PreflightReport(ContractModel):
    """Static audit report required before candidate build/review."""

    schema_version: SchemaVersion
    scene_revision: Identifier
    scene_ir_checksum: Checksum
    ruleset_version: Identifier
    rules: list[PreflightRule]
    blocking_result: RuleResult
    report_checksum: Checksum


class ObjectTransform(ContractModel):
    """Candidate manifest projection of a canonical SceneObject transform."""

    object_id: Identifier
    transform: Transform


class CandidateManifest(ContractModel):
    """Inventory contract sealed inside an immutable CandidatePackage."""

    schema_version: SchemaVersion
    candidate_id: Identifier
    scene_revision: Identifier
    scene_ir_checksum: Checksum
    job_manifest_checksum: Checksum
    coordinate_system: CoordinateSystem
    object_transforms: list[ObjectTransform]
    asset_refs: list[ProductArtifactRef]
    collider_refs: list[ProductArtifactRef]
    artifact_checksums: list[Checksum]
    build_config_checksum: Checksum
    collision_source_ref: ProductArtifactRef | None = None
    collision_selection_ref: ProductArtifactRef | None = None

    @model_validator(mode="after")
    def _validate_collision_source_pair(self) -> Self:
        source_ref = self.collision_source_ref
        selection_ref = self.collision_selection_ref
        if source_ref is None and selection_ref is None:
            return self
        if source_ref is None or selection_ref is None:
            raise ValueError("candidate collision source and selection refs must be set together")
        if selection_ref.artifact_type != "CollisionSourceSelection":
            raise ValueError("candidate collision_selection_ref must reference CollisionSourceSelection")
        if _artifact_job_id(source_ref) != _artifact_job_id(selection_ref):
            raise ValueError("candidate collision source and selection must belong to the same job")
        return self


class CandidatePackage(ContractModel):
    """Immutable OpenUSD candidate used for validation and review."""

    candidate_manifest: CandidateManifest
    entrypoint_usd: ProductArtifactRef
    assets: list[ProductArtifactRef]
    geometry: list[ProductArtifactRef]
    colliders: list[ProductArtifactRef]
    candidate_checksum: Checksum


class ValidationCheck(ContractModel):
    """One structured simulator or preflight-derived validation check."""

    check_id: Identifier
    result: RuleResult
    evidence_refs: list[ProductArtifactRef]
    message: str | None = None


class ObservedPathResult(StrEnum):
    """Observed Isaac result without hidden benchmark expectation."""

    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class CollisionPathSupportEvidence(ContractModel):
    """Coverage for one path, bound by the enclosing ValidationReport candidate checksum."""

    pair_id: Identifier
    state: CollisionObservationState
    observation_ids: list[Identifier] = Field(default_factory=list)
    coverage_fraction: FiniteFloat = Field(ge=0, le=1)
    diagnostic_ref: ProductArtifactRef | None = None

    @model_validator(mode="after")
    def _observed_pair_has_evidence(self) -> Self:
        if self.state == CollisionObservationState.OBSERVED_STATIC and (
            not self.observation_ids or self.coverage_fraction <= 0 or self.diagnostic_ref is None
        ):
            raise ValueError("observed static path pair requires observations, measured coverage and a diagnostic ref")
        if self.diagnostic_ref is not None and self.diagnostic_ref.artifact_type != "CollisionPathCoverageDiagnostic":
            raise ValueError("diagnostic_ref must reference a CollisionPathCoverageDiagnostic artifact")
        return self


class CollisionPathCoverageDiagnostic(ContractModel):
    """Persisted pair-level support evidence bound to a candidate and its collision QA report."""

    artifact_type: Literal["CollisionPathCoverageDiagnostic"] = "CollisionPathCoverageDiagnostic"
    schema_version: Literal["1.0"] = "1.0"
    job_id: Identifier
    candidate_checksum: Checksum
    effective_collision_ref: ProductArtifactRef
    collision_quality_ref: ProductArtifactRef
    pair_id: Identifier
    state: CollisionObservationState
    observation_ids: list[Identifier] = Field(default_factory=list)
    coverage_fraction: FiniteFloat = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _validate_candidate_and_report_binding(self) -> Self:
        if self.collision_quality_ref.artifact_type != "CollisionQualityReport":
            raise ValueError("collision_quality_ref must reference a CollisionQualityReport artifact")
        for reference in (self.effective_collision_ref, self.collision_quality_ref):
            if _artifact_job_id(reference) != self.job_id:
                raise ValueError("collision path coverage refs must belong to the diagnostic job")
        if self.state == CollisionObservationState.OBSERVED_STATIC and (
            not self.observation_ids or self.coverage_fraction <= 0
        ):
            raise ValueError("observed static path coverage requires observations and measured coverage")
        return self


class PathResult(ContractModel):
    """Observed result for one configured Start-Goal pair."""

    pair_id: Identifier
    result: ObservedPathResult
    evidence_refs: list[ProductArtifactRef]
    message: str | None = None


class ValidationReport(ContractModel):
    """Structured simulator report bound to one immutable candidate checksum."""

    schema_version: SchemaVersion
    candidate_checksum: Checksum
    validator_version: str
    environment_versions: dict[Identifier, str]
    checks: list[ValidationCheck] = Field(min_length=1)
    path_results: list[PathResult]
    collision_quality_ref: ProductArtifactRef | None = Field(default=None, exclude_if=lambda value: value is None)
    collision_path_support: list[CollisionPathSupportEvidence] = Field(
        default_factory=list,
        exclude_if=lambda value: not value,
    )
    overall_result: RuleResult
    report_checksum: Checksum

    @model_validator(mode="after")
    def _unique_collision_path_support(self) -> Self:
        if (
            self.collision_quality_ref is not None
            and self.collision_quality_ref.artifact_type != "CollisionQualityReport"
        ):
            raise ValueError("collision_quality_ref must reference a CollisionQualityReport artifact")
        if self.collision_path_support and self.collision_quality_ref is None:
            raise ValueError("collision path support requires its CollisionQualityReport ref")
        if self.collision_quality_ref is not None:
            quality_job_id = _artifact_job_id(self.collision_quality_ref)
            for item in self.collision_path_support:
                if item.diagnostic_ref is not None and _artifact_job_id(item.diagnostic_ref) != quality_job_id:
                    raise ValueError("collision path diagnostic and quality report must belong to the same job")
        pair_ids = [item.pair_id for item in self.collision_path_support]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("collision path support pair IDs must be unique")
        return self


class EvaluationSubjectType(StrEnum):
    """Artifact identities supported by the evaluation protocol."""

    RECONSTRUCTION = "reconstruction"
    SCENE_REVISION = "scene_revision"
    CANDIDATE_PACKAGE = "candidate_package"


class PathEvaluationComparison(ContractModel):
    """Evaluation-only comparison of observed and locked expected labels."""

    pair_id: Identifier
    observed_result: ObservedPathResult
    expected_result: ObservedPathResult
    agreement: bool


class EvaluationReport(ContractModel):
    """Benchmark report isolated from product ValidationReport."""

    schema_version: SchemaVersion
    subject_type: EvaluationSubjectType
    subject_id: Identifier
    subject_checksum: Checksum
    evaluation_protocol_id: Identifier
    split_manifest_checksum: Checksum | None = None
    references_used: list[ArtifactRef]
    preprocessing_dependencies: list[ArtifactRef]
    metrics: list[dict[str, JsonValue]]
    path_comparisons: list[PathEvaluationComparison]
    report_checksum: Checksum
