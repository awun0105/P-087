"""Read-only region previews and synchronous Draft membership edits."""

import base64
import json

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import ObjectRegionCommand
from src.models.contracts.scene import SceneIR, SceneObject
from src.services.orchestration.artifacts import FilesystemArtifactStore
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.membership_regeneration import MembershipSource, load_membership_source
from src.services.orchestration.scene.models import SceneEditResult
from src.services.orchestration.scene.objectify import _reference
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.scene.decomposition.gaussian_split import write_gaussian_ply
from src.services.scene.editing.membership import (
    ObjectMembershipValidationError,
    StaleObjectMembershipRevisionError,
    encode_gaussian_membership_labels,
)
from src.services.scene.editing.region_box import (
    MIN_OBJECT_ROWS,
    RegionResolution,
    apply_resolution,
    preview_payload,
    resolve_region,
)
from src.services.scene.gaussian_shell import GaussianShellError, ShellParams, build_gaussian_shell
from src.services.scene.geometry_state import object_geometry_state


def _source_pose(item: SceneObject) -> Transform:
    try:
        pose = Transform.model_validate(item.provenance.get("source_transform"))
        if pose.parent_frame != "world" or pose.local_frame != item.id:
            raise ValueError("source_transform must bind world to the object frame")
        return pose
    except ValueError as error:
        raise ObjectMembershipValidationError(f"{item.id}: {error}") from error


def _local(positions: np.ndarray, item: SceneObject) -> np.ndarray:
    pose = _source_pose(item)
    return (positions - np.asarray(pose.translation_xyz)) @ rotation_matrix(pose.rotation_quaternion_xyzw)


def _resolve(
    registry: ProjectRegistry, job_id: str, object_id: str, command: ObjectRegionCommand
) -> tuple[SceneIR, SceneObject, MembershipSource, RegionResolution, np.ndarray]:
    scene = registry.scene.current(job_id).scene
    if scene.scene_revision != command.expected_scene_revision:
        raise StaleObjectMembershipRevisionError("scene đã đổi; tải lại trước khi chỉnh vùng")
    manifest = scene.environment.membership
    if manifest is None:
        raise ObjectMembershipValidationError("scene has no persisted Gaussian membership")
    if manifest.labels_ref.artifact_checksum != command.membership_checksum:
        raise StaleObjectMembershipRevisionError("membership checksum đã đổi; tải lại trước khi chỉnh vùng")
    objects = {item.id: item for item in scene.objects}
    mapped = set(manifest.label_to_object_id.values())
    for selected in {object_id, *command.claim_from}:
        item = objects.get(selected)
        if selected not in mapped or item is None:
            raise ObjectMembershipValidationError(f"vật {selected} không có trong membership")
        if item.state.value in {"DELETED", "IGNORED", "MERGED"} or item.provenance.get("review") in {
            "DELETED",
            "IGNORED",
            "MERGED",
        }:
            raise ObjectMembershipValidationError(f"vật {selected} đã xoá/bỏ qua/gộp")
        _source_pose(item)
    item = objects[object_id]
    source = load_membership_source(registry, job_id, scene)
    resolution = resolve_region(
        positions_world=source.positions,
        labels=source.labels,
        manifest=manifest,
        object_id=object_id,
        source_world_from_object=_source_pose(item),
        command=command,
        floor_protected=source.floor_protected,
    )
    return scene, item, source, resolution, _local(source.positions, item)


def _shell(points: np.ndarray, opacity: np.ndarray) -> tuple[bytes | None, dict, str | None]:
    try:
        shell = build_gaussian_shell(points, opacity, ShellParams(voxel_m=0.05, smooth_iterations=0))
        payload = trimesh.Trimesh(shell.vertices, shell.faces, process=False).export(file_type="glb")
        return payload, {"voxel_m": 0.05, "checksum": shell.checksum, "statistics": shell.statistics}, None
    except GaussianShellError as error:
        return None, {}, str(error)


