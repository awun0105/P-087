"""Backend SceneIR edit operations owned by EX-SCENE."""

import math
from dataclasses import dataclass

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import (
    ColliderSpec,
    ColliderType,
    ObjectPhysics,
    SceneIR,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
)
from src.services.scene.publisher import with_scene_checksum


def move_object(scene: SceneIR, object_id: str, transform: Transform) -> SceneIR:
    """Create a new revision with one object's canonical transform changed."""
    target = _find_object(scene, object_id)
    if transform.local_frame != target.local_frame:
        raise ValueError("edit transform local_frame must match SceneObject.local_frame")
    updated = target.model_copy(update={"transform": transform}, deep=True)
    return _replace_object(scene, updated, "move")


def edit_box_collider(
    scene: SceneIR,
    object_id: str,
    *,
    dimensions_xyz_m: tuple[float, float, float] | None = None,
    local_translation_xyz_m: tuple[float, float, float] | None = None,
    local_rotation_quaternion_xyzw: tuple[float, float, float, float] | None = None,
) -> SceneIR:
    """Return a checksummed SceneIR with one AABB/OBB edited in its object-local frame."""
    if dimensions_xyz_m is None and local_translation_xyz_m is None and local_rotation_quaternion_xyzw is None:
        raise ValueError("collider edit must change dimensions or local pose")

    target = _find_object(scene, object_id)
    collider = target.collider
    if collider is None:
        raise ValueError(f"object {object_id} has no collider")
    if collider.collider_type not in (ColliderType.AABB, ColliderType.OBB):
        raise ValueError(f"collider edit supports only AABB/OBB, got {collider.collider_type}")
    if collider.dimensions_xyz_m is None:
        raise ValueError(f"box collider {collider.collider_id} has no dimensions")
    if collider.local_transform.parent_frame != target.local_frame:
        raise ValueError(f"collider {collider.collider_id} is not parented to object frame {target.local_frame}")

    dimensions = collider.dimensions_xyz_m if dimensions_xyz_m is None else dimensions_xyz_m
    if len(dimensions) != 3 or any(not math.isfinite(value) or value <= 0 for value in dimensions):
        raise ValueError("collider dimensions must be three finite positive values in meters")
    translation = (
        collider.local_transform.translation_xyz if local_translation_xyz_m is None else local_translation_xyz_m
    )
    if len(translation) != 3 or any(not math.isfinite(value) for value in translation):
        raise ValueError("collider local translation must contain three finite values in meters")
    rotation = (
        collider.local_transform.rotation_quaternion_xyzw
        if local_rotation_quaternion_xyzw is None
        else local_rotation_quaternion_xyzw
    )

    local_transform = Transform.model_validate(
        {
            **collider.local_transform.model_dump(mode="python"),
            "parent_frame": target.local_frame,
            "translation_xyz": translation,
            "rotation_quaternion_xyzw": rotation,
        }
    )
    changed_fields = {
        name
        for name, value in (
            ("dimensions_xyz_m", dimensions_xyz_m),
            ("local_translation_xyz_m", local_translation_xyz_m),
            ("local_rotation_quaternion_xyzw", local_rotation_quaternion_xyzw),
        )
        if value is not None
    }
    previous_fields = collider.provenance.get("manual_override_fields", [])
    if not isinstance(previous_fields, list):
        previous_fields = []
    provenance = {
        **collider.provenance,
        "manual_override": {
            "source": "studio",
            "operation": "collider_edit",
            "base_scene_revision": scene.scene_revision,
        },
        "manual_override_fields": sorted(
            changed_fields | {field for field in previous_fields if isinstance(field, str)}
        ),
    }
    updated_collider = ColliderSpec.model_validate(
        {
            **collider.model_dump(mode="python"),
            "dimensions_xyz_m": dimensions,
            "local_transform": local_transform,
            "provenance": provenance,
        }
    )
    updated_object = SceneObject.model_validate({**target.model_dump(mode="python"), "collider": updated_collider})
    updated_scene = _replace_object(scene, updated_object, "edit_collider")
    return SceneIR.model_validate(updated_scene.model_dump(mode="python"))


