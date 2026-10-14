"""Thao tác vật thể trên SceneIR (PRODUCT-07/07A) qua lệnh domain của EX-SCENE.

PRODUCT chỉ điều phối: kiểm revision (khoá optimistic), gọi lệnh EX-SCENE, publish revision kế
tiếp bằng `SceneEditor.publish_next`. Ý nghĩa từng thao tác do `editing/commands.py` quyết định.
"""

import hashlib
import io
from typing import Literal

import trimesh

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import SceneIR, SceneObject
from src.services.orchestration.scene.catalog import load_catalog, physics_for
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.errors import (
    SceneEditRejectedError,
    SceneObjectNotFoundError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.models import ColliderEditCommand, SceneEditResult
from src.services.scene.editing.commands import (
    PrimitiveObjectCommand,
    add_primitive_object,
    confirm_object,
    delete_object,
    duplicate_object,
    edit_box_collider,
    ignore_object,
    rename_object,
    restore_object,
    set_object_active,
    set_object_semantics,
)

ObjectAction = Literal["confirm", "ignore", "hide", "delete", "rename", "restore", "duplicate", "label"]
OBJECT_ACTIONS: frozenset[str] = frozenset(
    {"confirm", "ignore", "hide", "delete", "rename", "restore", "duplicate", "label"}
)
#: Bản sao đặt lệch sang bên để không trùng khít vật gốc.
_DUPLICATE_OFFSET_M = (0.5, 0.0, 0.0)


def _current(editor: SceneEditor, job_id: str, expected_revision: str) -> SceneIR:
    scene = editor.current(job_id).scene
    if expected_revision != scene.scene_revision:
        raise SceneRevisionConflictError(
            f"scene đã đổi: client đang giữ {expected_revision}, revision hiện tại là {scene.scene_revision}"
        )
    return scene


def apply_object_action(
    editor: SceneEditor,
    job_id: str,
    object_id: str,
    action: ObjectAction,
    expected_revision: str,
    *,
    active: bool | None = None,
    name: str | None = None,
    semantic_class: str | None = None,
    mass_kg: float | None = None,
    asset_family: str | None = None,
) -> SceneEditResult:
    """Một thao tác trên một vật, publish revision kế tiếp.

    confirm/ignore ứng viên; hide (active=False/True); delete (vật thêm tay gỡ hẳn, vật tái dựng đánh
    dấu DELETED); restore; rename; duplicate; label (nhãn + vật lý: khối lượng người dùng nhập, nếu
    không thì mặc định của nhãn hoặc mật độ × thể tích collider).
    """
    scene = _current(editor, job_id, expected_revision)
    if object_id not in {item.id for item in scene.objects}:
        raise SceneObjectNotFoundError(f"object {object_id} không tồn tại trong revision")
    try:
        if action == "confirm":
            updated = confirm_object(scene, object_id)
        elif action == "ignore":
            updated = ignore_object(scene, object_id)
        elif action == "hide":
            if not isinstance(active, bool):
                raise ValueError("simulation activation requires an explicit boolean")
            updated = set_object_active(scene, object_id, active)
        elif action == "delete":
            updated = delete_object(scene, object_id)
        elif action == "restore":
            updated = restore_object(scene, object_id)
        elif action == "duplicate":
            updated = duplicate_object(scene, object_id, _next_id(scene, "user"), _DUPLICATE_OFFSET_M)
        elif action == "label":
            target = next(item for item in scene.objects if item.id == object_id)
            physics = (
                physics_for(semantic_class, object_volume_m3(target), mass_kg, asset_family) if semantic_class else None
            )
            updated = set_object_semantics(scene, object_id, semantic_class, physics)
        elif action == "rename":
            updated = rename_object(scene, object_id, name or "")
        else:
            raise SceneEditRejectedError(f"action {action} không được hỗ trợ")
    except ValueError as error:
        raise SceneEditRejectedError(str(error)) from error
    return editor.publish_next(job_id, expected_revision, updated, action)


def edit_collider_scene(scene: SceneIR, command: ColliderEditCommand) -> SceneIR:
    """Validate a collider command against one scene snapshot and return its pure edit result."""
    if command.expected_scene_revision != scene.scene_revision:
        raise SceneRevisionConflictError(
            f"scene đã đổi: client đang giữ {command.expected_scene_revision}, revision hiện tại là {scene.scene_revision}"
        )
    try:
        return edit_box_collider(
            scene,
            command.object_id,
            dimensions_xyz_m=command.dimensions_xyz_m,
            local_translation_xyz_m=command.local_translation_xyz_m,
            local_rotation_quaternion_xyzw=command.local_rotation_quaternion_xyzw,
        )
    except ValueError as error:
        raise SceneEditRejectedError(str(error)) from error


def edit_collider(editor: SceneEditor, job_id: str, command: ColliderEditCommand) -> SceneEditResult:
    """Publish a validated collider override as the next canonical scene revision."""
    current = editor.current(job_id).scene
    updated = edit_collider_scene(current, command)
    return editor.publish_next(job_id, command.expected_scene_revision, updated, "edit_collider")


def _next_id(scene: SceneIR, prefix: str) -> str:
    """Id `prefix-NNN` chưa dùng trong revision."""
    taken = {item.id for item in scene.objects}
    number = 1
    while f"{prefix}-{number:03d}" in taken:
        number += 1
    return f"{prefix}-{number:03d}"


def object_volume_m3(item: SceneObject) -> float | None:
    """Thể tích để suy khối lượng: thể tích các khối lồi nếu có, không thì thể tích hộp bao."""
    if item.collider is not None:
        volume = item.collider.parameters.get("volume_m3")
        if isinstance(volume, int | float) and volume > 0:
            return float(volume)
    if item.primitive_dimensions_xyz_m is not None:
        x, y, z = item.primitive_dimensions_xyz_m
        return float(x * y * z)
    return None


def _box_glb(dimensions: tuple[float, float, float]) -> bytes:
    buffer = io.BytesIO()
    trimesh.creation.box(extents=dimensions).export(buffer, file_type="glb")
    return buffer.getvalue()


def add_box_object(
    editor: SceneEditor,
    job_id: str,
    expected_revision: str,
    name: str,
    dimensions_xyz_m: tuple[float, float, float],
    center_xyz: tuple[float, float, float],
) -> SceneEditResult:
    """Thêm vật cản hộp do người dùng đặt (PRODUCT-07A): CONFIRMED, tâm hộp tại `center_xyz` (mét, world)."""
    scene = _current(editor, job_id, expected_revision)
    if min(dimensions_xyz_m) <= 0:
        raise SceneEditRejectedError("kích thước hộp phải dương")
    taken = {item.id for item in scene.objects}
    number = 1
    while f"user-{number:03d}" in taken:
        number += 1
    object_id = f"user-{number:03d}"
    payload = _box_glb(dimensions_xyz_m)
    digest = hashlib.sha256(payload).hexdigest()
    reference = ProductArtifactRef(
        artifact_type="SceneObjectGeometry",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/scene/user_objects/{digest}.glb",
        artifact_checksum=f"sha256:{digest}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.EDIT,
        job_id=job_id,
    )
    # GLB hộp định danh theo nội dung: đã có thì dùng lại (cùng kích thước → cùng bytes).
    if editor.resolver.locate(reference.artifact_uri) is None:
        editor.store.publish(reference, payload)
    command = PrimitiveObjectCommand(
        object_id=object_id,
        name=name.strip() or f"Vật cản {number}",
        transform=Transform(
            parent_frame="world",
            local_frame=object_id,
            translation_xyz=center_xyz,
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        geometry_ref=reference,
        dimensions_xyz_m=dimensions_xyz_m,
    )
    try:
        updated = add_primitive_object(scene, command)
    except ValueError as error:
        raise SceneEditRejectedError(str(error)) from error
    return editor.publish_next(job_id, expected_revision, updated, "add_primitive")


def add_catalog_object(
    editor: SceneEditor,
    job_id: str,
    expected_revision: str,
    family: str,
    position_xyz: tuple[float, float, float],
    name: str = "",
) -> SceneEditResult:
    """Thêm một vật từ danh mục asset Isaac (ADR 0007): hộp đúng kích thước asset, nhãn + vật lý mặc định.

    Trên web vật hiện bằng hộp; khi xuất USD, vật tham chiếu asset Isaac qua `provenance.asset_url`.
    `position_xyz` là điểm đặt trên sàn (đáy hộp), tâm hộp được nâng nửa chiều cao.
    """
    scene = _current(editor, job_id, expected_revision)
    entry = load_catalog().family(family)
    if entry is None or not entry.placeable:
        raise SceneEditRejectedError(f"họ asset {family} không có trong danh mục đặt được")
    dimensions = tuple(max(float(value), 0.01) for value in entry.size_xyz_m)
    object_id = _next_id(scene, "asset")
    payload = _box_glb(dimensions)  # type: ignore[arg-type]
    digest = hashlib.sha256(payload).hexdigest()
    reference = ProductArtifactRef(
        artifact_type="SceneObjectGeometry",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/scene/user_objects/{digest}.glb",
        artifact_checksum=f"sha256:{digest}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.EDIT,
        job_id=job_id,
    )
    if editor.resolver.locate(reference.artifact_uri) is None:
        editor.store.publish(reference, payload)
    volume = dimensions[0] * dimensions[1] * dimensions[2]
    command = PrimitiveObjectCommand(
        object_id=object_id,
        name=name.strip() or f"{entry.semantic_class or family} ({object_id})",
        transform=Transform(
            parent_frame="world",
            local_frame=object_id,
            translation_xyz=(position_xyz[0], position_xyz[1], position_xyz[2] + dimensions[2] / 2),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        geometry_ref=reference,
        dimensions_xyz_m=dimensions,  # type: ignore[arg-type]
        semantic_class=entry.semantic_class,
        physics=physics_for(entry.semantic_class, volume),
        provenance={"catalog_family": entry.family, "asset_url": entry.asset_url, "operation": "add_catalog_asset"},
    )
    try:
        updated = add_primitive_object(scene, command)
    except ValueError as error:
        raise SceneEditRejectedError(str(error)) from error
    return editor.publish_next(job_id, expected_revision, updated, "add_catalog_asset")


def restore_revision(editor: SceneEditor, job_id: str, expected_revision: str, target_revision: str) -> SceneEditResult:
    """Hoàn tác: publish nội dung của một revision cũ thành revision kế tiếp (lịch sử chỉ tiến, không xoá)."""
    current = _current(editor, job_id, expected_revision)
    target = editor.revision(job_id, target_revision)
    if target is None:
        raise SceneEditRejectedError(f"không có revision {target_revision}")
    restored = current.model_copy(
        update={
            "environment": target.scene.environment,
            "objects": target.scene.objects,
            "provenance": {**target.scene.provenance, "restored_from": target_revision, "invalidates_validation": True},
        }
    )
    return editor.publish_next(job_id, expected_revision, restored, "restore_revision")
