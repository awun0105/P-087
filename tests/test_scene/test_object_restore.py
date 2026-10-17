"""Restoring a merge must conserve ownership and never discard later unrelated edits."""

from pathlib import Path

import pytest

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.object_membership import ObjectMembershipMergeCommand
from src.services.orchestration.scene.errors import SceneEditRejectedError, SceneRevisionConflictError
from src.services.orchestration.scene.object_correction import merge_object_candidates
from src.services.orchestration.scene.objects import apply_object_action
from tests.test_scene.test_object_correction import _JOB_ID, _command, _fake_collider_runner, _fixture


def _merged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN202
    fixture = _fixture(tmp_path)
    _fake_collider_runner(monkeypatch)
    result = merge_object_candidates(
        fixture.editor,
        _JOB_ID,
        _command(fixture, ["candidate-002"]),
        actor_id="reviewer",
        runtime_python=Path("/runtime/python"),
        workspace=tmp_path / "work",
        timeout_seconds=30,
    )
    return fixture, result.revision.scene


def test_restore_merge_keeps_later_unrelated_edit_and_original_source_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, merged = _merged(tmp_path, monkeypatch)
    refs = [fixture.membership.source_visual_ref, fixture.membership.labels_ref, fixture.scene.environment.geometry_ref]
    source_bytes = [fixture.editor.resolver.require(ref).read_bytes() for ref in refs]
    renamed = apply_object_action(
        fixture.editor, _JOB_ID, "candidate-003", "rename", merged.scene_revision, name="Giữ tên mới"
    ).revision.scene
    result = apply_object_action(fixture.editor, _JOB_ID, "candidate-002", "restore", renamed.scene_revision)
    restored = result.revision.scene
    assert restored.scene_revision == "rev-004"
    for object_id in ("candidate-001", "candidate-002"):
        assert next(item for item in restored.objects if item.id == object_id) == next(
            item for item in fixture.scene.objects if item.id == object_id
        )
    assert restored.objects[2].name == "Giữ tên mới"
    assert restored.environment.membership == fixture.membership
    assert source_bytes == [fixture.editor.resolver.require(ref).read_bytes() for ref in refs]
    verify_content_checksum(restored, "scene_ir_checksum")


def test_nested_merge_restore_unwinds_until_selected_object_is_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, merged = _merged(tmp_path, monkeypatch)
    command = ObjectMembershipMergeCommand(
        expected_scene_revision=merged.scene_revision,
        membership_checksum=merged.environment.membership.labels_ref.artifact_checksum,
        primary_object_id="candidate-001",
        secondary_object_ids=["candidate-003"],
        semantic_class_source_object_id="candidate-003",
    )
    second = merge_object_candidates(
        fixture.editor,
        _JOB_ID,
        command,
        actor_id="reviewer",
        runtime_python=Path("/runtime/python"),
        workspace=tmp_path / "work-2",
        timeout_seconds=30,
    ).revision.scene
    restored = apply_object_action(
        fixture.editor, _JOB_ID, "candidate-002", "restore", second.scene_revision
    ).revision.scene
    assert restored.objects == fixture.scene.objects
    assert restored.environment.membership == fixture.membership
    assert restored.provenance["restored_merge"]["before_revisions"] == ["rev-002", "rev-001"]


@pytest.mark.parametrize("change", ["name", "confirmation", "membership", "missing_history"])
def test_restore_merge_refuses_to_overwrite_changed_group_or_unknown_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    fixture, merged = _merged(tmp_path, monkeypatch)
    if change == "name":
        current = apply_object_action(
            fixture.editor, _JOB_ID, "candidate-001", "rename", merged.scene_revision, name="Đã chỉnh"
        ).revision.scene
    elif change == "confirmation":
        current = apply_object_action(
            fixture.editor, _JOB_ID, "candidate-001", "confirm", merged.scene_revision
        ).revision.scene
    else:
        if change == "membership":
            membership = merged.environment.membership.model_copy(
                update={
                    "labels_ref": merged.environment.membership.labels_ref.model_copy(
                        update={"artifact_checksum": "sha256:" + "f" * 64}
                    )
                }
            )
            draft = merged.model_copy(
                update={"environment": merged.environment.model_copy(update={"membership": membership})}
            )
        else:
            objects = [
                item.model_copy(update={"provenance": {**item.provenance, "merged_from_revision": "rev-missing"}})
                if item.id == "candidate-002"
                else item
                for item in merged.objects
            ]
            draft = merged.model_copy(update={"objects": objects})
        current = fixture.editor.publish_next(_JOB_ID, merged.scene_revision, draft, "test_changed").revision.scene
    before = fixture.editor.current(_JOB_ID)
    with pytest.raises(SceneEditRejectedError):
        apply_object_action(fixture.editor, _JOB_ID, "candidate-002", "restore", current.scene_revision)
    assert fixture.editor.current(_JOB_ID) == before


def test_restore_merge_requires_current_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, merged = _merged(tmp_path, monkeypatch)
    with pytest.raises(SceneRevisionConflictError):
        apply_object_action(fixture.editor, _JOB_ID, "candidate-002", "restore", fixture.scene.scene_revision)
    assert fixture.editor.current(_JOB_ID).scene == merged
