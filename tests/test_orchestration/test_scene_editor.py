"""Unit tests for SceneIR revision editing (PRODUCT-06).

Covers the properties the viewer depends on:
- Every served revision has a published URI + checksum the client can bind.
- Edits produce a NEW revision; the previous one is never rewritten.
- A stale `expected_scene_revision` is rejected instead of silently overwriting.
- Quaternions entering canonical SceneIR are validated, not trusted.
"""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.scene import SceneIR, SceneObjectState, SourceCollisionRegion
from src.services.orchestration.artifacts import ArtifactResolver, with_canonical_checksum
from src.services.orchestration.scene import (
    SceneEditCommand,
    SceneEditor,
    SceneEditRejectedError,
    SceneObjectNotFoundError,
    SceneRevisionConflictError,
    TransformEdit,
)
from src.services.orchestration.scene.editor import scene_artifact_uri
from src.services.orchestration.scene.errors import ObjectGeometryNotReadyError
from src.services.orchestration.scene.objects import apply_object_action

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


@pytest.fixture
def draft_editor(tmp_path) -> SceneEditor:
    """Editor whose only revision is a Draft scene; rack and floor are candidates awaiting review."""
    scene = SceneIR.model_validate_json((_FIXTURE_ROOT / "scene_ir" / "scene.json").read_text(encoding="utf-8"))
    candidates = {"object-rack-001", "object-floor-001"}
    objects = [
        item.model_copy(update={"state": SceneObjectState.CANDIDATE}) if item.id in candidates else item
        for item in scene.objects
    ]
    draft = scene.model_copy(
        update={"objects": objects, "provenance": {**scene.provenance, "object_geometry": "awaiting_review"}}
    )
    root = tmp_path / "fixtures"
    (root / "scene_ir").mkdir(parents=True)
    (root / "scene_ir" / "scene.json").write_text(
        with_canonical_checksum(draft, "scene_ir_checksum").model_dump_json(), encoding="utf-8"
    )
    shutil.copytree(_FIXTURE_ROOT / "reconstruction_bundle", root / "reconstruction_bundle")
    return SceneEditor(root, ArtifactResolver(tmp_path / "artifacts"))


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


# ── restart recovery ─────────────────────────────────────────────────────────


def _restart(tmp_path) -> SceneEditor:
    """Editor mới trên cùng artifact root — mô phỏng tiến trình khởi động lại."""
    return SceneEditor(_FIXTURE_ROOT, ArtifactResolver(tmp_path / "artifacts"))


def _move_rack(from_revision: str, x: float) -> SceneEditCommand:
    return SceneEditCommand(
        expected_scene_revision=from_revision,
        edits=[TransformEdit(object_id="object-rack-001", translation_xyz=(x, x, 0.0))],
    )


def test_restart_recovers_latest_published_revision(tmp_path, move_pallet: SceneEditCommand) -> None:
    """Revision không được sống chỉ trong bộ nhớ: tiến trình mới phải thấy bản mới nhất."""
    first = _restart(tmp_path)
    first.apply(_JOB_ID, move_pallet)
    first.apply(_JOB_ID, _move_rack("rev-002", 5.0))
    assert _restart(tmp_path).current(_JOB_ID).scene.scene_revision == "rev-003"


def test_restart_then_edit_does_not_collide(tmp_path, move_pallet: SceneEditCommand) -> None:
    """Regression: sửa sau restart từng đụng `ArtifactAlreadyExistsError`.

    Tiến trình mới seed `rev-001`, tính ra `rev-002`, nhưng `rev-002` đã có trên đĩa
    với bytes khác — `_publish_once` re-raise và route trả 500.
    """
    _restart(tmp_path).apply(_JOB_ID, move_pallet)
    result = _restart(tmp_path).apply(_JOB_ID, _move_rack("rev-002", 7.0))
    assert result.revision.scene.scene_revision == "rev-003"


