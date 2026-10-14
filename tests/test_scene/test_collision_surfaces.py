"""Source-bound planar repair and explicit floor/wall authoring regressions."""

import numpy as np
import pytest
from pydantic import ValidationError

from src.services.orchestration.scene.collision_surfaces import CollisionSurfaceCommand, edit_collision_surfaces
from src.services.orchestration.scene.errors import SceneEditRejectedError, SceneRevisionConflictError
from src.services.scene.collision_surfaces import CollisionSurfacePlane, patch_planar_holes
from src.services.scene.effective_collision import compose_effective_collision
from tests.test_scene.test_effective_collision import fixture


def grid(wall: bool = False):
    vertices = np.array([[0, x, y] if wall else [x, y, 0] for y in range(4) for x in range(4)], dtype=float)
    faces = []
    for y in range(3):
        for x in range(3):
            if (x, y) == (1, 1):
                continue
            a = y * 4 + x
            faces.extend([[a, a + 1, a + 5], [a, a + 5, a + 4]])
    return vertices, np.array(faces, dtype=np.int64)


@pytest.mark.parametrize("wall", [False, True])
def test_caps_only_the_marked_planar_hole_inside_the_source_region(wall: bool) -> None:
    vertices, faces = grid(wall)
    normal = np.array([1, 0, 0] if wall else [0, 0, 1], dtype=float)
    region = np.array([[0, 1, 1], [0, 2, 2]] if wall else [[1, 1, 0], [2, 2, 0]])
    patched, caps = patch_planar_holes(vertices, faces, [(normal, 0, 0.01)], [region])
    assert len(caps) == 2
    np.testing.assert_allclose(patched[caps] @ normal, 0)
    areas = (
        np.linalg.norm(
            np.cross(patched[caps[:, 1]] - patched[caps[:, 0]], patched[caps[:, 2]] - patched[caps[:, 0]]), axis=1
        )
        / 2
    )
    assert areas.sum() == pytest.approx(1)
    assert not patch_planar_holes(vertices, faces, [(normal, 0, 0.01)], [region + 10])[1].size
    assert not patch_planar_holes(vertices, faces, [], [region])[1].size
    # Even a broad object footprint cannot cap the entire outside scene boundary.
    broad = np.array([vertices.min(axis=0), vertices.max(axis=0)])
    assert len(patch_planar_holes(vertices, faces, [(normal, 0, 0.01)], [broad])[1]) == 2


def test_glb_duplicate_vertex_seams_do_not_hide_a_real_hole() -> None:
    vertices, faces = grid()
    split = vertices[faces].reshape(-1, 3)
    split_faces = np.arange(len(split)).reshape(-1, 3)
    patched, caps = patch_planar_holes(
        split, split_faces, [(np.array([0, 0, 1]), 0, 0.01)], [np.array([[1, 1, 0], [2, 2, 0]])]
    )
    assert len(caps) == 2


def test_nonplanar_hole_is_not_flattened_into_a_fake_floor() -> None:
    vertices, faces = grid()
    vertices[5, 2] = 0.3
    assert not patch_planar_holes(
        vertices, faces, [(np.array([0, 0, 1]), 0, 0.01)], [np.array([[1, 1, -0.1], [2, 2, 0.5]])]
    )[1].size


def test_annotation_is_revision_checked_source_bound_and_removable(tmp_path) -> None:
    scene, _, ref, _, _ = fixture(tmp_path)
    command = CollisionSurfaceCommand(
        expected_scene_revision=scene.scene_revision,
        source_checksum=ref.artifact_checksum,
        kind="floor",
        points=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
    )
    updated = edit_collision_surfaces(scene, command)
    assert not scene.provenance.get("collision_surface_planes")
    plane = updated.provenance["collision_surface_planes"][0]
    assert plane["kind"] == "floor"
    removed = edit_collision_surfaces(updated, command.model_copy(update={"action": "remove", "plane_id": plane["id"]}))
    assert removed.provenance["collision_surface_planes"] == []
    with pytest.raises(SceneRevisionConflictError):
        edit_collision_surfaces(scene, command.model_copy(update={"expected_scene_revision": "stale"}))
    with pytest.raises(SceneEditRejectedError):
        edit_collision_surfaces(scene, command.model_copy(update={"source_checksum": "sha256:" + "0" * 64}))
    with pytest.raises(ValidationError):
        CollisionSurfacePlane(
            id="bad", kind="floor", source_checksum=ref.artifact_checksum, points=((0, 0, 0), (0, 1, 0), (0, 0, 1))
        )


