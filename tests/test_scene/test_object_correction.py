from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import ObjectMembershipArtifact, ObjectMembershipMergeCommand
from src.models.contracts.scene import (
    ColliderType,
    MassSource,
    ObjectPhysics,
    SceneIR,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
    SourceCollisionRegion,
)
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.orchestration.projects.registry import DEFAULT_FIXTURE_ROOT
from src.services.orchestration.review.simulation_package import _is_pending, _source_region_removed
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.errors import SceneEditRejectedError, SceneRevisionConflictError
from src.services.orchestration.scene.models import SceneEditCommand, TransformEdit
from src.services.orchestration.scene.object_correction import merge_object_candidates
from src.services.scene.decomposition import gaussian_split
from src.services.scene.editing.commands import confirm_object, restore_object
from src.services.scene.editing.membership import ObjectMembershipValidationError, encode_gaussian_membership_labels

_JOB_ID = "job-fixture-001"
_IDENTITY = (0.0, 0.0, 0.0, 1.0)


@dataclass(frozen=True)
class CorrectionFixture:
    editor: SceneEditor
    scene: SceneIR
    source_rows: np.ndarray
    source_labels: np.ndarray
    membership: ObjectMembershipArtifact


def _artifact_ref(artifact_type: str, payload: bytes, name: str) -> ProductArtifactRef:
    checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB_ID}/scene/object-correction/{checksum.removeprefix('sha256:')}/{name}",
        artifact_checksum=checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.SCENE_DECOMPOSE,
        job_id=_JOB_ID,
    )


def _source_rows() -> np.ndarray:
    rows = np.zeros(
        9,
        dtype=[
            ("x", "<f4"),
            ("y", "<f4"),
            ("z", "<f4"),
            ("opacity", "<f4"),
            ("scale_0", "<f4"),
            ("rot_0", "<f4"),
            ("f_dc_0", "<f4"),
        ],
    )
    rows["x"] = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 100.0]
    rows["y"] = [0.0, 0.1, 0.2, 0.0, 0.1, 0.2, 0.0, 0.1, 10.0]
    rows["z"] = [1.0, 1.1, 1.2, 1.0, 1.1, 1.2, 1.0, 1.1, 10.0]
    rows["opacity"] = 2.0
    rows["scale_0"] = np.log(0.05)
    rows["rot_0"] = 1.0
    rows["f_dc_0"] = np.arange(len(rows), dtype=np.float32)
    return rows


def _candidate(
    scene: SceneIR,
    object_id: str,
    translation: tuple[float, float, float],
    semantic_class: str,
    *,
    physics: ObjectPhysics | None = None,
) -> SceneObject:
    transform = Transform(
        parent_frame="world",
        local_frame=object_id,
        translation_xyz=translation,
        rotation_quaternion_xyzw=_IDENTITY,
    )
    return SceneObject(
        id=object_id,
        name=object_id,
        state=SceneObjectState.CANDIDATE,
        origin=SceneObjectOrigin.RECONSTRUCTED,
        active=False,
        local_frame=object_id,
        transform=transform,
        visual_ref=None,
        geometry_ref=scene.environment.geometry_ref,
        asset_ref=None,
        primitive_dimensions_xyz_m=(1.0, 0.5, 0.5),
        collider=None,
        semantic_class=semantic_class,
        tags=["objectify_v1"],
        provenance={"method": "objectify_test"},
        physics=physics,
        source_collision=SourceCollisionRegion(
            object_id=object_id,
            source_geometry_ref=scene.environment.geometry_ref,
            extraction_revision="rev-001",
            source_transform=transform,
            region_kind="source_obb",
            source_obb_dimensions_xyz_m=(1.5, 0.5, 0.5),
        ),
    )


