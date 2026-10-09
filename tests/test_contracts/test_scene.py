"""Contract tests for canonical SceneIR content."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.scene import ObjectPhysics, SceneIR, SourceCollisionRegion
from src.services.scene.publisher import with_scene_checksum

FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_scene_ir_fixture_is_valid() -> None:
    """EX-SIM can consume typed SceneIR without workflow state."""
    scene = SceneIR.model_validate_json((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))

    assert scene.environment.geometry_ref.artifact_checksum.startswith("sha256:")
    assert scene.objects[0].local_frame == scene.objects[0].transform.local_frame
    assert scene.objects[0].transform.translation_xyz == (1.0, 2.0, 0.0)
    assert {item.name for item in scene.objects} == {"Fixture Pallet", "Fixture Rack", "Fixture Floor"}
    assert scene.environment.collider_ref is not None
    dumped_environment = scene.model_dump(mode="json")["environment"]
    assert "collision_source_ref" not in dumped_environment
    assert "collision_selection_ref" not in dumped_environment
    assert all(item.transform.parent_frame == "world" for item in scene.objects)
    assert all(item.collider is not None for item in scene.objects if item.name != "Fixture Floor")
    assert all(
        item.collider.local_transform.parent_frame == item.local_frame for item in scene.objects if item.collider
    )
    assert "review_state" not in scene.model_dump()


def test_scene_object_ids_are_unique_within_revision() -> None:
    """A valid scene has one unambiguous identity per object."""
    scene = SceneIR.model_validate_json((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    assert len({item.id for item in scene.objects}) == len(scene.objects)


def test_duplicate_scene_object_id_is_rejected() -> None:
    """Duplicate IDs cannot make edit/collider/viewer lookup nondeterministic."""
    payload = json.loads((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    payload["objects"].append(payload["objects"][0])
    with pytest.raises(ValidationError, match="duplicate SceneObject.id"):
        SceneIR.model_validate(payload)


def test_collider_transform_must_be_local_to_scene_object() -> None:
    """Collider pose is an object-local offset, not a competing world transform."""
    payload = json.loads((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    payload["objects"][0]["collider"]["local_transform"]["parent_frame"] = "world"
    with pytest.raises(ValidationError, match="collider local offset"):
        SceneIR.model_validate(payload)


def test_user_added_object_requires_asset_or_sized_primitive() -> None:
    """A user-added object cannot have unspecified geometry dimensions."""
    payload = json.loads((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    added = payload["objects"][0]
    added["origin"] = "user_added"
    with pytest.raises(ValidationError, match="asset_ref or primitive_dimensions_xyz_m"):
        SceneIR.model_validate(payload)
    added["primitive_dimensions_xyz_m"] = [1.0, 1.0, 0.5]
    assert SceneIR.model_validate(payload).objects[0].primitive_dimensions_xyz_m == (1.0, 1.0, 0.5)
    added.pop("primitive_dimensions_xyz_m")
    added["asset_ref"] = added["geometry_ref"]
    assert SceneIR.model_validate(payload).objects[0].asset_ref is not None


@pytest.mark.parametrize("dimensions", [[0.0, 1.0, 1.0], [-1.0, 1.0, 1.0], [float("inf"), 1.0, 1.0]])
def test_user_added_primitive_dimensions_must_be_positive_finite(dimensions: list[float]) -> None:
    """Primitive geometry sizing is explicit and metric-valid."""
    payload = json.loads((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    payload["objects"][0].update(origin="user_added", primitive_dimensions_xyz_m=dimensions)
    with pytest.raises(ValidationError, match="primitive_dimensions_xyz_m"):
        SceneIR.model_validate(payload)


def test_scene_missing_required_local_frame_is_rejected() -> None:
    """Every P0 SceneObject declares its local frame explicitly."""
    with pytest.raises(ValidationError, match="local_frame"):
        SceneIR.model_validate_json((FIXTURES / "invalid/scene_missing_local_frame.json").read_text(encoding="utf-8"))


def test_review_state_cannot_leak_into_scene_ir() -> None:
    """Review lifecycle changes cannot mutate canonical SceneIR content."""
    payload = (FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8")
    scene_data = SceneIR.model_validate_json(payload).model_dump(mode="json")
    scene_data["review_state"] = "APPROVED"

    with pytest.raises(ValidationError, match="review_state"):
        SceneIR.model_validate(scene_data)


def _physics(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "dynamic": True,
        "mass_kg": 25.0,
        "mass_source": "catalog_default",
        "static_friction": 0.6,
        "dynamic_friction": 0.5,
        "restitution": 0.1,
        "provenance": {},
    }
    return {**base, **overrides}


def test_optional_v2_fields_do_not_change_legacy_scene_checksum() -> None:
    """Trường pipeline v2 không ghi khi rỗng → SceneIR đã lưu trước đó vẫn khớp checksum."""
    raw = (FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8")
    scene = SceneIR.model_validate_json(raw)
    dumped = scene.model_dump(mode="json")

    assert "physics" not in dumped["objects"][0]
    assert "source_collision" not in dumped["objects"][0]
    assert "visual_master_ref" not in dumped["environment"]
    assert canonical_content_checksum(scene, "scene_ir_checksum") == json.loads(raw)["scene_ir_checksum"]


def test_source_collision_region_v1_round_trips_through_scene_ir() -> None:
    """EX-SIM's existing SceneIR reader consumes typed source ownership without a side channel."""
    scene = SceneIR.model_validate_json((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    ownership = SourceCollisionRegion.model_validate_json(
        (FIXTURES / "scene_ir/source_collision_region_v1.json").read_text(encoding="utf-8")
    )
    pallet = scene.objects[0].model_copy(update={"source_collision": ownership}, deep=True)
    scene_with_ownership = with_scene_checksum(
        scene.model_copy(update={"objects": [pallet, *scene.objects[1:]]}, deep=True)
    )

    serialized = scene_with_ownership.model_dump_json()
    consumed = SceneIR.model_validate_json(serialized)

    assert consumed.objects[0].source_collision == ownership
    assert consumed.objects[0].source_collision.source_transform == consumed.objects[0].transform
    assert canonical_content_checksum(consumed, "scene_ir_checksum") == consumed.scene_ir_checksum


@pytest.mark.parametrize("invalid_dimension", [0.0, -0.1, float("nan"), float("inf")])
def test_source_collision_requires_source_pose_and_positive_finite_obb_dimensions(invalid_dimension: float) -> None:
    payload = json.loads((FIXTURES / "scene_ir/source_collision_region_v1.json").read_text(encoding="utf-8"))
    missing_pose = dict(payload)
    missing_pose.pop("source_transform")
    with pytest.raises(ValidationError, match="source_transform"):
        SourceCollisionRegion.model_validate(missing_pose)

    invalid_dimensions = json.loads(json.dumps(payload))
    invalid_dimensions["source_obb_dimensions_xyz_m"][1] = invalid_dimension
    with pytest.raises(ValidationError, match="source_obb_dimensions_xyz_m"):
        SourceCollisionRegion.model_validate(invalid_dimensions)


def test_source_collision_region_must_bind_scene_environment_geometry() -> None:
    payload = json.loads((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    ownership = json.loads((FIXTURES / "scene_ir/source_collision_region_v1.json").read_text(encoding="utf-8"))
    ownership["source_geometry_ref"]["artifact_checksum"] = "sha256:" + "0" * 64
    payload["objects"][0]["source_collision"] = ownership

    with pytest.raises(ValidationError, match="SceneIR environment geometry"):
        SceneIR.model_validate(payload)


def test_object_physics_round_trips_and_is_serialized_when_set() -> None:
    payload = json.loads((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    payload["objects"][0]["physics"] = _physics()
    scene = SceneIR.model_validate(payload)

    assert scene.objects[0].physics is not None and scene.objects[0].physics.mass_kg == 25.0
    assert scene.model_dump(mode="json")["objects"][0]["physics"]["mass_source"] == "catalog_default"


@pytest.mark.parametrize(
    "overrides",
    [{"mass_kg": None}, {"mass_source": None}, {"mass_kg": 0.0}, {"restitution": 1.5}, {"static_friction": -0.1}],
)
def test_object_physics_rejects_invalid_values(overrides: dict[str, object]) -> None:
    """Vật động phải có khối lượng dương và nguồn; ma sát không âm; độ nảy trong [0, 1]."""
    with pytest.raises(ValidationError):
        ObjectPhysics.model_validate(_physics(**overrides))


def test_static_object_physics_needs_no_mass() -> None:
    physics = ObjectPhysics.model_validate(_physics(dynamic=False, mass_kg=None, mass_source=None))

    assert physics.dynamic is False
