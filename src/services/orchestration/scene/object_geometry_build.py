"""Build reviewed object geometry and publish it through the existing SceneIR revision fence."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import numpy as np
import trimesh
from PIL import Image
from scipy.spatial.transform import Rotation

from src.config import Settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_geometry import ObjectShellManifest, ObjectSurfaceManifest
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.scene import (
    ColliderSpec,
    ColliderType,
    SceneEnvironment,
    SceneIR,
    SceneObject,
    SceneObjectState,
)
from src.services.orchestration.artifacts import ArtifactStoreError, FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.processing.config import load_job_config
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene import objectify
from src.services.orchestration.scene.floor_evidence import publish_floor_fit_evidence, scene_floor_fit_summary
from src.services.orchestration.scene.object_geometry_steps import (
    SurfaceInput,
    build_environment_collision,
    run_inpaint_and_package,
    run_surface_colliders,
)
from src.services.orchestration.scene.objectgs_observations import unpack_observations
from src.services.orchestration.scene.objectify import (
    ObjectifyConfig,
    ObjectifyError,
    Publish,
    _ensure_not_cancelled,
    _reference,
)
from src.services.orchestration.scene.surface_evidence import publish_surface_artifacts
from src.services.process_control import ProcessCancelledError
from src.services.reconstruction import camera_views
from src.services.scene.collision_ownership import bind_source_collision_ownership
from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply, write_gaussian_ply
from src.services.scene.editing.membership import StaleObjectMembershipRevisionError, decode_gaussian_membership_labels
from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.gaussian_shell import GaussianShellError, ShellParams, build_gaussian_shell
from src.services.scene.geometry_state import object_geometry_state
from src.services.scene.objectgs import ObjectGSRuntime, ObjectGSView, PreparedObjectGSRequest, run_prepared_objectgs


class ObjectGeometryBuildError(RuntimeError):
    """A geometry build failed without changing the active scene."""

    def __init__(self, message: str, *, object_id: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.object_id = object_id
        self.retryable = retryable


@dataclass(frozen=True)
class MembershipOverride:
    labels: np.ndarray
    manifest: ObjectMembershipArtifact
    evidence_ref: ProductArtifactRef


@dataclass(frozen=True)
class _Surface:
    """Surface chosen for one object's collider; `surface_ref` is what the scene records as surface_mesh_ref."""

    origin: str  # "gaussian_shell" | "objectgs"
    # None for a shell: its ref is read from the GLB only after CoACD succeeds, as before.
    surface_ref: ProductArtifactRef | None
    collider_input: SurfaceInput
    selection: dict
    provenance: dict = field(default_factory=dict)


_SURFACE_LABEL = {"gaussian_shell": "Gaussian shell", "objectgs": "ObjectGS surface"}
_SURFACE_ORIGIN = {"gaussian_shell": "gaussian_shell_v1", "objectgs": "objectgs_v1"}


def _objectgs_runtime(settings: Settings, config: ObjectifyConfig) -> ObjectGSRuntime:
    try:
        return objectify.objectgs_runtime_for(settings, config)
    except ObjectifyError as error:
        raise ObjectGeometryBuildError(
            "ObjectGS được chọn nhưng runtime/checkout chưa cấu hình; scene duyệt vẫn được giữ. "
            "Cấu hình runtime rồi thử lại, hoặc đổi geometry_method sang shell.",
            retryable=False,
        ) from error


def _observations_ref(scene: SceneIR) -> ProductArtifactRef:
    raw = scene.provenance.get("objectgs_observations_ref")
    if not isinstance(raw, dict):
        raise ObjectGeometryBuildError(
            "Scene không có quan sát ObjectGS; tạo lại scene duyệt với geometry_method=objectgs.", retryable=False
        )
    try:
        return ProductArtifactRef.model_validate(raw)
    except ValueError as error:
        raise ObjectGeometryBuildError(
            "Tham chiếu quan sát ObjectGS trong scene hỏng; tạo lại scene duyệt.", retryable=False
        ) from error


