"""PR-03: exact source triangles survive review and object pose edits consistently."""

import io
from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.services.scene.collision_ownership import SourceCollisionOwnershipError
from src.services.scene.editing.commands import (
    confirm_object,
    delete_object,
    duplicate_object,
    ignore_object,
    move_object,
    restore_object,
)
from src.services.scene.effective_collision import compose_effective_collision
from tests.test_orchestration.test_simulation_package import _scene_job
from tests.test_simulation.test_collision_edit_composition import _membership_ref, _owner, _source_ref


def fixture(tmp_path: Path):
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    # Disjoint floor, wall, A and B; face order is explicit and sealed by the source checksum.
    meshes = [trimesh.creation.box(extents=size) for size in [(8, 8, 0.02), (0.1, 8, 3), (1, 2, 3), (1, 1, 1)]]
    for mesh, offset in zip(meshes, [(0, 0, -0.01), (-4, 0, 1.5), (0, 0, 1.5), (3, 0, 0.5)], strict=True):
        mesh.apply_translation(offset)
    payload = trimesh.util.concatenate(meshes).export(file_type="glb")
    ref = _source_ref(job.job_id, payload)
    blobs = {}
    objects = []
    for id_, indices in [("A", list(range(24, 36))), ("B", list(range(36, 48)))]:
        owner, blob = _owner(id_, ref, _membership_ref(job.job_id, id_), indices)
        blobs[owner.region_ref.artifact_uri] = blob
        objects.append(scene.objects[0].model_copy(update={"id": id_, "source_collision": owner}, deep=True))
    scene = scene.model_copy(
        update={"objects": objects, "environment": scene.environment.model_copy(update={"geometry_ref": ref})},
        deep=True,
    )

    def compose(value):
        return compose_effective_collision(value, ref, payload, lambda r: blobs[r.artifact_uri])

    return scene, compose, ref, payload, blobs


def test_floor_wall_other_object_and_lifecycle_masks(tmp_path: Path) -> None:
    scene, compose, *_ = fixture(tmp_path)
    original = compose(scene)
    assert not original.source_remove_mask.any()
    assert not compose(ignore_object(scene, "A")).source_remove_mask.any()
    confirmed = confirm_object(scene, "A")
    expected = np.zeros(48, dtype=bool)
    expected[24:36] = True
    actual = compose(confirmed)
    np.testing.assert_array_equal(actual.source_remove_mask, expected)
    moved = move_object(
        confirmed,
        "A",
        confirmed.objects[0].transform.model_copy(
            update={"translation_xyz": (9, 7, 6), "rotation_quaternion_xyzw": (0, 0, 1, 0)}
        ),
    )
    for value in [
        moved,
        delete_object(moved, "A"),
        restore_object(delete_object(moved, "A"), "A"),
        duplicate_object(moved, "A", "copy", (5, 0, 0)),
    ]:
        result = compose(value)
        assert result.identity == actual.identity
        np.testing.assert_array_equal(result.source_remove_mask, expected)
        np.testing.assert_array_equal(result.vertices[result.faces], actual.vertices[actual.faces])
    inactive = moved.model_copy(
        update={"objects": [moved.objects[0].model_copy(update={"active": False}), moved.objects[1]]}
    )
    assert compose(inactive).identity == actual.identity
    restored_pending = restore_object(delete_object(scene, "A"), "A")
    assert compose(restored_pending).identity == original.identity


def test_overlap_keeps_shared_faces_and_merge_uses_target_disposition(tmp_path: Path) -> None:
    scene, compose, ref, payload, blobs = fixture(tmp_path)
    b_owner, b_blob = _owner("B", ref, _membership_ref(ref.job_id, "B"), [24, *range(36, 48)])
    blobs[b_owner.region_ref.artifact_uri] = b_blob
    overlap = scene.model_copy(
        update={"objects": [scene.objects[0], scene.objects[1].model_copy(update={"source_collision": b_owner})]}
    )
    carved = compose(confirm_object(overlap, "A"))
    assert not carved.source_remove_mask[24] and carved.retained_shared_triangles == 1
    scene = overlap
    merged = confirm_object(scene, "A")
    merged = merged.model_copy(
        update={
            "objects": [
                merged.objects[0],
                merged.objects[1].model_copy(update={"provenance": {"review": "MERGED", "merged_into": "A"}}),
            ]
        }
    )
    result = compose_effective_collision(merged, ref, payload, lambda r: blobs[r.artifact_uri])
    assert result.source_remove_mask[24:48].all()
    assert result.carved_triangles == 24


