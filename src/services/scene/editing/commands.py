"""Backend SceneIR edit operations owned by EX-SCENE."""

from dataclasses import dataclass

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import SceneIR, SceneObject, SceneObjectOrigin, SceneObjectState
from src.services.scene.publisher import with_scene_checksum


def move_object(scene: SceneIR, object_id: str, transform: Transform) -> SceneIR:
    """Create a new revision with one object's canonical transform changed."""
    target = _find_object(scene, object_id)
    if transform.local_frame != target.local_frame:
        raise ValueError("edit transform local_frame must match SceneObject.local_frame")
    updated = target.model_copy(update={"transform": transform}, deep=True)
    return _replace_object(scene, updated, "move")


def rename_object(scene: SceneIR, object_id: str, name: str) -> SceneIR:
    """Create a new revision with a renamed object."""
    if not name.strip():
        raise ValueError("object name cannot be empty")
    updated = _find_object(scene, object_id).model_copy(update={"name": name.strip()}, deep=True)
    return _replace_object(scene, updated, "rename")


def set_object_active(scene: SceneIR, object_id: str, active: bool) -> SceneIR:
    """Hide/show or logically delete an object from active consumers."""
    updated = _find_object(scene, object_id).model_copy(update={"active": active}, deep=True)
    operation = "show" if active else "delete"
    return _replace_object(scene, updated, operation)


def confirm_object(scene: SceneIR, object_id: str) -> SceneIR:
    """Người dùng xác nhận ứng viên là vật thể thật: CONFIRMED và active cho mô phỏng."""
    target = _find_object(scene, object_id)
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


def add_primitive_object(scene: SceneIR, command: "PrimitiveObjectCommand") -> SceneIR:
    """Add a user-defined primitive object with explicit metric dimensions."""
    if command.object_id in {item.id for item in scene.objects}:
        raise ValueError(f"duplicate SceneObject.id in SceneIR: {command.object_id}")
    added = _primitive_object(command)
    return _replace_objects(scene, [*scene.objects, added], "add_primitive")


def _find_object(scene: SceneIR, object_id: str) -> SceneObject:
    for item in scene.objects:
        if item.id == object_id:
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
        primitive_dimensions_xyz_m=command.dimensions_xyz_m,
        provenance={"origin": "user_added", "operation": "add_primitive"},
    )


@dataclass(frozen=True)
class PrimitiveObjectCommand:
    """Command object keeps add_primitive_object within the parameter budget."""

    object_id: str
    name: str
    transform: Transform
    geometry_ref: ProductArtifactRef
    dimensions_xyz_m: tuple[float, float, float]
