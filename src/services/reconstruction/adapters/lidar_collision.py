"""Bounded voxel-surface mesh candidate builder for already aligned LiDAR points."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Literal, Self

import numpy as np
from pydantic import Field, FiniteFloat, model_validator
from scipy import ndimage

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.floor_model import FloorModel
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.manifests import StageId
from src.services.reconstruction.adapters.collision_glb import CollisionMesh, encode_collision_glb
from src.services.scene.floor_model import point_cloud_checksum


class LidarCollisionProfile(ContractModel):
    """Explicit resource and resolution limits for one LiDAR mesh candidate."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = Field(min_length=1)
    algorithm: Literal["voxel_surface_boundary_cubes_v1"] = "voxel_surface_boundary_cubes_v1"
    distance_unit: Literal["m"] = "m"
    voxel_m: FiniteFloat = Field(gt=0)
    max_input_points: int = Field(default=5_000_000, ge=1, le=10_000_000, strict=True)
    max_voxel_cells: int = Field(default=20_000_000, ge=8, le=100_000_000, strict=True)
    max_triangles: int = Field(default=10_000_000, ge=12, le=30_000_000, strict=True)

    def checksum(self) -> Checksum:
        """Stable identity for the exact voxel size and allocation ceilings."""
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self)).hexdigest()