def _fixture(tmp_path: Path) -> CorrectionFixture:
    scene = SceneIR.model_validate_json((DEFAULT_FIXTURE_ROOT / "scene_ir" / "scene.json").read_bytes())
    source_rows = _source_rows()
    source_labels = np.array([0, 0, 1, 1, 2, 2, 3, 3, -1], dtype=np.int32)
    mapping = {
        "0": "candidate-001",
        "1": "candidate-001",  # A prior merge may map several labels to the same object.
        "2": "candidate-002",
        "3": "candidate-003",
    }
    source_payload = gaussian_split.write_gaussian_ply(source_rows)
    labels_payload = encode_gaussian_membership_labels(
        source_labels,
        gaussian_count=len(source_rows),
        label_to_object_id=mapping,
    )
    source_visual_ref = _artifact_ref("GaussianPLY", source_payload, "source.ply")
    labels_ref = _artifact_ref("ObjectMembershipLabels", labels_payload, "labels.i32le")
    membership = ObjectMembershipArtifact(
        source_visual_ref=source_visual_ref,
        source_geometry_ref=scene.environment.geometry_ref,
        extraction_revision="rev-001",
        coordinate_system=CoordinateSystem(),
        gaussian_count=len(source_rows),
        labels_ref=labels_ref,
        label_to_object_id=mapping,
    )
    physics = ObjectPhysics(
        dynamic=True,
        mass_kg=18.0,
        mass_source=MassSource.USER,
        static_friction=0.8,
        dynamic_friction=0.6,
        restitution=0.1,
        provenance={"fixture": True},
    )
    candidates = [
        _candidate(scene, "candidate-001", (1.5, 0.1, 1.1), "pallet", physics=physics),
        _candidate(scene, "candidate-002", (4.5, 0.1, 1.1), "box"),
        _candidate(scene, "candidate-003", (6.5, 0.1, 1.1), "bin"),
    ]
    environment = scene.environment.model_copy(update={"membership": membership}, deep=True)
    scene = with_canonical_checksum(
        scene.model_copy(update={"environment": environment, "objects": candidates}, deep=True),
        "scene_ir_checksum",
    )

    editor = SceneEditor(DEFAULT_FIXTURE_ROOT, ArtifactResolver(tmp_path / "artifacts"))
    editor.store.publish(source_visual_ref, source_payload)
    editor.store.publish(labels_ref, labels_payload)
    editor.publish_initial(_JOB_ID, scene)
    return CorrectionFixture(editor, scene, source_rows, source_labels, membership)


def _command(
    fixture: CorrectionFixture,
    secondary_ids: list[str],
    *,
    semantic_source: str | None = "candidate-002",
) -> ObjectMembershipMergeCommand:
    return ObjectMembershipMergeCommand(
        expected_scene_revision=fixture.scene.scene_revision,
        membership_checksum=fixture.membership.labels_ref.artifact_checksum,
        primary_object_id="candidate-001",
        secondary_object_ids=secondary_ids,
        semantic_class_source_object_id=semantic_source,
    )


def _fake_collider_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    editor: SceneEditor | None = None,
    concurrent_edit: bool = False,
) -> list[np.ndarray]:
    captured: list[np.ndarray] = []

    def run(python, script, request, workspace, name, timeout, *, cancel_event=None):  # noqa: ANN001, ANN202
        item = request["objects"][0]
        rows = gaussian_split.read_gaussian_ply(Path(item["gaussians_ply"]).read_bytes())
        captured.append(rows)
        Path(item["output_glb"]).write_bytes(trimesh.creation.box().export(file_type="glb"))
        if concurrent_edit:
            assert editor is not None
            current = editor.current(_JOB_ID).scene
            changed = current.model_copy(update={"provenance": {**current.provenance, "concurrent_edit": True}})
            editor.publish_next(_JOB_ID, current.scene_revision, changed, "concurrent_edit")
        return {"objects": [{"id": item["id"], "parts": 1, "volume_m3": 2.5}]}

    monkeypatch.setattr("src.services.orchestration.scene.object_correction._run", run)
    return captured


