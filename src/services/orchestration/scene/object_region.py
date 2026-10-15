"""Read-only region previews and synchronous Draft membership edits."""

import base64

import numpy as np
import trimesh

from src.models.contracts.coordinates import Transform
from src.models.contracts.object_membership import ObjectRegionCommand
from src.models.contracts.scene import SceneIR, SceneObject
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.membership_regeneration import MembershipSource, load_membership_source
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.scene.editing.membership import ObjectMembershipValidationError, StaleObjectMembershipRevisionError
from src.services.scene.editing.region_box import RegionResolution, preview_payload, resolve_region
from src.services.scene.gaussian_shell import GaussianShellError, ShellParams, build_gaussian_shell


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
    payload, _, error = _shell(local[resolution.object_mask], source.rows["opacity"][resolution.object_mask])
    return {
        "scene_revision": scene.scene_revision,
        "membership_checksum": source.manifest.labels_ref.artifact_checksum,
        "object_id": object_id,
        **preview_payload(resolution, local),
        "shell_glb_base64": base64.b64encode(payload).decode("ascii") if payload is not None else None,
        "shell_error": error,
    }
