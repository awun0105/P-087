from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import (
    ObjectMembershipArtifact,
    ObjectMembershipMergeCommand,
    ObjectMembershipReassignCommand,
    SourceGaussianROI,
)
from src.models.contracts.scene import (
    ColliderType,
    MassSource,
    ObjectPhysics,
    SceneIR,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
    SourceCollisionMembership,
    SourceCollisionRegion,
)
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.orchestration.projects.registry import DEFAULT_FIXTURE_ROOT
from src.services.orchestration.review.simulation_package import (
    _carved_environment,
    _is_pending,
    _source_region_removed,
)
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.errors import SceneEditRejectedError, SceneRevisionConflictError
from src.services.orchestration.scene.models import SceneEditCommand, TransformEdit
from src.services.orchestration.scene.object_correction import merge_object_candidates, reassign_object_membership
from src.services.process_control import ProcessCancelledError
from src.services.scene.collision_ownership import SourceCollisionOwnershipError, source_triangle_ownership
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


def _fixture(
    tmp_path: Path,
    *,
    source_rows: np.ndarray | None = None,
    source_labels: np.ndarray | None = None,
) -> CorrectionFixture:
    scene = SceneIR.model_validate_json((DEFAULT_FIXTURE_ROOT / "scene_ir" / "scene.json").read_bytes())
    floor = trimesh.creation.box(extents=(12.0, 12.0, 0.02))
    floor.apply_translation((3.5, 0.0, -0.01))
    collision_boxes = []
    for center in ((1.5, 0.1, 1.1), (4.5, 0.1, 1.1), (6.5, 0.1, 1.1)):
        box = trimesh.creation.box(extents=(1.5, 0.5, 0.5))
        box.apply_translation(center)
        collision_boxes.append(box)
    unowned_box = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    unowned_box.apply_translation((9.0, 0.0, 1.0))
    collision_boxes.append(unowned_box)
    geometry_payload = trimesh.util.concatenate([floor, *collision_boxes]).export(file_type="glb")
    geometry_ref = _artifact_ref("CanonicalGeometry", geometry_payload, "environment.glb")
    scene = scene.model_copy(
        update={"environment": scene.environment.model_copy(update={"geometry_ref": geometry_ref}, deep=True)},
        deep=True,
    )
    source_rows = _source_rows() if source_rows is None else source_rows
    source_labels = np.array([0, 0, 1, 1, 2, 2, 3, 3, -1], dtype=np.int32) if source_labels is None else source_labels
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
        source_geometry_ref=geometry_ref,
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
    editor.store.publish(geometry_ref, geometry_payload)
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


def _reassign_command(
    fixture: CorrectionFixture,
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    source_object_id: str | None,
    target_object_id: str | None,
) -> ObjectMembershipReassignCommand:
    return ObjectMembershipReassignCommand(
        expected_scene_revision=fixture.scene.scene_revision,
        membership_checksum=fixture.membership.labels_ref.artifact_checksum,
        region=SourceGaussianROI(min_xyz_m=bounds[0], max_xyz_m=bounds[1]),
        source_object_id=source_object_id,
        target_object_id=target_object_id,
    )


