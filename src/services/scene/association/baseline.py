"""Deterministic baseline association for fixture masks."""

from src.services.scene.association.models import CandidateGroup
from src.services.scene.bundle_consumer import ValidatedBundleView
from src.services.scene.extraction.models import MaskObservation, MaskSet


def associate_masks(mask_set: MaskSet, view: ValidatedBundleView) -> tuple[CandidateGroup, ...]:
    """Group masks by deterministic object hint and bind the canonical geometry."""
    grouped: dict[str, list[MaskObservation]] = {}
    for mask in mask_set.masks:
        grouped.setdefault(mask.object_hint, []).append(mask)
    return tuple(_group_to_candidate(key, grouped[key], view) for key in sorted(grouped))


def _group_to_candidate(
    object_hint: str,
    masks: list[MaskObservation],
    view: ValidatedBundleView,
) -> CandidateGroup:
    mask_ids = tuple(mask.mask_id for mask in sorted(masks, key=lambda item: item.mask_id))
    frame_ids = tuple(mask.frame_id for mask in sorted(masks, key=lambda item: item.frame_id))
    return CandidateGroup(
        candidate_id=f"candidate-{object_hint}",
        mask_ids=mask_ids,
        source_frame_ids=frame_ids,
        geometry_ref=view.bundle.canonical_geometry_ref,
        confidence=min(mask.confidence for mask in masks),
        provenance={"association": "object_hint_baseline", "bundle_checksum": view.bundle.artifact_checksum},
    )