@pytest.mark.parametrize("secondary_ids", [["candidate-002"], ["candidate-002", "candidate-003"]])
def test_merge_rebuilds_visual_collider_and_membership_without_loss_or_physics_carryover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, secondary_ids: list[str]
) -> None:
    fixture = _fixture(tmp_path)
    captured = _fake_collider_runner(monkeypatch)
    base_primary = next(item for item in fixture.scene.objects if item.id == "candidate-001")
    selected_ids = {"candidate-001", *secondary_ids}
    selected_labels = [
        int(label) for label, object_id in fixture.membership.label_to_object_id.items() if object_id in selected_ids
    ]
    selected_rows = np.isin(fixture.source_labels, selected_labels)

    result = merge_object_candidates(
        fixture.editor,
        _JOB_ID,
        _command(fixture, secondary_ids),
        actor_id="reviewer-001",
        runtime_python=Path("/runtime/python"),
        workspace=tmp_path / "worker",
        timeout_seconds=30,
    )

    scene = result.revision.scene
    assert scene.scene_revision == "rev-002"
    objects = {item.id: item for item in scene.objects}
    primary = objects["candidate-001"]
    assert primary.state == SceneObjectState.CANDIDATE and primary.semantic_class == "box"
    assert primary.physics is None
    assert primary.provenance["physics_reconfirmation_required"] is True
    assert primary.source_collision == base_primary.source_collision
    assert primary.visual_ref is not None and primary.visual_ref.artifact_type == "ObjectGaussians"
    assert primary.geometry_ref == primary.collider.geometry_ref
    assert primary.collider is not None and primary.collider.collider_type == ColliderType.CONVEX_DECOMPOSITION
    assert primary.primitive_dimensions_xyz_m == pytest.approx((float(selected_rows.sum() - 1), 0.2, 0.2))
    assert len(captured) == 1 and len(captured[0]) == int(selected_rows.sum())

    visual_rows = gaussian_split.read_gaussian_ply(fixture.editor.resolver.require(primary.visual_ref).read_bytes())
    expected_world = gaussian_split.positions(fixture.source_rows[selected_rows])
    observed_world = gaussian_split.positions(visual_rows) + np.asarray(primary.transform.translation_xyz)
    np.testing.assert_allclose(observed_world, expected_world, atol=2e-8)
    for field in fixture.source_rows.dtype.names or ():
        if field not in {"x", "y", "z"}:
            np.testing.assert_array_equal(visual_rows[field], fixture.source_rows[selected_rows][field])

    union_center = (expected_world.min(axis=0) + expected_world.max(axis=0)) / 2
    collider_rows = captured[0]
    collider_world = (
        gaussian_split.positions(collider_rows)
        + np.asarray(primary.transform.translation_xyz)
        + np.asarray(primary.collider.local_transform.translation_xyz)
    )
    np.testing.assert_allclose(collider_world, expected_world, atol=2e-8)
    np.testing.assert_allclose(
        primary.collider.local_transform.translation_xyz,
        union_center - np.asarray(base_primary.transform.translation_xyz),
    )

    for object_id in secondary_ids:
        tombstone = objects[object_id]
        original = next(item for item in fixture.scene.objects if item.id == object_id)
        assert tombstone.active is False
        assert tombstone.provenance["review"] == "MERGED"
        assert tombstone.provenance["merged_into"] == primary.id
        assert tombstone.source_collision == original.source_collision
    assert all(scene.environment.membership.label_to_object_id[str(label)] == primary.id for label in selected_labels)
    assert scene.environment.membership.labels_ref == fixture.membership.labels_ref
    assert scene.provenance["membership_correction"]["actor_id"] == "reviewer-001"
    assert primary.visual_ref in fixture.editor.artifact_references(scene)
    assert primary.geometry_ref in fixture.editor.artifact_references(scene)
    assert fixture.editor.revision(_JOB_ID, "rev-001").scene == fixture.scene

    with pytest.raises(ValueError, match="audit tombstone"):
        restore_object(scene, secondary_ids[0])
    with pytest.raises(ValueError, match="audit tombstone"):
        confirm_object(scene, secondary_ids[0])
    with pytest.raises(SceneEditRejectedError, match="audit tombstone"):
        fixture.editor.apply(
            _JOB_ID,
            SceneEditCommand(
                expected_scene_revision="rev-002",
                edits=[TransformEdit(object_id=secondary_ids[0], translation_xyz=(0.0, 0.0, 0.0))],
            ),
        )


