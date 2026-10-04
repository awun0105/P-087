"""Fixture-first scene decomposition from confirmed candidates."""

from src.services.scene.bundle_consumer import ValidatedBundleView
from src.services.scene.candidates.models import CandidateObject, CandidateState
from src.services.scene.decomposition.models import DecompositionResult, ObjectBinding


def decompose_scene(
    candidates: tuple[CandidateObject, ...],
    view: ValidatedBundleView,
) -> DecompositionResult:
    """Create object bindings without reading reconstruction temp folders."""
    confirmed = [item for item in candidates if item.state == CandidateState.CONFIRMED]
    if not confirmed:
        raise ValueError("at least one confirmed candidate is required")
    bindings = tuple(_binding(item, index) for index, item in enumerate(confirmed))
    return DecompositionResult(
        environment_geometry_ref=view.bundle.canonical_geometry_ref,
        visual_ref=view.bundle.visual_artifact_ref,
        object_bindings=bindings,
        provenance={"decomposition": "fixture_baseline", "bundle_checksum": view.bundle.artifact_checksum},
    )


def _binding(candidate: CandidateObject, index: int) -> ObjectBinding:
    return ObjectBinding(
        object_id=f"object-{index + 1:03d}",
        name=candidate.name,
        geometry_ref=candidate.geometry_ref,
        source_candidate_id=candidate.candidate_id,
        provenance={"source_candidate_id": candidate.candidate_id, **candidate.provenance},
    )
