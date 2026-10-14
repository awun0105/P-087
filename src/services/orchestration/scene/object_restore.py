"""Undo a merge from committed snapshots without rolling back unrelated scene edits."""

from src.models.contracts.scene import SceneIR
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.errors import SceneEditRejectedError


def restore_merged_group(editor: SceneEditor, job_id: str, scene: SceneIR, object_id: str) -> SceneIR:
    """Restore the complete merge group; nested merges unwind until the selected object is independent."""
    restored = scene
    undone: list[str] = []
    while True:
        target = next(item for item in restored.objects if item.id == object_id)
        if target.provenance.get("review") != "MERGED":
            break
        before_id = target.provenance.get("merged_from_revision")
        if not isinstance(before_id, str) or before_id in undone:
            raise SceneEditRejectedError("Không có lịch sử gộp hợp lệ để khôi phục nhóm vật.")
        before = editor.revision(job_id, before_id)
        merged = None
        cursor = scene.scene_revision
        visited: set[str] = set()
        while cursor and cursor not in visited:
            visited.add(cursor)
            revision = editor.revision(job_id, cursor)
            if revision is None:
                break
            if (
                revision.supersedes_revision == before_id
                and revision.scene.provenance.get("operation") == "object_membership_merge"
            ):
                merged = revision
                break
            cursor = revision.supersedes_revision
        if before is None or merged is None:
            raise SceneEditRejectedError("Không tìm thấy snapshot đã publish trước và sau lần gộp.")
        original = {item.id: item for item in before.scene.objects}
        combined = {item.id: item for item in merged.scene.objects}
        current = {item.id: item for item in restored.objects}
        affected = {key for key in original if original[key] != combined.get(key)}
        if object_id not in affected or any(current.get(key) != combined.get(key) for key in affected):
            raise SceneEditRejectedError(
                "Nhóm đã được chỉnh sửa sau khi gộp. Không thể tự khôi phục nhóm mà ghi đè chỉnh sửa đó; dùng lịch sử scene để chọn revision cần khôi phục."
            )
        old_map = before.scene.environment.membership
        merged_map = merged.scene.environment.membership
        current_map = restored.environment.membership
        if old_map is None or merged_map is None or current_map is None:
            raise SceneEditRejectedError("Thiếu membership đã publish để khôi phục nhóm gộp.")
        if (
            current_map.model_dump(exclude={"label_to_object_id"})
            != merged_map.model_dump(exclude={"label_to_object_id"})
            or old_map.model_dump(exclude={"label_to_object_id"})
            != merged_map.model_dump(exclude={"label_to_object_id"})
            or restored.environment.geometry_ref != merged.scene.environment.geometry_ref
            or restored.environment.collision_source_ref != merged.scene.environment.collision_source_ref
        ):
            raise SceneEditRejectedError(
                "Nguồn hoặc membership đã thay đổi sau lần gộp; không thể khôi phục ownership từ snapshot cũ."
            )
        changed = {
            key
            for key in old_map.label_to_object_id
            if old_map.label_to_object_id[key] != merged_map.label_to_object_id.get(key)
        }
        if any(current_map.label_to_object_id.get(key) != merged_map.label_to_object_id.get(key) for key in changed):
            raise SceneEditRejectedError("Ownership của nhóm đã thay đổi sau lần gộp.")
        mapping = {**current_map.label_to_object_id, **{key: old_map.label_to_object_id[key] for key in changed}}
        restored = restored.model_copy(
            update={
                "objects": [original[item.id] if item.id in affected else item for item in restored.objects],
                "environment": restored.environment.model_copy(
                    update={"membership": current_map.model_copy(update={"label_to_object_id": mapping})}
                ),
            },
            deep=True,
        )
        undone.append(before_id)
    return SceneIR.model_validate(
        restored.model_copy(
            update={
                "provenance": {
                    **restored.provenance,
                    "invalidates_validation": True,
                    "last_scene_operation": "restore_merge",
                    "restored_merge": {"object_id": object_id, "before_revisions": undone},
                }
            }
        ).model_dump(mode="python")
    )