def _fake_reassign_runtimes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    editor: SceneEditor | None = None,
    concurrent_edit: bool = False,
) -> None:
    def publish_concurrent_edit() -> None:
        if not concurrent_edit:
            return
        assert editor is not None
        current = editor.current(_JOB_ID).scene
        changed = current.model_copy(update={"provenance": {**current.provenance, "concurrent_edit": True}})
        editor.publish_next(_JOB_ID, current.scene_revision, changed, "concurrent_edit")

    def run(python, script, request, workspace, name, timeout, *, cancel_event=None):  # noqa: ANN001, ANN202
        if "background_ply" in request:
            output = Path(request["output_ply"])
            output.write_bytes(Path(request["background_ply"]).read_bytes())
            publish_concurrent_edit()
            return {"method": "fixture-copy", "inpainted_gaussians": 0}
        records = []
        for item in request.get("objects", []):
            Path(item["output_glb"]).write_bytes(trimesh.creation.box().export(file_type="glb"))
            records.append({"id": item["id"], "parts": 1, "volume_m3": 1.0})
        return {"objects": records}

    def package(source_ply, workspace, gpu_index=None, *, cancel_event=None):  # noqa: ANN001
        workspace.mkdir(parents=True, exist_ok=True)
        output = workspace / "scene.sog"
        output.write_bytes(b"fixture-sog:" + Path(source_ply).read_bytes()[:32])
        return output

    monkeypatch.setattr("src.services.orchestration.scene.object_correction._run", run)
    monkeypatch.setattr("src.services.orchestration.scene.object_correction.package_splat", package)


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
    collision_bytes = fixture.editor.resolver.require(fixture.scene.environment.geometry_ref).read_bytes()
    collision_before = source_triangle_ownership(
        fixture.scene.objects,
        fixture.scene.environment.geometry_ref,
        collision_bytes,
        lambda reference: fixture.editor.resolver.require(reference).read_bytes(),
    )
    collision_labels_by_id = {object_id: int(label) for label, object_id in collision_before.label_to_object_id.items()}
    collision_source_labels = [collision_labels_by_id[object_id] for object_id in selected_ids]
    expected_collision_indices = np.flatnonzero(
        np.isin(collision_before.owner_labels, collision_source_labels)
    ).tolist()

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
    assert primary.source_collision is not None and base_primary.source_collision is not None
    assert primary.source_collision.source_geometry_ref == fixture.scene.environment.geometry_ref
    assert primary.source_collision.region_kind == "triangle_indices"
    assert primary.source_collision.region_ref is not None
    primary_collision_membership = SourceCollisionMembership.model_validate_json(
        fixture.editor.resolver.require(primary.source_collision.region_ref).read_bytes()
    )
    assert primary_collision_membership.triangle_indices == expected_collision_indices
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
        assert tombstone.active is False
        assert tombstone.provenance["review"] == "MERGED"
        assert tombstone.provenance["merged_into"] == primary.id
        assert tombstone.source_collision is not None and tombstone.source_collision.region_ref is not None
        tombstone_membership = SourceCollisionMembership.model_validate_json(
            fixture.editor.resolver.require(tombstone.source_collision.region_ref).read_bytes()
        )
        assert tombstone.source_collision.source_geometry_ref == fixture.scene.environment.geometry_ref
        assert tombstone_membership.triangle_indices == []
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
    with pytest.raises(SourceCollisionOwnershipError, match="merged ownership target is missing"):
        _source_region_removed(malformed, {malformed.id: malformed})