def _source_pose(item: SceneObject) -> Transform:
    try:
        pose = Transform.model_validate(item.provenance.get("source_transform"))
    except ValueError as error:
        raise ObjectGeometryBuildError(
            f"{item.id}: source_transform không hợp lệ: {error}", object_id=item.id
        ) from error
    if pose.parent_frame != "world" or pose.local_frame != item.id:
        raise ObjectGeometryBuildError(
            f"{item.id}: source_transform phải nối world với khung của vật", object_id=item.id
        )
    return pose


def _publish_verified(
    receipt: dict, kind: str, job_id: str, tail: str, artifact_type: str, publish: Publish
) -> ProductArtifactRef:
    payload = Path(receipt[f"{kind}_path"]).read_bytes()
    if sha256_bytes(payload) != receipt[f"{kind}_checksum"]:
        raise ObjectGeometryBuildError(f"ObjectGS {kind} không khớp checksum trong biên nhận.", retryable=False)
    return publish(_reference(job_id, tail, artifact_type, StageId.SCENE_DECOMPOSE, payload), payload)


def _rasterize_current_labels(
    observed: list[dict],
    membership: ObjectMembershipArtifact,
    labels_file: Path,
    source_ply: Path,
    settings: Settings,
    workspace: Path,
    cancel_event: Event | None,
) -> list[dict]:
    """Render hàng nguồn theo nhãn hiện tại lên từng quan sát, bằng đúng bộ render của correction_observations."""
    if settings.product_scene_runtime_python is None:
        raise ObjectGeometryBuildError("Chưa cấu hình runtime scene để render mask ObjectGS.", retryable=False)
    try:
        result = objectify._run(
            settings.product_scene_runtime_python,
            objectify.CORRECTION_OBSERVATIONS_RUNNER,
            {
                "gaussians_ply": str(source_ply),
                "labels_path": str(labels_file),
                "label_to_object_id": membership.label_to_object_id,
                "views": observed,
                "output_dir": str(workspace / "objectgs-masks"),
            },
            workspace,
            "correction-observations",
            settings.product_scene_timeout_seconds,
            cancel_event=cancel_event,
        )
    except ObjectifyError as error:
        raise ObjectGeometryBuildError(
            f"Không render được mask ObjectGS từ nhãn hiện tại: {error}", retryable=error.retryable
        ) from error
    rendered = result.get("objectgs_views", [])
    if len(rendered) != len(observed):
        raise ObjectGeometryBuildError("Bộ render mask trả số quan sát khác gói quan sát.", retryable=False)
    return rendered


def _compact_masks(rendered: list[dict], membership: ObjectMembershipArtifact, workspace: Path) -> list[ObjectGSView]:
    """Đổi nhãn nguồn sang id compact 1..N theo membership hiện tại, cùng quy ước với prepare_dataset."""
    object_ids = sorted(set(membership.label_to_object_id.values()))
    compact = {object_id: index + 1 for index, object_id in enumerate(object_ids)}
    views = []
    for index, view in enumerate(rendered):
        raw = np.load(view["mask_path"], allow_pickle=False)
        mask = np.zeros(raw.shape, dtype=np.uint8)
        for source_label, object_id in membership.label_to_object_id.items():
            mask[raw == int(source_label)] = compact[object_id]
        path = (workspace / f"objectgs-mask-{index:06d}.png").resolve()
        Image.fromarray(mask).save(path)
        views.append(ObjectGSView.model_validate({**view, "mask_path": str(path)}))
    return views