def rename_object(scene: SceneIR, object_id: str, name: str) -> SceneIR:
    """Create a new revision with a renamed object."""
    if not name.strip():
        raise ValueError("object name cannot be empty")
    updated = _find_object(scene, object_id).model_copy(update={"name": name.strip()}, deep=True)
    return _replace_object(scene, updated, "rename")


def set_object_active(scene: SceneIR, object_id: str, active: bool) -> SceneIR:
    """Bật/tắt mô phỏng của vật đã xác nhận, độc lập ẩn viewport và Delete."""
    if not isinstance(active, bool):
        raise ValueError("simulation activation requires an explicit boolean")
    target = _find_object(scene, object_id)
    if target.state != SceneObjectState.CONFIRMED or target.provenance.get("review") in {"IGNORED", "DELETED"}:
        raise ValueError("simulation activation requires a confirmed object that has not been removed")
    updated = target.model_copy(update={"active": active}, deep=True)
    operation = "activate_simulation" if active else "deactivate_simulation"
    return _replace_object(scene, updated, operation)


def confirm_object(scene: SceneIR, object_id: str) -> SceneIR:
    """Người dùng xác nhận ứng viên là vật thể thật: CONFIRMED và active cho mô phỏng."""
    target = _find_object(scene, object_id)
    blocker = target.provenance.get("membership_reassign_blocker")
    if isinstance(blocker, str) and blocker:
        raise ValueError(f"object {object_id} cannot be confirmed: {blocker}")
    review = {**target.provenance, "review": "CONFIRMED"}
    updated = target.model_copy(
        update={"state": SceneObjectState.CONFIRMED, "active": True, "provenance": review}, deep=True
    )
    return _replace_object(scene, updated, "confirm")


def ignore_object(scene: SceneIR, object_id: str) -> SceneIR:
    """Loại ứng viên: SceneIR chỉ có CANDIDATE/CONFIRMED nên giữ CANDIDATE, tắt active, ghi IGNORED.

    Không xoá khỏi revision để còn audit và khôi phục (PRD: confirm/ignore/correct là metric vận hành).
    """
    target = _find_object(scene, object_id)
    if target.state == SceneObjectState.CONFIRMED:
        raise ValueError("vật thể đã xác nhận; ẩn/xoá thay vì loại ứng viên")
    review = {**target.provenance, "review": "IGNORED"}
    updated = target.model_copy(update={"active": False, "provenance": review}, deep=True)
    return _replace_object(scene, updated, "ignore")


def delete_object(scene: SceneIR, object_id: str) -> SceneIR:
    """Soft-delete every object so user-added assets remain auditable and restorable."""
    target = _find_object(scene, object_id)
    review = {**target.provenance, "review": "DELETED"}
    updated = target.model_copy(update={"active": False, "provenance": review}, deep=True)
    return _replace_object(scene, updated, "delete")


def restore_object(scene: SceneIR, object_id: str) -> SceneIR:
    """Đưa vật đã xoá/loại trở lại trạng thái trước đó (ứng viên chờ xác nhận, hoặc đã xác nhận + active)."""
    target = _find_object(scene, object_id)
    provenance = {key: value for key, value in target.provenance.items() if key != "review"}
    confirmed = target.state == SceneObjectState.CONFIRMED
    if confirmed:
        provenance["review"] = "CONFIRMED"
    updated = target.model_copy(update={"active": confirmed, "provenance": provenance}, deep=True)
    return _replace_object(scene, updated, "restore")


