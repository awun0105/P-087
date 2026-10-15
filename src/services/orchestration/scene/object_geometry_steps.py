"""Reusable geometry stages for object extraction and builds from reviewed membership."""

from collections.abc import Callable

import numpy as np
import trimesh

from src.models.contracts.artifacts import JsonObject, ProductArtifactRef
from src.models.contracts.floor_model import FloorModel
from src.models.contracts.manifests import StageId
from src.models.contracts.object_geometry import ObjectAwareEnvironmentManifest
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.reconstruction import ReconstructionBundle

Publish = Callable[[ProductArtifactRef, bytes], ProductArtifactRef]


def build_environment_collision(
    *,
    source_points: np.ndarray,
    membership_labels: np.ndarray,
    label_to_object_id: dict[str, str],
    footprints: list[tuple[np.ndarray, np.ndarray]],
    floor_model: FloorModel,
    floor_fit: JsonObject,
    voxel_m: float,
    bundle: ReconstructionBundle,
    membership: ObjectMembershipArtifact,
    publish: Publish,
    job_id: str,
    footprint_centers: list[tuple[float, float, float]] | None = None,
) -> tuple[ProductArtifactRef, ProductArtifactRef]:
    """Publish source-world background collision with inferred support under source footprints.

    Corrections can retain an off-centre source pose; footprint_centers preserves its contact check.
    """
    # Resolve shared execution primitives at call time; objectify also calls these geometry stages.
    from src.services.orchestration.scene.objectify import ObjectifyError, _reference, build_background_collision

    support = []
    # Inferred support never comes from inpaint rows or a current edited object pose.
    if floor_model.status in {"supported", "confirmed_prior_fallback"}:
        normal = np.asarray(floor_model.plane_normal_world)
        for index, (low, high) in enumerate(footprints):
            center = (low + high) / 2 if footprint_centers is None else footprint_centers[index]
            base = np.array([center[0], center[1], low[2]])
            if abs(float(normal @ base + floor_model.plane_offset_m)) > floor_model.floor_band_m + 2 * voxel_m:
                continue
            xs = np.arange(low[0], high[0] + voxel_m, voxel_m)
            ys = np.arange(low[1], high[1] + voxel_m, voxel_m)
            if len(xs) * len(ys) > 1_000_000:
                raise ObjectifyError("inferred support exceeds the geometry budget", retryable=False)
            for x in xs:
                for y in ys:
                    z = -(normal[0] * x + normal[1] * y + floor_model.plane_offset_m) / normal[2]
                    support.append([x, y, z])
    background_mesh = build_background_collision(
        source_points,
        membership_labels,
        {int(label) for label in label_to_object_id},
        voxel_m=voxel_m,
        unknown=membership_labels < 0,
        inferred_support_points=np.asarray(support).reshape(-1, 3),
    )
    mesh = trimesh.Trimesh(background_mesh.vertices, background_mesh.faces, process=False)
    collision_payload = mesh.export(file_type="glb")
    active_ref = publish(
        _reference(
            job_id,
            "objectgs/environment/{digest}.glb",
            "ObjectAwareEnvironmentCollision",
            StageId.COLLIDER,
            collision_payload,
        ),
        collision_payload,
    )
    manifest = ObjectAwareEnvironmentManifest(
        source_geometry_ref=bundle.canonical_geometry_ref,
        collision_ref=active_ref,
        source_membership=membership,
        removed_object_ids=sorted(label_to_object_id.values()),
        occupancy_checksum=background_mesh.occupancy_checksum,
        provenance={
            "statistics": background_mesh.statistics,
            "voxel_m": voxel_m,
            "support_origin": "inferred_floor_plane_under_source_contact_footprints",
            "floor_fit": floor_fit,
            "watertight": bool(mesh.is_watertight),
            "inpaint_used_for_physics": False,
        },
    )
    manifest_payload = manifest.model_dump_json().encode()
    manifest_ref = publish(
        _reference(
            job_id,
            "objectgs/environment/{digest}.json",
            "ObjectAwareEnvironmentManifest",
            StageId.COLLIDER,
            manifest_payload,
        ),
        manifest_payload,
    )
    return active_ref, manifest_ref
