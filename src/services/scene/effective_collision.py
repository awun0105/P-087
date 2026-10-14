"""Effective canonical environment collision from immutable source ownership."""

import hashlib
import io
import json
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.scene import SceneIR, SceneObject, SceneObjectOrigin, SceneObjectState
from src.services.scene.collision_ownership import SourceCollisionOwnershipError, read_triangle_memberships
from src.services.simulation.colliders.carve import (
    COLLISION_CARVE_MARGIN_M,
    CarveBox,
    carve_triangle_mask,
    triangle_mask_in_box,
)
from src.services.simulation.usd.physics_config import physics_build_config


@dataclass(frozen=True)
class CarvedBackground:
    """Verified source collision mesh shared by all package builders."""

    vertices: np.ndarray
    faces: np.ndarray
    carved_triangles: int
    identity: str
    source_remove_mask: np.ndarray
    #: Triangles claimed by both a carved and a kept source region; they stay in the background.
    retained_shared_triangles: int = 0
    #: Kept objects whose region shares triangles with a carved one (the user can resolve them).
    retained_shared_object_ids: tuple[str, ...] = ()


def _source_region_removed(item: SceneObject, objects_by_id: dict[str, SceneObject]) -> bool:
    """Whether this immutable source region leaves the background after review/merge."""
    visited: set[str] = set()
    while item.provenance.get("review") == "MERGED":
        if item.id in visited:
            return False
        visited.add(item.id)
        merged_into = item.provenance.get("merged_into")
        if not isinstance(merged_into, str) or merged_into not in objects_by_id:
            return False
        item = objects_by_id[merged_into]
    if item.provenance.get("duplicated_from") is not None:
        return False
    review = item.provenance.get("review")
    return review == "DELETED" or (review != "IGNORED" and item.state == SceneObjectState.CONFIRMED)


def compose_effective_collision(
    scene: SceneIR,
    source_ref: ProductArtifactRef,
    glb: bytes,
    read_artifact: Callable[[ProductArtifactRef], bytes],
    *,
    margin_m: float = COLLISION_CARVE_MARGIN_M,
) -> CarvedBackground:
    """Resolve the selected collision source; edited object transforms never define carve regions."""
    margin_m = physics_build_config({"carve_margin_m": margin_m})["carve_margin_m"]
    source_checksum = f"sha256:{hashlib.sha256(glb).hexdigest()}"
    if source_checksum != source_ref.artifact_checksum:
        raise SourceCollisionOwnershipError("source collision bytes differ from selected geometry checksum")

    mesh = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh", process=False)
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    if not len(faces):
        raise SourceCollisionOwnershipError("source collision mesh has no triangles")

    reconstructed = [item for item in scene.objects if item.origin == SceneObjectOrigin.RECONSTRUCTED]
    objects_by_id = {item.id: item for item in reconstructed}
    selected_source = scene.environment.collision_source_ref is not None
    missing = [
        item.id
        for item in reconstructed
        if item.provenance.get("duplicated_from") is None
        and (
            (
                selected_source
                and (
                    item.source_collision is None
                    or item.source_collision.source_geometry_ref != source_ref
                    or item.source_collision.region_kind != "triangle_indices"
                )
            )
            or (not selected_source and _source_region_removed(item, objects_by_id) and item.source_collision is None)
        )
    ]
    if missing:
        ids = ", ".join(sorted(missing))
        raise SourceCollisionOwnershipError(
            f"reconstructed objects require source collision ownership before rebuilding background: {ids}"
        )

    owned = sorted((item for item in reconstructed if item.source_collision is not None), key=lambda item: item.id)
    source_owners = [item.source_collision for item in owned]
    if any(owner is None for owner in source_owners):  # narrowed below for static type checkers
        raise SourceCollisionOwnershipError("source collision ownership is incomplete")
    owners = [owner for owner in source_owners if owner is not None]
    for item, owner in zip(owned, owners, strict=True):
        if owner.object_id != item.id or owner.source_geometry_ref != source_ref:
            raise SourceCollisionOwnershipError(
                f"{item.id}: source collision ownership is not bound to this environment"
            )

    exact_owners = [owner for owner in owners if owner.region_kind == "triangle_indices"]
    memberships = read_triangle_memberships(
        exact_owners,
        glb,
        len(faces),
        read_artifact,
        allow_shared=True,
    )

    centroids = vertices[faces].mean(axis=1)
    triangle_count = len(faces)
    regions: list[tuple[SceneObject, np.ndarray, bool]] = []
    exact_claim = np.zeros(triangle_count, dtype=bool)
    for item, owner in zip(owned, owners, strict=True):
        if owner.region_kind == "triangle_indices":
            indices = np.asarray(memberships[owner.object_id], dtype=np.intp)
            exact_claim[indices] = True
            regions.append((item, indices, True))
            continue
        dimensions = owner.source_obb_dimensions_xyz_m
        if dimensions is None:
            raise SourceCollisionOwnershipError(f"{owner.object_id}: source OBB dimensions are missing")
        box = CarveBox.from_transform(owner.source_transform, dimensions)
        indices = np.flatnonzero(triangle_mask_in_box(centroids, box, margin_m))
        regions.append((item, indices, False))

    carve_claim = np.zeros(triangle_count, dtype=bool)
    keep_claim = np.zeros(triangle_count, dtype=bool)
    kept_regions: list[tuple[str, np.ndarray]] = []
    for item, indices, exact in regions:
        if not exact:
            # Exact triangle membership is authoritative: an approximate box never takes a triangle from it.
            indices = indices[~exact_claim[indices]]
        if _source_region_removed(item, objects_by_id):
            carve_claim[indices] = True
        else:
            keep_claim[indices] = True
            kept_regions.append((item.id, indices))
    # Whoever owns a triangle claimed only by carved regions (or only by kept ones), the result is the same.
    # A triangle shared by a carved box and a kept box cannot be attributed: carving it could delete collision
    # of an object that stays, keeping it leaves at most that shared sliver. Keep it, never guess, and report it.
    shared = carve_claim & keep_claim
    remove_mask = carve_claim & ~keep_claim
    shared_object_ids = tuple(sorted(object_id for object_id, indices in kept_regions if shared[indices].any()))

    background_hash = hashlib.sha256()
    identity_header = json.dumps(
        {
            "algorithm": "source_geometry_checksum+removed_triangle_mask_v1",
            "source_geometry_checksum": source_checksum,
            "source_triangle_count": len(faces),
            "carve_margin_m": margin_m,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    background_hash.update(identity_header)
    background_hash.update(np.packbits(remove_mask, bitorder="little").tobytes())
    carved_vertices, carved_faces, carved = carve_triangle_mask(vertices, faces, remove_mask)
    return CarvedBackground(
        carved_vertices,
        carved_faces,
        carved,
        f"sha256:{background_hash.hexdigest()}",
        source_remove_mask=remove_mask,
        retained_shared_triangles=int(np.count_nonzero(shared)),
        retained_shared_object_ids=shared_object_ids,
    )