def duplicate_object(scene: SceneIR, object_id: str, new_id: str, offset_xyz: tuple[float, float, float]) -> SceneIR:
    """Nhân bản một vật (dùng chung visual/geometry bất biến) và đặt lệch `offset_xyz` mét."""
    if new_id in {item.id for item in scene.objects}:
        raise ValueError(f"duplicate SceneObject.id in SceneIR: {new_id}")
    source = _find_object(scene, object_id)
    translation = tuple(
        value + delta for value, delta in zip(source.transform.translation_xyz, offset_xyz, strict=True)
    )
    transform = source.transform.model_copy(update={"local_frame": new_id, "translation_xyz": translation})
    collider = source.collider
    if collider is not None:
        collider = collider.model_copy(
            update={
                "collider_id": f"{new_id}-collider",
                "local_transform": collider.local_transform.model_copy(
                    update={"parent_frame": new_id, "local_frame": f"{new_id}-collider"}
                ),
            }
        )
    copy = SceneObject.model_validate(
        {
            **source.model_dump(),
            "id": new_id,
            "name": f"{source.name} (bản sao)",
            "local_frame": new_id,
            "transform": transform.model_dump(),
            "collider": collider.model_dump() if collider else None,
            # A duplicate is placed independently and does not own the source region.
            "source_collision": None,
            "state": SceneObjectState.CONFIRMED,
            "active": True,
            "provenance": {**source.provenance, "review": "CONFIRMED", "duplicated_from": object_id},
        }
    )
    return _replace_objects(scene, [*scene.objects, copy], "duplicate")


def set_object_semantics(
    scene: SceneIR, object_id: str, semantic_class: str | None, physics: ObjectPhysics | None
) -> SceneIR:
    """Gán nhãn lớp và thuộc tính vật lý (người dùng xác nhận; hệ thống chỉ gợi ý)."""
    label = semantic_class.strip() if semantic_class else None
    updated = _find_object(scene, object_id).model_copy(
        update={"semantic_class": label or None, "physics": physics}, deep=True
    )
    return _replace_object(scene, updated, "label")


def add_primitive_object(scene: SceneIR, command: "PrimitiveObjectCommand") -> SceneIR:
    """Add a user-defined primitive object with explicit metric dimensions."""
    if command.object_id in {item.id for item in scene.objects}:
        raise ValueError(f"duplicate SceneObject.id in SceneIR: {command.object_id}")
    added = _primitive_object(command)
    return _replace_objects(scene, [*scene.objects, added], "add_primitive")


def _find_object(scene: SceneIR, object_id: str) -> SceneObject:
    for item in scene.objects:
        if item.id == object_id:
            if item.provenance.get("review") == "MERGED":
                raise ValueError("merged object is an audit tombstone; restore a revision before the merge to undo it")
            return item
    raise ValueError(f"unknown SceneObject.id: {object_id}")


def _replace_object(scene: SceneIR, updated: SceneObject, operation: str) -> SceneIR:
    objects = [updated if item.id == updated.id else item for item in scene.objects]
    return _replace_objects(scene, objects, operation)


def _replace_objects(scene: SceneIR, objects: list[SceneObject], operation: str) -> SceneIR:
    provenance = {**scene.provenance, "last_scene_operation": operation, "invalidates_validation": True}
    changed = scene.model_copy(update={"objects": objects, "provenance": provenance}, deep=True)
    return with_scene_checksum(changed)


def _primitive_object(command: "PrimitiveObjectCommand") -> SceneObject:
    return SceneObject(
        id=command.object_id,
        name=command.name,
        state=SceneObjectState.CONFIRMED,
        origin=SceneObjectOrigin.USER_ADDED,
        active=True,
        local_frame=command.object_id,
        transform=command.transform,
        geometry_ref=command.geometry_ref,
        asset_ref=command.asset_ref,
        primitive_dimensions_xyz_m=command.dimensions_xyz_m,
        semantic_class=command.semantic_class,
        physics=command.physics,
        provenance={"origin": "user_added", "operation": "add_primitive", **(command.provenance or {})},
    )


@dataclass(frozen=True)
class PrimitiveObjectCommand:
    """Command object keeps add_primitive_object within the parameter budget."""

    object_id: str
    name: str
    transform: Transform
    geometry_ref: ProductArtifactRef
    dimensions_xyz_m: tuple[float, float, float]
    asset_ref: ProductArtifactRef | None = None
    semantic_class: str | None = None
    physics: ObjectPhysics | None = None
    provenance: dict | None = None
