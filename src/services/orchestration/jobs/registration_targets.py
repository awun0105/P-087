"""Resolve checksum-bound RGB collision geometry and measured floor evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.floor_model import FloorFitEvidence
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.manifests import StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationInputMode,
    RegistrationRequest,
)
from src.services.orchestration.artifacts.store import ArtifactResolver
from src.services.orchestration.scene.floor_evidence import load_floor_fit_evidence
from src.services.reconstruction.adapters.collision_glb import read_collision_glb
from src.services.reconstruction.alignment.bev_search import RegistrationFloorPlane

_GLB_MAX_BYTES = (1 << 32) - 1
_SURFACE_SAMPLING_METHOD = "seeded_uniform_triangle_centroid_v1"


class RegistrationTargetResolutionError(ValueError):
    """The request's RGB collision geometry or measured target floor is unusable."""


@dataclass(frozen=True)
class VerifiedRegistrationTarget:
    """Bounded surface samples and floor plane from exact target-job artifacts."""

    collision_surface_points_world_m: np.ndarray
    collision_surface_normals_world: np.ndarray
    target_floor: RegistrationFloorPlane
    metric_confirmation_ref: ProductArtifactRef
    target_rgb_geometry_ref: ProductArtifactRef
    floor_evidence_ref: ProductArtifactRef
    floor_fit_evidence: FloorFitEvidence
    mesh_vertex_count: int
    mesh_triangle_count: int
    surface_sampling_method: Literal["seeded_uniform_triangle_centroid_v1"]
    profile_checksum: str