def test_merge_rejects_semantic_conflict_without_an_explicit_source(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(ObjectMembershipValidationError, match="conflicting semantic classes"):
        merge_object_candidates(
            fixture.editor,
            _JOB_ID,
            _command(fixture, ["candidate-002"], semantic_source=None),
            actor_id="reviewer-001",
            runtime_python=Path("/runtime/python"),
            workspace=tmp_path / "worker",
            timeout_seconds=30,
        )

    with pytest.raises(ValidationError, match="one of the merged objects"):
        _command(fixture, ["candidate-002"], semantic_source="candidate-003")


def test_artifact_publication_failure_does_not_advance_scene_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    _fake_collider_runner(monkeypatch)
    original_publish = fixture.editor.store.publish

    def fail_collider(reference, payload):  # noqa: ANN001, ANN202
        if reference.artifact_type == "ObjectCollider":
            raise ArtifactStoreError("injected collider publication failure")
        return original_publish(reference, payload)

    monkeypatch.setattr(fixture.editor.store, "publish", fail_collider)
    with pytest.raises(ArtifactStoreError, match="injected collider"):
        merge_object_candidates(
            fixture.editor,
            _JOB_ID,
            _command(fixture, ["candidate-002"]),
            actor_id="reviewer-001",
            runtime_python=Path("/runtime/python"),
            workspace=tmp_path / "worker",
            timeout_seconds=30,
        )
    assert fixture.editor.current(_JOB_ID).scene.scene_revision == "rev-001"
    assert fixture.editor.current(_JOB_ID).scene.objects == fixture.scene.objects


def test_stale_user_revision_after_rebuild_cannot_commit_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path)
    _fake_collider_runner(monkeypatch, editor=fixture.editor, concurrent_edit=True)

    with pytest.raises(SceneRevisionConflictError):
        merge_object_candidates(
            fixture.editor,
            _JOB_ID,
            _command(fixture, ["candidate-002"]),
            actor_id="reviewer-001",
            runtime_python=Path("/runtime/python"),
            workspace=tmp_path / "worker",
            timeout_seconds=30,
        )
    current = fixture.editor.current(_JOB_ID).scene
    assert current.scene_revision == "rev-002"
    assert current.provenance["concurrent_edit"] is True
    assert current.environment.membership.label_to_object_id == fixture.membership.label_to_object_id
    assert all(item.provenance.get("review") != "MERGED" for item in current.objects)


def test_source_collision_region_for_merged_tombstone_follows_primary_review_state() -> None:
    scene = SceneIR.model_validate_json((DEFAULT_FIXTURE_ROOT / "scene_ir" / "scene.json").read_bytes())
    primary_source, secondary_source = scene.objects[:2]
    primary = primary_source.model_copy(
        update={"state": SceneObjectState.CANDIDATE, "active": False, "provenance": {}}, deep=True
    )
    secondary = secondary_source.model_copy(
        update={
            "state": SceneObjectState.CANDIDATE,
            "active": False,
            "provenance": {"review": "MERGED", "merged_into": primary.id},
        },
        deep=True,
    )
    objects = {primary.id: primary, secondary.id: secondary}
    assert _is_pending(secondary) is False
    assert _source_region_removed(secondary, objects) is False

    confirmed = primary.model_copy(
        update={"state": SceneObjectState.CONFIRMED, "provenance": {"review": "CONFIRMED"}}, deep=True
    )
    assert _source_region_removed(secondary, {confirmed.id: confirmed, secondary.id: secondary}) is True

    ignored = primary.model_copy(update={"provenance": {"review": "IGNORED"}}, deep=True)
    assert _source_region_removed(secondary, {ignored.id: ignored, secondary.id: secondary}) is False

    malformed = secondary.model_copy(update={"provenance": {"review": "MERGED", "merged_into": "missing"}})
    assert _source_region_removed(malformed, {malformed.id: malformed}) is False
