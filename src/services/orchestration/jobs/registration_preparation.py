"""Build a sealed independent-map registration request from one accepted input run."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.input_assembly import (
    CloudObservationState,
    InputRecipe,
    InputRole,
    RecipeGroup,
    verify_input_assembly_checksum,
    verify_input_recipe_checksum,
)
from src.models.contracts.manifests import JobManifest, StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationInputMode,
    RegistrationPreflight,
    RegistrationPreflightState,
    RegistrationProfile,
    RegistrationRequest,
    RegistrationROI,
    RegistrationSourceBinding,
    registration_preflight,
    seal_registration_profile,
    seal_registration_request,
)
from src.models.contracts.scene import SceneIR
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.inputs.assembly import InputAssemblyService
from src.services.orchestration.jobs.registration_sources import RegistrationSourceResolver
from src.services.orchestration.jobs.registration_targets import RegistrationTargetResolver
from src.services.orchestration.projects import ProjectRegistry
from src.services.orchestration.scene.floor_evidence import load_floor_fit_evidence
from src.services.reconstruction.adapters.collision_glb import read_collision_glb

_CHECKSUM_PLACEHOLDER = "sha256:" + "0" * 64
_DEFAULT_PROFILE_ID = "studio-registration-provisional-v1"
_ROI_PADDING_M = 0.5


class RegistrationRequestPreparationError(ValueError):
    """The accepted job does not contain enough exact evidence to prepare registration."""


class RegistrationSceneRevisionConflictError(RegistrationRequestPreparationError):
    """The caller prepared against a scene revision that is no longer current."""


@dataclass(frozen=True)
class PreparedRegistrationRequest:
    request: RegistrationRequest
    preflight: RegistrationPreflight


class RegistrationRequestPreparer:
    """Derive a checksum-bound request without trusting browser-supplied artifact claims."""

    def __init__(
        self,
        registry: ProjectRegistry,
        assemblies: InputAssemblyService,
        *,
        max_collision_glb_bytes: int,
        max_source_points: int = 20_000_000,
    ) -> None:
        if registry.persistence is None:
            raise ValueError("registration preparation requires persistent input-run lineage")
        if max_source_points < 1:
            raise ValueError("registration source point limit must be positive")
        self.registry = registry
        self.assemblies = assemblies
        self.max_collision_glb_bytes = max_collision_glb_bytes
        self.max_source_points = max_source_points
        self.source_resolver = RegistrationSourceResolver(assemblies, registry.persistence)
        self.target_resolver = RegistrationTargetResolver(
            registry.runtime_resolver,
            max_collision_glb_bytes=max_collision_glb_bytes,
        )

    def prepare(
        self,
        job: JobManifest,
        *,
        requested_by: str,
        expected_scene_revision: str,
    ) -> PreparedRegistrationRequest:
        """Build and check a request against the accepted recipe and current scene head."""
        current = self.registry.scene.current(job.job_id).scene
        if current.scene_revision != expected_scene_revision:
            raise RegistrationSceneRevisionConflictError(
                "scene revision changed; refresh before preparing registration"
            )
        if current.environment.geometry_ref.artifact_type != "RgbGeometry":
            raise RegistrationRequestPreparationError("current scene does not use canonical RGB geometry")

        run = self.registry.persistence.input_run_for_job(job.job_id)
        if run is None:
            raise RegistrationRequestPreparationError("job has no durable accepted input-assembly run")
        project = self.registry.get_project(job.project_id)
        if project.input_recipe_ref != run.recipe_ref:
            raise RegistrationRequestPreparationError("accepted job recipe reference differs from durable lineage")
        recipe = self.registry.runtime_resolver.load_model(run.recipe_ref, InputRecipe)
        try:
            verify_input_recipe_checksum(recipe)
        except ValueError as error:
            raise RegistrationRequestPreparationError("accepted input recipe checksum is invalid") from error
        if (
            recipe.assembly_id != run.assembly_id
            or recipe.assembly_revision != run.assembly_revision
            or recipe.assembly_checksum != run.assembly_checksum
            or recipe.resolution_checksum != run.resolution_checksum
            or recipe.candidate_id != run.candidate_id
            or recipe.recipe_checksum != run.recipe_checksum
        ):
            raise RegistrationRequestPreparationError("accepted recipe differs from its durable input-run record")

        mode, role, source_file_id = self._accepted_map_source(recipe)
        stored = self.assemblies.get_assembly(run.assembly_id, run.assembly_revision)
        snapshot = stored.snapshot
        try:
            verify_input_assembly_checksum(snapshot)
        except ValueError as error:
            raise RegistrationRequestPreparationError("accepted input assembly checksum is invalid") from error
        if (
            snapshot.assembly_id != run.assembly_id
            or snapshot.revision != run.assembly_revision
            or snapshot.assembly_checksum != run.assembly_checksum
        ):
            raise RegistrationRequestPreparationError("accepted recipe does not name the exact assembly revision")
        if not any(binding.role == role and binding.file_ids == [source_file_id] for binding in snapshot.bindings):
            raise RegistrationRequestPreparationError("accepted source file is not bound to its declared assembly role")

        declarations = snapshot.declarations
        declared_cloud_state = declarations.cloud_state.value if declarations.cloud_state is not None else None
        expected_cloud_state = (
            CloudObservationState.REGISTERED_MAP
            if mode == RegistrationInputMode.REGISTERED_MAP
            else CloudObservationState.SINGLE_STATIC_CLOUD
        )
        if declared_cloud_state != expected_cloud_state:
            raise RegistrationRequestPreparationError("accepted cloud-state declaration differs from its recipe")
        source_unit = declarations.coordinate_unit.value if declarations.coordinate_unit is not None else None
        source_frame = declarations.lidar_frame_id.value if declarations.lidar_frame_id is not None else None
        same_scene = declarations.same_scene.value if declarations.same_scene is not None else None
        profile = self._profile()

        with tempfile.TemporaryDirectory(prefix="r2s-registration-prepare-") as workspace:
            inspected = self.source_resolver.inspect_staged_source(
                mode=mode,
                assembly_id=snapshot.assembly_id,
                assembly_revision=snapshot.revision,
                source_role=role,
                source_file_id=source_file_id,
                distance_unit=source_unit,
                source_frame=source_frame,
                same_scene_attestation=same_scene,
                workspace=Path(workspace),
                max_source_points=profile.max_source_points,
                expected_assembly_checksum=snapshot.assembly_checksum,
            )

            geometry_ref = current.environment.geometry_ref
            metric_ref = self._metric_ref(geometry_ref, job.job_id)
            floor_ref, floor_state = self._floor_ref(current, job.job_id)
            roi = self._target_roi(job.job_id, geometry_ref, profile)
            source = RegistrationSourceBinding(
                mode=mode,
                target_job_id=job.job_id,
                authorized_project_id=job.project_id,
                source_input_checksum=inspected.source_checksum,
                source_frame=inspected.source_frame,
                source_distance_unit=inspected.distance_unit,
                source_point_count=inspected.point_count,
                source_format=inspected.input_format,
                source_header_checksum=inspected.header_checksum,
                source_role=role,
                input_assembly_id=inspected.input_assembly_id,
                input_assembly_revision=inspected.input_assembly_revision,
                input_assembly_checksum=inspected.input_assembly_checksum,
                source_file_ids=[inspected.file_id],
                same_scene_attestation=inspected.same_scene_attestation,
            )
            request = seal_registration_request(
                {
                    "request_id": f"registration-request-{uuid4().hex}",
                    "requested_by": requested_by,
                    "target_project_id": job.project_id,
                    "target_job_id": job.job_id,
                    "target_rgb_geometry_ref": geometry_ref,
                    "expected_scene_revision": current.scene_revision,
                    "source": source,
                    "metric_state": "confirmed" if metric_ref is not None else "unknown",
                    "metric_confirmation_ref": metric_ref,
                    "floor_state": floor_state,
                    "floor_model_refs": [floor_ref] if floor_ref is not None else [],
                    "target_roi_world": roi,
                    "profile": profile,
                    "profile_checksum": profile.profile_checksum,
                    "request_checksum": _CHECKSUM_PLACEHOLDER,
                }
            )
            preflight = registration_preflight(request)
            if preflight.state == RegistrationPreflightState.READY:
                verified_source = self.source_resolver.resolve(request, Path(workspace))
                if not verified_source.same_scene_lineage_verified:
                    raise RegistrationRequestPreparationError(
                        "selected LiDAR map is not part of this job's accepted RGB input lineage"
                    )
                self.target_resolver.resolve(request)
        return PreparedRegistrationRequest(request=request, preflight=preflight)

    @staticmethod
    def _accepted_map_source(recipe: InputRecipe) -> tuple[RegistrationInputMode, InputRole, str]:
        role_by_group = {
            RecipeGroup.REGISTERED_MAP: (RegistrationInputMode.REGISTERED_MAP, InputRole.REGISTERED_LIDAR_MAP),
            RecipeGroup.SINGLE_STATIC_CLOUD: (RegistrationInputMode.STATIC_CLOUD, InputRole.STATIC_LIDAR_CLOUD),
        }
        expected = role_by_group.get(recipe.recipe_group)
        if expected is None:
            raise RegistrationRequestPreparationError(
                "automatic registration preparation supports accepted R2 registered-map and R3 static-cloud recipes"
            )
        mode, role = expected
        bindings = [item for item in recipe.bindings if item.role == role]
        if len(bindings) != 1 or len(bindings[0].file_ids) != 1:
            raise RegistrationRequestPreparationError("accepted map recipe must bind exactly one point-cloud file")
        if not any(item.role == InputRole.RGB_VIDEO for item in recipe.bindings):
            raise RegistrationRequestPreparationError("accepted map recipe has no RGB video binding")
        return mode, role, bindings[0].file_ids[0]

    def _metric_ref(self, geometry_ref: ProductArtifactRef, job_id: str) -> ProductArtifactRef | None:
        provenance = geometry_ref.source_provenance
        if not isinstance(provenance, dict):
            return None
        raw_ref = provenance.get("metric_confirmation_ref")
        if raw_ref is None:
            return None
        try:
            reference = ProductArtifactRef.model_validate(raw_ref)
        except ValidationError as error:
            raise RegistrationRequestPreparationError("RGB geometry metric provenance is malformed") from error
        if (
            reference.artifact_type != "RGBMetricConfirmation"
            or reference.producer_stage != StageId.METRIC_CANONICALIZE
            or reference.job_id != job_id
            or not reference.artifact_uri.startswith(f"artifact://jobs/{job_id}/")
        ):
            raise RegistrationRequestPreparationError("RGB geometry metric provenance is not bound to this job")
        return reference

    def _floor_ref(self, scene: SceneIR, job_id: str) -> tuple[ProductArtifactRef | None, str]:
        summary = scene.provenance.get("floor_fit")
        if not isinstance(summary, dict) or not isinstance(summary.get("artifact_ref"), dict):
            return None, "unsupported"
        try:
            reference = ProductArtifactRef.model_validate(summary["artifact_ref"])
            path = self.registry.resolve_artifact(job_id, reference)
            evidence = load_floor_fit_evidence(reference, lambda _reference: path)
        except (ArtifactStoreError, ValidationError, ValueError, OSError) as error:
            raise RegistrationRequestPreparationError(
                "current scene floor-fit evidence is unavailable or invalid"
            ) from error
        if evidence.job_id != job_id:
            raise RegistrationRequestPreparationError("floor-fit evidence belongs to another job")
        if evidence.floor_model.status == "supported" and evidence.floor_model.prior is not None:
            return reference, "supported"
        if evidence.floor_model.status == "uncertain":
            return reference, "uncertain"
        return reference, "unsupported"

    def _target_roi(
        self,
        job_id: str,
        geometry_ref: ProductArtifactRef,
        profile: RegistrationProfile,
    ) -> RegistrationROI:
        try:
            path = self.registry.resolve_artifact(job_id, geometry_ref)
            if path.stat().st_size > self.max_collision_glb_bytes:
                raise RegistrationRequestPreparationError(
                    "canonical RGB collision GLB exceeds the registration byte limit"
                )
            mesh = read_collision_glb(path)
        except RegistrationRequestPreparationError:
            raise
        except (ArtifactStoreError, OSError, ValueError) as error:
            raise RegistrationRequestPreparationError(
                "canonical RGB collision geometry is unavailable or invalid"
            ) from error
        mins = [min(point[axis] for point in mesh.positions) - _ROI_PADDING_M for axis in range(3)]
        maxs = [max(point[axis] for point in mesh.positions) + _ROI_PADDING_M for axis in range(3)]
        if any(high - low > profile.max_roi_extent_m for low, high in zip(mins, maxs, strict=True)):
            raise RegistrationRequestPreparationError(
                "canonical RGB scene exceeds the bounded registration ROI; automatic full-scene registration is unavailable"
            )
        return RegistrationROI(min_xyz_m=tuple(mins), max_xyz_m=tuple(maxs))  # type: ignore[arg-type]

    def _profile(self) -> RegistrationProfile:
        return seal_registration_profile(
            {
                "profile_id": _DEFAULT_PROFILE_ID,
                "qualification_state": "provisional",
                "max_source_points": self.max_source_points,
                "profile_checksum": _CHECKSUM_PLACEHOLDER,
            }
        )