class RegistrationTargetResolver:
    """Load canonical target surface points and one measured floor from artifact storage."""

    def __init__(self, resolver: ArtifactResolver, *, max_collision_glb_bytes: int) -> None:
        if (
            isinstance(max_collision_glb_bytes, bool)
            or not isinstance(max_collision_glb_bytes, int)
            or not 0 < max_collision_glb_bytes <= _GLB_MAX_BYTES
        ):
            raise ValueError("maximum collision GLB size must be a positive uint32-sized byte limit")
        self.resolver = resolver
        self.max_collision_glb_bytes = max_collision_glb_bytes

    def resolve(self, request: RegistrationRequest) -> VerifiedRegistrationTarget:
        """Recheck request identity, then load bounded points from its canonical GLB."""
        verify_content_checksum(request, "request_checksum")
        if request.profile.checksum() != request.profile_checksum:
            raise RegistrationTargetResolutionError("registration profile checksum changed")
        if request.source.mode not in {RegistrationInputMode.REGISTERED_MAP, RegistrationInputMode.STATIC_CLOUD}:
            raise RegistrationTargetResolutionError("RGB target resolver only accepts independent map requests")
        if request.floor_state != "supported" or len(request.floor_evidence_refs) != 1:
            raise RegistrationTargetResolutionError(
                "map registration requires exactly one supported target floor evidence reference"
            )

        geometry_ref = request.target_rgb_geometry_ref
        self._validate_target_ref(geometry_ref, request.target_job_id, "RgbGeometry", StageId.RGB_GEOMETRY)
        metric_ref, master_ref = self._target_metric_sources(request, geometry_ref)
        self.resolver.require_uri(metric_ref.artifact_uri, metric_ref.artifact_checksum)
        floor_ref = request.floor_evidence_refs[0]
        self._validate_target_ref(floor_ref, request.target_job_id, "FloorFitEvidence", StageId.OBJECT_EXTRACT)

        geometry_path = self.resolver.require_uri(geometry_ref.artifact_uri, geometry_ref.artifact_checksum)
        if geometry_path.stat().st_size > self.max_collision_glb_bytes:
            raise RegistrationTargetResolutionError("canonical RGB collision GLB exceeds the worker byte limit")
        try:
            mesh = read_collision_glb(geometry_path)
        except ValueError as error:
            raise RegistrationTargetResolutionError("canonical RGB collision GLB is malformed") from error

        profile = request.profile
        if len(mesh.positions) > profile.max_source_points or len(mesh.triangles) > profile.max_source_points:
            raise RegistrationTargetResolutionError("canonical RGB collision mesh exceeds the sealed point budget")
        if len(mesh.triangles) < 3:
            raise RegistrationTargetResolutionError("canonical RGB collision mesh has insufficient surface support")

        selected_indices = self._sample_triangle_indices(
            len(mesh.triangles), profile.max_points_per_map, profile.search_seed
        )
        selected_triangles = [mesh.triangles[index] for index in selected_indices]
        triangle_vertices = np.asarray(
            [[mesh.positions[vertex] for vertex in triangle] for triangle in selected_triangles], dtype=np.float64
        )
        points = triangle_vertices.mean(axis=1)
        face_normals = np.cross(
            triangle_vertices[:, 1] - triangle_vertices[:, 0],
            triangle_vertices[:, 2] - triangle_vertices[:, 0],
        )
        lengths = np.linalg.norm(face_normals, axis=1)
        if not np.isfinite(points).all() or not np.isfinite(lengths).all() or np.any(lengths <= 0):
            raise RegistrationTargetResolutionError("canonical RGB surface has invalid triangle geometry")
        normals = face_normals / lengths[:, None]

        try:
            floor_evidence = load_floor_fit_evidence(floor_ref, self.resolver.require)
        except (ValidationError, ValueError, OSError) as error:
            raise RegistrationTargetResolutionError("target floor-fit evidence is malformed") from error
        if not any(
            floor_evidence.source_artifact_ref == expected for expected in (geometry_ref, metric_ref, master_ref)
        ):
            raise RegistrationTargetResolutionError(
                "target floor evidence is not bound to the exact RGB geometry lineage"
            )
        floor_model = floor_evidence.floor_model
        if (
            floor_model.status != "supported"
            or floor_model.plane_normal_world is None
            or floor_model.plane_offset_m is None
        ):
            raise RegistrationTargetResolutionError("target floor model does not contain a measured supported plane")
        if floor_model.prior is None:
            raise RegistrationTargetResolutionError("target floor model is missing its confirmed up direction")

        floor = RegistrationFloorPlane(
            frame="world",
            normal_xyz=floor_model.plane_normal_world,
            offset_m=float(floor_model.plane_offset_m),
            up_direction_xyz=floor_model.prior.up_direction_world,
            evidence_checksum=floor_ref.artifact_checksum,
        )
        points.setflags(write=False)
        normals.setflags(write=False)
        return VerifiedRegistrationTarget(
            collision_surface_points_world_m=points,
            collision_surface_normals_world=normals,
            target_floor=floor,
            metric_confirmation_ref=metric_ref,
            target_rgb_geometry_ref=geometry_ref,
            floor_evidence_ref=floor_ref,
            floor_fit_evidence=floor_evidence,
            mesh_vertex_count=len(mesh.positions),
            mesh_triangle_count=len(mesh.triangles),
            surface_sampling_method=_SURFACE_SAMPLING_METHOD,
            profile_checksum=request.profile_checksum,
        )

    @staticmethod
    def _target_metric_sources(
        request: RegistrationRequest, geometry_ref: ProductArtifactRef
    ) -> tuple[ProductArtifactRef, ProductArtifactRef]:
        """Read exact metric/master lineage embedded by the current RGB geometry publisher."""
        provenance = geometry_ref.source_provenance
        try:
            if not isinstance(provenance, dict):
                raise TypeError("missing geometry provenance")
            metric_ref = ProductArtifactRef.model_validate(provenance["metric_confirmation_ref"])
            preprocessing = provenance["preprocessing_provenance"]
            master_ref = ProductArtifactRef.model_validate(preprocessing["details"]["master"])
        except (KeyError, TypeError, ValidationError) as error:
            raise RegistrationTargetResolutionError("RGB geometry is missing exact metric/master provenance") from error

        if (
            metric_ref.artifact_type != "RGBMetricConfirmation"
            or metric_ref.job_id != request.target_job_id
            or metric_ref.producer_stage != StageId.METRIC_CANONICALIZE
            or not metric_ref.artifact_uri.startswith(f"artifact://jobs/{request.target_job_id}/")
        ):
            raise RegistrationTargetResolutionError("RGB geometry metric provenance is not bound to the target job")
        if request.metric_state == "confirmed" and request.metric_confirmation_ref != metric_ref:
            raise RegistrationTargetResolutionError(
                "request metric confirmation differs from the RGB geometry producer"
            )
        if (
            master_ref.artifact_type != "GaussianPLY"
            or master_ref.job_id != request.target_job_id
            or not master_ref.artifact_uri.startswith(f"artifact://jobs/{request.target_job_id}/")
        ):
            raise RegistrationTargetResolutionError("RGB geometry master provenance is not bound to the target job")
        return metric_ref, master_ref

    @staticmethod
    def _validate_target_ref(
        reference: ProductArtifactRef,
        job_id: str,
        artifact_type: str,
        producer_stage: StageId | None = None,
    ) -> None:
        if (
            reference.artifact_type != artifact_type
            or reference.job_id != job_id
            or not reference.artifact_uri.startswith(f"artifact://jobs/{job_id}/")
            or (producer_stage is not None and reference.producer_stage != producer_stage)
        ):
            raise RegistrationTargetResolutionError(f"registration target reference is not a same-job {artifact_type}")

    @staticmethod
    def _sample_triangle_indices(triangle_count: int, sample_limit: int, seed: int) -> np.ndarray:
        if triangle_count <= sample_limit:
            return np.arange(triangle_count, dtype=np.int64)
        selected = np.random.default_rng(seed ^ 0xA5A5_19E3).choice(triangle_count, size=sample_limit, replace=False)
        return np.sort(selected.astype(np.int64, copy=False))