@pytest.mark.parametrize("fault", ["missing", "stale", "corrupt"])
def test_ownership_failures_block_instead_of_guessing(tmp_path: Path, fault: str) -> None:
    scene, compose, ref, _, blobs = fixture(tmp_path)
    scene = confirm_object(scene, "A")
    a = scene.objects[0]
    if fault == "missing":
        a = a.model_copy(update={"source_collision": None})
    elif fault == "stale":
        a = a.model_copy(
            update={
                "source_collision": a.source_collision.model_copy(
                    update={"source_geometry_ref": ref.model_copy(update={"artifact_checksum": "sha256:" + "0" * 64})}
                )
            }
        )
    else:
        blobs[a.source_collision.region_ref.artifact_uri] = b"corrupt"
    with pytest.raises(SourceCollisionOwnershipError):
        compose(scene.model_copy(update={"objects": [a, scene.objects[1]]}))


def test_studio_walk_usd_share_geometry_revision_and_identity(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException

    from src.api.product import artifacts
    from src.services.orchestration.projects.registry import ProjectRegistry
    from src.services.orchestration.review.simulation_package import _carved_environment
    from src.services.orchestration.scene.errors import SceneRevisionConflictError
    from src.services.orchestration.scene.physics_collision import effective_collision_for_revision

    scene, compose, ref, payload, blobs = fixture(tmp_path)
    scene = confirm_object(scene, "A")
    registry, _ = _scene_job(tmp_path / "api")
    source = tmp_path / "source.glb"
    source.write_bytes(payload)

    def require(reference):
        value = payload if reference == ref else blobs[reference.artifact_uri]
        return SimpleNamespace(read_bytes=lambda: value)

    monkeypatch.setattr(registry.runtime_resolver, "require", require)
    monkeypatch.setattr(registry.runtime_resolver, "locate", lambda uri: None)
    monkeypatch.setattr(registry.scene, "current", lambda job_id: SimpleNamespace(scene=scene))
    monkeypatch.setattr(ProjectRegistry, "resolve_artifact", lambda self, job_id, reference: source)
    monkeypatch.setattr(registry, "get_job", lambda job_id: SimpleNamespace(config_checksum="sha256:" + "0" * 64))
    monkeypatch.setattr(artifacts.deps, "registry", lambda: registry)
    monkeypatch.setattr(artifacts.deps, "job_or_404", lambda job_id: None)
    args = dict(
        job_id=ref.job_id,
        filename="collision.glb",
        artifact_uri=ref.artifact_uri,
        artifact_checksum=ref.artifact_checksum,
        dynamic=[],
        scene_revision=scene.scene_revision,
    )
    studio = artifacts.get_walk_collision(**args, frame="canonical")
    walk = artifacts.get_walk_collision(**args, frame="display")
    usd = _carved_environment(registry, scene)
    assert (
        studio.headers["x-collision-composition"]
        == walk.headers["x-collision-composition"]
        == usd.identity
        == compose(scene).identity
    )
    assert studio.headers["x-scene-revision"] == scene.scene_revision
    assert "no-cache" in studio.headers["cache-control"]
    canonical = trimesh.load(io.BytesIO(studio.body), file_type="glb", force="mesh", process=False)
    display = trimesh.load(io.BytesIO(walk.body), file_type="glb", force="mesh", process=False)
    np.testing.assert_allclose(canonical.vertices[canonical.faces], usd.vertices[usd.faces])
    np.testing.assert_allclose(
        display.vertices[display.faces], canonical.vertices[canonical.faces][..., [0, 2, 1]] * [1, 1, -1]
    )
    before = usd.identity
    scene = move_object(scene, "A", scene.objects[0].transform.model_copy(update={"translation_xyz": (10, 5, 4)}))
    assert _carved_environment(registry, scene).identity == before
    with pytest.raises(SceneRevisionConflictError):
        effective_collision_for_revision(registry, ref.job_id, "rev-stale")
    with pytest.raises(HTTPException) as exc:
        artifacts.get_walk_collision(**{**args, "scene_revision": "rev-stale"}, frame="display")
    assert exc.value.status_code == 409
    assert source.read_bytes() == payload
