"""Resolve verified source collision and legacy extraction ownership for all consumers."""

import json

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.collision_quality import CollisionInputMode, CollisionSourceMode, CollisionSourceSelection
from src.models.contracts.scene import SceneIR, SceneObjectOrigin, SourceCollisionRegion
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.orchestration.processing.config import job_config_reference
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction.adapters.lidar_collision import LidarCollisionBuildReport
from src.services.reconstruction.lidar.collision_candidate_publisher import (
    LidarCollisionCandidateManifest,
    load_lidar_collision_eligibility_inputs,
)
from src.services.reconstruction.lidar.collision_eligibility import evaluate_lidar_collision_eligibility
from src.services.scene.collision_ownership import SourceCollisionOwnershipError, bind_source_collision_ownership
from src.services.scene.effective_collision import CarvedBackground, compose_effective_collision
from src.services.simulation.colliders.carve import COLLISION_CARVE_MARGIN_M
from src.services.simulation.usd.physics_config import physics_build_config

#: Operations that replace the whole reconstructed object set. Their revision still holds each object at
#: the pose it was extracted with, so it is the original artifact ownership can be recovered from.
_EXTRACTION_OPERATIONS = frozenset({"objectify", "use_boxes"})


def _recover_legacy_source_ownership(
    registry: ProjectRegistry, job_id: str, scene: SceneIR
) -> tuple[SceneIR, dict[str, str]]:
    """Recover omitted ownership without ever using an edited pose.

    1. An earlier checksum-validated revision of the same object (same id and geometry artifact) that
       already carries ownership wins.
    2. Otherwise the object's unbroken run of revisions must start at an extraction output: the root
       revision, or the first revision of a re-extraction. That revision still has the pose the object
       was extracted with, which is exactly what `bind_source_collision_ownership` records.
    Anything else stays unrecovered and the carve fails closed.
    """
    current_objects = {item.id: item for item in scene.objects}
    # A duplicate never owns a source region, so it must not send recovery through the whole history.
    missing = {
        item.id
        for item in scene.objects
        if item.origin == SceneObjectOrigin.RECONSTRUCTED
        and item.source_collision is None
        and item.provenance.get("duplicated_from") is None
    }
    selected_source_ref = scene.environment.collision_source_ref
    if selected_source_ref is not None:
        incomplete = [
            item.id
            for item in scene.objects
            if item.origin == SceneObjectOrigin.RECONSTRUCTED
            and item.provenance.get("duplicated_from") is None
            and (
                item.source_collision is None
                or item.source_collision.source_geometry_ref != selected_source_ref
                or item.source_collision.region_kind != "triangle_indices"
            )
        ]
        if incomplete:
            raise SourceCollisionOwnershipError(
                "selected collision source cannot recover ownership from RGB history; remap exact LiDAR regions for: "
                + ", ".join(sorted(incomplete))
            )
        return scene, {}
    if not missing:
        return scene, {}

    recovered: dict[str, tuple[SourceCollisionRegion, str]] = {}
    run_start: dict[str, SceneIR] = {object_id: scene for object_id in missing}
    open_runs, introduced = set(missing), set[str]()
    seen = {scene.scene_revision}
    cursor = scene
    while missing:
        # A restore republishes the objects of `restored_from` verbatim, so their history continues there
        # rather than in the revision that happened to be current when the restore was requested.
        restored_from = cursor.provenance.get("restored_from")
        previous_revision = restored_from if cursor.provenance.get("operation") == "restore_revision" else None
        if not isinstance(previous_revision, str):
            previous_revision = cursor.provenance.get("edited_from")
        if not isinstance(previous_revision, str):
            previous_revision = cursor.provenance.get("previous_revision")
        if not isinstance(previous_revision, str) or previous_revision in seen:
            break
        seen.add(previous_revision)
        prior_record = registry.scene.revision(job_id, previous_revision)
        if prior_record is None:
            break
        prior = prior_record.scene
        if prior.scene_id != scene.scene_id or prior.environment.geometry_ref != scene.environment.geometry_ref:
            break
        prior_objects = {item.id: item for item in prior.objects}
        for object_id in tuple(missing):
            prior_object = prior_objects.get(object_id)
            # A re-extraction reuses ids (candidate-001...) for different objects; only the same
            # immutable geometry artifact proves an earlier revision describes this object.
            same_object = (
                prior_object is not None
                and prior_object.origin == SceneObjectOrigin.RECONSTRUCTED
                and prior_object.geometry_ref == current_objects[object_id].geometry_ref
            )
            owner = prior_object.source_collision if same_object and prior_object is not None else None
            if (
                owner is not None
                and owner.object_id == object_id
                and owner.source_geometry_ref == scene.environment.geometry_ref
            ):
                recovered[object_id] = owner, previous_revision
                missing.remove(object_id)
            elif object_id in open_runs:
                if same_object:
                    run_start[object_id] = prior
                else:
                    open_runs.discard(object_id)
                    introduced.add(object_id)
        cursor = prior

    for object_id in tuple(missing):
        start = run_start[object_id]
        is_root = start.provenance.get("edited_from") is None and start.provenance.get("previous_revision") is None
        extracted_here = object_id in introduced and start.provenance.get("operation") in _EXTRACTION_OPERATIONS
        if not (is_root or extracted_here) or start.environment.geometry_ref != scene.environment.geometry_ref:
            continue
        start_object = next(item for item in start.objects if item.id == object_id)
        try:
            (bound,) = bind_source_collision_ownership(
                [start_object], start.environment.geometry_ref, start.scene_revision
            )
        except ValueError:
            continue
        if bound.source_collision is not None:
            recovered[object_id] = bound.source_collision, start.scene_revision

    if not recovered:
        return scene, {}
    owners = {object_id: entry[0] for object_id, entry in recovered.items()}
    recovery_sources = {object_id: entry[1] for object_id, entry in sorted(recovered.items())}
    objects = [
        item.model_copy(update={"source_collision": owners[item.id]}, deep=True) if item.id in owners else item
        for item in scene.objects
    ]
    recovered_scene = scene.model_copy(
        update={
            "objects": objects,
            "provenance": {
                **scene.provenance,
                "source_collision_ownership_recovered": recovery_sources,
            },
        },
        deep=True,
    )
    return recovered_scene, recovery_sources


