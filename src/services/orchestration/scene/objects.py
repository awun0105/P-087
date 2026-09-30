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
from src.models.contracts.scene import SceneIR
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.errors import (
    SceneEditRejectedError,
    SceneObjectNotFoundError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.models import SceneEditResult
from src.services.scene.editing.commands import (
    PrimitiveObjectCommand,
    add_primitive_object,
    confirm_object,
    ignore_object,
    rename_object,
    set_object_active,
)

ObjectAction = Literal["confirm", "ignore", "hide", "delete", "rename"]
OBJECT_ACTIONS: frozenset[str] = frozenset({"confirm", "ignore", "hide", "delete", "rename"})


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
) -> SceneEditResult:
    """confirm/ignore ứng viên; hide (active=False, hoặc active=True để hiện lại); delete (tắt hẳn); rename."""
    scene = _current(editor, job_id, expected_revision)
    if object_id not in {item.id for item in scene.objects}:
        raise SceneObjectNotFoundError(f"object {object_id} không tồn tại trong revision")
    try:
        if action == "confirm":
            updated = confirm_object(scene, object_id)
        elif action == "ignore":
            updated = ignore_object(scene, object_id)
        elif action == "hide":
            updated = set_object_active(scene, object_id, bool(active))
        elif action == "delete":
            updated = set_object_active(scene, object_id, False)
        elif action == "rename":
            updated = rename_object(scene, object_id, name or "")
        else:
            raise SceneEditRejectedError(f"action {action} không được hỗ trợ")
    except ValueError as error:
        raise SceneEditRejectedError(str(error)) from error
    return editor.publish_next(job_id, expected_revision, updated, action)


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
    if not editor.resolver.resolve(reference.artifact_uri).is_file():
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
