"""AUD-01 source ownership contracts and current collision-edit regressions."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import (
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
    SourceCollisionMembership,
    SourceCollisionRegion,
)
from src.services.orchestration.review import simulation_package
from src.services.orchestration.review.simulation_package import (
    _carved_environment,
    _environment_layer,
    _hybrid_layers,
    _package_build_config,
)
from src.services.scene.collision_ownership import (
    SourceCollisionOwnershipError,
    read_triangle_memberships,
)
from src.services.scene.editing.commands import (
    confirm_object,
    delete_object,
    duplicate_object,
    ignore_object,
    move_object,
    restore_object,
)
from src.services.simulation.colliders.carve import CarveBox, triangle_mask_in_box
from src.services.simulation.usd.capabilities import EffectiveExportMode
from tests.test_orchestration.test_simulation_package import _scene_job


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source_ref(job_id: str, payload: bytes) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type="CanonicalGeometry",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec05/collision.glb",
        artifact_checksum=_sha256(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )


def _owner(
    object_id: str,
    source_ref: ProductArtifactRef,
    region_ref: ProductArtifactRef,
    indices: list[int],
    extraction_revision: str = "rev-001",
) -> tuple[SourceCollisionRegion, bytes]:
    sidecar = SourceCollisionMembership(
        object_id=object_id,
        source_geometry_ref=source_ref,
        extraction_revision=extraction_revision,
        triangle_indices=indices,
    )
    payload = sidecar.model_dump_json(indent=2).encode("utf-8") + b"\n"
    reference = region_ref.model_copy(update={"artifact_checksum": _sha256(payload)})
    owner = SourceCollisionRegion(
        object_id=object_id,
        source_geometry_ref=source_ref,
        extraction_revision=extraction_revision,
        source_transform=Transform(
            parent_frame="world",
            local_frame=object_id,
            translation_xyz=(1.0, 2.0, 0.3),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        region_kind="triangle_indices",
        region_ref=reference,
    )
    return owner, payload


def _membership_ref(job_id: str, object_id: str) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type="SourceCollisionMembership",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/scene/source_regions/{object_id}.json",
        artifact_checksum="sha256:" + "0" * 64,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.OBJECT_EXTRACT,
        job_id=job_id,
    )


def test_source_membership_consumer_checks_both_byte_refs_and_triangle_bounds() -> None:
    source_bytes = b"fixture-source-collision-mesh"
    source_ref = _source_ref("job-ownership-001", source_bytes)
    owner, sidecar_bytes = _owner("pallet", source_ref, _membership_ref(source_ref.job_id or "", "pallet"), [0, 2])
    resolved = {owner.region_ref.artifact_uri: sidecar_bytes}

    result = read_triangle_memberships([owner], source_bytes, 3, lambda reference: resolved[reference.artifact_uri])

    assert result == {"pallet": (0, 2)}

    with pytest.raises(KeyError):
        read_triangle_memberships([owner], source_bytes, 3, lambda reference: {}[reference.artifact_uri])

    with pytest.raises(SourceCollisionOwnershipError, match="source collision bytes"):
        read_triangle_memberships(
            [owner], source_bytes + b"changed", 3, lambda reference: resolved[reference.artifact_uri]
        )

    with pytest.raises(SourceCollisionOwnershipError, match="outside source mesh bounds"):
        out_of_bounds, payload = _owner("pallet", source_ref, _membership_ref(source_ref.job_id or "", "pallet"), [3])
        resolved[out_of_bounds.region_ref.artifact_uri] = payload
        read_triangle_memberships([out_of_bounds], source_bytes, 3, lambda reference: resolved[reference.artifact_uri])


def test_membership_sidecar_byte_checksum_and_source_geometry_identity_are_enforced() -> None:
    source_bytes = b"fixture-source-collision-mesh"
    source_ref = _source_ref("job-ownership-002", source_bytes)
    owner, sidecar_bytes = _owner("pallet", source_ref, _membership_ref(source_ref.job_id or "", "pallet"), [1])
    resolved = {owner.region_ref.artifact_uri: sidecar_bytes}
    tampered = b" " + sidecar_bytes

    with pytest.raises(SourceCollisionOwnershipError, match="sidecar byte checksum"):
        read_triangle_memberships([owner], source_bytes, 3, lambda reference: tampered)

    different_source_ref = source_ref.model_copy(update={"artifact_checksum": "sha256:" + "1" * 64})
    mismatched_sidecar = SourceCollisionMembership(
        object_id="pallet",
        source_geometry_ref=different_source_ref,
        extraction_revision="rev-001",
        triangle_indices=[1],
    )
    mismatched_payload = mismatched_sidecar.model_dump_json(indent=2).encode("utf-8") + b"\n"
    mismatched_ref = _membership_ref(source_ref.job_id or "", "pallet").model_copy(
        update={"artifact_checksum": _sha256(mismatched_payload)}
    )
    mismatched = SourceCollisionRegion(
        object_id="pallet",
        source_geometry_ref=source_ref,
        extraction_revision="rev-001",
        source_transform=Transform(
            parent_frame="world",
            local_frame="pallet",
            translation_xyz=(1.0, 2.0, 0.3),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        region_kind="triangle_indices",
        region_ref=mismatched_ref,
    )
    resolved[mismatched.region_ref.artifact_uri] = mismatched_payload
    with pytest.raises(SourceCollisionOwnershipError, match="source geometry ref"):
        read_triangle_memberships([mismatched], source_bytes, 3, lambda reference: resolved[reference.artifact_uri])


def test_overlapping_exact_membership_is_rejected() -> None:
    source_bytes = b"fixture-source-collision-mesh"
    source_ref = _source_ref("job-ownership-003", source_bytes)
    first, first_payload = _owner("pallet", source_ref, _membership_ref(source_ref.job_id or "", "pallet"), [0, 1])
    second, second_payload = _owner("rack", source_ref, _membership_ref(source_ref.job_id or "", "rack"), [1, 2])
    resolved = {first.region_ref.artifact_uri: first_payload, second.region_ref.artifact_uri: second_payload}

    with pytest.raises(SourceCollisionOwnershipError, match="claimed by both pallet and rack"):
        read_triangle_memberships([first, second], source_bytes, 3, lambda reference: resolved[reference.artifact_uri])


def test_duplicate_object_ownership_records_are_rejected_before_resolution() -> None:
    source_bytes = b"fixture-source-collision-mesh"
    source_ref = _source_ref("job-ownership-duplicate", source_bytes)
    first, _ = _owner("pallet", source_ref, _membership_ref(source_ref.job_id or "", "pallet"), [0])
    second, _ = _owner("pallet", source_ref, _membership_ref(source_ref.job_id or "", "pallet"), [1])

    with pytest.raises(SourceCollisionOwnershipError, match="duplicate object ids"):
        read_triangle_memberships([first, second], source_bytes, 3, lambda _: b"")


def test_triangle_membership_requires_region_ref_and_obb_requires_positive_dimensions() -> None:
    source_bytes = b"fixture-source-collision-mesh"
    source_ref = _source_ref("job-ownership-004", source_bytes)
    base = {
        "object_id": "pallet",
        "source_geometry_ref": source_ref.model_dump(mode="json"),
        "extraction_revision": "rev-001",
        "source_transform": Transform(
            parent_frame="world",
            local_frame="pallet",
            translation_xyz=(1.0, 2.0, 0.3),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ).model_dump(mode="json"),
        "region_kind": "triangle_indices",
    }

    with pytest.raises(ValidationError, match="SourceCollisionMembership region_ref"):
        SourceCollisionRegion.model_validate(base)

    obb = {**base, "region_kind": "source_obb", "source_obb_dimensions_xyz_m": [1.0, 0.0, 0.5]}
    with pytest.raises(ValidationError, match="source_obb_dimensions_xyz_m"):
        SourceCollisionRegion.model_validate(obb)


@pytest.mark.parametrize("indices", [[-1], [1, 1], [2, 1], []])
def test_membership_indices_must_be_nonnegative_unique_sorted_and_nonempty(indices: list[int]) -> None:
    source_ref = _source_ref("job-ownership-invalid", b"fixture-source-collision-mesh")

    with pytest.raises(ValidationError):
        SourceCollisionMembership(
            object_id="pallet",
            source_geometry_ref=source_ref,
            extraction_revision="rev-001",
            triangle_indices=indices,
        )


def test_source_pose_stays_immutable_through_move_delete_and_restore(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    (pallet,) = scene.objects
    ownership = pallet.source_collision
    assert ownership is not None

    confirmed = confirm_object(scene, pallet.id)
    moved = move_object(
        confirmed,
        pallet.id,
        pallet.transform.model_copy(update={"translation_xyz": (4.0, 0.5, 0.3)}),
    )
    deleted = delete_object(moved, pallet.id)
    restored = restore_object(deleted, pallet.id)
    duplicated = duplicate_object(confirmed, pallet.id, "pallet-copy", (2.0, 0.0, 0.0))

    assert moved.objects[0].transform.translation_xyz != ownership.source_transform.translation_xyz
    assert moved.objects[0].source_collision == ownership
    assert deleted.objects[0].source_collision == ownership
    assert restored.objects[0].source_collision == ownership
    assert duplicated.objects[-1].source_collision is None


def test_source_owned_background_stays_at_source_pose_through_edits_and_keeps_floor(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    pallet = scene.objects[0]
    ownership = pallet.source_collision
    assert ownership is not None

    original = _carved_environment(registry, scene)
    confirmed = confirm_object(scene, pallet.id)
    confirmed_background = _carved_environment(registry, confirmed)
    moved = move_object(
        confirmed,
        pallet.id,
        pallet.transform.model_copy(update={"translation_xyz": (4.0, 0.5, 0.3)}),
    )
    moved_background = _carved_environment(registry, moved)
    deleted = delete_object(moved, pallet.id)
    deleted_background = _carved_environment(registry, deleted)
    restored = restore_object(deleted, pallet.id)
    restored_background = _carved_environment(registry, restored)
    ignored = ignore_object(scene, pallet.id)
    ignored_background = _carved_environment(registry, ignored)
    deleted_candidate = delete_object(scene, pallet.id)
    deleted_candidate_background = _carved_environment(registry, deleted_candidate)
    hidden_confirmed = confirmed.model_copy(
        update={"objects": [confirmed.objects[0].model_copy(update={"active": False}, deep=True)]}, deep=True
    )
    hidden_background = _carved_environment(registry, hidden_confirmed)
    duplicated = duplicate_object(confirmed, pallet.id, "pallet-copy", (2.0, 0.0, 0.0))
    duplicated_background = _carved_environment(registry, duplicated)

    assert original.carved_triangles == ignored_background.carved_triangles == 0
    assert len(original.faces) == len(ignored_background.faces)
    assert confirmed_background.carved_triangles > 0
    assert confirmed_background.carved_triangles == moved_background.carved_triangles
    assert moved_background.carved_triangles == deleted_background.carved_triangles
    assert deleted_background.carved_triangles == restored_background.carved_triangles
    assert restored_background.carved_triangles == hidden_background.carved_triangles
    assert duplicated_background.identity == confirmed_background.identity
    assert confirmed_background.identity == moved_background.identity
    assert moved_background.identity == deleted_background.identity == restored_background.identity
    assert deleted_candidate_background.carved_triangles > 0

    floor_centroids = restored_background.vertices[restored_background.faces].mean(axis=1)
    assert len(restored_background.faces) == 12
    assert np.all(np.abs(floor_centroids[:, 0]) <= 4.0)
    assert np.all(np.abs(floor_centroids[:, 1]) <= 4.0)
    assert np.all(np.abs(floor_centroids[:, 2]) <= 0.02)
    assert restored.objects[0].transform.translation_xyz == (4.0, 0.5, 0.3)
    assert pallet.source_collision == ownership
    assert pallet.transform == ownership.source_transform


def test_source_owned_background_does_not_carve_user_added_boxes_and_rejects_overlap(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    pallet = scene.objects[0]
    confirmed = confirm_object(scene, pallet.id)
    confirmed_background = _carved_environment(registry, confirmed)

    user_transform = pallet.transform.model_copy(
        update={"local_frame": "user-added", "translation_xyz": pallet.transform.translation_xyz}
    )
    user_added = SceneObject.model_validate(
        {
            **pallet.model_dump(mode="json"),
            "id": "user-added",
            "origin": SceneObjectOrigin.USER_ADDED,
            "state": SceneObjectState.CONFIRMED,
            "active": True,
            "local_frame": "user-added",
            "transform": user_transform.model_dump(mode="json"),
            "collider": None,
            "source_collision": None,
        }
    )
    user_scene = scene.model_copy(update={"objects": [user_added]}, deep=True)
    user_background = _carved_environment(registry, user_scene)

    overlap_transform = pallet.transform.model_copy(update={"local_frame": "overlap"})
    overlap_ownership = pallet.source_collision.model_copy(
        update={"object_id": "overlap", "source_transform": overlap_transform}, deep=True
    )
    overlap = SceneObject.model_validate(
        {
            **pallet.model_dump(mode="json"),
            "id": "overlap",
            "state": SceneObjectState.CONFIRMED,
            "active": True,
            "local_frame": "overlap",
            "transform": overlap_transform.model_dump(mode="json"),
            "collider": None,
            "source_collision": overlap_ownership.model_dump(mode="json"),
        }
    )
    overlap_scene = scene.model_copy(update={"objects": [confirmed.objects[0], overlap]}, deep=True)
    with pytest.raises(SourceCollisionOwnershipError, match="claimed by both"):
        _carved_environment(registry, overlap_scene)

    assert confirmed_background.carved_triangles > 0
    assert user_background.carved_triangles == 0


def test_reconstructed_legacy_object_without_ownership_blocks_background_rebuild(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    pallet = scene.objects[0]
    legacy = scene.model_copy(
        update={"objects": [pallet.model_copy(update={"source_collision": None}, deep=True)]}, deep=True
    )
    confirmed = confirm_object(legacy, pallet.id)

    with pytest.raises(SourceCollisionOwnershipError, match="require source collision ownership"):
        _carved_environment(registry, confirmed)

    assert registry.runtime_resolver.require(scene.environment.geometry_ref).is_file()


def test_exact_membership_sidecar_is_consumed_by_background_builder(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    pallet = scene.objects[0]
    ownership = pallet.source_collision
    assert ownership is not None and ownership.source_obb_dimensions_xyz_m is not None
    glb = registry.runtime_resolver.require(scene.environment.geometry_ref).read_bytes()
    mesh = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh", process=False)
    centroids = np.asarray(mesh.vertices)[np.asarray(mesh.faces)].mean(axis=1)
    box = CarveBox.from_transform(ownership.source_transform, ownership.source_obb_dimensions_xyz_m)
    source_indices = np.flatnonzero(triangle_mask_in_box(centroids, box, 0.05))
    assert len(source_indices) > 0

    membership = SourceCollisionMembership(
        object_id=pallet.id,
        source_geometry_ref=scene.environment.geometry_ref,
        extraction_revision=ownership.extraction_revision,
        triangle_indices=[int(source_indices[0])],
    )
    payload = membership.model_dump_json(indent=2).encode("utf-8") + b"\n"
    reference = ProductArtifactRef(
        artifact_type="SourceCollisionMembership",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job.job_id}/scene/source_regions/{pallet.id}-exact.json",
        artifact_checksum=_sha256(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.OBJECT_EXTRACT,
        job_id=job.job_id,
    )
    registry.scene.store.publish(reference, payload)
    exact_ownership = SourceCollisionRegion(
        object_id=pallet.id,
        source_geometry_ref=scene.environment.geometry_ref,
        extraction_revision=ownership.extraction_revision,
        source_transform=ownership.source_transform,
        region_kind="triangle_indices",
        region_ref=reference,
    )
    exact_scene = scene.model_copy(
        update={"objects": [pallet.model_copy(update={"source_collision": exact_ownership}, deep=True)]}, deep=True
    )

    background = _carved_environment(registry, confirm_object(exact_scene, pallet.id))

    assert background.carved_triangles == 1
    assert len(background.faces) == len(mesh.faces) - 1

    overlap_transform = pallet.transform.model_copy(update={"local_frame": "overlap"})
    overlap_source_transform = ownership.source_transform.model_copy(update={"local_frame": "overlap"})
    overlap_ownership = ownership.model_copy(
        update={"object_id": "overlap", "source_transform": overlap_source_transform}, deep=True
    )
    overlap = pallet.model_copy(
        update={
            "id": "overlap",
            "local_frame": "overlap",
            "transform": overlap_transform,
            "source_collision": overlap_ownership,
        },
        deep=True,
    )
    exact_overlap_scene = exact_scene.model_copy(update={"objects": [exact_scene.objects[0], overlap]}, deep=True)
    with pytest.raises(SourceCollisionOwnershipError, match="claimed by both"):
        _carved_environment(registry, exact_overlap_scene)


def test_both_package_builders_share_background_and_current_hybrid_object_pose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    pallet = scene.objects[0]
    moved = move_object(
        confirm_object(scene, pallet.id),
        pallet.id,
        pallet.transform.model_copy(update={"translation_xyz": (4.0, 0.5, 0.3)}),
    )
    background = _carved_environment(registry, moved)
    layer_ref, layer_triangles, layer_carved = _environment_layer(registry, job.job_id, background)
    assert layer_triangles == len(background.faces) and layer_carved == background.carved_triangles
    assert layer_ref.artifact_checksum.startswith("sha256:")

    visual_scene = moved.model_copy(
        update={
            "environment": moved.environment.model_copy(
                update={"visual_master_ref": moved.environment.geometry_ref}, deep=True
            )
        },
        deep=True,
    )
    runtime_python = tmp_path / "fake-usd-python"
    runtime_python.write_text("fixture runtime marker", encoding="utf-8")
    output = tmp_path / "hybrid-output"
    output.mkdir()
    captured: dict = {}

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        request_path = Path(command[command.index("--request") + 1])
        captured.update(json.loads(request_path.read_text(encoding="utf-8")))
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(simulation_package.subprocess, "run", fake_run)
    _hybrid_layers(registry, visual_scene, output, background, runtime_python)

    assert captured["collision_background_identity"] == background.identity
    assert captured["objects"][0]["translation"] == [4.0, 0.5, 0.3]
    collision_mesh = trimesh.load(
        captured["environment"]["collision_mesh"], file_type="ply", force="mesh", process=False
    )
    assert len(collision_mesh.faces) == len(background.faces)
    assert (
        _package_build_config(EffectiveExportMode.LEGACY_BOX, background.identity, None)[
            "collision_background_identity"
        ]
        == background.identity
    )
    hybrid_config = _package_build_config(EffectiveExportMode.HYBRID, background.identity, "26.5.0")
    assert hybrid_config["collision_background_identity"] == background.identity
    assert hybrid_config["runtime_usd_version"] == "26.5.0"