def preview_region(registry: ProjectRegistry, job_id: str, object_id: str, command: ObjectRegionCommand) -> dict:
    scene, _, source, resolution, local = _resolve(registry, job_id, object_id, command)
    selected = np.flatnonzero(resolution.object_mask)
    # Uniform deterministic stride bounds shell filtering cost; membership counts remain exact.
    stride = max(1, (len(selected) + 99_999) // 100_000)
    selected = selected[::stride]
    payload, _, error = _shell(local[selected], source.rows["opacity"][selected])
    return {
        "scene_revision": scene.scene_revision,
        "membership_checksum": source.manifest.labels_ref.artifact_checksum,
        "object_id": object_id,
        **preview_payload(resolution, local),
        "shell_glb_base64": base64.b64encode(payload).decode("ascii") if payload is not None else None,
        "shell_error": error,
        "shell_sample_rows": len(selected),
    }


def apply_region_draft(
    registry: ProjectRegistry, job_id: str, object_id: str, command: ObjectRegionCommand, *, actor_id: str
) -> SceneEditResult:
    scene, _, source, resolution, local = _resolve(registry, job_id, object_id, command)
    if object_geometry_state(scene) != "awaiting_review":
        raise ObjectMembershipValidationError("Scene đã có hình học; tính năng dựng lại vật sẽ có ở bước sau.")
    labels = apply_resolution(source.labels, source.manifest, object_id, resolution)
    affected = {object_id, *resolution.claimed}
    masks = {
        owner: np.isin(labels, [int(k) for k, v in source.manifest.label_to_object_id.items() if v == owner])
        for owner in affected
    }
    for owner, mask in masks.items():
        if np.count_nonzero(mask) < MIN_OBJECT_ROWS:
            raise ObjectMembershipValidationError(f"vật {owner} còn dưới 50 Gaussian; dùng Xoá vật thay vì thu box")
    # Prepare every affected object's bytes before publishing any artifact.
    prepared = {}
    for item in scene.objects:
        if item.id not in affected:
            continue
        mask = masks[item.id]
        points = _local(source.positions[mask], item)
        rows = source.rows[mask].copy()
        for axis, name in enumerate(("x", "y", "z")):
            rows[name] = points[:, axis]
        # Gaussian orientation, when present, uses the same immutable local frame as its centre.
        if all(f"rot_{axis}" in rows.dtype.names for axis in range(4)):
            world = np.column_stack([rows[f"rot_{axis}"] for axis in (1, 2, 3, 0)])
            quaternions = (
                Rotation.from_quat(_source_pose(item).rotation_quaternion_xyzw).inv() * Rotation.from_quat(world)
            ).as_quat()
            for axis, name in enumerate(("rot_1", "rot_2", "rot_3", "rot_0")):
                rows[name] = quaternions[:, axis]
        dimensions = tuple(float(v) for v in np.maximum(np.ptp(points, axis=0), 0.05))
        shell, metadata, error = _shell(points, rows["opacity"])
        provenance = {**item.provenance, "gaussians": len(rows)}
        for key in ("shell_error", "shell_display", "shell_preview"):
            provenance.pop(key, None)
        if shell is None:
            # Display-only placeholder, matching Draft extraction; never a collider.
            box = trimesh.creation.box(extents=dimensions)
            box.apply_translation((points.min(axis=0) + points.max(axis=0)) / 2)
            shell = box.export(file_type="glb")
            provenance.update(shell_error=error, shell_display="bounding_box_placeholder")
        else:
            provenance["shell_preview"] = metadata
        prepared[item.id] = (write_gaussian_ply(rows), shell, dimensions, provenance)

    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(payload: bytes, tail: str, kind: str) -> ProductArtifactRef:
        reference = _reference(job_id, tail, kind, StageId.SCENE_DECOMPOSE, payload)
        if registry.runtime_resolver.locate(reference.artifact_uri) is not None:
            registry.runtime_resolver.require(reference)
            return reference
        return store.publish(reference, payload)

    encoded = encode_gaussian_membership_labels(
        labels, gaussian_count=source.manifest.gaussian_count, label_to_object_id=source.manifest.label_to_object_id
    )
    labels_ref = publish(encoded, "objects/membership/{digest}.i32le", "ObjectMembershipLabels")
    membership = source.manifest.model_copy(update={"labels_ref": labels_ref}, deep=True)
    membership_ref = publish(
        membership.model_dump_json().encode(), "objects/membership/{digest}.json", "ObjectMembershipArtifact"
    )
    objects = []
    for item in scene.objects:
        if item.id not in prepared:
            objects.append(item)
            continue
        visual, shell, dimensions, provenance = prepared[item.id]
        objects.append(
            item.model_copy(
                update={
                    "visual_ref": publish(visual, "objects/{digest}.ply", "ObjectGaussians"),
                    "geometry_ref": publish(shell, "objects/shells/{digest}.glb", "ObjectShellMesh"),
                    "primitive_dimensions_xyz_m": dimensions,
                    "provenance": provenance,
                    "surface_mesh_ref": None,
                    "collider": None,
                },
                deep=True,
            )
        )
    preview = {
        key: value
        for key, value in preview_payload(resolution, local).items()
        if key not in {"added_sample_m", "removed_sample_m"}
    }
    evidence = {
        "command": command.model_dump(mode="json"),
        "preview": preview,
        "actor_id": actor_id,
        "source_membership": source.manifest.model_dump(mode="json"),
        "corrected_membership": membership.model_dump(mode="json"),
        "membership_ref": membership_ref.model_dump(mode="json"),
    }
    evidence_ref = publish(
        json.dumps(evidence, sort_keys=True).encode(), "objects/regions/{digest}.json", "ObjectRegionEdit"
    )
    updated = scene.model_copy(
        update={
            "objects": objects,
            "environment": scene.environment.model_copy(update={"membership": membership}, deep=True),
            "provenance": {
                **scene.provenance,
                "object_region_edit": {"actor_id": actor_id, "evidence_ref": evidence_ref.model_dump(mode="json")},
            },
        },
        deep=True,
    )
    return registry.scene.publish_next(job_id, command.expected_scene_revision, updated, "object_region_edit")
