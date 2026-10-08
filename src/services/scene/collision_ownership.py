"""Bind editable objects to immutable regions of their source collision mesh."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.scene import (
    SceneObject,
    SceneObjectOrigin,
    SourceCollisionMembership,
    SourceCollisionRegion,
)
from src.services.simulation.colliders.carve import COLLISION_CARVE_MARGIN_M, CarveBox, triangle_mask_in_box

ResolveArtifactBytes = Callable[[ProductArtifactRef], bytes]


@dataclass(frozen=True)
class SourceTriangleOwnership:
    """Exclusive, conservative source-mesh ownership for one immutable scene revision."""

    vertices: np.ndarray
    faces: np.ndarray
    centroids: np.ndarray
    owner_labels: np.ndarray
    label_to_object_id: dict[str, str]
    ambiguous_triangle_count: int


class SourceCollisionOwnershipError(ValueError):
    """Source collision ownership cannot be resolved without guessing."""


def bind_source_collision_ownership(
    objects: list[SceneObject], source_geometry_ref: ProductArtifactRef, extraction_revision: str
) -> list[SceneObject]:
    """Record each reconstructed object's extraction pose as immutable source OBB metadata."""
    bound: list[SceneObject] = []
    for item in objects:
        if item.origin != SceneObjectOrigin.RECONSTRUCTED or item.primitive_dimensions_xyz_m is None:
            bound.append(item)
            continue
        if item.source_collision is not None:
            existing = item.source_collision
            if (
                existing.source_geometry_ref != source_geometry_ref
                or existing.extraction_revision != extraction_revision
            ):
                raise SourceCollisionOwnershipError(
                    f"{item.id}: refusing to replace immutable source collision ownership"
                )
            bound.append(item)
            continue
        ownership = SourceCollisionRegion(
            object_id=item.id,
            source_geometry_ref=source_geometry_ref,
            extraction_revision=extraction_revision,
            source_transform=item.transform,
            region_kind="source_obb",
            source_obb_dimensions_xyz_m=item.primitive_dimensions_xyz_m,
        )
        bound.append(item.model_copy(update={"source_collision": ownership}, deep=True))
    return bound


def read_triangle_memberships(
    owners: list[SourceCollisionRegion],
    source_geometry_bytes: bytes,
    source_triangle_count: int,
    resolve_bytes: ResolveArtifactBytes,
) -> dict[str, tuple[int, ...]]:
    """Resolve exact membership sidecars and reject stale, out-of-range, or overlapping ownership.

    Both `ProductArtifactRef.artifact_checksum` values are byte checksums. The embedded source
    ref binds indices to the exact source mesh bytes; the membership ref binds the sidecar bytes.
    """
    if source_triangle_count < 1:
        raise SourceCollisionOwnershipError("source collision mesh has no triangles")
    if not owners:
        return {}
    owner_ids = [owner.object_id for owner in owners]
    if len(owner_ids) != len(set(owner_ids)):
        raise SourceCollisionOwnershipError("source collision ownership contains duplicate object ids")

    source_checksum = _sha256(source_geometry_bytes)
    expected_ref = owners[0].source_geometry_ref
    if source_checksum != expected_ref.artifact_checksum:
        raise SourceCollisionOwnershipError("source collision bytes differ from the ownership checksum")

    claimed: dict[int, str] = {}
    memberships: dict[str, tuple[int, ...]] = {}
    for owner in owners:
        if owner.region_kind != "triangle_indices" or owner.region_ref is None:
            raise SourceCollisionOwnershipError(f"{owner.object_id}: exact triangle membership is required")
        if owner.source_geometry_ref != expected_ref:
            raise SourceCollisionOwnershipError("all ownership regions must use the same source geometry ref")

        sidecar_bytes = resolve_bytes(owner.region_ref)
        if _sha256(sidecar_bytes) != owner.region_ref.artifact_checksum:
            raise SourceCollisionOwnershipError(f"{owner.object_id}: membership sidecar byte checksum mismatch")
        membership = SourceCollisionMembership.model_validate_json(sidecar_bytes)
        if membership.object_id != owner.object_id:
            raise SourceCollisionOwnershipError(f"{owner.object_id}: membership sidecar object_id mismatch")
        if membership.source_geometry_ref != owner.source_geometry_ref:
            raise SourceCollisionOwnershipError(f"{owner.object_id}: membership source geometry ref mismatch")
        if membership.extraction_revision != owner.extraction_revision:
            raise SourceCollisionOwnershipError(f"{owner.object_id}: membership extraction revision mismatch")
        indices = tuple(membership.triangle_indices)
        if any(index >= source_triangle_count for index in indices):
            raise SourceCollisionOwnershipError(f"{owner.object_id}: membership index is outside source mesh bounds")
        for index in indices:
            previous_owner = claimed.get(index)
            if previous_owner is not None:
                raise SourceCollisionOwnershipError(
                    f"source triangle {index} is claimed by both {previous_owner} and {owner.object_id}"
                )
            claimed[index] = owner.object_id
        memberships[owner.object_id] = indices
    return memberships


