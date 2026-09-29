"""Create candidate records from associated mask groups."""

from src.services.scene.association.models import CandidateGroup
from src.services.scene.candidates.models import CandidateObject, CandidateState


def build_candidates(groups: tuple[CandidateGroup, ...]) -> tuple[CandidateObject, ...]:
    """Convert deterministic groups into unreviewed domain candidates."""
    seen: set[str] = set()
    candidates: list[CandidateObject] = []
    for group in groups:
        if group.candidate_id in seen:
            raise ValueError(f"duplicate candidate_id: {group.candidate_id}")
        seen.add(group.candidate_id)
        candidates.append(_candidate_from_group(group))
    return tuple(candidates)


def _candidate_from_group(group: CandidateGroup) -> CandidateObject:
    return CandidateObject(
        candidate_id=group.candidate_id,
        name=group.candidate_id.replace("candidate-", "").replace("-", " ").title(),
        state=CandidateState.UNREVIEWED,
        mask_ids=group.mask_ids,
        geometry_ref=group.geometry_ref,
        provenance={"source_group": group.candidate_id, **group.provenance},
    )
