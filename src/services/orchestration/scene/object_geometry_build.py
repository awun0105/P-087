"""Build reviewed object geometry and publish it through the existing SceneIR revision fence."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from src.config import Settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_geometry import ObjectShellManifest
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.scene import ColliderSpec, ColliderType, SceneEnvironment, SceneIR, SceneObject
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.processing.config import load_job_config
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.floor_evidence import publish_floor_fit_evidence, scene_floor_fit_summary
from src.services.orchestration.scene.object_geometry_steps import (
    SurfaceInput,
    build_environment_collision,
    run_inpaint_and_package,
    run_surface_colliders,
)
from src.services.orchestration.scene.objectify import (
    ObjectifyConfig,
    ObjectifyError,
    Publish,
    _ensure_not_cancelled,
    _reference,
)
from src.services.reconstruction import camera_views
from src.services.scene.collision_ownership import bind_source_collision_ownership
from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply, write_gaussian_ply
from src.services.scene.editing.membership import StaleObjectMembershipRevisionError, decode_gaussian_membership_labels
from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.gaussian_shell import GaussianShellError, ShellParams, build_gaussian_shell
from src.services.scene.geometry_state import object_geometry_state


class ObjectGeometryBuildError(RuntimeError):
    """A geometry build failed without changing the active scene."""

    def __init__(self, message: str, *, object_id: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.object_id = object_id
        self.retryable = retryable


def _build_shell(
    item: SceneObject,
    rows: np.ndarray,
    membership: ObjectMembershipArtifact,
    workspace: Path,
    publish: Publish,
) -> tuple[ProductArtifactRef, ProductArtifactRef, SurfaceInput]:
    """Build from immutable world rows using the extraction frame, never the edited pose."""
    if item.provenance.get("shell_error"):
        raise ObjectGeometryBuildError(
            f"Vỏ của {item.name} không dựng được: {item.provenance['shell_error']}. Sửa vùng vật rồi thử lại.",
            object_id=item.id,
        )
    try:
        pose = Transform.model_validate(item.provenance.get("source_transform"))
        if pose.parent_frame != "world" or pose.local_frame != item.id:
            raise ValueError("source_transform must bind world to the object frame")
    except ValueError as error:
        raise ObjectGeometryBuildError(
            f"{item.id}: source_transform không hợp lệ: {error}", object_id=item.id
        ) from error
    params = ShellParams()
    local = (positions(rows) - np.asarray(pose.translation_xyz)) @ Rotation.from_quat(
        pose.rotation_quaternion_xyzw
    ).as_matrix()
    try:
        shell = build_gaussian_shell(local, rows["opacity"], params)
    except GaussianShellError as error:
        raise ObjectGeometryBuildError(str(error), object_id=item.id) from error
    payload = trimesh.Trimesh(shell.vertices, shell.faces, process=False).export(file_type="glb")
    job_id = membership.labels_ref.job_id
    shell_ref = publish(
        _reference(job_id, "objects/shells/{digest}.glb", "ObjectShellMesh", StageId.SCENE_DECOMPOSE, payload), payload
    )
    manifest = ObjectShellManifest(
        object_id=item.id,
        shell_mesh_ref=shell_ref,
        source_membership=membership,
        source_world_from_object=pose,
        voxel_m=shell.statistics["voxel_m_effective"],
        params=asdict(params),
        statistics=shell.statistics,
        quality=shell.quality,
        vertex_count=len(shell.vertices),
        triangle_count=len(shell.faces),
        provenance={
            "surface_origin": "gaussian_shell_v1",
            "inferred_regions": "unobserved faces closed by occupancy fill",
        },
    )
    manifest_payload = manifest.model_dump_json().encode()
    manifest_ref = publish(
        _reference(
            job_id, "objects/shells/{digest}.json", "ObjectShellManifest", StageId.SCENE_DECOMPOSE, manifest_payload
        ),
        manifest_payload,
    )
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / f"{item.id}-shell.glb"
    path.write_bytes(payload)
    return (
        shell_ref,
        manifest_ref,
        SurfaceInput(item.id, path, shell_ref.artifact_checksum, workspace / f"{item.id}-collider.glb"),
    )


def _build_colliders(
    inputs: list[SurfaceInput],
    settings: Settings,
    coacd_config: dict,
    workspace: Path,
    publish: Publish,
    job_id: str,
    cancel_event: Event | None = None,
) -> dict[str, tuple[ProductArtifactRef, ColliderSpec]]:
    if settings.product_scene_runtime_python is None:
        raise ObjectGeometryBuildError("Chưa cấu hình runtime CoACD.")
    try:
        result = run_surface_colliders(
            settings.product_scene_runtime_python,
            inputs,
            coacd_config,
            workspace,
            settings.product_scene_timeout_seconds,
            cancel_event,
            surface_label="Gaussian shell",
        )
    except ObjectifyError as error:
        raise ObjectGeometryBuildError(str(error), retryable=error.retryable) from error
    colliders = {}
    for item in inputs:
        _ensure_not_cancelled(cancel_event)
        payload = item.output_glb.read_bytes()
        geometry = publish(
            _reference(job_id, "colliders/{digest}.glb", "ObjectCollider", StageId.COLLIDER, payload), payload
        )
        shell_ref = _reference(
            job_id,
            "objects/shells/{digest}.glb",
            "ObjectShellMesh",
            StageId.SCENE_DECOMPOSE,
            item.surface_path.read_bytes(),
        )
        collider_id = f"{item.key}-collider"
        collider = ColliderSpec(
            collider_id=collider_id,
            collider_type=ColliderType.CONVEX_DECOMPOSITION,
            local_transform=Transform(
                parent_frame=item.key,
                local_frame=collider_id,
                translation_xyz=(0, 0, 0),
                rotation_quaternion_xyzw=(0, 0, 0, 1),
            ),
            geometry_ref=geometry,
            parameters={"parts": int(result[item.key]["parts"])},
            provenance={
                "generator": "coacd",
                "surface_origin": "gaussian_shell_v1",
                "surface_mesh_ref": shell_ref.model_dump(mode="json"),
                "coacd_config": coacd_config,
                "strict_surface_input": True,
            },
        )
        colliders[item.key] = (geometry, collider)
    return colliders


def _build_environment(
    registry: ProjectRegistry,
    settings: Settings,
    job_id: str,
    scene: SceneIR,
    rows: np.ndarray,
    labels: np.ndarray,
    config: ObjectifyConfig,
    workspace: Path,
    publish: Publish,
    cancel_event: Event | None,
) -> SceneEnvironment:
    membership = scene.environment.membership
    bundle = job_bundle(registry, registry.get_job(job_id))
    if bundle is None or bundle.canonical_geometry_ref != membership.source_geometry_ref:
        raise ObjectGeometryBuildError("Geometry build reconstruction source geometry mismatch")
    if settings.product_scene_runtime_python is None:
        raise ObjectGeometryBuildError("Chưa cấu hình runtime inpaint.")
    workspace.mkdir(parents=True, exist_ok=True)
    background, objects = workspace / "background.ply", workspace / "objects_world.ply"
    background.write_bytes(write_gaussian_ply(rows[labels == -1]))
    objects.write_bytes(write_gaussian_ply(rows[labels >= 0]))
    resolve = registry.runtime_resolver.require
    views = camera_views(bundle.camera_pose_refs[0], bundle.rgb_frame_refs, resolve)
    requests = [
        {**view.model_dump(mode="json", exclude={"image"}), "image_path": str(resolve(view.image))} for view in views
    ]
    master, visual, _ = run_inpaint_and_package(
        settings.product_scene_runtime_python,
        background_ply=background,
        objects_ply=objects,
        views=requests,
        settings=settings,
        inpaint_config=config.inpaint.model_dump(exclude_unset=True),
        workspace=workspace,
        timeout=settings.product_scene_timeout_seconds,
        cancel_event=cancel_event,
        publish=publish,
        job_id=job_id,
    )
    _ensure_not_cancelled(cancel_event)
    xyz = positions(rows)
    floor_model = fit_canonical_floor_model(xyz, point_cloud_checksum(xyz))
    floor_ref, evidence = publish_floor_fit_evidence(job_id, membership.source_visual_ref, floor_model, publish)
    footprints = []
    for owner in sorted(set(membership.label_to_object_id.values())):
        keys = [int(key) for key, value in membership.label_to_object_id.items() if value == owner]
        anchors = xyz[np.isin(labels, keys)]
        if len(anchors):
            footprints.append((anchors.min(axis=0), anchors.max(axis=0)))
    collision, manifest = build_environment_collision(
        source_points=xyz,
        membership_labels=labels,
        label_to_object_id=membership.label_to_object_id,
        footprints=footprints,
        floor_model=floor_model,
        floor_fit=scene_floor_fit_summary(floor_ref, evidence),
        voxel_m=config.scene.objectgs_background_voxel_m,
        bundle=bundle,
        membership=membership,
        publish=publish,
        job_id=job_id,
    )
    return scene.environment.model_copy(
        update={
            "visual_ref": visual,
            "visual_master_ref": master,
            "collider_ref": collision,
            "object_aware_collision_ref": manifest,
        },
        deep=True,
    )


def build_object_geometry(
    registry: ProjectRegistry,
    settings: Settings,
    job_id: str,
    *,
    expected_revision: str,
    workspace: Path,
    object_ids: set[str] | None = None,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> str:
    """Build source-bound geometry; publish one revision after all stages succeed."""
    _ensure_not_cancelled(cancel_event)
    scene = registry.scene.current(job_id).scene
    if scene.scene_revision != expected_revision:
        raise StaleObjectMembershipRevisionError(
            f"scene đã đổi: yêu cầu {expected_revision}, hiện tại {scene.scene_revision}"
        )
    if scene.environment.membership is None:
        raise ObjectGeometryBuildError("Scene không có source membership để dựng hình học.")
    if object_ids is None and object_geometry_state(scene) != "awaiting_review":
        raise ObjectGeometryBuildError("Scene phải đang duyệt tách vật trước khi tạo mesh.")
    membership = scene.environment.membership
    if membership.labels_ref.job_id != job_id or membership.source_geometry_ref != scene.environment.geometry_ref:
        raise ObjectGeometryBuildError("Geometry build source membership does not match the scene")
    if scene.environment.collision_selection_ref is not None:
        raise ObjectGeometryBuildError("Dựng hình học trên scene nguồn trước khi chọn collision source khác.")
    resolve = registry.runtime_resolver.require
    payload = resolve(membership.source_visual_ref).read_bytes()
    if sha256_bytes(payload) != membership.source_visual_ref.artifact_checksum:
        raise ObjectGeometryBuildError("source PLY checksum mismatch")
    try:
        rows = read_gaussian_ply(payload)
        labels = decode_gaussian_membership_labels(resolve(membership.labels_ref).read_bytes(), membership)
        if len(rows) != membership.gaussian_count:
            raise ValueError("source PLY row count does not match membership")
    except ValueError as error:
        raise ObjectGeometryBuildError(str(error)) from error
    job = registry.get_job(job_id)
    processing = load_job_config(job_id, job.config_checksum, registry.runtime_resolver)
    groups: dict[str, dict] = {"scene": {}, "coacd": {}, "inpaint": {}}
    for key, value in (processing.scene if processing is not None else {}).items():
        group, name = key.split("_", 1) if key.startswith(("coacd_", "inpaint_")) else ("scene", key)
        groups[group][name] = value
    config = ObjectifyConfig.model_validate(groups)
    if object_ids is not None and not object_ids <= {item.id for item in scene.objects}:
        raise ObjectGeometryBuildError("Geometry build requested unknown objects")
    selected = [
        item
        for item in scene.objects
        if item.id in membership.label_to_object_id.values()
        and item.provenance.get("review") not in {"DELETED", "IGNORED", "MERGED"}
        and (object_ids is None or item.id in object_ids)
    ]
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(reference: ProductArtifactRef, data: bytes) -> ProductArtifactRef:
        _ensure_not_cancelled(cancel_event)
        if registry.runtime_resolver.locate(reference.artifact_uri) is not None:
            if resolve(reference).read_bytes() != data:
                raise ObjectGeometryBuildError("immutable geometry artifact bytes differ")
            registry.runtime_resolver.published(reference.artifact_uri)
            return reference
        return store.publish(reference, data)

    def phase(name: str) -> None:
        _ensure_not_cancelled(cancel_event)
        if progress is not None:
            progress(name)
        _ensure_not_cancelled(cancel_event)

    phase("shell")
    shells = {}
    for item in selected:
        _ensure_not_cancelled(cancel_event)
        keys = [int(key) for key, owner in membership.label_to_object_id.items() if owner == item.id]
        shells[item.id] = _build_shell(item, rows[np.isin(labels, keys)], membership, workspace, publish)
    phase("quality")
    phase("collider")
    colliders = (
        _build_colliders(
            [shells[item.id][2] for item in selected],
            settings,
            config.coacd.model_dump(exclude_unset=True),
            workspace,
            publish,
            job_id,
            cancel_event,
        )
        if selected
        else {}
    )
    phase("environment")
    try:
        environment = _build_environment(
            registry, settings, job_id, scene, rows, labels, config, workspace, publish, cancel_event
        )
    except ObjectifyError as error:
        raise ObjectGeometryBuildError(str(error), retryable=error.retryable) from error
    objects = []
    for item in scene.objects:
        if item.id not in colliders:
            objects.append(item)
            continue
        geometry, collider = colliders[item.id]
        shell_ref, manifest_ref, _ = shells[item.id]
        updated = item.model_copy(
            update={
                "geometry_ref": geometry,
                "surface_mesh_ref": shell_ref,
                "collider": collider,
                "provenance": {
                    **item.provenance,
                    "shell_manifest_ref": manifest_ref.model_dump(mode="json"),
                    "surface_selection": {"chosen": "gaussian_shell"},
                },
            },
            deep=True,
        )
        if updated.source_collision is None:
            source_pose = Transform.model_validate(item.provenance["source_transform"])
            source_item = updated.model_copy(update={"transform": source_pose})
            (bound,) = bind_source_collision_ownership(
                [source_item], membership.source_geometry_ref, membership.extraction_revision
            )
            updated = updated.model_copy(update={"source_collision": bound.source_collision})
        objects.append(updated)
    updated_scene = scene.model_copy(
        update={
            "objects": objects,
            "environment": environment,
            "provenance": {
                **scene.provenance,
                "object_geometry": "ready",
                "geometry_build": {
                    "input_scene_revision": expected_revision,
                    "built_object_ids": sorted(colliders),
                    "at": datetime.now(UTC).isoformat(),
                },
            },
        },
        deep=True,
    )
    updated_scene = SceneIR.model_validate(updated_scene.model_dump())
    phase("publish")
    published = registry.scene.publish_next(
        job_id, expected_revision, updated_scene, "object_geometry_build", commit_guard=commit_guard
    )
    return published.revision.scene.scene_revision