def test_preview_carves_pending_at_immutable_source_without_changing_export(tmp_path) -> None:
    from src.services.scene.editing.commands import ignore_object, move_object

    scene, compose, ref, payload, blobs = fixture(tmp_path)
    preview = compose_effective_collision(scene, ref, payload, lambda r: blobs[r.artifact_uri], preview_pending=True)
    assert preview.source_remove_mask[24:48].all()
    assert not preview.source_remove_mask[:24].any()
    assert not compose(scene).source_remove_mask.any()
    moved = move_object(scene, "A", scene.objects[0].transform.model_copy(update={"translation_xyz": (10, 5, 4)}))
    after = compose_effective_collision(moved, ref, payload, lambda r: blobs[r.artifact_uri], preview_pending=True)
    assert after.identity == preview.identity
    ignored = compose_effective_collision(
        ignore_object(moved, "A"), ref, payload, lambda r: blobs[r.artifact_uri], preview_pending=True
    )
    assert not ignored.source_remove_mask[24:36].any()
    assert ignored.source_remove_mask[36:48].all()


def test_noise_is_projected_to_the_marked_plane_with_closed_seams() -> None:
    vertices, faces = grid()
    vertices[5, 2] = 0.005
    original = vertices.copy()
    patched, caps = patch_planar_holes(
        vertices, faces, [(np.array([0, 0, 1]), 0, 0.01)], [np.array([[1, 1, -0.1], [2, 2, 0.1]])]
    )
    assert len(caps) == 4  # two planar faces and two triangles joining the noisy source corner
    np.testing.assert_array_equal(vertices, original)
    np.testing.assert_allclose(patched[len(vertices) :, 2], 0)
    assert np.isfinite(patched).all()


def test_plane_label_alone_does_not_make_an_unclosed_cut_safe(tmp_path) -> None:
    scene, _, ref, payload, blobs = fixture(tmp_path)
    # Include source-floor faces in an object's ownership: an explicit floor label keeps them.
    from tests.test_simulation.test_collision_edit_composition import _membership_ref, _owner

    owner, blob = _owner("A", ref, _membership_ref(ref.job_id, "floor-claim"), list(range(12)) + list(range(24, 36)))
    blobs[owner.region_ref.artifact_uri] = blob
    scene = scene.model_copy(
        update={"objects": [scene.objects[0].model_copy(update={"source_collision": owner}), scene.objects[1]]}
    )
    command = CollisionSurfaceCommand(
        expected_scene_revision=scene.scene_revision,
        source_checksum=ref.artifact_checksum,
        kind="floor",
        points=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
    )
    scene = edit_collision_surfaces(scene, command)
    from src.services.scene.collision_ownership import SourceCollisionOwnershipError

    # The label preserves a top face but does not repair the removed slab sides/bottom.
    # Previously this returned an open surface as if the repair had succeeded.
    with pytest.raises(SourceCollisionOwnershipError, match="UNREPAIRED_COLLISION_CUT"):
        compose_effective_collision(
            scene, ref, payload, lambda r: blobs[r.artifact_uri], preview_pending=True, repair_surfaces=True
        )


