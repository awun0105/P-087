"""Lệnh review ứng viên của EX-SCENE: confirm/ignore trên SceneIR không đổi contract."""

import json
from pathlib import Path

import pytest

from src.models.contracts.scene import SceneIR, SceneObjectState
from src.services.scene.editing.commands import confirm_object, ignore_object

_SCENE = Path(__file__).parents[2] / "fixtures" / "scene_ir" / "scene.json"


def _candidate_scene() -> SceneIR:
    scene = SceneIR.model_validate(json.loads(_SCENE.read_text(encoding="utf-8")))
    first = scene.objects[0].model_copy(update={"state": SceneObjectState.CANDIDATE, "active": False})
    return scene.model_copy(update={"objects": [first, *scene.objects[1:]]})


def test_confirm_activates_candidate() -> None:
    scene = _candidate_scene()
    target = confirm_object(scene, scene.objects[0].id).objects[0]
    assert target.state == SceneObjectState.CONFIRMED and target.active
    assert target.provenance["review"] == "CONFIRMED"


def test_ignore_keeps_candidate_for_audit_but_inactive() -> None:
    scene = _candidate_scene()
    updated = ignore_object(scene, scene.objects[0].id)
    target = updated.objects[0]
    assert target.state == SceneObjectState.CANDIDATE and not target.active
    assert target.provenance["review"] == "IGNORED"
    assert len(updated.objects) == len(scene.objects)
    assert updated.provenance["last_scene_operation"] == "ignore"


def test_ignore_refuses_confirmed_object() -> None:
    scene = _candidate_scene()
    with pytest.raises(ValueError):
        ignore_object(scene, scene.objects[1].id)


def test_simulation_activation_is_distinct_from_viewport_hide_and_delete() -> None:
    from src.models.contracts.identity import verify_content_checksum
    from src.services.scene.editing.commands import set_object_active

    scene = _candidate_scene()
    object_id = scene.objects[0].id
    confirmed = confirm_object(scene, object_id)
    disabled = set_object_active(confirmed, object_id, False)
    assert disabled.objects[0].provenance["review"] == "CONFIRMED"
    assert disabled.provenance["last_scene_operation"] == "deactivate_simulation"
    assert not disabled.objects[0].active
    enabled = set_object_active(disabled, object_id, True)
    assert enabled.objects[0].active
    assert enabled.provenance["last_scene_operation"] == "activate_simulation"
    verify_content_checksum(enabled, "scene_ir_checksum")


@pytest.mark.parametrize("review", [None, "IGNORED", "DELETED", "MERGED"])
def test_candidate_or_removed_object_cannot_be_activated(review: str | None) -> None:
    from src.services.scene.editing.commands import set_object_active

    scene = _candidate_scene()
    first = scene.objects[0].model_copy(update={"provenance": {"review": review}})
    scene = scene.model_copy(update={"objects": [first]})
    with pytest.raises(ValueError):
        set_object_active(scene, first.id, True)


@pytest.mark.parametrize("active", [None, 0, 1, "true", "false"])
def test_activation_body_requires_a_boolean(active: object) -> None:
    from types import SimpleNamespace

    from pydantic import ValidationError

    from src.api.schemas import ObjectActionRequest
    from src.services.orchestration.scene.errors import SceneEditRejectedError
    from src.services.orchestration.scene.objects import apply_object_action

    scene = confirm_object(_candidate_scene(), _candidate_scene().objects[0].id)
    editor = SimpleNamespace(current=lambda _job: SimpleNamespace(scene=scene))
    with pytest.raises(SceneEditRejectedError, match="explicit boolean"):
        apply_object_action(editor, "job-fixture-001", scene.objects[0].id, "hide", scene.scene_revision, active=active)
    if active is not None:
        with pytest.raises(ValidationError):
            ObjectActionRequest(expected_scene_revision=scene.scene_revision, active=active)


def test_restore_repairs_legacy_active_candidate_without_confirming_or_moving_it() -> None:
    from src.models.contracts.identity import verify_content_checksum
    from src.services.scene.editing.commands import restore_object
    from src.services.scene.representation_composition import resolve_representation

    scene = _candidate_scene()
    candidate = scene.objects[0].model_copy(update={"active": True})
    updated = restore_object(scene.model_copy(update={"objects": [candidate]}), candidate.id)
    repaired = updated.objects[0]
    assert repaired.state == SceneObjectState.CANDIDATE and not repaired.active
    assert repaired.transform == candidate.transform and repaired.visual_ref == candidate.visual_ref
    assert repaired.source_collision == candidate.source_collision
    assert "INVALID_OBJECT_ACTIVATION" not in resolve_representation(repaired).readiness_blockers
    verify_content_checksum(updated, "scene_ir_checksum")
