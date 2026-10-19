"""Effective canonical environment collision from immutable source ownership."""

import hashlib
import io
import json
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.floor_model import FloorFitEvidence
from src.models.contracts.object_geometry import ObjectAwareEnvironmentManifest
from src.models.contracts.scene import SceneIR, SceneObject, SceneObjectOrigin, SceneObjectState
from src.services.scene.collision_ownership import SourceCollisionOwnershipError, read_triangle_memberships
from src.services.scene.collision_surfaces import (
    authored_plane_infill,
    patch_planar_holes,
    require_closed_cuts,
    surface_planes,
)
from src.services.scene.editing.membership import decode_gaussian_membership_labels
from src.services.simulation.colliders.carve import (
    COLLISION_CARVE_MARGIN_M,
    CarveBox,
    _rotation,
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
    protected_surface_triangles: int = 0
    repaired_triangles: int = 0


def _source_region_removed(
    item: SceneObject, objects_by_id: dict[str, SceneObject], *, preview_pending: bool = False
) -> bool:
    """Whether this immutable source region leaves the background after review/merge."""
    visited: set[str] = set()
    while item.provenance.get("review") == "MERGED":
        if item.id in visited:
            raise SourceCollisionOwnershipError(f"{item.id}: cyclic merged source ownership")
        visited.add(item.id)
        merged_into = item.provenance.get("merged_into")
        if not isinstance(merged_into, str) or merged_into not in objects_by_id:
            raise SourceCollisionOwnershipError(f"{item.id}: merged ownership target is missing")
        item = objects_by_id[merged_into]
    if item.provenance.get("duplicated_from") is not None:
        return False
    review = item.provenance.get("review")
    return review == "DELETED" or (
        review != "IGNORED"
        and (item.state == SceneObjectState.CONFIRMED or (preview_pending and item.state == SceneObjectState.CANDIDATE))
    )


def _object_aware_environment(
    scene: SceneIR,
    source_ref: ProductArtifactRef,
    source_faces: np.ndarray,
    read_artifact: Callable[[ProductArtifactRef], bytes],
    *,
    preview_pending: bool,
) -> CarvedBackground:
    """Use separately authored background; restore source colliders for objects kept at source pose."""

    def read(reference: ProductArtifactRef) -> bytes:
        payload = read_artifact(reference)
        if reference.artifact_checksum != f"sha256:{hashlib.sha256(payload).hexdigest()}":
            raise SourceCollisionOwnershipError("object-aware artifact checksum mismatch")
        return payload

    reference = scene.environment.object_aware_collision_ref
    if reference is None:
        raise SourceCollisionOwnershipError("object-aware manifest is missing")
    manifest = ObjectAwareEnvironmentManifest.model_validate_json(read(reference))
    if manifest.source_geometry_ref != source_ref or manifest.source_membership != scene.environment.membership:
        raise SourceCollisionOwnershipError("object-aware geometry is stale; regenerate from current membership")
    # collider_ref may be a derived USD layer after physics enrichment. The sealed
    # manifest owns the immutable GLB baseline; never re-carve a derived layer.
    separated = set(manifest.removed_object_ids)
    retained = set(manifest.source_membership.label_to_object_id.values()) - separated
    objects_by_id = {item.id: item for item in scene.objects}
    if any(
        object_id not in objects_by_id or objects_by_id[object_id].provenance.get("review") != "IGNORED"
        for object_id in retained
    ):
        raise SourceCollisionOwnershipError(
            "object-aware background retains an object that needs separate geometry; rebuild mesh"
        )
    # Read the sealed source map too: a manifest must not attest to corrupt/missing membership bytes.
    decode_gaussian_membership_labels(read(manifest.source_membership.labels_ref), manifest.source_membership)
    mesh = trimesh.load(io.BytesIO(read(manifest.collision_ref)), file_type="glb", force="mesh", process=False)
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise SourceCollisionOwnershipError("invalid object-aware environment mesh")
    meshes = [mesh]
    for object_id in manifest.removed_object_ids:
        item = objects_by_id.get(object_id)
        if item is None or item.source_collision is None or item.source_collision.source_geometry_ref != source_ref:
            raise SourceCollisionOwnershipError("object-aware source pose binding is missing or stale")
        if _source_region_removed(item, objects_by_id, preview_pending=preview_pending):
            continue
        collider = item.collider
        if collider is None or collider.geometry_ref is None:
            raise SourceCollisionOwnershipError(f"{object_id}: source collider is required by object-aware composition")
        restored = trimesh.load(io.BytesIO(read(collider.geometry_ref)), file_type="glb", force="mesh", process=False)
        if not len(restored.faces) or not np.isfinite(restored.vertices).all():
            raise SourceCollisionOwnershipError(f"{object_id}: invalid source collider geometry")
        local = collider.local_transform
        source = item.source_collision.source_transform
        points = np.asarray(restored.vertices) @ _rotation(local.rotation_quaternion_xyzw).T + np.asarray(
            local.translation_xyz
        )
        restored.vertices = points @ _rotation(source.rotation_quaternion_xyzw).T + np.asarray(source.translation_xyz)
        meshes.append(restored)
    combined = trimesh.util.concatenate(meshes)
    vertices = np.asarray(combined.vertices, dtype=np.float64)
    faces = np.asarray(combined.faces, dtype=np.int64)
    digest = hashlib.sha256(reference.artifact_checksum.encode())
    digest.update(vertices.tobytes())
    digest.update(faces.tobytes())
    return CarvedBackground(vertices, faces, 0, f"sha256:{digest.hexdigest()}", np.zeros(len(source_faces), dtype=bool))


def compose_effective_collision(
    scene: SceneIR,
    source_ref: ProductArtifactRef,
    glb: bytes,
    read_artifact: Callable[[ProductArtifactRef], bytes],
    *,
    margin_m: float = COLLISION_CARVE_MARGIN_M,
    preview_pending: bool = False,
    repair_surfaces: bool = False,
) -> CarvedBackground:
    """Resolve the selected collision source; edited object transforms never define carve regions."""
    repair_surfaces = repair_surfaces or preview_pending
    margin_m = physics_build_config({"carve_margin_m": margin_m})["carve_margin_m"]
    source_checksum = f"sha256:{hashlib.sha256(glb).hexdigest()}"
    if source_checksum != source_ref.artifact_checksum:
        raise SourceCollisionOwnershipError("source collision bytes differ from selected geometry checksum")

    mesh = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh", process=False)
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    if not len(faces):
        raise SourceCollisionOwnershipError("source collision mesh has no triangles")
    if scene.environment.object_aware_collision_ref is not None:
        return _object_aware_environment(scene, source_ref, faces, read_artifact, preview_pending=preview_pending)

    reconstructed = [item for item in scene.objects if item.origin == SceneObjectOrigin.RECONSTRUCTED]
    objects_by_id = {item.id: item for item in reconstructed}
    selected_source = scene.environment.collision_source_ref is not None
    has_removed_region = any(
        _source_region_removed(item, objects_by_id, preview_pending=preview_pending) for item in reconstructed
    )
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
            or (not selected_source and has_removed_region and item.source_collision is None)
        )
    ]
    if missing:
        ids = ", ".join(sorted(missing))
        raise SourceCollisionOwnershipError(
            f"reconstructed objects require source collision ownership before rebuilding background: {ids}"
        )

    owned = sorted(
        (
            item
            for item in reconstructed
            if item.source_collision is not None and item.provenance.get("duplicated_from") is None
        ),
        key=lambda item: item.id,
    )
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
        if _source_region_removed(item, objects_by_id, preview_pending=preview_pending):
            carve_claim[indices] = True
        else:
            keep_claim[indices] = True
            kept_regions.append((item.id, indices))
    # Whoever owns a triangle claimed only by carved regions (or only by kept ones), the result is the same.
    # A triangle shared by a carved box and a kept box cannot be attributed: carving it could delete collision
    # of an object that stays, keeping it leaves at most that shared sliver. Keep it, never guess, and report it.
    shared = carve_claim & keep_claim
    remove_mask = carve_claim & ~keep_claim
    floor = np.zeros(triangle_count, dtype=bool)
    planes = []
    if repair_surfaces:
        floor, planes = _floor_triangle_mask(scene, source_ref, vertices, faces, read_artifact)
    labels = surface_planes(scene.provenance, source_checksum) if repair_surfaces else []
    for plane in labels:
        normal, offset = plane.equation()
        planes.append((normal, offset, 0.01))
        floor |= (np.abs(vertices[faces] @ normal + offset) <= 0.01).all(axis=1)
    retained_floor = int(np.count_nonzero(remove_mask & floor))
    remove_mask &= ~floor
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
    caps = np.empty((0, 3), dtype=np.int64)
    patched_vertices = vertices
    if repair_surfaces:
        footprints = []
        for item, indices, _ in regions:
            if len(indices) and _source_region_removed(item, objects_by_id, preview_pending=preview_pending):
                owner = item.source_collision
                if owner is not None and owner.source_obb_dimensions_xyz_m is not None:
                    half = np.asarray(owner.source_obb_dimensions_xyz_m) / 2
                    corners = np.array(
                        [
                            [x, y, z]
                            for x in [-half[0], half[0]]
                            for y in [-half[1], half[1]]
                            for z in [-half[2], half[2]]
                        ]
                    )
                    points = corners @ _rotation(owner.source_transform.rotation_quaternion_xyzw).T + np.asarray(
                        owner.source_transform.translation_xyz
                    )
                else:
                    points = vertices[faces[indices]].reshape(-1, 3)
                footprints.append(np.array([points.min(axis=0), points.max(axis=0)]))
        patched_vertices, caps = patch_planar_holes(
            vertices, faces[~remove_mask], planes, footprints, source_faces=faces
        )
        floor_labels = [value for value in labels if value.kind == "floor"]
        for plane in labels:
            selected_footprints = footprints
            if plane.kind == "floor":
                selected_footprints = []
                for region in footprints:
                    base = np.array(
                        [(region[0, 0] + region[1, 0]) / 2, (region[0, 1] + region[1, 1]) / 2, region[0, 2]]
                    )
                    candidates = [
                        (float(normal @ base + offset), value.id)
                        for value in floor_labels
                        for normal, offset in [value.equation()]
                        if float(normal @ base + offset) >= -0.05
                    ]
                    if candidates and min(candidates)[1] == plane.id:
                        selected_footprints.append(region)
            kept = np.concatenate([faces[~remove_mask], caps])
            patched_vertices, authored = authored_plane_infill(patched_vertices, kept, plane, selected_footprints)
            caps = np.concatenate([caps, authored])
        require_closed_cuts(patched_vertices, faces, np.concatenate([faces[~remove_mask], caps]))
    # Include inferred surface topology in identity; object pose is deliberately absent.
    if len(caps):
        background_hash.update(b"authored_or_planar_surface_caps_v1")
        background_hash.update(np.asarray([len(caps), len(patched_vertices) - len(vertices)], dtype=np.int64).tobytes())
        background_hash.update(caps.tobytes())
        background_hash.update(patched_vertices[len(vertices) :].tobytes())
    combined = np.concatenate([faces, caps])
    combined_mask = np.concatenate([remove_mask, np.zeros(len(caps), dtype=bool)])
    carved_vertices, carved_faces, carved = carve_triangle_mask(patched_vertices, combined, combined_mask)
    return CarvedBackground(
        carved_vertices,
        carved_faces,
        carved,
        f"sha256:{background_hash.hexdigest()}",
        source_remove_mask=remove_mask,
        retained_shared_triangles=int(np.count_nonzero(shared)),
        retained_shared_object_ids=shared_object_ids,
        protected_surface_triangles=retained_floor,
        repaired_triangles=len(caps),
    )