def test_floor_evidence_is_checksum_bound_and_not_silently_substituted(tmp_path) -> None:
    import hashlib

    from src.models.contracts.artifacts import ProductArtifactRef
    from src.models.contracts.floor_model import FloorFitEvidence
    from src.services.orchestration.scene.floor_evidence import scene_floor_fit_summary
    from src.services.scene.collision_ownership import SourceCollisionOwnershipError
    from tests.test_orchestration.test_floor_evidence import _floor_model

    scene, _, ref, payload, blobs = fixture(tmp_path)
    model = _floor_model()
    evidence = FloorFitEvidence(
        job_id=ref.job_id,
        source_artifact_ref=scene.environment.visual_master_ref or scene.environment.visual_ref,
        point_cloud_checksum=model.source_checksum,
        floor_model=model,
    )
    raw = evidence.model_dump_json().encode()
    digest = hashlib.sha256(raw).hexdigest()
    floor_ref = ProductArtifactRef(
        artifact_type="FloorFitEvidence",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{ref.job_id}/scene/floor-fit/{digest}.json",
        artifact_checksum=f"sha256:{digest}",
        data_class="derived",
        producer_stage="ST-OBJECT-EXTRACT",
        job_id=ref.job_id,
    )
    blobs[floor_ref.artifact_uri] = raw
    scene = scene.model_copy(
        update={"provenance": {**scene.provenance, "floor_fit": scene_floor_fit_summary(floor_ref, evidence)}}
    )
    import io

    import trimesh

    from src.services.scene.effective_collision import _floor_triangle_mask

    mesh = trimesh.load(io.BytesIO(payload), file_type="glb", force="mesh", process=False)
    mask, planes = _floor_triangle_mask(scene, ref, mesh.vertices, mesh.faces, lambda r: blobs[r.artifact_uri])
    assert mask.any() and planes
    # Valid plane evidence still cannot make nonplanar cuts safe by itself.
    with pytest.raises(SourceCollisionOwnershipError, match="UNREPAIRED_COLLISION_CUT"):
        compose_effective_collision(
            scene, ref, payload, lambda r: blobs[r.artifact_uri], preview_pending=True, repair_surfaces=True
        )
    blobs[floor_ref.artifact_uri] = b"corrupt"
    with pytest.raises(SourceCollisionOwnershipError, match="floor evidence checksum"):
        compose_effective_collision(
            scene, ref, payload, lambda r: blobs[r.artifact_uri], preview_pending=True, repair_surfaces=True
        )


def test_surface_command_publishes_an_undoable_revision(tmp_path) -> None:
    from src.services.orchestration.scene.collision_surfaces import publish_collision_surface
    from tests.test_orchestration.test_simulation_package import _scene_job

    registry, job = _scene_job(tmp_path)
    previous = registry.scene.current(job.job_id).scene
    ref = previous.environment.collision_source_ref or previous.environment.geometry_ref
    command = CollisionSurfaceCommand(
        expected_scene_revision=previous.scene_revision,
        source_checksum=ref.artifact_checksum,
        kind="wall",
        points=((0, 0, 0), (0, 1, 0), (0, 0, 1)),
    )
    result = publish_collision_surface(registry.scene, job.job_id, command)
    assert result.revision.scene.scene_revision != previous.scene_revision
    assert registry.scene.current(job.job_id).scene.provenance["collision_surface_planes"][0]["kind"] == "wall"
    assert (
        registry.scene.revision(job.job_id, previous.scene_revision).scene.provenance.get("collision_surface_planes")
        is None
    )


def test_explicit_authored_infill_handles_open_boundaries_on_the_requested_plane() -> None:
    from src.services.scene.collision_surfaces import authored_plane_infill

    vertices = np.array([[0, 0, 0], [3, 0, 0], [3, 3, 0]], dtype=float)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    plane = CollisionSurfacePlane(
        id="floor", kind="floor", source_checksum="sha256:" + "a" * 64, points=((0, 0, 0), (1, 0, 0), (0, 1, 0))
    )
    region = np.array([[1, 1, 0.5], [2, 2, 1.5]])
    assert not authored_plane_infill(vertices, faces, plane, [region])[1].size
    patched, caps = authored_plane_infill(vertices, faces, plane.model_copy(update={"fill_regions": True}), [region])
    assert len(caps) == 2
    np.testing.assert_allclose(patched[caps][:, :, 2], 0)
    assert (patched[caps][:, :, :2] >= 1).all() and (patched[caps][:, :, :2] <= 2).all()


def test_fill_flag_is_saved_and_remove_clears_it(tmp_path) -> None:
    scene, _, ref, _, _ = fixture(tmp_path)
    command = CollisionSurfaceCommand(
        expected_scene_revision=scene.scene_revision,
        source_checksum=ref.artifact_checksum,
        kind="floor",
        points=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
    )
    marked = edit_collision_surfaces(scene, command)
    plane = marked.provenance["collision_surface_planes"][0]
    assert plane["fill_regions"] is False
    filled = edit_collision_surfaces(marked, command.model_copy(update={"action": "fill", "plane_id": plane["id"]}))
    assert filled.provenance["collision_surface_planes"][0]["fill_regions"] is True
    removed = edit_collision_surfaces(filled, command.model_copy(update={"action": "remove", "plane_id": plane["id"]}))
    assert removed.provenance["collision_surface_planes"] == []


