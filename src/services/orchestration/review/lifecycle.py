"""Revision invalidation rules for scene edits."""

from src.models.contracts.artifacts import Checksum, Identifier
from src.models.contracts.release import SceneRevisionRecord, SceneRevisionStatus


def invalidate_after_scene_edit(
    current: SceneRevisionRecord,
    new_revision: Identifier,
    new_scene_ir_checksum: Checksum,
) -> SceneRevisionRecord:
    """Create a DRAFT revision and discard all old derived approvals/reports."""
    if new_revision == current.scene_revision:
        raise ValueError("scene edit must create a new revision")
    if new_scene_ir_checksum == current.scene_ir_checksum:
        raise ValueError("scene edit must change the SceneIR content checksum")
    return SceneRevisionRecord(
        schema_version=current.schema_version,
        scene_id=current.scene_id,
        scene_revision=new_revision,
        scene_ir_checksum=new_scene_ir_checksum,
        status=SceneRevisionStatus.DRAFT,
    )