def test_restart_reports_same_reference_as_live_process(tmp_path, move_pallet: SceneEditCommand) -> None:
    """Hai đường (ghi mới / phục hồi) phải dựng ra ref giống hệt nhau."""
    live = _restart(tmp_path).apply(_JOB_ID, move_pallet).revision
    recovered = _restart(tmp_path).current(_JOB_ID)
    assert recovered.scene_reference == live.scene_reference
    assert recovered.scene.scene_ir_checksum == live.scene.scene_ir_checksum


def test_restart_recovers_supersedes_revision(tmp_path, move_pallet: SceneEditCommand) -> None:
    """`supersedes_revision` phục hồi từ `provenance["edited_from"]`."""
    _restart(tmp_path).apply(_JOB_ID, move_pallet)
    assert _restart(tmp_path).current(_JOB_ID).supersedes_revision == "rev-001"


def test_restart_falls_back_to_fixture_when_nothing_published(tmp_path) -> None:
    """Root sạch thì hành vi cũ giữ nguyên: seed `rev-001`."""
    revision = _restart(tmp_path).current(_JOB_ID)
    assert revision.scene.scene_revision == "rev-001"
    assert revision.supersedes_revision is None


def test_restart_rejects_inconsistent_revision(tmp_path, editor: SceneEditor) -> None:
    """Artifact bị sửa tay phải fail closed, không được phục vụ rồi lan cái sai đi."""
    path = editor.resolver.require(editor.current(_JOB_ID).scene_reference)
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["objects"][0]["transform"]["translation_xyz"] = [99.0, 99.0, 99.0]
    path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(SceneEditRejectedError, match="canonical content"):
        _restart(tmp_path).current(_JOB_ID)


def test_restart_rejects_revision_with_wrong_name(tmp_path, editor: SceneEditor) -> None:
    """File `rev-002` chứa document khai `rev-001` là artifact hỏng, không phải rev-002."""
    source = editor.resolver.require(editor.current(_JOB_ID).scene_reference)
    editor.resolver.resolve(scene_artifact_uri(_JOB_ID, "rev-002")).write_bytes(source.read_bytes())

    with pytest.raises(SceneEditRejectedError, match="scene_revision"):
        _restart(tmp_path).current(_JOB_ID)


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
    assert binding.available is False
    assert binding.unavailable_reason
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


def test_artifact_references_include_collision_source_and_selection(editor: SceneEditor) -> None:
    scene = editor.current(_JOB_ID).scene
    assert scene.environment.collider_ref is not None
    selection_ref = ProductArtifactRef.model_validate(
        {
            "artifact_type": "CollisionSourceSelection",
            "schema_version": "1.0",
            "artifact_uri": f"artifact://jobs/{_JOB_ID}/collision/selection.json",
            "artifact_checksum": "sha256:" + "a" * 64,
            "data_class": "derived",
            "producer_stage": "ST-CANDIDATE-BUILD",
            "job_id": _JOB_ID,
        }
    )
    environment = scene.environment.model_copy(
        update={
            "collision_source_ref": scene.environment.collider_ref,
            "collision_selection_ref": selection_ref,
        }
    )
    selected_scene = scene.model_copy(update={"environment": environment})

    references = SceneEditor.artifact_references(selected_scene)

    assert scene.environment.collider_ref in references
    assert selection_ref in references
    assert len(references) == len({reference.artifact_uri for reference in references})


def test_artifact_references_include_exact_object_collision_membership(editor: SceneEditor) -> None:
    scene = editor.current(_JOB_ID).scene
    item = scene.objects[0]
    membership_ref = ProductArtifactRef.model_validate(
        {
            "artifact_type": "SourceCollisionMembership",
            "schema_version": "1.0",
            "artifact_uri": f"artifact://jobs/{_JOB_ID}/collider/membership.json",
            "artifact_checksum": "sha256:" + "c" * 64,
            "data_class": "derived",
            "producer_stage": "ST-COLLIDER",
            "job_id": _JOB_ID,
        }
    )
    ownership = SourceCollisionRegion(
        object_id=item.id,
        source_geometry_ref=scene.environment.geometry_ref,
        extraction_revision=scene.scene_revision,
        source_transform=item.transform,
        region_kind="triangle_indices",
        region_ref=membership_ref,
    )
    selected_scene = scene.model_copy(
        update={"objects": [item.model_copy(update={"source_collision": ownership}), *scene.objects[1:]]},
        deep=True,
    )

    references = SceneEditor.artifact_references(selected_scene)

    assert membership_ref in references


