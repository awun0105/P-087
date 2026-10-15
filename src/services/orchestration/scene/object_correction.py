"""Revision-bound scene object corrections backed by immutable Gaussian artifacts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Event
from uuid import uuid4

import numpy as np
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import ObjectMembershipMergeCommand, ObjectMembershipReassignCommand
from src.models.contracts.scene import (
    ColliderSpec,
    ColliderType,
    SceneObject,
    SourceCollisionMembership,
    SourceCollisionRegion,
)
from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.models import SceneEditResult
from src.services.orchestration.scene.objectify import CONVEX_RUNNER, INPAINT_RUNNER, _reference, _run
from src.services.process_control import ProcessCancelledError
from src.services.reconstruction.imports import package_splat
from src.services.scene.collision_ownership import SourceCollisionOwnershipError, source_triangle_ownership
from src.services.scene.decomposition import gaussian_split
from src.services.scene.decomposition.gaussian_split import SplitConfig
from src.services.scene.editing.membership import (
    ObjectMembershipValidationError,
    decode_gaussian_membership_labels,
    encode_gaussian_membership_labels,
    validate_object_membership_command,
)
from src.services.scene.floor_model import above_floor_mask, fit_canonical_floor_model, point_cloud_checksum

_IDENTITY = (0.0, 0.0, 0.0, 1.0)
_MIN_OBJECT_GAUSSIANS = 50
_ROI_EPSILON_M = 1e-6


def merge_object_candidates(
    editor: SceneEditor,
    job_id: str,
    command: ObjectMembershipMergeCommand,
    *,
    actor_id: str,
    runtime_python: Path,
    workspace: Path,
    timeout_seconds: float,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
) -> SceneEditResult:
    """Merge source Gaussian ownership and publish its candidate artifacts before the SceneIR CAS."""
    if not actor_id:
        raise ValueError("actor_id is required for a scene correction audit event")
    revision = editor.current(job_id)
    scene = revision.scene
    manifest = validate_object_membership_command(scene, command)
    if scene.environment.object_aware_collision_ref is not None:
        raise ObjectMembershipValidationError(
            "OBJECTGS_RETRAIN_REQUIRED: membership merge requires rebuilt ObjectGS observations/surfaces; "
            "the legacy Gaussian collider producer cannot update this scene"
        )
    objects_by_id = {item.id: item for item in scene.objects}
    selected_ids = [command.primary_object_id, *command.secondary_object_ids]
    selected_objects = [objects_by_id[object_id] for object_id in selected_ids]
    if any(not np.allclose(item.transform.rotation_quaternion_xyzw, _IDENTITY, atol=1e-6) for item in selected_objects):
        raise ObjectMembershipValidationError("merge requires unrotated source frames so Gaussian SH remains valid")

    source_ply = editor.resolver.require(manifest.source_visual_ref).read_bytes()
    source_rows = gaussian_split.read_gaussian_ply(source_ply)
    if len(source_rows) != manifest.gaussian_count:
        raise ObjectMembershipValidationError("source PLY row count does not match membership gaussian_count")
    labels_payload = editor.resolver.require(manifest.labels_ref).read_bytes()
    labels = decode_gaussian_membership_labels(labels_payload, manifest)
    if len(labels) != len(source_rows):
        raise ObjectMembershipValidationError("membership rows do not match source PLY rows")

    collision_geometry_ref = scene.environment.collision_source_ref or manifest.source_geometry_ref
    collision_geometry_bytes = editor.resolver.require(collision_geometry_ref).read_bytes()
    try:
        collision_ownership = source_triangle_ownership(
            scene.objects,
            collision_geometry_ref,
            collision_geometry_bytes,
            lambda reference: editor.resolver.require(reference).read_bytes(),
        )
    except SourceCollisionOwnershipError as error:
        raise ObjectMembershipValidationError(str(error)) from error
    collision_labels_by_object = {
        object_id: int(label) for label, object_id in collision_ownership.label_to_object_id.items()
    }
    missing_collision_regions = [object_id for object_id in selected_ids if object_id not in collision_labels_by_object]
    if missing_collision_regions:
        raise ObjectMembershipValidationError(
            "merge candidates lack source collision ownership: " + ", ".join(sorted(missing_collision_regions))
        )
    selected_collision_labels = [collision_labels_by_object[object_id] for object_id in selected_ids]
    merged_collision_indices = np.flatnonzero(
        np.isin(collision_ownership.owner_labels, selected_collision_labels)
    ).tolist()

    selected_id_set = set(selected_ids)
    selected_label_values = [
        int(label) for label, object_id in manifest.label_to_object_id.items() if object_id in selected_id_set
    ]
    selection = np.isin(labels, selected_label_values)
    gaussian_count = int(np.count_nonzero(selection))
    if gaussian_count == 0:
        raise ObjectMembershipValidationError("merged candidates own no source Gaussian rows")
    for object_id in selected_ids:
        owned_labels = [int(label) for label, owner in manifest.label_to_object_id.items() if owner == object_id]
        if not owned_labels or not np.isin(labels, owned_labels).any():
            raise ObjectMembershipValidationError(f"candidate {object_id} has no source Gaussian rows to merge")

    world_positions = gaussian_split.positions(source_rows[selection])
    if not np.isfinite(world_positions).all():
        raise ObjectMembershipValidationError("selected source Gaussian positions must be finite")
    merged_labels = np.full(manifest.gaussian_count, gaussian_split.BACKGROUND, dtype=np.int32)
    merged_labels[selection] = 0
    _, parts = gaussian_split.split(source_rows, merged_labels, SplitConfig(min_object_gaussians=1))
    if len(parts) != 1:
        raise ObjectMembershipValidationError("selected memberships did not produce exactly one merged Gaussian part")
    part = parts[0]

    primary = objects_by_id[command.primary_object_id]
    primary_origin = np.asarray(primary.transform.translation_xyz, dtype=np.float64)
    visual_rows = source_rows[selection].copy()
    for axis, name in enumerate(("x", "y", "z")):
        visual_rows[name] = (world_positions[:, axis] - primary_origin[axis]).astype(visual_rows.dtype[name])
    visual_payload = gaussian_split.write_gaussian_ply(visual_rows)
    collider_payload = gaussian_split.write_gaussian_ply(part.rows)

    operation_workspace = workspace / f"membership-merge-{uuid4().hex}"
    operation_workspace.mkdir(parents=True, exist_ok=True)
    visual_ply_path = operation_workspace / "merged-object-local.ply"
    collider_ply_path = operation_workspace / "merged-collider-local.ply"
    collider_glb_path = operation_workspace / "merged-collider.glb"
    visual_ply_path.write_bytes(visual_payload)
    collider_ply_path.write_bytes(collider_payload)
    _ensure_not_cancelled(cancel_event)

    summary = _run(
        runtime_python,
        CONVEX_RUNNER,
        {
            "objects": [
                {
                    "id": primary.id,
                    "gaussians_ply": str(collider_ply_path),
                    "output_glb": str(collider_glb_path),
                }
            ]
        },
        operation_workspace,
        "convex",
        timeout_seconds,
        cancel_event=cancel_event,
    )
    objects_summary = summary.get("objects") if isinstance(summary, dict) else None
    collider_info = next(
        (
            item
            for item in (objects_summary if isinstance(objects_summary, list) else [])
            if isinstance(item, dict) and item.get("id") == primary.id
        ),
        {},
    )
    if collider_info.get("parts") and collider_glb_path.is_file():
        collider_geometry = collider_glb_path.read_bytes()
        collider_type = ColliderType.CONVEX_DECOMPOSITION
        collider_parts = int(collider_info["parts"])
        volume_m3 = float(collider_info.get("volume_m3", 0.0))
        generator = "coacd"
    else:
        collider_geometry = trimesh.creation.box(extents=part.dimensions).export(file_type="glb")
        collider_type = ColliderType.OBB
        collider_parts = 1
        volume_m3 = 0.0
        generator = "aabb"

    _ensure_not_cancelled(cancel_event)
    visual_ref = _reference(job_id, "objects/{digest}.ply", "ObjectGaussians", StageId.SCENE_DECOMPOSE, visual_payload)
    collider_ref = _reference(job_id, "colliders/{digest}.glb", "ObjectCollider", StageId.COLLIDER, collider_geometry)
    _publish_artifact(editor, visual_ref, visual_payload)
    _publish_artifact(editor, collider_ref, collider_geometry)

    collision_memberships: dict[str, SourceCollisionRegion] = {}
    for object_id in selected_ids:
        original = objects_by_id[object_id].source_collision
        if original is None:
            raise ObjectMembershipValidationError(f"{object_id}: source collision ownership disappeared")
        indices = merged_collision_indices if object_id == command.primary_object_id else []
        membership_payload = (
            SourceCollisionMembership(
                object_id=object_id,
                source_geometry_ref=collision_geometry_ref,
                extraction_revision=original.extraction_revision,
                triangle_indices=indices,
            )
            .model_dump_json(indent=2)
            .encode("utf-8")
            + b"\n"
        )
        membership_ref = _reference(
            job_id,
            "colliders/source-membership/{digest}.json",
            "SourceCollisionMembership",
            StageId.COLLIDER,
            membership_payload,
        )
        _publish_artifact(editor, membership_ref, membership_payload)
        collision_memberships[object_id] = original.model_copy(
            update={
                "source_geometry_ref": collision_geometry_ref,
                "region_kind": "triangle_indices",
                "region_ref": membership_ref,
                "source_obb_dimensions_xyz_m": None,
            },
            deep=True,
        )

    local_collider_center = tuple(float(part.center[index] - primary_origin[index]) for index in range(3))
    collider = ColliderSpec(
        collider_id=f"{primary.id}-collider",
        collider_type=collider_type,
        local_transform=Transform(
            parent_frame=primary.local_frame,
            local_frame=f"{primary.id}-collider",
            translation_xyz=local_collider_center,
            rotation_quaternion_xyzw=_IDENTITY,
        ),
        dimensions_xyz_m=part.dimensions if collider_type == ColliderType.OBB else None,
        geometry_ref=collider_ref,
        parameters={"parts": collider_parts, "volume_m3": volume_m3},
        provenance={"generator": generator, "operation": "object_membership_merge_v1"},
    )
    semantic_source = command.semantic_class_source_object_id
    semantic_class = (
        objects_by_id[semantic_source].semantic_class if semantic_source is not None else primary.semantic_class
    )
    primary_provenance = {
        **primary.provenance,
        "gaussians": gaussian_count,
        "physics_reconfirmation_required": True,
        "membership_merge": {
            "source_object_ids": selected_ids,
            "source_membership_checksum": manifest.labels_ref.artifact_checksum,
            "gaussian_count": gaussian_count,
            "source_collision_triangle_count": len(merged_collision_indices),
            "source_collision_ambiguous_triangle_count": collision_ownership.ambiguous_triangle_count,
            "semantic_class_source_object_id": semantic_source,
            "source_collision_regions_rebound": True,
        },
    }
    merged_primary = primary.model_copy(
        update={
            "visual_ref": visual_ref,
            "geometry_ref": collider_ref,
            "primitive_dimensions_xyz_m": part.dimensions,
            "collider": collider,
            "source_collision": collision_memberships[primary.id],
            "semantic_class": semantic_class,
            "physics": None,
            "provenance": primary_provenance,
        },
        deep=True,
    )
    merged_into = selected_id_set
    updated_objects: list[SceneObject] = []
    for item in scene.objects:
        provenance = dict(item.provenance)
        if item.id == primary.id:
            updated_objects.append(merged_primary)
        elif item.id in command.secondary_object_ids:
            provenance.update(
                {
                    "review": "MERGED",
                    "merged_into": primary.id,
                    "merged_from_revision": scene.scene_revision,
                    "merged_by": actor_id,
                }
            )
            updated_objects.append(
                item.model_copy(
                    update={
                        "active": False,
                        "provenance": provenance,
                        "source_collision": collision_memberships[item.id],
                    },
                    deep=True,
                )
            )
        elif provenance.get("review") == "MERGED" and provenance.get("merged_into") in merged_into:
            provenance["merged_into"] = primary.id
            provenance["merged_from_revision"] = scene.scene_revision
            updated_objects.append(item.model_copy(update={"provenance": provenance}, deep=True))
        else:
            updated_objects.append(item)

    label_to_object_id = {
        label: primary.id if object_id in merged_into else object_id
        for label, object_id in manifest.label_to_object_id.items()
    }
    ordered_mapping = dict(sorted(label_to_object_id.items(), key=lambda pair: int(pair[0])))
    merged_manifest = manifest.model_copy(update={"label_to_object_id": ordered_mapping}, deep=True)
    environment = scene.environment.model_copy(update={"membership": merged_manifest}, deep=True)
    correction = {
        "operation": "merge",
        "actor_id": actor_id,
        "primary_object_id": primary.id,
        "secondary_object_ids": list(command.secondary_object_ids),
        "semantic_class_source_object_id": semantic_source,
        "membership_checksum": manifest.labels_ref.artifact_checksum,
        "gaussian_count": gaussian_count,
    }
    updated_scene = scene.model_copy(
        update={
            "environment": environment,
            "objects": updated_objects,
            "provenance": {**scene.provenance, "membership_correction": correction},
        },
        deep=True,
    )
    _ensure_not_cancelled(cancel_event)
    return editor.publish_next(
        job_id,
        command.expected_scene_revision,
        updated_scene,
        "object_membership_merge",
        commit_guard=commit_guard,
    )


def reassign_object_membership(
    editor: SceneEditor,
    job_id: str,
    command: ObjectMembershipReassignCommand,
    *,
    actor_id: str,
    runtime_python: Path,
    workspace: Path,
    timeout_seconds: float,
    view_requests: Sequence[dict[str, object]],
    lama_checkpoint: Path | None,
    gpu_index: int | None = None,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
) -> SceneEditResult:
    """Move source rows and source-mesh collision ownership in one revision-bound operation."""
    if not actor_id:
        raise ValueError("actor_id is required for a scene correction audit event")
    _ensure_not_cancelled(cancel_event)
    revision = editor.current(job_id)
    scene = revision.scene
    manifest = validate_object_membership_command(scene, command)
    if scene.environment.object_aware_collision_ref is not None:
        raise ObjectMembershipValidationError(
            "OBJECTGS_RETRAIN_REQUIRED: membership reassignment requires regenerated masks and ObjectGS training; "
            "existing checkpoints and geometry cannot be reused as corrected output"
        )
    if command.region is None:
        raise ObjectMembershipValidationError(
            "explicit source-row selection requires ObjectGS regeneration; legacy ROI remains supported"
        )
    source_ply = editor.resolver.require(manifest.source_visual_ref).read_bytes()
    source_rows = gaussian_split.read_gaussian_ply(source_ply)
    if len(source_rows) != manifest.gaussian_count:
        raise ObjectMembershipValidationError("source PLY row count does not match membership gaussian_count")
    positions = gaussian_split.positions(source_rows)
    if not np.isfinite(positions).all():
        raise ObjectMembershipValidationError("source Gaussian positions must be finite")
    gaussian_floor = fit_canonical_floor_model(positions, point_cloud_checksum(positions))
    gaussian_above_floor = above_floor_mask(positions, gaussian_floor)
    labels = decode_gaussian_membership_labels(editor.resolver.require(manifest.labels_ref).read_bytes(), manifest)
    if len(labels) != len(source_rows):
        raise ObjectMembershipValidationError("membership rows do not match source PLY rows")

    low = np.asarray(command.region.min_xyz_m, dtype=np.float64)
    high = np.asarray(command.region.max_xyz_m, dtype=np.float64)
    in_region = np.all((positions >= low - _ROI_EPSILON_M) & (positions <= high + _ROI_EPSILON_M), axis=1)
    source_labels = [
        int(label) for label, object_id in manifest.label_to_object_id.items() if object_id == command.source_object_id
    ]
    source_rows_mask = (
        labels == gaussian_split.BACKGROUND if command.source_object_id is None else np.isin(labels, source_labels)
    )
    selected_rows = in_region & source_rows_mask
    if command.target_object_id is not None:
        selected_rows &= gaussian_above_floor
    moved_gaussian_count = int(np.count_nonzero(selected_rows))
    if moved_gaussian_count == 0:
        raise ObjectMembershipValidationError("source ROI contains no Gaussian rows owned by the requested source")

    objects_by_id = {item.id: item for item in scene.objects}
    affected_ids = list(dict.fromkeys(item for item in (command.source_object_id, command.target_object_id) if item))
    for object_id in affected_ids:
        item = objects_by_id[object_id]
        if not np.allclose(item.transform.rotation_quaternion_xyzw, _IDENTITY, atol=1e-6):
            raise ObjectMembershipValidationError(
                f"reassign requires unrotated source frames so Gaussian SH remains valid ({object_id})"
            )

    collision_geometry_ref = scene.environment.collision_source_ref or manifest.source_geometry_ref
    geometry_bytes = editor.resolver.require(collision_geometry_ref).read_bytes()
    try:
        collision = source_triangle_ownership(
            scene.objects,
            collision_geometry_ref,
            geometry_bytes,
            lambda reference: editor.resolver.require(reference).read_bytes(),
        )
    except SourceCollisionOwnershipError as error:
        raise ObjectMembershipValidationError(str(error)) from error
    collision_label_by_id = {object_id: int(label) for label, object_id in collision.label_to_object_id.items()}
    collision_source_label = (
        -1 if command.source_object_id is None else collision_label_by_id.get(command.source_object_id)
    )
    if collision_source_label is None:
        raise ObjectMembershipValidationError("source object has no source collision ownership")
    collision_roi = np.all(
        (collision.centroids >= low - _ROI_EPSILON_M) & (collision.centroids <= high + _ROI_EPSILON_M), axis=1
    )
    collision_floor = fit_canonical_floor_model(collision.centroids, point_cloud_checksum(collision.centroids))
    collision_above_floor = above_floor_mask(collision.centroids, collision_floor)
    protected_floor = collision_roi & ~collision_above_floor
    selected_triangles = collision_roi & (collision.owner_labels == collision_source_label)
    if command.target_object_id is not None:
        selected_triangles &= collision_above_floor
    moved_triangle_count = int(np.count_nonzero(selected_triangles))
    if command.target_object_id is not None and moved_triangle_count == 0:
        raise ObjectMembershipValidationError(
            "source ROI contains Gaussian rows but no unambiguous collision triangles above the fitted floor plane"
        )

    updated_labels = labels.copy()
    if command.target_object_id is None:
        updated_labels[selected_rows] = gaussian_split.BACKGROUND
        target_collision_label = -1
    else:
        target_labels = [
            int(label)
            for label, object_id in manifest.label_to_object_id.items()
            if object_id == command.target_object_id
        ]
        if not target_labels:
            raise ObjectMembershipValidationError("target object has no label in the current membership map")
        target_gaussian_label = min(target_labels)
        updated_labels[selected_rows] = target_gaussian_label
        target_collision_label = collision_label_by_id.get(command.target_object_id)
        if target_collision_label is None:
            raise ObjectMembershipValidationError("target object has no source collision ownership")

    updated_collision_labels = collision.owner_labels.copy()
    updated_collision_labels[selected_triangles] = target_collision_label
    updated_label_payload = encode_gaussian_membership_labels(
        updated_labels,
        gaussian_count=len(source_rows),
        label_to_object_id=manifest.label_to_object_id,
    )
    updated_manifest = manifest.model_copy(deep=True)
    operation_workspace = workspace / f"membership-reassign-{uuid4().hex}"
    operation_workspace.mkdir(parents=True, exist_ok=False)
    _ensure_not_cancelled(cancel_event)

    candidate_records: dict[str, dict[str, object]] = {}
    collider_requests: list[dict[str, str]] = []
    for object_id in affected_ids:
        item = objects_by_id[object_id]
        owner_labels = [int(label) for label, owner_id in manifest.label_to_object_id.items() if owner_id == object_id]
        owned = np.isin(updated_labels, owner_labels)
        count = int(np.count_nonzero(owned))
        if not count:
            candidate_records[object_id] = {"count": 0}
            continue
        local_rows = source_rows[owned].copy()
        origin = np.asarray(item.transform.translation_xyz, dtype=np.float64)
        local_positions = gaussian_split.positions(local_rows) - origin
        if not np.isfinite(local_positions).all():
            raise ObjectMembershipValidationError(f"reassigned Gaussian positions are not finite for {object_id}")
        for axis, name in enumerate(("x", "y", "z")):
            local_rows[name] = local_positions[:, axis].astype(local_rows.dtype[name])
        _, parts = gaussian_split.split(
            local_rows,
            np.zeros(count, dtype=np.int32),
            SplitConfig(min_object_gaussians=1),
        )
        if len(parts) != 1:
            raise ObjectMembershipValidationError(f"reassigned object {object_id} did not form one valid part")
        part = parts[0]
        visual_payload = gaussian_split.write_gaussian_ply(local_rows)
        collider_input = operation_workspace / f"{object_id}.collider.ply"
        collider_output = operation_workspace / f"{object_id}.collider.glb"
        collider_input.write_bytes(gaussian_split.write_gaussian_ply(part.rows))
        candidate_records[object_id] = {
            "count": count,
            "part": part,
            "visual_payload": visual_payload,
            "collider_input": collider_input,
            "collider_output": collider_output,
        }
        if count >= _MIN_OBJECT_GAUSSIANS:
            collider_requests.append(
                {"id": object_id, "gaussians_ply": str(collider_input), "output_glb": str(collider_output)}
            )

    collider_summary: dict[str, object] = {}
    if collider_requests:
        _ensure_not_cancelled(cancel_event)
        raw_summary = _run(
            runtime_python,
            CONVEX_RUNNER,
            {"objects": collider_requests},
            operation_workspace,
            "convex",
            timeout_seconds,
            cancel_event=cancel_event,
        )
        records = raw_summary.get("objects") if isinstance(raw_summary, dict) else None
        if isinstance(records, list):
            collider_summary = {
                record["id"]: record
                for record in records
                if isinstance(record, dict) and isinstance(record.get("id"), str)
            }

    background_rows = source_rows[updated_labels == gaussian_split.BACKGROUND]
    object_rows = source_rows[updated_labels != gaussian_split.BACKGROUND]
    environment_master_ref: ProductArtifactRef | None = None
    environment_visual_ref: ProductArtifactRef | None = None
    background_count = int(len(background_rows))
    inpainted_count = 0
    inpaint_method = "none"
    if background_count:
        background_raw = operation_workspace / "background.ply"
        background_raw.write_bytes(gaussian_split.write_gaussian_ply(background_rows))
        background_path = background_raw
        if len(object_rows):
            if not view_requests:
                raise ObjectMembershipValidationError("camera views are required to regenerate an inpainted background")
            objects_world_path = operation_workspace / "objects-world.ply"
            objects_world_path.write_bytes(gaussian_split.write_gaussian_ply(object_rows))
            inpaint_output = operation_workspace / "background-inpainted.ply"
            inpaint_result = _run(
                runtime_python,
                INPAINT_RUNNER,
                {
                    "background_ply": str(background_raw),
                    "objects_ply": str(objects_world_path),
                    "output_ply": str(inpaint_output),
                    "lama_checkpoint": str(lama_checkpoint) if lama_checkpoint is not None else None,
                    "views": [dict(view) for view in view_requests],
                },
                operation_workspace,
                "inpaint",
                timeout_seconds,
                cancel_event=cancel_event,
            )
            background_path = inpaint_output
            inpaint_method = str(inpaint_result.get("method", "unknown"))
            inpainted_count = int(inpaint_result.get("inpainted_gaussians", 0))
        background_ply = background_path.read_bytes()
        rebuilt_background_rows = gaussian_split.read_gaussian_ply(background_ply)
        if not np.isfinite(gaussian_split.positions(rebuilt_background_rows)).all():
            raise ObjectMembershipValidationError("regenerated environment PLY contains non-finite Gaussian positions")
        sog_path = package_splat(
            background_path, operation_workspace / "environment-sog", gpu_index, cancel_event=cancel_event
        )
        sog_payload = sog_path.read_bytes()
        environment_master_ref = _reference(
            job_id,
            "environment/{digest}/background.ply",
            "GaussianPLY",
            StageId.SCENE_DECOMPOSE,
            background_ply,
        )
        environment_visual_ref = _reference(
            job_id,
            "environment/{digest}/background.sog",
            "VisualArtifact",
            StageId.SCENE_DECOMPOSE,
            sog_payload,
        )
        _publish_artifact(editor, environment_master_ref, background_ply)
        _publish_artifact(editor, environment_visual_ref, sog_payload)

    collision_regions: dict[str, object] = {}
    for label, object_id in collision.label_to_object_id.items():
        original = objects_by_id[object_id].source_collision
        if original is None:
            raise ObjectMembershipValidationError(f"{object_id}: source collision ownership disappeared")
        triangle_indices = np.flatnonzero(updated_collision_labels == int(label)).tolist()
        membership_payload = (
            SourceCollisionMembership(
                object_id=object_id,
                source_geometry_ref=collision_geometry_ref,
                extraction_revision=original.extraction_revision,
                triangle_indices=triangle_indices,
            )
            .model_dump_json()
            .encode("utf-8")
        )
        membership_ref = _reference(
            job_id,
            "collision/membership/{digest}.json",
            "SourceCollisionMembership",
            StageId.COLLIDER,
            membership_payload,
        )
        _publish_artifact(editor, membership_ref, membership_payload)
        collision_regions[object_id] = original.model_copy(
            update={
                "source_geometry_ref": collision_geometry_ref,
                "region_kind": "triangle_indices",
                "region_ref": membership_ref,
                "source_obb_dimensions_xyz_m": None,
            },
            deep=True,
        )

    for object_id, record in candidate_records.items():
        count = int(record["count"])
        if count == 0:
            continue
        item = objects_by_id[object_id]
        part = record["part"]
        visual_payload = record["visual_payload"]
        visual_ref = _reference(
            job_id, "objects/{digest}.ply", "ObjectGaussians", StageId.SCENE_DECOMPOSE, visual_payload
        )
        _publish_artifact(editor, visual_ref, visual_payload)
        collider_path = record["collider_output"]
        collider_info = collider_summary.get(object_id, {})
        if (
            isinstance(collider_info, dict)
            and collider_info.get("parts")
            and isinstance(collider_path, Path)
            and collider_path.is_file()
        ):
            collider_payload = collider_path.read_bytes()
            collider_type = ColliderType.CONVEX_DECOMPOSITION
            collider_parts = int(collider_info["parts"])
            volume_m3 = float(collider_info.get("volume_m3", 0.0))
            generator = "coacd"
        else:
            collider_payload = trimesh.creation.box(extents=part.dimensions).export(file_type="glb")
            collider_type = ColliderType.OBB
            collider_parts = 1
            volume_m3 = 0.0
            generator = "aabb"
        if not np.isfinite(volume_m3) or volume_m3 < 0:
            raise ObjectMembershipValidationError(f"collider runner returned invalid volume for {object_id}")
        collider_ref = _reference(
            job_id, "colliders/{digest}.glb", "ObjectCollider", StageId.COLLIDER, collider_payload
        )
        _publish_artifact(editor, collider_ref, collider_payload)
        local_collider_center = tuple(float(value) for value in part.center)
        collider = ColliderSpec(
            collider_id=f"{object_id}-collider",
            collider_type=collider_type,
            local_transform=Transform(
                parent_frame=item.local_frame,
                local_frame=f"{object_id}-collider",
                translation_xyz=local_collider_center,
                rotation_quaternion_xyzw=_IDENTITY,
            ),
            dimensions_xyz_m=part.dimensions if collider_type == ColliderType.OBB else None,
            geometry_ref=collider_ref,
            parameters={"parts": collider_parts, "volume_m3": volume_m3},
            provenance={"generator": generator, "operation": "object_membership_reassign_v1"},
        )
        provenance = {
            **item.provenance,
            "gaussians": count,
            "physics_reconfirmation_required": True,
            "membership_reassign": {
                "source_object_id": command.source_object_id,
                "target_object_id": command.target_object_id,
                "moved_gaussians": moved_gaussian_count,
                "collision_triangles": moved_triangle_count,
            },
        }
        if count < _MIN_OBJECT_GAUSSIANS:
            provenance["membership_reassign_blocker"] = "TOO_FEW_GAUSSIANS"
        else:
            provenance.pop("membership_reassign_blocker", None)
        candidate_records[object_id]["updated_object"] = item.model_copy(
            update={
                "visual_ref": visual_ref,
                "geometry_ref": collider_ref,
                "primitive_dimensions_xyz_m": part.dimensions,
                "collider": collider,
                "physics": None,
                "provenance": provenance,
            },
            deep=True,
        )

    updated_label_ref = _reference(
        job_id,
        "objects/membership/{digest}.i32le",
        "ObjectMembershipLabels",
        StageId.SCENE_DECOMPOSE,
        updated_label_payload,
    )
    _publish_artifact(editor, updated_label_ref, updated_label_payload)
    updated_manifest = updated_manifest.model_copy(update={"labels_ref": updated_label_ref}, deep=True)
    environment = scene.environment.model_copy(
        update={
            "membership": updated_manifest,
            "visual_master_ref": environment_master_ref,
            "visual_ref": environment_visual_ref,
        },
        deep=True,
    )
    updated_objects: list[SceneObject] = []
    for item in scene.objects:
        collision_region = collision_regions.get(item.id)
        record = candidate_records.get(item.id)
        if record is not None:
            count = int(record["count"])
            if count == 0:
                provenance = {
                    **item.provenance,
                    "gaussians": 0,
                    "physics_reconfirmation_required": True,
                    "membership_reassign": {
                        "source_object_id": command.source_object_id,
                        "target_object_id": command.target_object_id,
                        "moved_gaussians": moved_gaussian_count,
                        "collision_triangles": moved_triangle_count,
                    },
                    "membership_reassign_blocker": "NO_SOURCE_GAUSSIANS",
                }
                updates: dict[str, object] = {
                    "visual_ref": None,
                    "collider": None,
                    "primitive_dimensions_xyz_m": None,
                    "physics": None,
                    "active": False,
                    "provenance": provenance,
                }
                if collision_region is not None:
                    updates = {**updates, "source_collision": collision_region}
                updated_objects.append(item.model_copy(update=updates, deep=True))
                continue
            else:
                updated_object = record.get("updated_object")
                if not isinstance(updated_object, SceneObject):
                    raise ObjectMembershipValidationError(f"reassigned object {item.id} was not rebuilt")
                updates = {"physics": None}
                if collision_region is not None:
                    updates["source_collision"] = collision_region
                updated_objects.append(updated_object.model_copy(update=updates, deep=True))
                continue
        if collision_region is not None:
            updated_objects.append(item.model_copy(update={"source_collision": collision_region}, deep=True))
        else:
            updated_objects.append(item)

    correction = {
        "operation": "reassign",
        "actor_id": actor_id,
        "source_object_id": command.source_object_id,
        "target_object_id": command.target_object_id,
        "region": command.region.model_dump(mode="json"),
        "membership_checksum_before": manifest.labels_ref.artifact_checksum,
        "membership_checksum_after": updated_label_ref.artifact_checksum,
        "moved_gaussians": moved_gaussian_count,
        "collision_triangles": moved_triangle_count,
        "floor_triangles_preserved": int(np.count_nonzero(protected_floor & ~selected_triangles)),
        "ambiguous_collision_triangles_preserved_as_background": collision.ambiguous_triangle_count,
        "background_gaussians": background_count,
        "inpainted_gaussians": inpainted_count,
        "inpaint_method": inpaint_method,
    }
    updated_scene = scene.model_copy(
        update={
            "environment": environment,
            "objects": updated_objects,
            "provenance": {**scene.provenance, "membership_correction": correction},
        },
        deep=True,
    )
    _ensure_not_cancelled(cancel_event)
    return editor.publish_next(
        job_id,
        command.expected_scene_revision,
        updated_scene,
        "object_membership_reassign",
        commit_guard=commit_guard,
    )


def _publish_artifact(editor: SceneEditor, reference: ProductArtifactRef, payload: bytes) -> None:
    try:
        editor.store.publish(reference, payload)
    except ArtifactAlreadyExistsError:
        pass
    published = editor.resolver.require(reference)
    if published.read_bytes() != payload:
        raise ObjectMembershipValidationError(f"published artifact bytes differ from {reference.artifact_uri}")


def _ensure_not_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCancelledError("Object membership merge was cancelled")
