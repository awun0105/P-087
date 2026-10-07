"""AUD-01 source ownership contracts and current collision-edit regressions."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
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
from src.services.orchestration.review.simulation_package import _carved_environment
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


def test_current_carver_reintroduces_source_collision_after_move_delete_and_restore(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    pallet = scene.objects[0]

    _, original_faces, original_removed = _carved_environment(registry, scene)
    confirmed = confirm_object(scene, pallet.id)
    _, confirmed_faces, confirmed_removed = _carved_environment(registry, confirmed)
    moved = move_object(
        confirmed,
        pallet.id,
        pallet.transform.model_copy(update={"translation_xyz": (4.0, 0.5, 0.3)}),
    )
    _, moved_faces, moved_removed = _carved_environment(registry, moved)
    deleted = delete_object(moved, pallet.id)
    _, deleted_faces, deleted_removed = _carved_environment(registry, deleted)
    restored = restore_object(deleted, pallet.id)
    _, restored_faces, restored_removed = _carved_environment(registry, restored)
    ignored = ignore_object(scene, pallet.id)
    _, ignored_faces, ignored_removed = _carved_environment(registry, ignored)

    # Characterization: this is the current failure. The edited pose has no mesh underneath,
    # so the original pallet triangles reappear after move/delete and remain after restore.
    assert original_removed == ignored_removed == 0
    assert len(ignored_faces) == len(original_faces)
    assert confirmed_removed > 0 and len(confirmed_faces) < len(original_faces)
    assert moved_removed == deleted_removed == restored_removed == 0
    assert len(moved_faces) == len(deleted_faces) == len(restored_faces) == len(original_faces)


def test_current_carver_blindly_claims_user_added_and_overlapping_source_regions(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    pallet = scene.objects[0]
    confirmed = confirm_object(scene, pallet.id)
    _, _, confirmed_removed = _carved_environment(registry, confirmed)

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
    _, _, user_added_removed = _carved_environment(registry, user_scene)

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
    _, _, overlap_removed = _carved_environment(registry, overlap_scene)

    assert confirmed_removed > 0
    assert user_added_removed == confirmed_removed
    # Two source owners with coincident OBBs collapse to the same blind box carve; ownership is not used.
    assert overlap_removed == confirmed_removed
