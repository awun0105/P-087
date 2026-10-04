"""Preflight, candidate, validation and evaluation contracts."""

from enum import StrEnum

from pydantic import Field, JsonValue

from src.models.contracts.artifacts import (
    ArtifactRef,
    Checksum,
    ContractModel,
    Identifier,
    ProductArtifactRef,
    SchemaVersion,
)
from src.models.contracts.coordinates import CoordinateSystem, Transform


class RuleResult(StrEnum):
    """Result of a preflight or simulator validation rule."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class PreflightRuleId(StrEnum):
    """Stable blocking-rule identifiers shared with EX-SIM."""

    METRIC_SCALE_MISSING = "METRIC_SCALE_MISSING"
    COLLIDER_MISSING = "COLLIDER_MISSING"
    TRANSFORM_INVALID = "TRANSFORM_INVALID"
    OBJECT_OUT_OF_BOUNDS = "OBJECT_OUT_OF_BOUNDS"
    REQUIRED_ARTIFACT_MISSING = "REQUIRED_ARTIFACT_MISSING"
    OBJECT_CONFIRMATION_INCOMPLETE = "OBJECT_CONFIRMATION_INCOMPLETE"


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
    overall_result: RuleResult
    report_checksum: Checksum


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
