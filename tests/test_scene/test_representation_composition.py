"""State matrix của visual lifecycle không được suy ra chỉ từ active."""

from pathlib import Path

import pytest

from src.models.contracts.scene import SceneIR, SceneObjectState
from src.services.scene.representation_composition import VisualPolicy, resolve_representation, scene_representations


def _scene() -> SceneIR:
    return SceneIR.model_validate_json(Path("fixtures/scene_ir/scene.json").read_bytes())


@pytest.mark.parametrize(
    ("state", "active", "review", "expected"),
    [
        ("CANDIDATE", False, None, VisualPolicy.SOURCE),
        ("CANDIDATE", False, "IGNORED", VisualPolicy.SOURCE),
        ("CONFIRMED", True, "CONFIRMED", VisualPolicy.OBJECT),
        ("CONFIRMED", False, "CONFIRMED", VisualPolicy.OMIT),
        ("CANDIDATE", False, "DELETED", VisualPolicy.OMIT),
        ("CONFIRMED", False, "DELETED", VisualPolicy.OMIT),
        ("CANDIDATE", False, "MERGED", VisualPolicy.OMIT),
    ],
)
def test_state_matrix(state: str, active: bool, review: str | None, expected: VisualPolicy) -> None:
    item = _scene().objects[0]
    item = item.model_copy(
        update={"state": SceneObjectState(state), "active": active, "provenance": {"review": review}}
    )
    original = item.model_dump_json()
    result = resolve_representation(item)
    assert result.visual_policy == expected
    assert result.export_as_object == (expected == VisualPolicy.OBJECT)
    assert item.model_dump_json() == original


def test_legacy_active_candidate_is_blocked_instead_of_implicitly_confirmed() -> None:
    item = _scene().objects[0].model_copy(update={"state": SceneObjectState.CANDIDATE, "active": True})
    result = resolve_representation(item)
    assert result.visual_policy == VisualPolicy.SOURCE
    assert result.readiness_blockers == ("INVALID_OBJECT_ACTIVATION",)


def test_duplicate_has_only_an_independent_object_representation() -> None:
    item = _scene().objects[0]
    duplicate = item.model_copy(update={"provenance": {"duplicated_from": item.id}})
    result = resolve_representation(duplicate, split_visuals=True)
    assert result.visual_policy == VisualPolicy.OBJECT and not result.source_visual_required


def test_decomposed_scene_missing_candidate_visual_cannot_be_silently_omitted() -> None:
    scene = _scene()
    item = scene.objects[0].model_copy(
        update={"state": SceneObjectState.CANDIDATE, "active": False, "visual_ref": None}
    )
    scene = scene.model_copy(update={"objects": [item], "provenance": {"object_extraction": "objectify_v1(test)"}})
    (result,) = scene_representations(scene)
    assert result.source_visual_required
    assert result.readiness_blockers == ("SOURCE_VISUAL_MISSING",)


def test_legacy_global_visual_does_not_require_an_object_gaussian_artifact() -> None:
    item = (
        _scene()
        .objects[0]
        .model_copy(update={"state": SceneObjectState.CANDIDATE, "active": False, "visual_ref": None})
    )
    result = resolve_representation(item)
    assert result.visual_policy == VisualPolicy.SOURCE
    assert not result.source_visual_required and not result.readiness_blockers


def test_user_added_candidate_cannot_claim_reconstructed_source_content() -> None:
    item = (
        _scene()
        .objects[0]
        .model_copy(update={"state": SceneObjectState.CANDIDATE, "active": False, "origin": "user_added"})
    )
    assert resolve_representation(item).readiness_blockers == ("SOURCE_REPRESENTATION_UNSUPPORTED",)