def source_triangle_ownership(
    objects: list[SceneObject],
    source_geometry_ref: ProductArtifactRef,
    source_geometry_bytes: bytes,
    resolve_bytes: ResolveArtifactBytes,
) -> SourceTriangleOwnership:
    """Materialize OBB/exact regions as exclusive labels; ambiguous OBB overlaps stay background."""
    if _sha256(source_geometry_bytes) != source_geometry_ref.artifact_checksum:
        raise SourceCollisionOwnershipError("source collision bytes differ from the ownership checksum")
    mesh = trimesh.load(io.BytesIO(source_geometry_bytes), file_type="glb", force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise SourceCollisionOwnershipError("source collision artifact is not a triangle mesh")
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if (
        vertices.ndim != 2
        or vertices.shape[1] != 3
        or not np.isfinite(vertices).all()
        or faces.ndim != 2
        or faces.shape[1] != 3
        or not len(faces)
        or np.any(faces < 0)
        or np.any(faces >= len(vertices))
    ):
        raise SourceCollisionOwnershipError("source collision mesh has invalid vertices or faces")

    owners = sorted(
        (item.source_collision for item in objects if item.source_collision is not None),
        key=lambda region: region.object_id,
    )
    if any(owner.source_geometry_ref != source_geometry_ref for owner in owners):
        raise SourceCollisionOwnershipError("source collision ownership is bound to another geometry artifact")
    labels_by_id = {owner.object_id: label for label, owner in enumerate(owners)}
    if len(labels_by_id) != len(owners):
        raise SourceCollisionOwnershipError("source collision ownership contains duplicate object ids")
    label_to_object_id = {str(label): object_id for object_id, label in labels_by_id.items()}
    owner_labels = np.full(len(faces), -1, dtype=np.int32)
    exact_owners = [owner for owner in owners if owner.region_kind == "triangle_indices"]
    exact_memberships = read_triangle_memberships(
        exact_owners,
        source_geometry_bytes,
        len(faces),
        resolve_bytes,
    )
    exact_claim = np.zeros(len(faces), dtype=bool)
    for object_id, indices in exact_memberships.items():
        selected = np.asarray(indices, dtype=np.intp)
        owner_labels[selected] = labels_by_id[object_id]
        exact_claim[selected] = True

    centroids = vertices[faces].mean(axis=1)
    obb_claim_count = np.zeros(len(faces), dtype=np.uint16)
    obb_claim_label = np.full(len(faces), -1, dtype=np.int32)
    by_id = {item.id: item for item in objects}
    for owner in owners:
        if owner.region_kind != "source_obb":
            continue
        item = by_id.get(owner.object_id)
        dimensions = owner.source_obb_dimensions_xyz_m
        if item is None or dimensions is None:
            raise SourceCollisionOwnershipError(f"{owner.object_id}: source OBB owner is incomplete")
        claimed = (
            triangle_mask_in_box(
                centroids,
                CarveBox.from_transform(owner.source_transform, dimensions),
                COLLISION_CARVE_MARGIN_M,
            )
            & ~exact_claim
        )
        first = claimed & (obb_claim_count == 0)
        obb_claim_label[first] = labels_by_id[owner.object_id]
        obb_claim_count[claimed] += 1

    exclusive = obb_claim_count == 1
    owner_labels[exclusive] = obb_claim_label[exclusive]
    return SourceTriangleOwnership(
        vertices=vertices,
        faces=faces,
        centroids=centroids,
        owner_labels=owner_labels,
        label_to_object_id=label_to_object_id,
        ambiguous_triangle_count=int(np.count_nonzero(obb_claim_count > 1)),
    )


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