def test_reassign_object_to_object_preserves_rows_and_rebuilds_visual_collision_and_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    _fake_reassign_runtimes(monkeypatch)
    result = reassign_object_membership(
        fixture.editor,
        _JOB_ID,
        _reassign_command(fixture, ((0.75, -3.0, 0.0), (1.9, 3.0, 1.35)), "candidate-001", "candidate-002"),
        actor_id="reviewer-001",
        runtime_python=Path("/runtime/python"),
        workspace=tmp_path / "reassign-worker",
        timeout_seconds=30,
        view_requests=[{"image_path": "frame.png"}],
        lama_checkpoint=None,
    )

    scene = result.revision.scene
    manifest = scene.environment.membership
    assert manifest is not None
    updated_labels = np.frombuffer(fixture.editor.resolver.require(manifest.labels_ref).read_bytes(), dtype="<i4")
    assert len(updated_labels) == len(fixture.source_rows)
    low = np.asarray((0.75, -3.0, 0.0))
    high = np.asarray((1.9, 3.0, 1.35))
    positions = gaussian_split.positions(fixture.source_rows)
    selected = np.all((positions >= low) & (positions <= high), axis=1) & np.isin(
        fixture.source_labels,
        [
            int(label)
            for label, object_id in fixture.membership.label_to_object_id.items()
            if object_id == "candidate-001"
        ],
    )
    expected_labels = fixture.source_labels.copy()
    expected_labels[selected] = min(
        int(label) for label, object_id in fixture.membership.label_to_object_id.items() if object_id == "candidate-002"
    )
    np.testing.assert_array_equal(updated_labels, expected_labels)
    owner_ids = np.full(len(updated_labels), None, dtype=object)
    for label, object_id in manifest.label_to_object_id.items():
        owner_ids[updated_labels == int(label)] = object_id
    assert np.count_nonzero(owner_ids == "candidate-001") == 3
    assert np.count_nonzero(owner_ids == "candidate-002") == 3
    assert np.count_nonzero(owner_ids == "candidate-003") == 2
    assert np.count_nonzero(updated_labels == -1) == 1

    objects = {item.id: item for item in scene.objects}
    source = objects["candidate-001"]
    target = objects["candidate-002"]
    assert source.visual_ref is not None and target.visual_ref is not None
    assert source.physics is None and target.physics is None
    assert source.provenance["membership_reassign_blocker"] == "TOO_FEW_GAUSSIANS"
    assert target.provenance["membership_reassign_blocker"] == "TOO_FEW_GAUSSIANS"
    assert len(gaussian_split.read_gaussian_ply(fixture.editor.resolver.require(source.visual_ref).read_bytes())) == 3
    assert len(gaussian_split.read_gaussian_ply(fixture.editor.resolver.require(target.visual_ref).read_bytes())) == 3
    assert scene.environment.visual_master_ref is not None and scene.environment.visual_ref is not None
    assert (
        len(
            gaussian_split.read_gaussian_ply(
                fixture.editor.resolver.require(scene.environment.visual_master_ref).read_bytes()
            )
        )
        == 1
    )
    assert fixture.editor.resolver.require(scene.environment.visual_ref).read_bytes().startswith(b"fixture-sog:")

    source_region = source.source_collision
    target_region = target.source_collision
    assert source_region is not None and source_region.region_kind == "triangle_indices"
    assert target_region is not None and target_region.region_kind == "triangle_indices"
    assert source_region.region_ref is not None and target_region.region_ref is not None
    source_membership = fixture.editor.resolver.require(source_region.region_ref).read_bytes()
    target_membership = fixture.editor.resolver.require(target_region.region_ref).read_bytes()
    assert source_membership and target_membership
    with pytest.raises(ValueError, match="TOO_FEW_GAUSSIANS"):
        confirm_object(scene, target.id)

    snapshot = source_triangle_ownership(
        scene.objects,
        manifest.source_geometry_ref,
        fixture.editor.resolver.require(manifest.source_geometry_ref).read_bytes(),
        lambda reference: fixture.editor.resolver.require(reference).read_bytes(),
    )
    roi_floor = np.all(
        (snapshot.centroids >= np.array((0.75, -3.0, 0.0))) & (snapshot.centroids <= np.array((1.9, 3.0, 1.35))),
        axis=1,
    ) & (snapshot.centroids[:, 2] <= 0.04)
    assert scene.provenance["membership_correction"]["collision_triangles"] > 0
    assert scene.provenance["membership_correction"]["floor_triangles_preserved"] > 0
    assert np.all(snapshot.owner_labels[roi_floor] == -1)

    target_indices = SourceCollisionMembership.model_validate_json(
        fixture.editor.resolver.require(target_region.region_ref).read_bytes()
    ).triangle_indices
    confirmed_target = target.model_copy(
        update={"state": SceneObjectState.CONFIRMED, "active": True, "provenance": {"review": "CONFIRMED"}},
        deep=True,
    )
    confirmed_scene = scene.model_copy(
        update={
            "objects": [confirmed_target if item.id == target.id else item for item in scene.objects],
        },
        deep=True,
    )
    carved = _carved_environment(SimpleNamespace(runtime_resolver=fixture.editor.resolver), confirmed_scene)
    assert carved.carved_triangles == len(target_indices)
    assert np.any(np.isclose(carved.vertices[:, 2], 0.0))