def _objectgs_surfaces(
    *,
    registry: ProjectRegistry,
    settings: Settings,
    runtime: ObjectGSRuntime,
    job_id: str,
    membership: ObjectMembershipArtifact,
    selected: list[SceneObject],
    shells: dict[str, tuple[ProductArtifactRef, ProductArtifactRef, SurfaceInput]],
    observations_ref: ProductArtifactRef,
    workspace: Path,
    publish: Publish,
    cancel_event: Event | None,
) -> dict[str, _Surface]:
    """Chạy ObjectGS trên quan sát với mask dựng từ nhãn hiện tại. Lỗi toàn cục làm build thất bại, không có fallback."""
    resolve = registry.runtime_resolver.require
    selected_ids = {item.id for item in selected}
    if selected_ids != set(membership.label_to_object_id.values()):
        labels = decode_gaussian_membership_labels(resolve(membership.labels_ref).read_bytes(), membership).copy()
        mapping = {key: owner for key, owner in membership.label_to_object_id.items() if owner in selected_ids}
        labels[~np.isin(labels, [int(key) for key in mapping])] = -1
        payload = labels.astype("<i4").tobytes()
        labels_ref = publish(
            _reference(
                job_id,
                "objectgs/selected-labels/{digest}.i32le",
                "ObjectMembershipLabels",
                StageId.SCENE_DECOMPOSE,
                payload,
            ),
            payload,
        )
        membership = membership.model_copy(update={"labels_ref": labels_ref, "label_to_object_id": mapping})
    try:
        # The store verifies the declared checksum on read; a mismatch or missing file never reaches ObjectGS.
        payload = resolve(observations_ref).read_bytes()
    except ArtifactStoreError as error:
        raise ObjectGeometryBuildError(
            "Quan sát ObjectGS không đọc được hoặc sai checksum; tạo lại scene duyệt.", retryable=False
        ) from error
    try:
        observed = unpack_observations(payload, workspace / "objectgs-observations")
    except ValueError as error:
        raise ObjectGeometryBuildError(f"Gói quan sát ObjectGS hỏng: {error}", retryable=False) from error
    if not observed:
        raise ObjectGeometryBuildError(
            "Gói quan sát ObjectGS rỗng; tạo lại scene duyệt với geometry_method=objectgs.", retryable=False
        )
    labels_file = workspace / "source-labels.i32le"
    labels_file.write_bytes(resolve(membership.labels_ref).read_bytes())
    source_ply = resolve(membership.source_visual_ref)
    rendered = _rasterize_current_labels(
        observed, membership, labels_file, source_ply, settings, workspace, cancel_event
    )
    views = _compact_masks(rendered, membership, workspace)
    poses = {item.id: _source_pose(item) for item in selected}
    if set(poses) != set(membership.label_to_object_id.values()):
        raise ObjectGeometryBuildError("Scene thiếu vật của membership nên không thể chạy ObjectGS.", retryable=False)
    expected = {object_id: pose.model_dump(mode="json") for object_id, pose in poses.items()}
    try:
        request = PreparedObjectGSRequest(
            job_id=job_id,
            source_ply=source_ply,
            source_labels=labels_file,
            membership=membership,
            source_poses=poses,
            views=views,
            runtime=runtime,
            workspace=workspace / "objectgs-run",
        )
        receipt = run_prepared_objectgs(
            request,
            cancel_event=cancel_event,
            evidence_dir=workspace / "evidence" / "objectgs",
            surface_artifact_callback=lambda object_id, item: publish_surface_artifacts(
                job_id, object_id, item, publish
            ),
            raise_on_quality_failure=False,
        )
    except ProcessCancelledError:
        raise
    except (RuntimeError, ValueError, OSError) as error:
        raise ObjectGeometryBuildError(
            f"ObjectGS lỗi: {error}. Scene duyệt vẫn được giữ; thử lại, hoặc đổi geometry_method sang shell "
            "nếu muốn bỏ ObjectGS.",
            retryable=isinstance(error, (RuntimeError, OSError)),
        ) from error
    if (
        receipt.get("coordinate_frame") != "object_local"
        or receipt.get("distance_unit") != "m"
        or receipt.get("source_membership") != membership.model_dump(mode="json")
        or receipt.get("source_poses") != expected
        or set(receipt.get("objects", {})) != set(membership.label_to_object_id.values())
    ):
        raise ObjectGeometryBuildError("Biên nhận ObjectGS không khớp membership hoặc pose nguồn.", retryable=False)
    checkpoint_ref = _publish_verified(
        receipt, "checkpoint", job_id, "objectgs/{digest}/checkpoint.tar.gz", "ObjectGSCheckpoint", publish
    )
    dataset_ref = _publish_verified(
        receipt, "dataset", job_id, "objectgs/{digest}/dataset.tar.gz", "ObjectGSDataset", publish
    )
    surfaces: dict[str, _Surface] = {}
    for item in selected:
        info = receipt["objects"][item.id]
        evidence = {
            "checkpoint": checkpoint_ref.model_dump(mode="json"),
            "dataset": dataset_ref.model_dump(mode="json"),
            "surface_evidence": info["evidence_refs"],
        }
        if info.get("quality_passed") is not True:
            # Per-object rule (architecture §8.4): this object keeps its Gaussian shell, and the reason is recorded.
            shell_ref, _, shell_input = shells[item.id]
            surfaces[item.id] = _Surface(
                origin="gaussian_shell",
                surface_ref=shell_ref,
                collider_input=shell_input,
                selection={
                    "chosen": "gaussian_shell",
                    "reason": "objectgs_quality_failed",
                    "quality_reasons": list(info.get("quality_reasons", [])),
                },
                provenance={"objectgs_evidence": evidence},
            )
            continue
        surface_payload = Path(info["path"]).read_bytes()
        if sha256_bytes(surface_payload) != info["checksum"]:
            raise ObjectGeometryBuildError("Surface ObjectGS không khớp checksum", object_id=item.id)
        surface_ref = ProductArtifactRef.model_validate(info["evidence_refs"]["surface"])
        if (
            surface_ref.artifact_type != "ObjectSurfaceMesh"
            or surface_ref.job_id != job_id
            or surface_ref.artifact_checksum != info["checksum"]
        ):
            raise ObjectGeometryBuildError("Evidence surface ObjectGS không ràng buộc đúng vật", object_id=item.id)
        manifest = ObjectSurfaceManifest(
            object_id=item.id,
            objectgs_label_id=info["label"],
            surface_mesh_ref=surface_ref,
            source_checkpoint_ref=checkpoint_ref,
            source_dataset_ref=dataset_ref,
            source_membership=membership,
            upstream_commit=receipt["upstream_commit"],
            canonical_world_from_training=Transform(
                parent_frame="world",
                local_frame="objectgs_training",
                translation_xyz=(0, 0, 0),
                rotation_quaternion_xyzw=(0, 0, 0, 1),
            ),
            vertex_count=info["vertex_count"],
            triangle_count=info["triangle_count"],
            quality={
                "watertight": info["watertight"],
                "passed": True,
                "report_ref": info["evidence_refs"].get("quality_report"),
            },
            provenance={
                "upstream_commit": receipt["upstream_commit"],
                "gsplat_commit": receipt["gsplat_commit"],
                "glm_commit": receipt.get("glm_commit"),
                "training_config_checksum": receipt["config_checksum"],
                "export_config": receipt["export_config"],
                "runtime": receipt["runtime"],
                "source_world_from_object": expected[item.id],
                "surface_evidence": info["evidence_refs"],
            },
        )
        manifest_payload = manifest.model_dump_json().encode()
        manifest_ref = publish(
            _reference(
                job_id,
                "objectgs/surfaces/{digest}.json",
                "ObjectSurfaceManifest",
                StageId.SCENE_DECOMPOSE,
                manifest_payload,
            ),
            manifest_payload,
        )
        surfaces[item.id] = _Surface(
            origin="objectgs",
            surface_ref=surface_ref,
            collider_input=SurfaceInput(
                item.id, Path(info["path"]), info["checksum"], workspace / f"{item.id}-collider.glb"
            ),
            selection={"chosen": "objectgs"},
            provenance={
                "objectgs_surface_manifest_ref": manifest_ref.model_dump(mode="json"),
                "objectgs_evidence": evidence,
            },
        )
    return surfaces


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
    """Shell-only colliders (T-007 contract): each input is a Gaussian shell GLB already on disk."""
    surfaces = {
        item.key: _Surface(
            origin="gaussian_shell",
            surface_ref=None,
            collider_input=item,
            selection={"chosen": "gaussian_shell"},
        )
        for item in inputs
    }
    return _publish_colliders(surfaces, settings, coacd_config, workspace, publish, job_id, cancel_event)


