"""Bind editable objects to immutable regions of their source collision mesh."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.scene import (
    SceneObject,
    SceneObjectOrigin,
    SourceCollisionMembership,
    SourceCollisionRegion,
)

ResolveArtifactBytes = Callable[[ProductArtifactRef], bytes]


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


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
