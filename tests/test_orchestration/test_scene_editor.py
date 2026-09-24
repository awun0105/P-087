"""Unit tests for SceneIR revision editing (PRODUCT-06).

Covers the properties the viewer depends on:
- Every served revision has a published URI + checksum the client can bind.
- Edits produce a NEW revision; the previous one is never rewritten.
- A stale `expected_scene_revision` is rejected instead of silently overwriting.
- Quaternions entering canonical SceneIR are validated, not trusted.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.scene import SceneIR
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.scene import (
    SceneEditCommand,
    SceneEditor,
    SceneEditRejectedError,
    SceneObjectNotFoundError,
    SceneRevisionConflictError,
    TransformEdit,
)
from src.services.orchestration.scene.editor import scene_artifact_uri

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures"
_JOB_ID = "job-fixture-001"


@pytest.fixture
def editor(tmp_path) -> SceneEditor:
    """Editor ghi revision vào tmp_path, fixture vẫn chỉ đọc."""
    return SceneEditor(_FIXTURE_ROOT, ArtifactResolver(tmp_path / "artifacts"))


@pytest.fixture
def move_pallet() -> SceneEditCommand:
    return SceneEditCommand(
        expected_scene_revision="rev-001",
        edits=[TransformEdit(object_id="object-pallet-001", translation_xyz=(3.0, 2.0, 0.0))],
    )


# ── baseline revision ────────────────────────────────────────────────────────


def test_current_revision_is_published(editor: SceneEditor) -> None:
    revision = editor.current(_JOB_ID)
    assert revision.scene.scene_revision == "rev-001"
    assert revision.scene_reference.artifact_uri == scene_artifact_uri(_JOB_ID, "rev-001")
    assert revision.scene_reference.artifact_checksum.startswith("sha256:")
    assert revision.supersedes_revision is None


def test_published_revision_verifies_on_disk(editor: SceneEditor) -> None:
    """Ref phải đọc lại được và khớp byte hash đã công bố."""
    revision = editor.current(_JOB_ID)
    path = editor.resolver.require(revision.scene_reference)
    assert SceneIR.model_validate_json(path.read_text(encoding="utf-8")).scene_id == "scene-fixture-001"


def test_seeding_is_idempotent(tmp_path) -> None:
    """Hai editor cùng root không được ghi đè revision đã có."""
    root = tmp_path / "artifacts"
    first = SceneEditor(_FIXTURE_ROOT, ArtifactResolver(root)).current(_JOB_ID)
    second = SceneEditor(_FIXTURE_ROOT, ArtifactResolver(root)).current(_JOB_ID)
    assert first.scene_reference == second.scene_reference


def test_fixture_checksum_matches_canonical_content(editor: SceneEditor) -> None:
    """`scene_ir_checksum` là canonical content checksum, khớp fixture đã khoá."""
    scene = editor.current(_JOB_ID).scene
    assert scene.scene_ir_checksum.startswith("sha256:")
    assert SceneIR.model_validate(scene.model_dump()).scene_ir_checksum == scene.scene_ir_checksum


# ── edits produce a new revision ─────────────────────────────────────────────


def test_edit_bumps_revision_and_moves_object(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    result = editor.apply(_JOB_ID, move_pallet)
    assert result.previous_scene_revision == "rev-001"
    assert result.revision.scene.scene_revision == "rev-002"
    moved = next(item for item in result.revision.scene.objects if item.id == "object-pallet-001")
    assert moved.transform.translation_xyz == (3.0, 2.0, 0.0)


def test_edit_recomputes_scene_checksum(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    before = editor.current(_JOB_ID).scene.scene_ir_checksum
    after = editor.apply(_JOB_ID, move_pallet).revision.scene.scene_ir_checksum
    assert before != after, "nội dung đổi thì checksum canonical phải đổi"


def test_new_revision_is_readable_at_its_own_uri(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    revision = editor.apply(_JOB_ID, move_pallet).revision
    path = editor.resolver.require(revision.scene_reference)
    assert path.name == "scene_ir.rev-002.json"


def test_previous_revision_bytes_are_untouched(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    """Revision cũ là artifact bất biến — sửa xong nó vẫn còn nguyên."""
    before = editor.current(_JOB_ID)
    before_bytes = editor.resolver.require(before.scene_reference).read_bytes()
    editor.apply(_JOB_ID, move_pallet)
    assert editor.resolver.require(before.scene_reference).read_bytes() == before_bytes


def test_edit_records_provenance(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    scene = editor.apply(_JOB_ID, move_pallet).revision.scene
    assert scene.provenance["edited_from"] == "rev-001"
    assert scene.provenance["edited_objects"] == ["object-pallet-001"]


def test_edit_keeps_untouched_objects(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    scene = editor.apply(_JOB_ID, move_pallet).revision.scene
    rack = next(item for item in scene.objects if item.id == "object-rack-001")
    assert rack.transform.translation_xyz == (2.0, 1.0, 0.0)


def test_second_edit_chains_onto_first(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    editor.apply(_JOB_ID, move_pallet)
    rotated = SceneEditCommand(
        expected_scene_revision="rev-002",
        edits=[
            TransformEdit(
                object_id="object-rack-001", rotation_quaternion_xyzw=(0.0, 0.0, 0.7071067811865476, 0.7071067811865476)
            )
        ],
    )
    result = editor.apply(_JOB_ID, rotated)
    assert result.revision.scene.scene_revision == "rev-003"
    moved = next(item for item in result.revision.scene.objects if item.id == "object-pallet-001")
    assert moved.transform.translation_xyz == (3.0, 2.0, 0.0), "sửa lần hai không được nuốt thay đổi lần một"


# ── rejection paths ──────────────────────────────────────────────────────────


def test_stale_revision_is_rejected(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    """Hai client cùng sửa: client giữ revision cũ phải bị 409, không ghi đè."""
    editor.apply(_JOB_ID, move_pallet)
    with pytest.raises(SceneRevisionConflictError, match="rev-001"):
        editor.apply(_JOB_ID, move_pallet)


def test_stale_revision_does_not_advance_state(editor: SceneEditor, move_pallet: SceneEditCommand) -> None:
    editor.apply(_JOB_ID, move_pallet)
    with pytest.raises(SceneRevisionConflictError):
        editor.apply(_JOB_ID, move_pallet)
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-002"


def test_unknown_object_is_rejected(editor: SceneEditor) -> None:
    command = SceneEditCommand(
        expected_scene_revision="rev-001",
        edits=[TransformEdit(object_id="object-khong-ton-tai", translation_xyz=(1.0, 1.0, 1.0))],
    )
    with pytest.raises(SceneObjectNotFoundError):
        editor.apply(_JOB_ID, command)


def test_unknown_object_does_not_publish_a_revision(editor: SceneEditor) -> None:
    command = SceneEditCommand(
        expected_scene_revision="rev-001",
        edits=[TransformEdit(object_id="object-khong-ton-tai", translation_xyz=(1.0, 1.0, 1.0))],
    )
    with pytest.raises(SceneObjectNotFoundError):
        editor.apply(_JOB_ID, command)
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-001"


def test_non_normalized_quaternion_is_rejected(editor: SceneEditor) -> None:
    """Quaternion không chuẩn hoá là command bị từ chối, không phải lỗi server.

    Editor phải dịch `ValidationError` của contract thành `SceneEditRejectedError`
    để tầng trên map được sang 422 thay vì 500.
    """
    command = SceneEditCommand(
        expected_scene_revision="rev-001",
        edits=[TransformEdit(object_id="object-pallet-001", rotation_quaternion_xyzw=(0.0, 0.0, 0.5, 0.5))],
    )
    with pytest.raises(SceneEditRejectedError, match="normalized"):
        editor.apply(_JOB_ID, command)


def test_rejected_transform_does_not_publish_a_revision(editor: SceneEditor) -> None:
    command = SceneEditCommand(
        expected_scene_revision="rev-001",
        edits=[TransformEdit(object_id="object-pallet-001", rotation_quaternion_xyzw=(0.0, 0.0, 0.5, 0.5))],
    )
    with pytest.raises(SceneEditRejectedError):
        editor.apply(_JOB_ID, command)
    assert editor.current(_JOB_ID).scene.scene_revision == "rev-001"


def test_duplicate_object_targets_are_rejected() -> None:
    with pytest.raises(ValidationError, match="một lần"):
        SceneEditCommand(
            expected_scene_revision="rev-001",
            edits=[
                TransformEdit(object_id="object-pallet-001", translation_xyz=(1.0, 0.0, 0.0)),
                TransformEdit(object_id="object-pallet-001", translation_xyz=(2.0, 0.0, 0.0)),
            ],
        )


def test_empty_edit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TransformEdit(object_id="object-pallet-001")


def test_empty_command_is_rejected() -> None:
    with pytest.raises(ValidationError, match="ít nhất một"):
        SceneEditCommand(expected_scene_revision="rev-001", edits=[])


# ── visual binding and artifact refs ─────────────────────────────────────────


def test_visual_binding_denies_brush_proof(editor: SceneEditor) -> None:
    """Visual fixture là tổng hợp: cờ Brush phải là false để không bị đọc thành AC-11."""
    binding = editor.visual_binding()
    assert binding.available is True
    assert binding.format == "real2sim.synthetic.visual.v1"
    assert binding.brush_compatibility_proof is False


def test_visual_binding_carries_source_checksum(editor: SceneEditor) -> None:
    binding = editor.visual_binding()
    assert binding.source_input_checksum is not None
    assert binding.reference is not None
    assert binding.reference.artifact_uri.startswith("artifact://jobs/")


def test_artifact_references_cover_geometry_and_colliders(editor: SceneEditor) -> None:
    scene = editor.current(_JOB_ID).scene
    uris = [reference.artifact_uri for reference in SceneEditor.artifact_references(scene)]
    assert scene.environment.geometry_ref.artifact_uri in uris
    assert scene.environment.collider_ref.artifact_uri in uris
    assert len(uris) == len(set(uris)), "ref không được lặp"


def test_artifact_references_are_product_visible_only(editor: SceneEditor) -> None:
    scene = editor.current(_JOB_ID).scene
    for reference in SceneEditor.artifact_references(scene):
        assert reference.data_class in {"product_input", "derived"}