def _publish_colliders(
    surfaces: dict[str, _Surface],
    settings: Settings,
    coacd_config: dict,
    workspace: Path,
    publish: Publish,
    job_id: str,
    cancel_event: Event | None = None,
) -> dict[str, tuple[ProductArtifactRef, ColliderSpec]]:
    if settings.product_scene_runtime_python is None:
        raise ObjectGeometryBuildError("Chưa cấu hình runtime CoACD.")
    results: dict[str, dict] = {}
    for origin in dict.fromkeys(surface.origin for surface in surfaces.values()):
        group = [surface.collider_input for surface in surfaces.values() if surface.origin == origin]
        try:
            results.update(
                run_surface_colliders(
                    settings.product_scene_runtime_python,
                    group,
                    coacd_config,
                    workspace,
                    settings.product_scene_timeout_seconds,
                    cancel_event,
                    surface_label=_SURFACE_LABEL[origin],
                    surface_origin=origin,
                )
            )
        except ObjectifyError as error:
            raise ObjectGeometryBuildError(str(error), retryable=error.retryable) from error
    colliders = {}
    for key, surface in surfaces.items():
        _ensure_not_cancelled(cancel_event)
        payload = surface.collider_input.output_glb.read_bytes()
        geometry = publish(
            _reference(job_id, "colliders/{digest}.glb", "ObjectCollider", StageId.COLLIDER, payload), payload
        )
        surface_ref = surface.surface_ref or _reference(
            job_id,
            "objects/shells/{digest}.glb",
            "ObjectShellMesh",
            StageId.SCENE_DECOMPOSE,
            surface.collider_input.surface_path.read_bytes(),
        )
        collider_id = f"{key}-collider"
        collider = ColliderSpec(
            collider_id=collider_id,
            collider_type=ColliderType.CONVEX_DECOMPOSITION,
            local_transform=Transform(
                parent_frame=key,
                local_frame=collider_id,
                translation_xyz=(0, 0, 0),
                rotation_quaternion_xyzw=(0, 0, 0, 1),
            ),
            geometry_ref=geometry,
            parameters={"parts": int(results[key]["parts"])},
            provenance={
                "generator": "coacd",
                "surface_origin": _SURFACE_ORIGIN[surface.origin],
                "surface_mesh_ref": surface_ref.model_dump(mode="json"),
                "coacd_config": coacd_config,
                "strict_surface_input": True,
            },
        )
        colliders[key] = (geometry, collider)
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
) -> tuple[SceneEnvironment, int]:
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
    master, visual, inpaint_result = run_inpaint_and_package(
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
    inpainted = inpaint_result.get("inpainted_gaussians")
    if isinstance(inpainted, bool) or not isinstance(inpainted, int) or inpainted < 0:
        raise ObjectGeometryBuildError("Inpaint không trả số Gaussian vá hợp lệ.")
    _ensure_not_cancelled(cancel_event)
    xyz = positions(rows)
    floor_model = fit_canonical_floor_model(xyz, point_cloud_checksum(xyz))
    floor_ref, evidence = publish_floor_fit_evidence(job_id, membership.source_visual_ref, floor_model, publish)
    # Ignored objects keep their source visuals separately and their source occupancy in the background.
    ignored = {
        item.id
        for item in scene.objects
        if item.provenance.get("review") == "IGNORED"
        and (object_geometry_state(scene) == "awaiting_review" or item.collider is None)
    }
    separated = {key: owner for key, owner in membership.label_to_object_id.items() if owner not in ignored}
    footprints = []
    for owner in sorted(set(separated.values())):
        keys = [int(key) for key, value in membership.label_to_object_id.items() if value == owner]
        anchors = xyz[np.isin(labels, keys)]
        if len(anchors):
            footprints.append((anchors.min(axis=0), anchors.max(axis=0)))
    collision, manifest = build_environment_collision(
        source_points=xyz,
        membership_labels=labels,
        label_to_object_id=separated,
        footprints=footprints,
        floor_model=floor_model,
        floor_fit=scene_floor_fit_summary(floor_ref, evidence),
        voxel_m=config.scene.objectgs_background_voxel_m,
        bundle=bundle,
        membership=membership,
        publish=publish,
        job_id=job_id,
    )
    environment = scene.environment.model_copy(
        update={
            "visual_ref": visual,
            "visual_master_ref": master,
            "collider_ref": collision,
            "object_aware_collision_ref": manifest,
        },
        deep=True,
    )
    return environment, inpainted


def build_object_geometry(
    registry: ProjectRegistry,
    settings: Settings,
    job_id: str,
    *,
    expected_revision: str,
    workspace: Path,
    object_ids: set[str] | None = None,
    membership_override: MembershipOverride | None = None,
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
    if object_ids is not None and object_geometry_state(scene) != "ready":
        raise ObjectGeometryBuildError("Scene Draft cần dựng hình học toàn bộ vật trước khi dựng lại từng vật.")
    if scene.environment.membership is None:
        raise ObjectGeometryBuildError("Scene không có source membership để dựng hình học.")
    if membership_override is not None and (object_geometry_state(scene) != "ready" or not object_ids):
        raise ObjectGeometryBuildError("Membership rebuild requires a Ready scene and affected object_ids")
    if membership_override is None and object_ids is None and object_geometry_state(scene) != "awaiting_review":
        raise ObjectGeometryBuildError("Scene phải đang duyệt tách vật trước khi tạo mesh.")
    if object_ids is None:
        pending = [
            item
            for item in scene.objects
            if item.state == SceneObjectState.CANDIDATE
            and item.provenance.get("review") not in {"IGNORED", "DELETED", "MERGED"}
        ]
        if pending:
            raise ObjectGeometryBuildError(
                f"Còn {len(pending)} vật chưa duyệt. Chọn vật để chỉnh sửa hoặc giữ trong nền cố định trước khi tạo mesh."
            )
    membership = scene.environment.membership
    if membership.labels_ref.job_id != job_id or membership.source_geometry_ref != scene.environment.geometry_ref:
        raise ObjectGeometryBuildError("Geometry build source membership does not match the scene")
    if scene.environment.collision_selection_ref is not None:
        raise ObjectGeometryBuildError("Dựng hình học trên scene nguồn trước khi chọn collision source khác.")
    resolve = registry.runtime_resolver.require
    if membership_override is not None:
        override = membership_override
        preserved = (
            "source_visual_ref",
            "source_geometry_ref",
            "extraction_revision",
            "coordinate_system",
            "gaussian_count",
        )
        if any(getattr(override.manifest, key) != getattr(membership, key) for key in preserved) or (
            set(override.manifest.label_to_object_id.values()) != set(membership.label_to_object_id.values())
            or override.manifest.labels_ref.job_id != job_id
            or override.evidence_ref.job_id != job_id
            or override.evidence_ref.artifact_type not in {"ObjectRegionEdit", "ObjectMembershipCorrection"}
        ):
            raise ObjectGeometryBuildError("Membership override does not match the immutable source")
        membership = override.manifest
        resolve(override.evidence_ref)
        scene = scene.model_copy(
            update={"environment": scene.environment.model_copy(update={"membership": membership})}
        )
    payload = resolve(membership.source_visual_ref).read_bytes()
    if sha256_bytes(payload) != membership.source_visual_ref.artifact_checksum:
        raise ObjectGeometryBuildError("source PLY checksum mismatch")
    try:
        rows = read_gaussian_ply(payload)
        labels = decode_gaussian_membership_labels(resolve(membership.labels_ref).read_bytes(), membership)
        if membership_override is not None and (
            membership_override.labels.dtype != np.dtype("int32")
            or membership_override.labels.shape != labels.shape
            or not np.array_equal(membership_override.labels, labels)
        ):
            raise ValueError("membership override labels do not match the published manifest")
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
    objectgs_mode = config.scene.geometry_method == "objectgs"
    run_objectgs = (
        objectgs_mode
        and object_ids is None
        and any(item.provenance.get("review") != "IGNORED" for item in scene.objects)
    )
    objectgs_runtime = _objectgs_runtime(settings, config) if run_objectgs else None
    observations_ref = _observations_ref(scene) if run_objectgs else None
    mapped = set(membership.label_to_object_id.values())
    if not mapped <= {item.id for item in scene.objects}:
        raise ObjectGeometryBuildError("Membership references missing scene objects")
    if object_ids is not None and (not object_ids or not object_ids <= mapped):
        raise ObjectGeometryBuildError("Geometry build requested unknown membership objects")
    if membership_override is not None:
        objects = []
        for item in scene.objects:
            if item.id in object_ids and "source_transform" not in item.provenance:
                ownership = item.source_collision
                if (
                    ownership is None
                    or ownership.source_geometry_ref != membership.source_geometry_ref
                    or ownership.extraction_revision != membership.extraction_revision
                ):
                    raise ObjectGeometryBuildError(f"{item.id}: missing matching source ownership", object_id=item.id)
                item = item.model_copy(
                    update={
                        "provenance": {
                            **item.provenance,
                            "source_transform": ownership.source_transform.model_dump(mode="json"),
                        }
                    }
                )
            objects.append(item)
        scene = scene.model_copy(update={"objects": objects})
    selected = [
        item
        for item in scene.objects
        if item.id in membership.label_to_object_id.values()
        and (object_ids is None or item.id in object_ids)
        and (object_ids is not None or item.provenance.get("review") != "IGNORED")
    ]
    if object_ids is not None and any(
        item.provenance.get("review") == "IGNORED" and item.collider is None for item in selected
    ):
        raise ObjectGeometryBuildError("Vật giữ trong nền cố định không cần dựng mesh riêng.")
    if membership_override is not None:
        for item in selected:
            keys = [int(key) for key, owner in membership.label_to_object_id.items() if owner == item.id]
            if np.count_nonzero(np.isin(labels, keys)) < 50:
                raise ObjectGeometryBuildError(f"{item.id}: rebuild requires at least 50 Gaussians", object_id=item.id)
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
        shell_item = item
        if membership_override is not None:
            provenance = dict(item.provenance)
            provenance.pop("shell_error", None)
            shell_item = item.model_copy(update={"provenance": provenance})
        shells[item.id] = _build_shell(shell_item, rows[np.isin(labels, keys)], membership, workspace, publish)
    if run_objectgs and selected:
        # ObjectGS chạy trước mọi collider: nếu nó lỗi toàn cục thì không có collider nào được dựng từ vỏ.
        phase("objectgs")
        surfaces = _objectgs_surfaces(
            registry=registry,
            settings=settings,
            runtime=objectgs_runtime,
            job_id=job_id,
            membership=membership,
            selected=selected,
            shells=shells,
            observations_ref=observations_ref,
            workspace=workspace,
            publish=publish,
            cancel_event=cancel_event,
        )
    else:
        surfaces = {
            item.id: _Surface(
                origin="gaussian_shell",
                surface_ref=shells[item.id][0],
                collider_input=shells[item.id][2],
                selection={
                    "chosen": "gaussian_shell",
                    **({"reason": "partial_rebuild_uses_shell"} if objectgs_mode else {}),
                },
            )
            for item in selected
        }
    phase("quality")
    phase("collider")
    colliders = (
        _publish_colliders(
            surfaces,
            settings,
            config.coacd.model_dump(exclude_unset=True),
            workspace,
            publish,
            job_id,
            cancel_event,
        )
        if surfaces
        else {}
    )
    phase("environment")
    try:
        environment, inpainted_count = _build_environment(
            registry, settings, job_id, scene, rows, labels, config, workspace, publish, cancel_event
        )
    except ObjectifyError as error:
        raise ObjectGeometryBuildError(str(error), retryable=error.retryable) from error
    objects = []
    for item in scene.objects:
        if item.id not in colliders:
            if item.id in mapped and item.provenance.get("review") == "IGNORED" and item.source_collision is None:
                source_item = item.model_copy(update={"transform": _source_pose(item)})
                (bound,) = bind_source_collision_ownership(
                    [source_item], membership.source_geometry_ref, membership.extraction_revision
                )
                item = item.model_copy(update={"source_collision": bound.source_collision})
            objects.append(item)
            continue
        geometry, collider = colliders[item.id]
        _, manifest_ref, _ = shells[item.id]
        surface = surfaces[item.id]
        visual_update = {}
        provenance = dict(item.provenance)
        if membership_override is not None:
            keys = [int(key) for key, owner in membership.label_to_object_id.items() if owner == item.id]
            local_rows = rows[np.isin(labels, keys)].copy()
            if len(local_rows) < 50:
                raise ObjectGeometryBuildError(f"{item.id}: rebuild requires at least 50 Gaussians", object_id=item.id)
            pose = _source_pose(item)
            rotation = Rotation.from_quat(pose.rotation_quaternion_xyzw)
            local = (positions(local_rows) - np.asarray(pose.translation_xyz)) @ rotation.as_matrix()
            for axis, name in enumerate(("x", "y", "z")):
                local_rows[name] = local[:, axis]
            if all(f"rot_{axis}" in local_rows.dtype.names for axis in range(4)):
                world = np.column_stack([local_rows[f"rot_{axis}"] for axis in (1, 2, 3, 0)])
                quaternions = (rotation.inv() * Rotation.from_quat(world)).as_quat()
                for axis, name in enumerate(("rot_1", "rot_2", "rot_3", "rot_0")):
                    local_rows[name] = quaternions[:, axis]
            visual_data = write_gaussian_ply(local_rows)
            visual_update = {
                "visual_ref": publish(
                    _reference(job_id, "objects/{digest}.ply", "ObjectGaussians", StageId.SCENE_DECOMPOSE, visual_data),
                    visual_data,
                ),
                "primitive_dimensions_xyz_m": tuple(float(v) for v in np.maximum(np.ptp(local, axis=0), 0.05)),
            }
            for key in (
                "shell_error",
                "shell_display",
                "shell_preview",
                "objectgs_surface_manifest_ref",
                "objectgs_evidence",
            ):
                provenance.pop(key, None)
            provenance["gaussians"] = len(local_rows)
        updated = item.model_copy(
            update={
                **visual_update,
                "geometry_ref": geometry,
                "surface_mesh_ref": surface.surface_ref,
                "collider": collider,
                "provenance": {
                    **provenance,
                    "shell_manifest_ref": manifest_ref.model_dump(mode="json"),
                    "surface_selection": surface.selection,
                    **surface.provenance,
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
    # Validator reads this count for the background master written above; a `reassign` correction carries its own copy.
    correction = scene.provenance.get("membership_correction")
    if membership_override is not None:
        correction = {"evidence_ref": membership_override.evidence_ref.model_dump(mode="json")}
    elif isinstance(correction, dict) and correction.get("operation") == "reassign":
        correction = {**correction, "inpainted_gaussians": inpainted_count}
    provenance = {
        **scene.provenance,
        "object_geometry": "ready",
        "inpainted_gaussians": inpainted_count,
        "geometry_build": {
            "input_scene_revision": expected_revision,
            "built_object_ids": sorted(colliders),
            "at": datetime.now(UTC).isoformat(),
        },
    }
    if correction is not None:
        provenance["membership_correction"] = correction
    updated_scene = scene.model_copy(
        update={"objects": objects, "environment": environment, "provenance": provenance},
        deep=True,
    )
    updated_scene = SceneIR.model_validate(updated_scene.model_dump())
    phase("publish")
    published = registry.scene.publish_next(
        job_id, expected_revision, updated_scene, "object_geometry_build", commit_guard=commit_guard
    )
    return published.revision.scene.scene_revision