def test_reassign_full_object_to_background_keeps_a_blocked_audit_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    _fake_reassign_runtimes(monkeypatch)
    result = reassign_object_membership(
        fixture.editor,
        _JOB_ID,
        _reassign_command(fixture, ((-0.1, -3.0, 0.0), (3.1, 3.0, 1.35)), "candidate-001", None),
        actor_id="reviewer-001",
        runtime_python=Path("/runtime/python"),
        workspace=tmp_path / "reassign-worker",
        timeout_seconds=30,
        view_requests=[{"image_path": "frame.png"}],
        lama_checkpoint=None,
    )

    scene = result.revision.scene
    empty = next(item for item in scene.objects if item.id == "candidate-001")
    assert empty.state == SceneObjectState.CANDIDATE
    assert empty.active is False
    assert empty.visual_ref is None and empty.collider is None and empty.primitive_dimensions_xyz_m is None
    assert empty.provenance["membership_reassign_blocker"] == "NO_SOURCE_GAUSSIANS"
    assert empty.source_collision is not None and empty.source_collision.region_ref is not None
    sidecar = SourceCollisionMembership.model_validate_json(
        fixture.editor.resolver.require(empty.source_collision.region_ref).read_bytes()
    )
    assert sidecar.triangle_indices == []
    assert scene.environment.visual_master_ref is not None
    background_rows = gaussian_split.read_gaussian_ply(
        fixture.editor.resolver.require(scene.environment.visual_master_ref).read_bytes()
    )
    assert len(background_rows) == 5
    with pytest.raises(ValueError, match="NO_SOURCE_GAUSSIANS"):
        confirm_object(scene, empty.id)


def test_reassign_background_to_object_claims_only_unowned_non_floor_triangles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_rows = np.concatenate((_source_rows(), _source_rows()[-1:].copy()))
    source_rows[-1]["x"], source_rows[-1]["y"], source_rows[-1]["z"] = 9.0, 0.0, 1.0
    source_labels = np.array([0, 0, 1, 1, 2, 2, 3, 3, -1, -1], dtype=np.int32)
    fixture = _fixture(tmp_path, source_rows=source_rows, source_labels=source_labels)
    _fake_reassign_runtimes(monkeypatch)
    result = reassign_object_membership(
        fixture.editor,
        _JOB_ID,
        _reassign_command(fixture, ((8.4, -0.6, 0.4), (9.6, 0.6, 1.6)), None, "candidate-002"),
        actor_id="reviewer-001",
        runtime_python=Path("/runtime/python"),
        workspace=tmp_path / "reassign-worker",
        timeout_seconds=30,
        view_requests=[{"image_path": "frame.png"}],
        lama_checkpoint=None,
    )

    scene = result.revision.scene
    manifest = scene.environment.membership
    assert manifest is not None
    labels = np.frombuffer(fixture.editor.resolver.require(manifest.labels_ref).read_bytes(), dtype="<i4")
    target_labels = [int(label) for label, owner in manifest.label_to_object_id.items() if owner == "candidate-002"]
    assert np.count_nonzero(np.isin(labels, target_labels)) == 3
    target = next(item for item in scene.objects if item.id == "candidate-002")
    assert target.source_collision is not None and target.source_collision.region_ref is not None
    target_membership = SourceCollisionMembership.model_validate_json(
        fixture.editor.resolver.require(target.source_collision.region_ref).read_bytes()
    )
    assert len(target_membership.triangle_indices) > 12
    assert scene.provenance["membership_correction"]["collision_triangles"] > 0