class LidarCollisionBuildReport(ContractModel):
    """Diagnostic evidence for a mesh candidate; this is not calibration or physics QA."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["LidarCollisionBuildReport"] = "LidarCollisionBuildReport"
    source_point_checksum: Checksum
    floor_model_checksum: Checksum
    floor_profile_checksum: Checksum
    profile_checksum: Checksum
    profile_id: str = Field(min_length=1)
    algorithm: Literal["voxel_surface_boundary_cubes_v1"]
    voxel_m: FiniteFloat = Field(gt=0)
    output_collision_checksum: Checksum
    self_mask_evidence_ref: ProductArtifactRef | None = None
    self_mask_binding_checksum: Checksum | None = None
    input_point_count: int = Field(ge=1, strict=True)
    retained_point_count: int = Field(ge=1, strict=True)
    self_masked_point_count: int = Field(ge=0, strict=True)
    floor_support_point_count: int = Field(ge=0, strict=True)
    above_floor_point_count: int = Field(ge=0, strict=True)
    below_floor_point_count: int = Field(ge=0, strict=True)
    occupied_voxel_count: int = Field(ge=1, strict=True)
    vertex_count: int = Field(ge=3, strict=True)
    triangle_count: int = Field(ge=1, strict=True)
    physics_claim: Literal["unverified"] = "unverified"
    calibration_eligibility: Literal["not_evaluated_by_mesh_builder"] = "not_evaluated_by_mesh_builder"

    @model_validator(mode="after")
    def _validate_mask_evidence(self) -> Self:
        has_ref = self.self_mask_evidence_ref is not None
        has_checksum = self.self_mask_binding_checksum is not None
        if has_ref != has_checksum or (self.self_masked_point_count > 0 and not has_ref):
            raise ValueError("self-masked LiDAR points require a bound mask evidence reference and checksum")
        if has_ref and (
            self.self_mask_evidence_ref.artifact_type != "LidarSelfMaskEvidence"
            or self.self_mask_evidence_ref.producer_stage != StageId.COLLIDER
        ):
            raise ValueError("self-mask evidence reference must identify collider-stage LidarSelfMaskEvidence")
        return self


@dataclass(frozen=True)
class LidarCollisionBuild:
    mesh: CollisionMesh
    glb_bytes: bytes
    report: LidarCollisionBuildReport


_VOXEL_CORNERS = (
    (0, 0, 0),
    (1, 0, 0),
    (1, 1, 0),
    (0, 1, 0),
    (0, 0, 1),
    (1, 0, 1),
    (1, 1, 1),
    (0, 1, 1),
)
_EXPOSED_FACES = (
    (0, -1, (0, 4, 7, 3)),
    (0, 1, (1, 2, 6, 5)),
    (1, -1, (0, 1, 5, 4)),
    (1, 1, (3, 7, 6, 2)),
    (2, -1, (0, 3, 2, 1)),
    (2, 1, (4, 5, 6, 7)),
)


def _exposed_voxels(occupied: np.ndarray, axis: int, side: int) -> np.ndarray:
    """Return occupied cells whose neighbor on one side is empty."""
    neighbors = np.roll(occupied, shift=-side, axis=axis)
    boundary = [slice(None)] * occupied.ndim
    boundary[axis] = -1 if side == 1 else 0
    neighbors[tuple(boundary)] = False
    return occupied & ~neighbors


def lidar_self_mask_binding_checksum(source_checksum: Checksum, self_mask: np.ndarray) -> Checksum:
    """Bind packed mask bits to one exact ordered world-point cloud."""
    mask = np.asarray(self_mask)
    if mask.dtype != np.bool_ or mask.ndim != 1 or mask.size < 1:
        raise ValueError("self-mask must be a non-empty boolean vector")
    packed_mask = np.packbits(mask, bitorder="little").tobytes()
    digest = hashlib.sha256()
    digest.update(source_checksum.encode("ascii"))
    digest.update(len(mask).to_bytes(8, "little", signed=False))
    digest.update(packed_mask)
    return "sha256:" + digest.hexdigest()


def build_lidar_collision_candidate(
    points_world_m: np.ndarray,
    floor_model: FloorModel,
    profile: LidarCollisionProfile,
    *,
    self_mask: np.ndarray | None = None,
    self_mask_ref: ProductArtifactRef | None = None,
) -> LidarCollisionBuild:
    """Build a voxel surface without changing the input frame or guessing point deletions.

    `points_world_m` must already be checksum-bound, metric, and expressed in the
    target world's canonical frame. A missing self-mask preserves every point. If
    a caller supplies a mask, the caller must resolve it from the exact referenced
    evidence and point ordering; the report records the artifact ref, bound mask
    checksum, and removed count. This function does not resolve artifact refs.
    Floor classification is diagnostic only: floor, low obstacles, and below-floor
    points all remain in the collision candidate.
    """
    raw = np.asarray(points_world_m)
    if raw.ndim != 2 or raw.shape[1] != 3 or not np.issubdtype(raw.dtype, np.number):
        raise ValueError("LiDAR collision input must be a numeric (N, 3) array in world meters")
    if len(raw) == 0 or len(raw) > profile.max_input_points:
        raise ValueError("LiDAR collision point count is empty or exceeds the profile limit")
    if not np.isfinite(raw).all():
        raise ValueError("LiDAR collision points contain non-finite values")

    source_checksum = point_cloud_checksum(raw)
    if floor_model.source_checksum != source_checksum:
        raise ValueError("floor model does not bind the exact ordered LiDAR point cloud")
    if floor_model.status != "supported" or floor_model.floor_band_m is None:
        raise ValueError("LiDAR collision requires a supported measured floor model")
    if floor_model.plane_normal_world is None or floor_model.plane_offset_m is None:
        raise ValueError("LiDAR collision floor model has no measured plane")

    points = np.asarray(raw, dtype=np.float64)
    if self_mask is None:
        if self_mask_ref is not None:
            raise ValueError("self-mask evidence reference has no resolved mask")
        mask = np.zeros(len(points), dtype=bool)
        mask_checksum = None
    else:
        mask = np.asarray(self_mask)
        if mask.dtype != np.bool_ or mask.shape != (len(points),):
            raise ValueError("self-mask must be a boolean vector aligned with the source point ordering")
        if self_mask_ref is None:
            raise ValueError("a supplied LiDAR self-mask requires an evidence reference artifact")
        mask_checksum = lidar_self_mask_binding_checksum(source_checksum, mask)
    retained = points[~mask]
    if len(retained) == 0:
        raise ValueError("self-mask removed every LiDAR point")

    normal = np.asarray(floor_model.plane_normal_world, dtype=np.float64)
    signed_distance = retained @ normal + float(floor_model.plane_offset_m)
    floor_band_m = float(floor_model.floor_band_m)
    floor_count = int(np.count_nonzero(np.abs(signed_distance) <= floor_band_m))
    above_count = int(np.count_nonzero(signed_distance > floor_band_m))
    below_count = int(np.count_nonzero(signed_distance < -floor_band_m))

    voxel_m = float(profile.voxel_m)
    scaled = retained / voxel_m
    int64_max = np.iinfo(np.int64).max - 4
    if np.max(np.abs(scaled)) > int64_max:
        raise ValueError("LiDAR coordinates exceed the bounded voxel index range")
    voxel_indices = np.floor(scaled).astype(np.int64)
    low = voxel_indices.min(axis=0) - 1
    high = voxel_indices.max(axis=0) + 2
    shape = high - low + 1
    cell_count = math.prod(int(component) for component in shape)
    if cell_count > profile.max_voxel_cells:
        raise ValueError("LiDAR collision voxel grid exceeds the profile cell limit")

    occupied = np.zeros(tuple(int(component) for component in shape), dtype=bool)
    local_indices = voxel_indices - low
    occupied[local_indices[:, 0], local_indices[:, 1], local_indices[:, 2]] = True
    connectivity = np.zeros((3, 3, 3), dtype=np.uint8)
    connectivity[1, 1, 1] = 1
    connectivity[0, 1, 1] = connectivity[2, 1, 1] = 1
    connectivity[1, 0, 1] = connectivity[1, 2, 1] = 1
    connectivity[1, 1, 0] = connectivity[1, 1, 2] = 1
    components, _ = ndimage.label(occupied, structure=connectivity)
    face_count = sum(int(np.count_nonzero(_exposed_voxels(occupied, axis, side))) for axis, side, _ in _EXPOSED_FACES)
    triangle_count = face_count * 2
    if triangle_count > profile.max_triangles:
        raise ValueError("LiDAR collision mesh exceeds the profile triangle limit")

    positions: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    vertex_ids: dict[tuple[int, int, int, int], int] = {}
    for axis, side, face_corners in _EXPOSED_FACES:
        for cell in np.argwhere(_exposed_voxels(occupied, axis, side)):
            lattice_cell = cell + low
            component = int(components[tuple(cell)])
            face_vertex_ids: list[int] = []
            for corner_index in face_corners:
                corner = _VOXEL_CORNERS[corner_index]
                lattice_vertex = tuple(int(lattice_cell[i]) + corner[i] for i in range(3))
                vertex_key = (component, *lattice_vertex)
                vertex_id = vertex_ids.get(vertex_key)
                if vertex_id is None:
                    vertex_id = len(positions)
                    vertex_ids[vertex_key] = vertex_id
                    positions.append(tuple(coordinate * voxel_m for coordinate in lattice_vertex))
                face_vertex_ids.append(vertex_id)
            a, b, c, d = face_vertex_ids
            triangles.extend(((a, b, c), (a, c, d)))

    mesh = CollisionMesh(
        positions=tuple(positions),
        triangles=tuple(triangles),
    )
    glb_bytes = encode_collision_glb(mesh)
    report = LidarCollisionBuildReport(
        source_point_checksum=source_checksum,
        floor_model_checksum="sha256:" + hashlib.sha256(canonical_json_bytes(floor_model)).hexdigest(),
        floor_profile_checksum=floor_model.profile_checksum,
        profile_checksum=profile.checksum(),
        profile_id=profile.profile_id,
        algorithm=profile.algorithm,
        voxel_m=profile.voxel_m,
        output_collision_checksum="sha256:" + hashlib.sha256(glb_bytes).hexdigest(),
        self_mask_evidence_ref=self_mask_ref,
        self_mask_binding_checksum=mask_checksum,
        input_point_count=len(points),
        retained_point_count=len(retained),
        self_masked_point_count=int(mask.sum()),
        floor_support_point_count=floor_count,
        above_floor_point_count=above_count,
        below_floor_point_count=below_count,
        occupied_voxel_count=int(occupied.sum()),
        vertex_count=len(mesh.positions),
        triangle_count=len(mesh.triangles),
    )
    return LidarCollisionBuild(mesh=mesh, glb_bytes=glb_bytes, report=report)
