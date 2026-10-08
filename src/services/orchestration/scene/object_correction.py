"""Revision-bound scene object corrections backed by immutable Gaussian artifacts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event
from uuid import uuid4

import numpy as np
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import ObjectMembershipMergeCommand
from src.models.contracts.scene import ColliderSpec, ColliderType, SceneObject
from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.models import SceneEditResult
from src.services.orchestration.scene.objectify import CONVEX_RUNNER, _reference, _run
from src.services.process_control import ProcessCancelledError
from src.services.scene.decomposition import gaussian_split
from src.services.scene.decomposition.gaussian_split import SplitConfig
from src.services.scene.editing.membership import (
    ObjectMembershipValidationError,
    decode_gaussian_membership_labels,
    validate_object_membership_command,
)

_IDENTITY = (0.0, 0.0, 0.0, 1.0)


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
            "semantic_class_source_object_id": semantic_source,
            "source_collision_regions_preserved": True,
        },
    }
    merged_primary = primary.model_copy(
        update={
            "visual_ref": visual_ref,
            "geometry_ref": collider_ref,
            "primitive_dimensions_xyz_m": part.dimensions,
            "collider": collider,
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
            updated_objects.append(item.model_copy(update={"active": False, "provenance": provenance}, deep=True))
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