def test_reassign_rejects_empty_or_stale_inputs_without_advancing_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    _fake_reassign_runtimes(monkeypatch)
    command = _reassign_command(
        fixture,
        ((20.0, 20.0, 20.0), (21.0, 21.0, 21.0)),
        "candidate-001",
        "candidate-002",
    )
    with pytest.raises(ObjectMembershipValidationError, match="contains no Gaussian rows"):
        reassign_object_membership(
            fixture.editor,
            _JOB_ID,
            command,
            actor_id="reviewer-001",
            runtime_python=Path("/runtime/python"),
            workspace=tmp_path / "empty-worker",
            timeout_seconds=30,
            view_requests=[{"image_path": "frame.png"}],
            lama_checkpoint=None,
        )
    with pytest.raises(ValidationError):
        SourceGaussianROI(min_xyz_m=(0.0, 0.0, 0.0), max_xyz_m=(1_000_001.0, 1.0, 1.0))
    stale = command.model_copy(update={"expected_scene_revision": "rev-000"})
    with pytest.raises(ObjectMembershipValidationError, match="targets rev-000"):
        reassign_object_membership(
            fixture.editor,
            _JOB_ID,
            stale,
            actor_id="reviewer-001",
            runtime_python=Path("/runtime/python"),
            workspace=tmp_path / "stale-worker",
            timeout_seconds=30,
            view_requests=[{"image_path": "frame.png"}],
            lama_checkpoint=None,
        )
    assert fixture.editor.current(_JOB_ID).scene.scene_revision == fixture.scene.scene_revision


def test_reassign_checks_artifact_bytes_and_stale_publication_cannot_replace_another_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    label_path = fixture.editor.resolver.require(fixture.membership.labels_ref)
    label_path.write_bytes(label_path.read_bytes() + b"corrupt")
    command = _reassign_command(
        fixture,
        ((0.75, -3.0, 0.0), (2.25, 3.0, 1.35)),
        "candidate-001",
        "candidate-002",
    )
    with pytest.raises((ArtifactStoreError, ObjectMembershipValidationError)):
        reassign_object_membership(
            fixture.editor,
            _JOB_ID,
            command,
            actor_id="reviewer-001",
            runtime_python=Path("/runtime/python"),
            workspace=tmp_path / "corrupt-worker",
            timeout_seconds=30,
            view_requests=[{"image_path": "frame.png"}],
            lama_checkpoint=None,
        )
    assert fixture.editor.current(_JOB_ID).scene.scene_revision == fixture.scene.scene_revision

    fixture = _fixture(tmp_path / "stale")
    _fake_reassign_runtimes(monkeypatch, editor=fixture.editor, concurrent_edit=True)
    with pytest.raises(SceneRevisionConflictError):
        reassign_object_membership(
            fixture.editor,
            _JOB_ID,
            _reassign_command(fixture, ((0.75, -3.0, 0.0), (1.9, 3.0, 1.35)), "candidate-001", "candidate-002"),
            actor_id="reviewer-001",
            runtime_python=Path("/runtime/python"),
            workspace=tmp_path / "stale-publication-worker",
            timeout_seconds=30,
            view_requests=[{"image_path": "frame.png"}],
            lama_checkpoint=None,
        )
    current = fixture.editor.current(_JOB_ID).scene
    assert current.provenance["concurrent_edit"] is True
    assert current.environment.membership is not None
    assert current.environment.membership.labels_ref == fixture.membership.labels_ref


def test_reassign_stops_when_cancelled_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path)
    _fake_reassign_runtimes(monkeypatch)
    cancel = Event()
    cancel.set()
    with pytest.raises(ProcessCancelledError, match="cancelled"):
        reassign_object_membership(
            fixture.editor,
            _JOB_ID,
            _reassign_command(fixture, ((0.75, -3.0, 0.0), (1.9, 3.0, 1.35)), "candidate-001", "candidate-002"),
            actor_id="reviewer-001",
            runtime_python=Path("/runtime/python"),
            workspace=tmp_path / "cancelled-worker",
            timeout_seconds=30,
            view_requests=[{"image_path": "frame.png"}],
            lama_checkpoint=None,
            cancel_event=cancel,
        )
    assert fixture.editor.current(_JOB_ID).scene.scene_revision == fixture.scene.scene_revision
