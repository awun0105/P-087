"""Revision invalidation proof after canonical scene edits."""

import pytest

from src.models.contracts.release import SceneRevisionRecord
from src.services.orchestration.review import invalidate_after_scene_edit

OLD = "sha256:" + "6" * 64
NEW = "sha256:" + "7" * 64


def _approved_revision() -> SceneRevisionRecord:
    return SceneRevisionRecord(
        schema_version="1.0",
        scene_id="scene-001",
        scene_revision="rev-001",
        scene_ir_checksum=OLD,
        status="APPROVED",
        candidate_checksum=OLD,
        validation_report_checksum=OLD,
        evaluation_report_checksum=OLD,
        approval_record_checksum=OLD,
    )


def test_scene_edit_invalidates_all_derived_evidence() -> None:
    """A changed SceneIR starts a new DRAFT with no stale validation/review."""
    updated = invalidate_after_scene_edit(_approved_revision(), "rev-002", NEW)

    assert updated.status == "DRAFT"
    assert updated.scene_ir_checksum == NEW
    assert updated.candidate_checksum is None
    assert updated.validation_report_checksum is None
    assert updated.evaluation_report_checksum is None
    assert updated.approval_record_checksum is None


@pytest.mark.parametrize(("revision", "checksum"), [("rev-001", NEW), ("rev-002", OLD)])
def test_revision_invalidation_requires_real_content_change(revision: str, checksum: str) -> None:
    """No-op edits cannot manufacture a fresh revision lifecycle."""
    with pytest.raises(ValueError):
        invalidate_after_scene_edit(_approved_revision(), revision, checksum)
