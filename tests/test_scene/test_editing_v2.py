"""Lệnh sửa scene theo vật (pipeline v2): xoá, khôi phục, nhân bản, gán nhãn + vật lý."""

import json
from pathlib import Path

import pytest

from src.models.contracts.scene import MassSource, ObjectPhysics, SceneIR
from src.services.scene.editing.commands import (
    delete_object,
    duplicate_object,
    restore_object,
    set_object_semantics,
)

_SCENE = Path(__file__).parents[2] / "fixtures" / "scene_ir" / "scene.json"
_PALLET = "object-pallet-001"


def _scene() -> SceneIR:
    return SceneIR.model_validate(json.loads(_SCENE.read_text(encoding="utf-8")))


def _object(scene: SceneIR, object_id: str):  # noqa: ANN202 - helper test
    return next(item for item in scene.objects if item.id == object_id)


def test_delete_keeps_reconstructed_object_for_audit_and_restore_brings_it_back() -> None:
    deleted = delete_object(_scene(), _PALLET)
    target = _object(deleted, _PALLET)

    assert target.active is False and target.provenance["review"] == "DELETED"
    assert deleted.provenance["invalidates_validation"] is True

    restored = _object(restore_object(deleted, _PALLET), _PALLET)
    assert restored.active is True and restored.provenance["review"] == "CONFIRMED"


def test_delete_removes_user_added_object_entirely() -> None:
    scene = duplicate_object(_scene(), _PALLET, "user-001", (0.5, 0.0, 0.0))
    user = _object(scene, "user-001").model_copy(update={"origin": "user_added"})
    scene = scene.model_copy(update={"objects": [*scene.objects[:-1], user]})

    assert "user-001" not in {item.id for item in delete_object(scene, "user-001").objects}


def test_duplicate_rebinds_frames_and_offsets_position() -> None:
    scene = duplicate_object(_scene(), _PALLET, "user-001", (0.5, 0.0, 0.0))
    source, copy = _object(scene, _PALLET), _object(scene, "user-001")

    assert copy.local_frame == copy.transform.local_frame == "user-001"
    assert copy.transform.translation_xyz[0] == pytest.approx(source.transform.translation_xyz[0] + 0.5)
    assert copy.collider is not None and copy.collider.local_transform.parent_frame == "user-001"
    assert copy.geometry_ref == source.geometry_ref  # dùng chung artifact bất biến
    assert copy.provenance["duplicated_from"] == _PALLET


def test_duplicate_rejects_existing_id() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        duplicate_object(_scene(), _PALLET, "object-rack-001", (0.5, 0.0, 0.0))


def test_label_sets_class_and_physics_and_clearing_label_removes_physics() -> None:
    physics = ObjectPhysics(
        dynamic=True,
        mass_kg=25.0,
        mass_source=MassSource.CATALOG_DEFAULT,
        static_friction=0.6,
        dynamic_friction=0.5,
        restitution=0.1,
        provenance={},
    )
    labelled = _object(set_object_semantics(_scene(), _PALLET, " pallet ", physics), _PALLET)

    assert labelled.semantic_class == "pallet" and labelled.physics == physics

    cleared = _object(set_object_semantics(_scene(), _PALLET, "", None), _PALLET)
    assert cleared.semantic_class is None and cleared.physics is None
