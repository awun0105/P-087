"""Human confirmation operations over candidate records."""

from dataclasses import replace

from src.services.scene.candidates.models import CandidateAuditEvent, CandidateObject, CandidateState


def confirm_candidate(candidate: CandidateObject, actor_id: str) -> tuple[CandidateObject, CandidateAuditEvent]:
    """Mark one candidate as confirmed for decomposition."""
    _require_reviewable(candidate)
    updated = replace(candidate, state=CandidateState.CONFIRMED)
    return updated, _event("confirm", actor_id, candidate.candidate_id)


def ignore_candidate(candidate: CandidateObject, actor_id: str) -> tuple[CandidateObject, CandidateAuditEvent]:
    """Mark one candidate as ignored without deleting its provenance."""
    _require_reviewable(candidate)
    updated = replace(candidate, state=CandidateState.IGNORED)
    return updated, _event("ignore", actor_id, candidate.candidate_id)


def rename_candidate(
    candidate: CandidateObject,
    new_name: str,
    actor_id: str,
) -> tuple[CandidateObject, CandidateAuditEvent]:
    """Rename a candidate while preserving identity."""
    if not new_name.strip():
        raise ValueError("candidate name cannot be empty")
    updated = replace(candidate, name=new_name.strip())
    return updated, _event("rename", actor_id, candidate.candidate_id)


def merge_candidates(
    primary: CandidateObject,
    secondary: CandidateObject,
    actor_id: str,
) -> tuple[CandidateObject, CandidateAuditEvent]:
    """Merge source masks into the primary candidate and ignore the secondary."""
    if primary.candidate_id == secondary.candidate_id:
        raise ValueError("cannot merge a candidate into itself")
    mask_ids = tuple(dict.fromkeys((*primary.mask_ids, *secondary.mask_ids)))
    provenance = {**primary.provenance, "merged_candidate_id": secondary.candidate_id}
    merged = replace(primary, mask_ids=mask_ids, provenance=provenance)
    return merged, _event("merge", actor_id, primary.candidate_id, secondary.candidate_id)


def mark_needs_correction(candidate: CandidateObject, actor_id: str) -> tuple[CandidateObject, CandidateAuditEvent]:
    """Flag a candidate that needs correction before decomposition."""
    updated = replace(candidate, state=CandidateState.NEEDS_CORRECTION)
    return updated, _event("needs_correction", actor_id, candidate.candidate_id)


def _require_reviewable(candidate: CandidateObject) -> None:
    if candidate.state == CandidateState.IGNORED:
        raise ValueError("ignored candidate cannot be reviewed again without correction")


def _event(operation: str, actor_id: str, *candidate_ids: str) -> CandidateAuditEvent:
    return CandidateAuditEvent(
        operation=operation,
        actor_id=actor_id,
        candidate_ids=tuple(candidate_ids),
        provenance={"source": "scene_candidate_operation"},
    )
