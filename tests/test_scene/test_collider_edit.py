"""Contract and domain tests for revision-bound box collider edits."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import ColliderSpec, ColliderType, MassSource, ObjectPhysics, SceneIR, SceneObject
from src.services.orchestration.scene.errors import SceneEditRejectedError, SceneRevisionConflictError
from src.services.orchestration.scene.models import ColliderEditCommand
from src.services.orchestration.scene.objects import edit_collider_scene
from src.services.scene.publisher import with_scene_checksum
from src.services.simulation.colliders.generator import BoxSpecRequest, create_box_collider
from src.services.simulation.enrichment.service import enrich_scene_physics

_FIXTURE = Path("fixtures/scene_ir/scene.json")
_ZERO_CHECKSUM = "sha256:" + "0" * 64


def _scene_with_box(
    *,
    collider_type: ColliderType = ColliderType.OBB,
    dimensions: tuple[float, float, float] = (1.0, 2.0, 3.0),
    physics: ObjectPhysics | None = None,
) -> SceneIR:
    scene = SceneIR.model_validate(json.loads(_FIXTURE.read_text(encoding="utf-8")))
    target = scene.objects[0]
    collider_id = f"{target.local_frame}-collider"
    collider = ColliderSpec(
        collider_id=collider_id,
        collider_type=collider_type,
        local_transform=Transform(
            parent_frame=target.local_frame,
            local_frame=collider_id,
            translation_xyz=(0.1, -0.2, 0.3),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        dimensions_xyz_m=dimensions,
        geometry_ref=None,
        parameters={"volume_m3": 6.0, "preserve_me": True},
        provenance={"generator": "test-fixture"},
    )
    object_physics = physics or ObjectPhysics(
        dynamic=True,
        mass_kg=12.5,
        mass_source=MassSource.USER,
        density_kg_m3=480.0,
        static_friction=0.5,
        dynamic_friction=0.4,
        restitution=0.1,
        provenance={"volume_m3": 6.0, "mass_source": "user"},
    )
    edited_target = SceneObject.model_validate(
        {**target.model_dump(mode="python"), "collider": collider, "physics": object_physics}
    )
    objects = [edited_target, *scene.objects[1:]]
    checked = SceneIR.model_validate(
        {**scene.model_dump(mode="python"), "objects": objects, "scene_ir_checksum": _ZERO_CHECKSUM}
    )
    return with_scene_checksum(checked)


def _command(scene: SceneIR, object_id: str | None = None, **changes: object) -> ColliderEditCommand:
    return ColliderEditCommand(
        expected_scene_revision=scene.scene_revision,
        object_id=object_id or scene.objects[0].id,
        **changes,
    )


def test_box_edit_preserves_object_visual_geometry_physics_and_frames() -> None:
    scene = _scene_with_box()
    target = scene.objects[0]
    command = _command(
        scene,
        dimensions_xyz_m=(1.5, 2.5, 3.5),
        local_translation_xyz_m=(0.4, -0.1, 0.2),
        local_rotation_quaternion_xyzw=(0.0, 0.0, 0.7071067811865475, 0.7071067811865475),
    )

    result = edit_collider_scene(scene, command)
    edited = next(item for item in result.objects if item.id == target.id)

    assert result.scene_revision == scene.scene_revision  # publication assigns the next revision
    assert result.scene_ir_checksum != scene.scene_ir_checksum
    assert result.provenance["last_scene_operation"] == "edit_collider"
    assert result.provenance["invalidates_validation"] is True
    assert edited.transform == target.transform
    assert edited.visual_ref == target.visual_ref
    assert edited.geometry_ref == target.geometry_ref
    assert edited.primitive_dimensions_xyz_m == target.primitive_dimensions_xyz_m
    assert edited.physics == target.physics
    assert edited.collider is not None
    assert edited.collider.dimensions_xyz_m == (1.5, 2.5, 3.5)
    assert edited.collider.local_transform.parent_frame == target.local_frame
    assert edited.collider.local_transform.local_frame == target.collider.local_transform.local_frame
    assert edited.collider.local_transform.translation_xyz == (0.4, -0.1, 0.2)
    assert edited.collider.parameters == target.collider.parameters
    assert edited.collider.provenance["manual_override"]["operation"] == "collider_edit"
    assert edited.collider.provenance["manual_override_fields"] == [
        "dimensions_xyz_m",
        "local_rotation_quaternion_xyzw",
        "local_translation_xyz_m",
    ]


def test_dimensions_only_edit_preserves_existing_local_offset_and_rotation() -> None:
    scene = _scene_with_box()
    original = scene.objects[0]

    result = edit_collider_scene(scene, _command(scene, dimensions_xyz_m=(1.5, 2.5, 3.5)))

    edited = result.objects[0]
    assert edited.collider.dimensions_xyz_m == (1.5, 2.5, 3.5)
    assert edited.collider.local_transform == original.collider.local_transform
    assert edited.physics.mass_kg == 12.5
    assert edited.physics.mass_source == MassSource.USER


def test_collider_resize_does_not_recompute_density_derived_mass_without_volume_policy() -> None:
    physics = ObjectPhysics(
        dynamic=True,
        mass_kg=12.5,
        mass_source=MassSource.CATALOG_DENSITY,
        density_kg_m3=480.0,
        static_friction=0.5,
        dynamic_friction=0.4,
        restitution=0.1,
        provenance={"volume_m3": 6.0, "mass_source": "catalog_density"},
    )
    scene = _scene_with_box(physics=physics)

    result = edit_collider_scene(scene, _command(scene, dimensions_xyz_m=(4.0, 5.0, 6.0)))

    assert result.objects[0].physics == physics


@pytest.mark.parametrize(
    "dimensions", [(0.0, 1.0, 1.0), (-1.0, 1.0, 1.0), (float("nan"), 1.0, 1.0), (float("inf"), 1.0, 1.0)]
)
def test_command_rejects_non_positive_or_non_finite_dimensions(dimensions: tuple[float, float, float]) -> None:
    scene = _scene_with_box()

    with pytest.raises(ValidationError):
        _command(scene, dimensions_xyz_m=dimensions)


@pytest.mark.parametrize(
    "rotation",
    [(0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 2.0), (0.0, 0.0, float("nan"), 1.0)],
)
def test_command_rejects_invalid_quaternion(rotation: tuple[float, float, float, float]) -> None:
    scene = _scene_with_box()

    with pytest.raises(ValidationError):
        _command(scene, local_rotation_quaternion_xyzw=rotation)


@pytest.mark.parametrize("translation", [(float("nan"), 0.0, 0.0), (0.0, float("inf"), 0.0)])
def test_command_rejects_non_finite_translation(translation: tuple[float, float, float]) -> None:
    scene = _scene_with_box()

    with pytest.raises(ValidationError):
        _command(scene, local_translation_xyz_m=translation)


def test_command_rejects_empty_change_and_client_owned_frames() -> None:
    scene = _scene_with_box()

    with pytest.raises(ValidationError, match="collider edit"):
        _command(scene)
    with pytest.raises(ValidationError):
        _command(scene, dimensions_xyz_m=(1.0, 1.0, 1.0), parent_frame="world")


def test_command_wire_payload_uses_the_published_api_field_names() -> None:
    scene = _scene_with_box()
    command = _command(
        scene,
        dimensions_xyz_m=(1.5, 2.5, 3.5),
        local_translation_xyz_m=(0.4, -0.1, 0.2),
    )

    assert command.model_dump(mode="json", exclude_unset=True) == {
        "expected_scene_revision": scene.scene_revision,
        "object_id": scene.objects[0].id,
        "dimensions_xyz_m": [1.5, 2.5, 3.5],
        "local_translation_xyz_m": [0.4, -0.1, 0.2],
    }


def test_equal_supplied_value_follows_existing_transform_command_policy() -> None:
    scene = _scene_with_box()
    original = scene.objects[0]

    result = edit_collider_scene(scene, _command(scene, dimensions_xyz_m=original.collider.dimensions_xyz_m))

    assert result.provenance["invalidates_validation"] is True
    assert result.objects[0].collider.dimensions_xyz_m == original.collider.dimensions_xyz_m


def test_scene_revision_must_match_and_target_must_have_supported_box() -> None:
    scene = _scene_with_box()
    stale = ColliderEditCommand(
        expected_scene_revision="rev-stale", object_id=scene.objects[0].id, dimensions_xyz_m=(1.0, 2.0, 3.0)
    )
    with pytest.raises(SceneRevisionConflictError):
        edit_collider_scene(scene, stale)

    unsupported = _scene_with_box(collider_type=ColliderType.CONVEX_DECOMPOSITION)
    with pytest.raises(SceneEditRejectedError, match="only AABB/OBB"):
        edit_collider_scene(unsupported, _command(unsupported, dimensions_xyz_m=(1.2, 2.2, 3.2)))


def test_missing_object_collider_and_wrong_parent_are_rejected() -> None:
    scene = _scene_with_box()
    with pytest.raises(SceneEditRejectedError, match="unknown SceneObject"):
        edit_collider_scene(scene, _command(scene, "missing-object", dimensions_xyz_m=(1.0, 1.0, 1.0)))

    without_collider = SceneObject.model_validate({**scene.objects[0].model_dump(mode="python"), "collider": None})
    no_collider_scene = with_scene_checksum(
        SceneIR.model_validate(
            {
                **scene.model_dump(mode="python"),
                "objects": [without_collider, *scene.objects[1:]],
                "scene_ir_checksum": _ZERO_CHECKSUM,
            }
        )
    )
    with pytest.raises(SceneEditRejectedError, match="has no collider"):
        edit_collider_scene(no_collider_scene, _command(no_collider_scene, dimensions_xyz_m=(1.0, 1.0, 1.0)))

    target = scene.objects[0]
    broken_collider = target.collider.model_copy(
        update={"local_transform": target.collider.local_transform.model_copy(update={"parent_frame": "wrong-frame"})}
    )
    broken_object = target.model_copy(update={"collider": broken_collider}, deep=True)
    broken_scene = scene.model_copy(update={"objects": [broken_object, *scene.objects[1:]]}, deep=True)
    with pytest.raises(SceneEditRejectedError, match="not parented to object frame"):
        edit_collider_scene(broken_scene, _command(broken_scene, dimensions_xyz_m=(1.0, 1.0, 1.0)))


def test_manual_collider_override_survives_later_physics_enrichment() -> None:
    scene = _scene_with_box()
    target = scene.objects[0]
    edited = edit_collider_scene(scene, _command(scene, dimensions_xyz_m=(1.4, 2.4, 3.4)))
    replacement = create_box_collider(
        BoxSpecRequest(
            dimensions_xyz_m=(8.0, 8.0, 8.0),
            parent_frame=target.local_frame,
            collider_id=f"replacement-{target.id}",
        )
    )

    enriched = enrich_scene_physics(
        edited, colliders=[replacement], auto_generate_missing=False, add_ground_plane=False
    )
    current = next(item for item in enriched.objects if item.id == target.id)

    assert current.collider is not None
    assert current.collider.dimensions_xyz_m == (1.4, 2.4, 3.4)
    assert current.collider.provenance["manual_override"]["operation"] == "collider_edit"
