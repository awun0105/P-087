"""Build a sealed independent-map registration request from one accepted input run."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.input_assembly import (
    CloudObservationState,
    DistanceUnit,
    InputAssetFormat,
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

        mode, role, source_file_ids = self._accepted_map_source(recipe)
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
        if not any(binding.role == role and binding.file_ids == source_file_ids for binding in snapshot.bindings):
            raise RegistrationRequestPreparationError("accepted source file is not bound to its declared assembly role")

        declarations = snapshot.declarations
        declared_cloud_state = declarations.cloud_state.value if declarations.cloud_state is not None else None
        expected_cloud_state = {
            RegistrationInputMode.REGISTERED_MAP: CloudObservationState.REGISTERED_MAP,
            RegistrationInputMode.STATIC_CLOUD: CloudObservationState.SINGLE_STATIC_CLOUD,
            RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP: CloudObservationState.RAW_SCAN_SEQUENCE,
        }[mode]
        if declared_cloud_state != expected_cloud_state:
            raise RegistrationRequestPreparationError("accepted cloud-state declaration differs from its recipe")
        source_unit = declarations.coordinate_unit.value if declarations.coordinate_unit is not None else None
        source_frame = declarations.lidar_frame_id.value if declarations.lidar_frame_id is not None else None
        same_scene = declarations.same_scene.value if declarations.same_scene is not None else None
        profile = self._profile()

        with tempfile.TemporaryDirectory(prefix="r2s-registration-prepare-") as workspace:
            estimated_refs: tuple[ProductArtifactRef | None, ProductArtifactRef | None] = (None, None)
            runtime_qualification_status = None
            if mode == RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP:
                estimated_refs = self._latest_estimated_map_refs(job)
                runtime_qualification_status = self._estimated_runtime_status(estimated_refs[0])
                inspected_estimated = self.source_resolver.inspect_estimated_trajectory_map(
                    job_id=job.job_id,
                    project_id=job.project_id,
                    assembly_id=snapshot.assembly_id,
                    assembly_revision=snapshot.revision,
                    assembly_checksum=snapshot.assembly_checksum,
                    source_scan_file_ids=source_file_ids,
                    source_distance_unit=source_unit,
                    source_frame=self._estimated_map_frame(estimated_refs[1]),
                    same_scene_attestation=same_scene,
                    estimated_trajectory_product_ref=estimated_refs[0],
                    estimated_map_cloud_ref=estimated_refs[1],
                    odometry_runtime_qualification_status=runtime_qualification_status,
                    workspace=Path(workspace),
                    max_source_points=profile.max_source_points,
                )
                source_checksum = inspected_estimated.source_checksum
                source_format = InputAssetFormat.POINT_CLOUD_PLY
                header_checksum = inspected_estimated.header_checksum
                point_count = inspected_estimated.point_count
                source_distance_unit = DistanceUnit.METER
                source_frame = inspected_estimated.source_frame
                same_scene = inspected_estimated.same_scene_attestation
                input_assembly_id = inspected_estimated.input_assembly_id
                input_assembly_revision = inspected_estimated.input_assembly_revision
                input_assembly_checksum = inspected_estimated.input_assembly_checksum
            else:
                inspected = self.source_resolver.inspect_staged_source(
                    mode=mode,
                    assembly_id=snapshot.assembly_id,
                    assembly_revision=snapshot.revision,
                    source_role=role,
                    source_file_id=source_file_ids[0],
                    distance_unit=source_unit,
                    source_frame=source_frame,
                    same_scene_attestation=same_scene,
                    workspace=Path(workspace),
                    max_source_points=profile.max_source_points,
                    expected_assembly_checksum=snapshot.assembly_checksum,
                )
                source_checksum = inspected.source_checksum
                source_format = inspected.input_format
                header_checksum = inspected.header_checksum
                point_count = inspected.point_count
                source_distance_unit = inspected.distance_unit
                source_frame = inspected.source_frame
                same_scene = inspected.same_scene_attestation
                input_assembly_id = inspected.input_assembly_id
                input_assembly_revision = inspected.input_assembly_revision
                input_assembly_checksum = inspected.input_assembly_checksum

            geometry_ref = current.environment.geometry_ref
            metric_ref = self._metric_ref(geometry_ref, job.job_id)
            floor_ref, floor_state = self._floor_ref(current, job.job_id)
            roi = self._target_roi(job.job_id, geometry_ref, profile)
            source = RegistrationSourceBinding(
                mode=mode,
                target_job_id=job.job_id,
                authorized_project_id=job.project_id,
                source_input_checksum=source_checksum,
                source_frame=source_frame,
                source_distance_unit=source_distance_unit,
                source_point_count=point_count,
                source_format=source_format,
                source_header_checksum=header_checksum,
                source_role=role,
                input_assembly_id=input_assembly_id,
                input_assembly_revision=input_assembly_revision,
                input_assembly_checksum=input_assembly_checksum,
                source_file_ids=source_file_ids,
                same_scene_attestation=same_scene,
                estimated_trajectory_product_ref=estimated_refs[0],
                estimated_map_cloud_ref=estimated_refs[1],
                odometry_runtime_qualification_status=runtime_qualification_status,
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
    def _accepted_map_source(recipe: InputRecipe) -> tuple[RegistrationInputMode, InputRole, list[str]]:
        role_by_group = {
            RecipeGroup.REGISTERED_MAP: (RegistrationInputMode.REGISTERED_MAP, InputRole.REGISTERED_LIDAR_MAP),
            RecipeGroup.SINGLE_STATIC_CLOUD: (RegistrationInputMode.STATIC_CLOUD, InputRole.STATIC_LIDAR_CLOUD),
            RecipeGroup.SENSOR_GUIDED: (RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP, InputRole.LIDAR_SCAN),
        }
        expected = role_by_group.get(recipe.recipe_group)
        if expected is None:
            raise RegistrationRequestPreparationError(
                "automatic registration preparation supports accepted R2, R3 and R6 map recipes"
            )
        mode, role = expected
        bindings = [item for item in recipe.bindings if item.role == role]
        if (
            len(bindings) != 1
            or (mode == RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP and len(bindings[0].file_ids) < 2)
            or (mode != RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP and len(bindings[0].file_ids) != 1)
        ):
            raise RegistrationRequestPreparationError("accepted map recipe has an invalid source-file binding")
        if not any(item.role == InputRole.RGB_VIDEO for item in recipe.bindings):
            raise RegistrationRequestPreparationError("accepted map recipe has no RGB video binding")
        return mode, role, list(bindings[0].file_ids)

    def _latest_estimated_map_refs(self, job: JobManifest) -> tuple[ProductArtifactRef, ProductArtifactRef]:
        from src.models.contracts.reconstruction import EstimatedTrajectoryProductEvidence

        stage = next(
            (
                item
                for item in reversed(job.stage_artifacts)
                if item.stage_id == StageId.LIDAR_ODOMETRY
                and item.status.value == "SUCCEEDED"
                and item.artifact_type == "EstimatedTrajectoryProductEvidence"
            ),
            None,
        )
        if stage is None or stage.artifact_uri is None or stage.artifact_checksum is None or stage.data_class is None:
            raise RegistrationRequestPreparationError("job has no successful estimated-trajectory product receipt")
        product_ref = ProductArtifactRef(
            artifact_type=stage.artifact_type,
            schema_version="1.0",
            artifact_uri=stage.artifact_uri,
            artifact_checksum=stage.artifact_checksum,
            data_class=stage.data_class,
            producer_stage=stage.stage_id,
            job_id=job.job_id,
        )
        if not product_ref.artifact_uri.startswith(f"artifact://jobs/{job.job_id}/attempts/"):
            raise RegistrationRequestPreparationError("odometry receipt is not attempt scoped")
        evidence = self.registry.runtime_resolver.load_model(product_ref, EstimatedTrajectoryProductEvidence)
        map_ref = evidence.map_evidence.map_cloud_ref
        if evidence.job_id != job.job_id or evidence.map_evidence.map_status != "ready" or map_ref is None:
            raise RegistrationRequestPreparationError("job's estimated trajectory has no ready fused map")
        return product_ref, ProductArtifactRef.model_validate(map_ref.model_dump(mode="python"))

    def _estimated_runtime_status(
        self, product_ref: ProductArtifactRef | None
    ) -> Literal["qualified", "wired_unqualified"]:
        from src.models.contracts.reconstruction import EstimatedTrajectoryProductEvidence

        if product_ref is None:
            raise RegistrationRequestPreparationError("estimated-map receipt is missing")
        evidence = self.registry.runtime_resolver.load_model(product_ref, EstimatedTrajectoryProductEvidence)
        return evidence.consumer_evidence.runtime_qualification_status

    def _estimated_map_frame(self, map_ref: ProductArtifactRef | None) -> str:
        if map_ref is None:
            raise RegistrationRequestPreparationError("estimated-map cloud ref is missing")
        frame_id = (map_ref.source_provenance or {}).get("map_frame_id")
        if not isinstance(frame_id, str) or not frame_id:
            raise RegistrationRequestPreparationError("estimated-map cloud has no declared local map frame")
        return frame_id

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
