"""Scene lifecycle, approval and release contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from src.models.contracts.artifacts import (
    ArtifactUri,
    Checksum,
    ContractModel,
    Identifier,
    ProductDataClass,
    SchemaVersion,
)


class SceneRevisionStatus(StrEnum):
    """Workflow state kept separate from canonical SceneIR content."""

    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    CANDIDATE_READY = "CANDIDATE_READY"
    VALIDATING = "VALIDATING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"


class SceneRevisionRecord(ContractModel):
    """Workflow projection and derived-artifact bindings for one SceneIR revision."""

    schema_version: SchemaVersion
    scene_id: Identifier
    scene_revision: Identifier
    scene_ir_checksum: Checksum
    status: SceneRevisionStatus
    candidate_checksum: Checksum | None = None
    validation_report_checksum: Checksum | None = None
    evaluation_report_checksum: Checksum | None = None
    approval_record_checksum: Checksum | None = None


class ApprovalDecision(StrEnum):
    """Human review decisions permitted by the contract."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ApprovalRecord(ContractModel):
    """Human decision bound to an exact candidate and validation report."""

    schema_version: SchemaVersion
    candidate_checksum: Checksum
    validation_report_checksum: Checksum
    reviewer_id: Identifier
    decision: ApprovalDecision
    reason: str | None = None
    decided_at: datetime
    accepted_warning_ids: list[Identifier]
    record_checksum: Checksum

    @model_validator(mode="after")
    def _require_rejection_reason(self) -> Self:
        if self.decision == ApprovalDecision.REJECT and not self.reason:
            raise ValueError("reason is required when decision is REJECT")
        return self


class ReleaseApproval(ContractModel):
    """Approval projection sealed into a ReleaseManifest."""

    reviewer_id: Identifier
    approved_at: datetime
    accepted_warning_ids: list[Identifier]
    record_checksum: Checksum


class ArtifactInventoryItem(ContractModel):
    """Artifact inventory entry in a ReleaseManifest."""

    artifact_type: Identifier
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    data_class: ProductDataClass


class ReleaseRunType(StrEnum):
    """Release modes with distinct evaluation requirements."""

    ORDINARY = "ORDINARY"
    LOCKED_MVP_ACCEPTANCE = "LOCKED_MVP_ACCEPTANCE"
    BENCHMARK = "BENCHMARK"


class ReleaseManifest(ContractModel):
    """Sealed release record for an approved immutable candidate."""

    schema_version: SchemaVersion
    run_type: ReleaseRunType
    project_id: Identifier
    scene_version: Identifier
    input_manifest_checksum: Checksum
    job_manifest_checksum: Checksum
    candidate_checksum: Checksum
    preflight_report_checksum: Checksum
    validation_report_checksum: Checksum
    evaluation_report_checksum: Checksum | None = None
    processing_config_checksum: Checksum
    software_versions: dict[str, str]
    artifact_inventory: list[ArtifactInventoryItem]
    review_state: Literal["APPROVED"]
    approval_record: ReleaseApproval
    release_timestamp: datetime
    release_manifest_checksum: Checksum

    @model_validator(mode="after")
    def _require_conditional_evaluation(self) -> Self:
        requires_evaluation = self.run_type in {
            ReleaseRunType.LOCKED_MVP_ACCEPTANCE,
            ReleaseRunType.BENCHMARK,
        }
        if requires_evaluation and self.evaluation_report_checksum is None:
            raise ValueError("this release run type requires an EvaluationReport checksum")
        return self