def test_artifact_references_are_product_visible_only(editor: SceneEditor) -> None:
    scene = editor.current(_JOB_ID).scene
    for reference in SceneEditor.artifact_references(scene):
        assert reference.data_class in {"product_input", "derived"}


# ── revision dựng từ bundle (EX-SCENE, ADR 0006) ─────────────────────────────


def test_publish_initial_keeps_existing_revision(editor: SceneEditor) -> None:
    """Chạy lại bước tách vật thể không được ghi đè revision người dùng đã sửa."""
    scene = editor.current(_JOB_ID).scene
    first = editor.publish_initial(_JOB_ID, scene.model_copy(update={"objects": []}))
    assert first.scene.objects == scene.objects  # revision đã có (seed) được giữ nguyên


def test_publish_initial_requires_root_revision(tmp_path) -> None:
    editor = SceneEditor(tmp_path / "no-fixture", ArtifactResolver(tmp_path / "artifacts"))
    scene = SceneEditor(_FIXTURE_ROOT, ArtifactResolver(tmp_path / "seed")).current(_JOB_ID).scene
    with pytest.raises(SceneEditRejectedError):
        editor.publish_initial(_JOB_ID, scene.model_copy(update={"scene_revision": "rev-002"}))
    revision = editor.publish_initial(_JOB_ID, scene)
    assert revision.scene.scene_revision == "rev-001" and revision.supersedes_revision is None


def test_publish_next_bumps_revision_and_rejects_stale_client(editor: SceneEditor) -> None:
    scene = editor.current(_JOB_ID).scene
    result = editor.publish_next(_JOB_ID, "rev-001", scene.model_copy(update={"objects": []}), "reject_object")
    assert result.revision.scene.scene_revision == "rev-002"
    assert result.revision.supersedes_revision == "rev-001"
    assert result.revision.scene.provenance["operation"] == "reject_object"
    assert editor.current(_JOB_ID).scene.objects == []
    with pytest.raises(SceneRevisionConflictError):
        editor.publish_next(_JOB_ID, "rev-001", scene, "confirm_object")


def test_draft_scene_refuses_transform_and_keeps_the_revision(
    draft_editor: SceneEditor, move_pallet: SceneEditCommand
) -> None:
    with pytest.raises(ObjectGeometryNotReadyError, match="Cần tạo mesh trước khi di chuyển/xoay vật"):
        draft_editor.apply(_JOB_ID, move_pallet)
    assert draft_editor.current(_JOB_ID).scene.scene_revision == "rev-001"


def test_draft_scene_keeps_review_actions(draft_editor: SceneEditor) -> None:
    """Confirm, ignore, hide, delete, restore và đổi tên vẫn chạy trên scene chờ tách vật, và giữ trạng thái Draft."""
    steps = [
        ("object-pallet-001", "rename", {"name": "Pallet A"}),
        ("object-pallet-001", "hide", {"active": False}),
        ("object-pallet-001", "delete", {}),
        ("object-pallet-001", "restore", {}),
        ("object-rack-001", "confirm", {}),
        ("object-floor-001", "ignore", {}),
    ]
    revision = "rev-001"
    for object_id, action, options in steps:
        result = apply_object_action(draft_editor, _JOB_ID, object_id, action, revision, **options)
        revision = result.revision.scene.scene_revision
        assert result.revision.scene.provenance["object_geometry"] == "awaiting_review"
    assert revision == "rev-007"