def _floor_triangle_mask(
    scene: SceneIR,
    source_ref: ProductArtifactRef,
    vertices: np.ndarray,
    faces: np.ndarray,
    read_artifact: Callable[[ProductArtifactRef], bytes],
) -> tuple[np.ndarray, list[tuple[np.ndarray, float, float]]]:
    """Retain existing source floor surfaces; never fabricate geometry behind an occluder."""
    summary = scene.provenance.get("floor_fit")
    if not isinstance(summary, dict) or not summary.get("artifact_ref"):
        return np.zeros(len(faces), dtype=bool), []
    ref = ProductArtifactRef.model_validate(summary["artifact_ref"])
    if ref.artifact_type != "FloorFitEvidence":
        raise SourceCollisionOwnershipError("floor plane requires a FloorFitEvidence artifact")
    payload = read_artifact(ref)
    if ref.artifact_checksum != f"sha256:{hashlib.sha256(payload).hexdigest()}":
        raise SourceCollisionOwnershipError("floor evidence checksum mismatch")
    evidence = FloorFitEvidence.model_validate_json(payload)
    model = evidence.floor_model
    if ref.job_id != source_ref.job_id or evidence.job_id != source_ref.job_id:
        raise SourceCollisionOwnershipError("floor evidence belongs to another job")
    if model.profile_checksum != summary.get("profile_checksum") or model.source_checksum != summary.get(
        "point_cloud_checksum"
    ):
        raise SourceCollisionOwnershipError("floor evidence does not match SceneIR floor identity")
    membership = scene.environment.membership
    if membership and evidence.source_artifact_ref != membership.source_visual_ref:
        raise SourceCollisionOwnershipError("floor evidence does not match scene source visual")
    if model.status not in {"supported", "confirmed_prior_fallback"}:
        return np.zeros(len(faces), dtype=bool), []
    points = vertices[faces]
    normal = np.asarray(model.plane_normal_world)
    # Geometry quantization is explicit source provenance; unknown resolution adds no tolerance.
    voxel = (source_ref.source_provenance or {}).get("voxel_resolution_m", 0.0)
    if isinstance(voxel, bool) or not isinstance(voxel, (int, float)) or not np.isfinite(voxel) or voxel < 0:
        raise SourceCollisionOwnershipError("invalid source voxel resolution for floor protection")
    band = float(model.floor_band_m) + float(voxel)
    distances = points @ normal + float(model.plane_offset_m)
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    alignment = np.abs(normals @ normal) / np.maximum(lengths, 1e-12)
    mask = (np.abs(distances) <= band).all(axis=1) & (alignment >= np.cos(np.deg2rad(model.profile.max_tilt_degrees)))
    return mask, [(normal, float(model.plane_offset_m), band)]
