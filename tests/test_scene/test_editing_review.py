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
