"""Candidate object domain state before SceneIR publication."""

from dataclasses import dataclass
from enum import StrEnum

from src.models.contracts.artifacts import JsonObject, ProductArtifactRef


class CandidateState(StrEnum):
    """EX-SCENE candidate lifecycle before decomposition."""

    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"
    IGNORED = "IGNORED"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"


@dataclass(frozen=True)
class CandidateObject:
    """Project-owned candidate identity with review state and provenance."""

    candidate_id: str
    name: str
    state: CandidateState
    mask_ids: tuple[str, ...]
    geometry_ref: ProductArtifactRef
    provenance: JsonObject

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.name or not self.mask_ids:
            raise ValueError("candidate_id, name and mask_ids are required")


@dataclass(frozen=True)
class CandidateAuditEvent:
    """Auditable human/domain operation over candidates."""

    operation: str
    actor_id: str
    candidate_ids: tuple[str, ...]
    provenance: JsonObject

    def __post_init__(self) -> None:
        if not self.operation or not self.actor_id or not self.candidate_ids:
            raise ValueError("operation, actor_id and candidate_ids are required")
