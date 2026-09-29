"""Candidate identity groups produced from multi-view mask association."""

from dataclasses import dataclass

from src.models.contracts.artifacts import JsonObject, ProductArtifactRef


@dataclass(frozen=True)
class CandidateGroup:
    """Stable association of observations believed to describe one object."""

    candidate_id: str
    mask_ids: tuple[str, ...]
    source_frame_ids: tuple[str, ...]
    geometry_ref: ProductArtifactRef
    confidence: float
    provenance: JsonObject

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.mask_ids:
            raise ValueError("candidate_id and mask_ids are required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("candidate confidence must be in [0, 1]")