def _selected_collision_source(registry: ProjectRegistry, scene: SceneIR) -> tuple[ProductArtifactRef, bytes]:
    """Resolve and revalidate a selected sensor-package candidate before any export use."""
    environment = scene.environment
    source_ref = environment.collision_source_ref
    selection_ref = environment.collision_selection_ref
    if source_ref is None and selection_ref is None:
        return environment.geometry_ref, registry.runtime_resolver.require(environment.geometry_ref).read_bytes()
    if source_ref is None or selection_ref is None:
        raise SourceCollisionOwnershipError("selected collision source refs are incomplete; refusing RGB fallback")

    try:
        selection = CollisionSourceSelection.model_validate_json(
            registry.runtime_resolver.require(selection_ref).read_bytes()
        )
        if (
            selection.mode != CollisionSourceMode.LIDAR_DERIVED
            or selection.input_mode != CollisionInputMode.LIDAR_SENSOR_PACKAGE
            or selection.output_collision_ref != source_ref
            or selection.source_qa_ref.artifact_type != "LidarCalibrationQAReport"
            or selection.alignment_qa_ref is None
            or selection.alignment_qa_ref.artifact_type != "LidarCalibrationProjectionEvidence"
        ):
            raise ValueError("selection mode, QA, or output does not match the selected LiDAR source")
        raw_manifest_ref = selection_ref.source_provenance.get("candidate_manifest_ref")
        if not isinstance(raw_manifest_ref, dict):
            raise ValueError("selection ref does not bind a candidate manifest")
        manifest_ref = ProductArtifactRef.model_validate(raw_manifest_ref)
        if manifest_ref.artifact_type != "LidarCollisionCandidateManifest" or manifest_ref.job_id != source_ref.job_id:
            raise ValueError("candidate manifest ref belongs to another artifact contract or job")
        manifest = LidarCollisionCandidateManifest.model_validate_json(
            registry.runtime_resolver.require(manifest_ref).read_bytes()
        )
        evidence_refs = {reference.artifact_type: reference for reference in manifest.eligibility_evidence_refs}
        if (
            manifest.candidate_ref != source_ref
            or manifest.source_geometry_ref != selection.source_geometry_ref
            or evidence_refs.get("LidarCalibrationQAReport") != selection.source_qa_ref
            or evidence_refs.get("LidarCalibrationProjectionEvidence") != selection.alignment_qa_ref
            or manifest.profile_checksum != selection.profile_checksum
            or manifest.profile_checksum != selection.config_checksum
        ):
            raise ValueError("selection does not bind the manifest source, QA, profile, or output")
        eligibility_inputs = load_lidar_collision_eligibility_inputs(manifest, registry.runtime_resolver)
        eligibility = evaluate_lidar_collision_eligibility(eligibility_inputs)
        if eligibility.state != "eligible" or eligibility != manifest.eligibility:
            raise ValueError("candidate eligibility is no longer valid")
        report = LidarCollisionBuildReport.model_validate_json(
            registry.runtime_resolver.require(manifest.build_report_ref).read_bytes()
        )
        if (
            report.output_collision_checksum != manifest.output_collision_checksum
            or report.profile_checksum != manifest.profile_checksum
            or report.profile_id != manifest.profile.profile_id
            or report.voxel_m != manifest.profile.voxel_m
            or report.source_point_checksum != manifest.source_point_checksum
            or report.self_mask_evidence_ref != manifest.self_mask_evidence_ref
            or report.self_mask_binding_checksum != manifest.self_mask_binding_checksum
        ):
            raise ValueError("candidate build report differs from its immutable manifest")
        return source_ref, registry.runtime_resolver.require(source_ref).read_bytes()
    except (ArtifactStoreError, TypeError, ValueError) as error:
        raise SourceCollisionOwnershipError(
            f"selected LiDAR source could not be revalidated; refusing to fall back to canonical RGB geometry: {error}"
        ) from error


def effective_environment(
    registry: ProjectRegistry, scene: SceneIR, *, margin_m: float = COLLISION_CARVE_MARGIN_M
) -> CarvedBackground:
    source_ref, glb = _selected_collision_source(registry, scene)
    return compose_effective_collision(
        scene, source_ref, glb, lambda ref: registry.runtime_resolver.require(ref).read_bytes(), margin_m=margin_m
    )


def _job_simulation_config(registry: ProjectRegistry, job_id: str) -> dict[str, bool | float]:
    """Read checksum-bound job controls; legacy jobs without an artifact retain defaults."""
    job = registry.get_job(job_id)
    reference = job_config_reference(job_id, job.config_checksum)
    if registry.runtime_resolver.locate(reference.artifact_uri) is None:
        return physics_build_config({})
    payload = json.loads(registry.runtime_resolver.require(reference).read_bytes())
    values = payload.get("simulation", {})
    if not isinstance(values, dict):
        raise ValueError("job simulation config must be an object")
    ground = values.get("ground_plane")
    if isinstance(ground, str):
        if ground not in {"enabled", "disabled"}:
            raise ValueError("job ground_plane must be enabled or disabled")
        values["ground_plane"] = ground == "enabled"
    return physics_build_config(values)
