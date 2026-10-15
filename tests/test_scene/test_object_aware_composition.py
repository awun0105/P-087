"""Object-aware environment composition restores only source representations, never double carves."""

import hashlib
import io

import numpy as np
import pytest
import trimesh

from src.models.contracts.coordinates import Transform
from src.models.contracts.object_geometry import ObjectAwareEnvironmentManifest
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.scene import ColliderSpec, ColliderType
from src.services.scene.collision_ownership import SourceCollisionOwnershipError
from src.services.scene.editing.commands import confirm_object, ignore_object, move_object
from src.services.scene.effective_collision import compose_effective_collision
from tests.test_scene.test_effective_collision import fixture


def case(tmp_path, registry_job=None):
    scene, _, ref, source, blobs = fixture(tmp_path, registry_job=registry_job)
    blobs[ref.artifact_uri] = source

    def bound(payload, kind, name):
        item = ref.model_copy(
            update={
                "artifact_type": kind,
                "artifact_uri": f"artifact://jobs/{ref.job_id}/pr05/{name}",
                "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }
        )
        blobs[item.artifact_uri] = payload
        return item

    labels = np.array([-1, 0, 1], dtype="<i4").tobytes()
    members = ObjectMembershipArtifact(
        source_visual_ref=ref,
        source_geometry_ref=ref,
        extraction_revision=scene.scene_revision,
        coordinate_system=scene.coordinate_system,
        gaussian_count=3,
        labels_ref=bound(labels, "ObjectMembershipLabels", "labels.bin"),
        label_to_object_id={"0": "A", "1": "B"},
    )
    mesh = trimesh.load(io.BytesIO(source), file_type="glb", force="mesh", process=False)
    background = trimesh.Trimesh(mesh.vertices, mesh.faces[:24], process=False).export(file_type="glb")
    active = bound(background, "ObjectAwareEnvironmentCollision", "background.glb")
    manifest = ObjectAwareEnvironmentManifest(
        source_geometry_ref=ref,
        collision_ref=active,
        source_membership=members,
        removed_object_ids=["A", "B"],
        occupancy_checksum="sha256:" + "a" * 64,
        provenance={},
    )
    manifest_ref = bound(manifest.model_dump_json().encode(), "ObjectAwareEnvironmentManifest", "manifest.json")
    objects = []
    for item, dimensions, center in zip(scene.objects, [(1, 2, 3), (1, 1, 1)], [(0, 0, 1.5), (3, 0, 0.5)], strict=True):
        payload = trimesh.creation.box(extents=dimensions).export(file_type="glb")
        collider_ref = bound(payload, "ObjectCollider", f"{item.id}.glb")
        pose = Transform(
            parent_frame="world", local_frame=item.id, translation_xyz=center, rotation_quaternion_xyzw=(0, 0, 0, 1)
        )
        local = Transform(
            parent_frame=item.id,
            local_frame=item.id + "-collider",
            translation_xyz=(0, 0, 0),
            rotation_quaternion_xyzw=(0, 0, 0, 1),
        )
        objects.append(
            item.model_copy(
                update={
                    "local_frame": item.id,
                    "transform": pose,
                    "source_collision": item.source_collision.model_copy(update={"source_transform": pose}),
                    "geometry_ref": collider_ref,
                    "collider": ColliderSpec(
                        collider_id=item.id + "-collider",
                        collider_type=ColliderType.CONVEX_DECOMPOSITION,
                        geometry_ref=collider_ref,
                        local_transform=local,
                        parameters={},
                        provenance={},
                    ),
                }
            )
        )
    scene = scene.model_copy(
        update={
            "objects": objects,
            "environment": scene.environment.model_copy(
                update={"collider_ref": active, "membership": members, "object_aware_collision_ref": manifest_ref}
            ),
        }
    )
    scene = type(scene).model_validate(scene.model_dump())

    def compose(value, preview=False):
        return compose_effective_collision(value, ref, source, lambda r: blobs[r.artifact_uri], preview_pending=preview)

    return scene, compose, blobs


def test_pending_source_restoration_confirm_move_and_preview_do_not_double_carve(tmp_path):
    scene, compose, _ = case(tmp_path)
    formal = compose(scene)
    preview = compose(scene, True)
    assert len(formal.faces) == 48  # floor/wall plus both source colliders
    assert len(preview.faces) == 24  # preview puts Pending colliders in the independent object layer
    assert preview.carved_triangles == 0 and not preview.source_remove_mask.any()
    confirmed = confirm_object(scene, "A")
    before = compose(confirmed)
    assert len(before.faces) == 36
    moved = move_object(
        confirmed, "A", confirmed.objects[0].transform.model_copy(update={"translation_xyz": (10, 4, 2)})
    )
    after = compose(moved)
    assert after.identity == before.identity
    np.testing.assert_array_equal(after.vertices, before.vertices)
    assert len(compose(ignore_object(scene, "A"), True).faces) == 36
    # Formal Pending geometry remains at extraction pose, including after a temporary edit.
    pending_move = move_object(
        scene, "A", scene.objects[0].transform.model_copy(update={"translation_xyz": (15, 5, 2)})
    )
    assert compose(pending_move).identity == formal.identity


def test_stale_membership_or_corrupt_authored_geometry_cannot_fall_back_to_global_mesh(tmp_path):
    scene, compose, blobs = case(tmp_path)
    members = scene.environment.membership.model_copy(update={"label_to_object_id": {"0": "B", "1": "A"}})
    stale = scene.model_copy(update={"environment": scene.environment.model_copy(update={"membership": members})})
    with pytest.raises(SourceCollisionOwnershipError, match="stale"):
        compose(stale)
    active = scene.environment.collider_ref
    blobs[active.artifact_uri] = b"corrupt"
    with pytest.raises(SourceCollisionOwnershipError, match="checksum"):
        compose(scene)


def test_usd_enrichment_keeps_manifest_baseline_instead_of_reading_derived_layer(tmp_path):
    from src.models.contracts.identity import canonical_content_checksum
    from src.services.simulation.enrichment.service import enrich_scene_physics

    scene, compose, _ = case(tmp_path)
    baseline = compose(scene, True)
    scene = scene.model_copy(update={"scene_ir_checksum": canonical_content_checksum(scene, "scene_ir_checksum")})
    derived = scene.environment.collider_ref.model_copy(
        update={"artifact_type": "ColliderGeometry", "artifact_uri": "artifact://jobs/test/derived.usda"}
    )
    enriched = enrich_scene_physics(scene, environment_collider_ref=derived, add_ground_plane=False)
    assert enriched.environment.collider_ref == derived
    assert enriched.environment.object_aware_collision_ref == scene.environment.object_aware_collision_ref
    result = compose(enriched, True)
    assert result.identity == baseline.identity
    np.testing.assert_array_equal(result.vertices[result.faces], baseline.vertices[baseline.faces])


def test_source_restoration_composes_parent_and_offcenter_child_rotation_once(tmp_path):
    scene, compose, _ = case(tmp_path)
    item = scene.objects[0]
    root = Transform(
        parent_frame="world",
        local_frame="A",
        translation_xyz=(1, 2, 3),
        rotation_quaternion_xyzw=(0, 0, np.sqrt(0.5), np.sqrt(0.5)),
    )
    child = Transform(
        parent_frame="A",
        local_frame="A-collider",
        translation_xyz=(-2, 1, 0.5),
        rotation_quaternion_xyzw=(0, 0, np.sqrt(0.5), np.sqrt(0.5)),
    )
    item = item.model_copy(
        update={
            "transform": root,
            "source_collision": item.source_collision.model_copy(update={"source_transform": root}),
            "collider": item.collider.model_copy(update={"local_transform": child}),
        }
    )
    scene = scene.model_copy(update={"objects": [item, scene.objects[1]]})
    result = compose(scene)
    source_triangles = result.vertices[result.faces[24:36]]
    np.testing.assert_allclose(source_triangles.reshape(-1, 3).min(axis=0), [-0.5, -1, 2], atol=1e-6)
    np.testing.assert_allclose(source_triangles.reshape(-1, 3).max(axis=0), [0.5, 1, 5], atol=1e-6)