@pytest.mark.parametrize("tilt", [0.0, 0.4, 1.2])
def test_cut_boundary_defines_plane_without_surface_labels(tilt: float) -> None:
    from src.services.scene.collision_surfaces import require_closed_cuts

    vertices, kept = grid()
    # Reinsert the source cell, then cut it. Rotate the entire surface to an arbitrary plane.
    source = np.concatenate([kept, np.array([[5, 6, 10], [5, 10, 9]])])
    rotation = np.array([[1, 0, 0], [0, np.cos(tilt), -np.sin(tilt)], [0, np.sin(tilt), np.cos(tilt)]])
    vertices = vertices @ rotation.T + np.array([4, -2, 7])
    original = vertices.copy()
    region = np.array([vertices.min(axis=0), vertices.max(axis=0)])
    patched, caps = patch_planar_holes(vertices, kept, [], [region], source_faces=source)
    assert len(caps) == 2
    normal = rotation @ np.array([0, 0, 1])
    np.testing.assert_allclose((patched[caps] - vertices[0]) @ normal, 0, atol=1e-10)
    require_closed_cuts(patched, source, np.concatenate([kept, caps]))
    np.testing.assert_array_equal(vertices, original)


def test_automatic_repair_preserves_original_openings_even_inside_cut_footprint() -> None:
    from src.services.scene.collision_surfaces import require_closed_cuts

    vertices, faces = grid()
    region = np.array([vertices.min(axis=0), vertices.max(axis=0)])
    patched, caps = patch_planar_holes(vertices, faces, [], [region], source_faces=faces)
    assert not caps.size
    require_closed_cuts(patched, faces, faces)


def test_unrepairable_nonplanar_cut_is_rejected_instead_of_returned_as_safe() -> None:
    from src.services.scene.collision_ownership import SourceCollisionOwnershipError
    from src.services.scene.collision_surfaces import require_closed_cuts

    vertices, kept = grid()
    source = np.concatenate([kept, np.array([[5, 6, 10], [5, 10, 9]])])
    vertices[5, 2] = 0.3
    region = np.array([vertices.min(axis=0), vertices.max(axis=0)])
    patched, caps = patch_planar_holes(vertices, kept, [], [region], source_faces=source)
    assert not caps.size
    with pytest.raises(SourceCollisionOwnershipError, match="UNREPAIRED_COLLISION_CUT"):
        require_closed_cuts(patched, source, kept)


def test_preview_automatically_repairs_cut_at_source_pose_without_plane_metadata(tmp_path) -> None:
    import io

    import trimesh

    from src.services.scene.editing.commands import move_object
    from tests.test_simulation.test_collision_edit_composition import _membership_ref, _owner, _source_ref

    scene, _, initial_ref, _, _ = fixture(tmp_path)
    vertices, kept = grid()
    source = np.concatenate([kept, np.array([[5, 6, 10], [5, 10, 9]])])
    payload = trimesh.Trimesh(vertices, source, process=False).export(file_type="glb")
    ref = _source_ref(initial_ref.job_id, payload)
    owner, blob = _owner("A", ref, _membership_ref(initial_ref.job_id, "cut"), [len(kept), len(kept) + 1])
    scene = scene.model_copy(
        update={
            "objects": [scene.objects[0].model_copy(update={"source_collision": owner})],
            "environment": scene.environment.model_copy(update={"geometry_ref": ref}),
        }
    )
    result = compose_effective_collision(scene, ref, payload, lambda r: blob, preview_pending=True)
    assert result.carved_triangles == 2
    assert result.repaired_triangles == 2
    assert len(result.faces) == len(source)
    # A later pose edit must never move the environment repair to the edited object location.
    moved = move_object(scene, "A", scene.objects[0].transform.model_copy(update={"translation_xyz": (20, 10, 5)}))
    after = compose_effective_collision(moved, ref, payload, lambda r: blob, preview_pending=True)
    assert result.identity == after.identity
    np.testing.assert_array_equal(result.vertices, after.vertices)
    np.testing.assert_array_equal(result.faces, after.faces)
    original = trimesh.load(io.BytesIO(payload), file_type="glb", force="mesh", process=False)
    assert len(original.faces) == len(source)
