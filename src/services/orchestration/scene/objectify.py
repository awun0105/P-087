"""Tách scene theo vật (pipeline v2, ADR 0007 chặng 4–7): nền đã vá + Gaussian/collider từng vật.

Điều phối các provider qua process riêng trong runtime GPU (`data/scene_runtime`):

    hạt giống SAMPro3D → gán nhãn theo đóng góp render (`lift_runner`) → cắt PLY (numpy)
    → collider phân rã lồi (`convex_runner`, CPU) ∥ vá nền (`inpaint_runner`, GPU) → nén SOG cho web

Mọi đầu ra publish thành artifact bất biến theo nội dung; module trả phần `SceneEnvironment` +
`SceneObject` để nơi gọi ghi revision SceneIR (revision đầu của job mới, hoặc revision kế tiếp khi
chạy lại cho job cũ). Legacy failures await a user choice; explicitly selected ObjectGS failures
propagate and cannot publish a legacy success. ObjectGS runs in its own runtime before strict mesh CoACD.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from typing import Literal

import numpy as np
import trimesh
from PIL import Image
from pydantic import Field, FiniteFloat

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ContractModel, JsonObject, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.floor_model import FloorModel
from src.models.contracts.manifests import JobManifest, StageId
from src.models.contracts.object_geometry import ObjectSurfaceManifest
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import (
    ColliderSpec,
    ColliderType,
    SceneEnvironment,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
)
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.processing.config import load_job_config
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.diagnostics import capture_attempt
from src.services.orchestration.scene.errors import SceneRevisionConflictError
from src.services.orchestration.scene.floor_evidence import publish_floor_fit_evidence, scene_floor_fit_summary
from src.services.orchestration.scene.object_geometry_steps import (
    SurfaceInput,
    build_environment_collision,
    run_inpaint,
    run_inpaint_and_package,
    run_surface_colliders,
)
from src.services.orchestration.scene.objectgs_observations import package_observations
from src.services.orchestration.scene.surface_evidence import publish_surface_artifacts
from src.services.process_control import ProcessCancelledError, ProcessTimeoutError, run_cancellable_process
from src.services.reconstruction import camera_views, metric_visual_master
from src.services.reconstruction import package_splat as package_splat
from src.services.scene.collision_ownership import bind_source_collision_ownership
from src.services.scene.decomposition import gaussian_split
from src.services.scene.diagnostics import EvidenceRecorder
from src.services.scene.editing.membership import (
    encode_gaussian_membership_labels,
    membership_labels_for_parts,
)
from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.gaussian_shell import GaussianShellError, ShellParams, build_gaussian_shell
from src.services.scene.geometric import GeometricConfig, box_from_points
from src.services.scene.object_aware_geometry import build_background_collision as build_background_collision
from src.services.scene.objectgs import OBJECTGS_COMMIT, ObjectGSRuntime, PreparedObjectGSRequest, run_prepared_objectgs
from src.services.scene.sampro3d.consolidate import Sampro3dConfig, segment
from src.services.scene.sampro3d.pipeline import CameraFrame, Sam2Runtime, Sampro3dInputError, run_sam2

logger = logging.getLogger(__name__)

METHOD = "objectify_v1(sampro3d_sam2+render_lift+coacd+seed_inpaint)"
#: Giá trị `provenance.object_extraction` khi tách theo vật lỗi hết số lần thử: scene chỉ có môi trường,
#: chờ người dùng chọn chạy lại hoặc dùng hộp ứng viên.
AWAITING_CHOICE = "objectify_failed_awaiting_choice"
_REPO = Path(__file__).resolve().parents[4]
LIFT_RUNNER = _REPO / "src/services/scene/association/lift_runner.py"
CONVEX_RUNNER = _REPO / "src/services/simulation/colliders/convex_runner.py"
CORRECTION_OBSERVATIONS_RUNNER = _REPO / "src/services/scene/association/correction_observations.py"
INPAINT_RUNNER = _REPO / "src/services/reconstruction/rgb/inpaint/inpaint_runner.py"
#: Vùng làm việc quanh quỹ đạo camera, cùng quy tắc với REC-05 (geometry_v1).
_CROP_MARGIN_M = 6.0
_CROP_Z = (-0.5, 4.0)
_IDENTITY = (0.0, 0.0, 0.0, 1.0)

Publish = Callable[[ProductArtifactRef, bytes], ProductArtifactRef]


class SceneObjectifyConfig(ContractModel):
    """Validated seed count and render-lift controls; defaults match the runners."""

    refinement: Literal["legacy", "multiview_v1"] = "legacy"
    max_objects: int = Field(default=60, ge=1, strict=True)
    min_score: FiniteFloat = Field(default=0.6, ge=0, le=1)
    max_area: FiniteFloat = Field(default=0.35, gt=0, le=1)
    box_margin_m: FiniteFloat = Field(default=0.15, ge=0)
    sam_batch: int = Field(default=32, ge=1, strict=True)
    geometry_method: Literal["legacy", "shell", "objectgs"] = "legacy"
    geometry_review: Literal["legacy", "required", "auto"] = "legacy"
    objectgs_iterations: int = Field(default=30000, ge=1, strict=True)
    objectgs_background_voxel_m: FiniteFloat = Field(default=0.04, gt=0)


class CoacdObjectifyConfig(ContractModel):
    """Validated collider controls before invoking the standalone runner."""

    threshold: FiniteFloat = Field(default=0.08, gt=0, le=1)
    max_convex_hull: int = Field(default=8, ge=1, strict=True)
    preprocess_resolution: int = Field(default=30, ge=1, strict=True)
    voxel_m: FiniteFloat = Field(default=0.04, gt=0)


class InpaintObjectifyConfig(ContractModel):
    """Validated background fill budget and depth offset."""

    max_new_gaussians: int = Field(default=400_000, ge=0, strict=True)
    behind_object_m: FiniteFloat = Field(default=0.05, ge=0)


class ObjectifyConfig(ContractModel):
    """Optional overrides for each provider; absent groups retain runner defaults."""

    scene: SceneObjectifyConfig = Field(default_factory=SceneObjectifyConfig)
    coacd: CoacdObjectifyConfig = Field(default_factory=CoacdObjectifyConfig)
    inpaint: InpaintObjectifyConfig = Field(default_factory=InpaintObjectifyConfig)


class ObjectifyError(RuntimeError):
    """Một bước tách scene theo vật không chạy được; nơi gọi lùi về đường hộp."""

    def __init__(self, message: str, *, retryable: bool = True, floor_fit: JsonObject | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.floor_fit = floor_fit


@dataclass(frozen=True)
class ObjectifyResult:
    """Phần SceneIR do bước này tạo ra + tóm tắt để ghi provenance."""

    environment: SceneEnvironment
    objects: list[SceneObject]
    provenance: dict


def _ensure_not_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCancelledError("Objectify operation was cancelled")


def _run(
    python: Path,
    script: Path,
    request: dict,
    workspace: Path,
    name: str,
    timeout: float,
    *,
    cancel_event: Event | None = None,
) -> dict:
    """Chạy một provider trong runtime; lỗi/timeout → ObjectifyError có ngữ cảnh, log nằm trong workspace."""
    _ensure_not_cancelled(cancel_event)
    workspace.mkdir(parents=True, exist_ok=True)
    trace = EvidenceRecorder(workspace / "evidence", "provider-" + name)
    trace.emit("started", provider=name)
    if name in {"lift", "convex"}:
        request = {**request, "evidence_dir": str(workspace / "evidence")}
    request_path, result_path = workspace / f"{name}.request.json", workspace / f"{name}.result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    with (workspace / f"{name}.log").open("w") as log:
        try:
            returncode = run_cancellable_process(
                [str(python), str(script), "--request", str(request_path), "--result", str(result_path)],
                cwd=workspace,
                timeout_seconds=timeout,
                output=log,
                cancel_event=cancel_event,
            )
        except ProcessTimeoutError as error:
            trace.emit("failed", provider=name, reason="timeout")
            raise ObjectifyError(f"{name} quá thời gian cho phép") from error
    if returncode != 0 or not result_path.is_file():
        trace.emit("failed", provider=name, returncode=returncode, reason="provider_exit_or_missing_result")
        raise ObjectifyError(f"{name} lỗi (exit {returncode}); xem {name}.log")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    trace.emit("completed", provider=name)
    if name == "convex":
        for item in result.get("objects", []):
            trace.emit("collider", **item)
    return result


def _reference(job_id: str, tail: str, artifact_type: str, stage: StageId, payload: bytes) -> ProductArtifactRef:
    digest = hashlib.sha256(payload).hexdigest()
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/scene/{tail.format(digest=digest)}",
        artifact_checksum=f"sha256:{digest}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=stage,
        job_id=job_id,
    )


def _seeds(
    rows: np.ndarray,
    frames: list[CameraFrame],
    centers: np.ndarray,
    runtime: Sam2Runtime,
    workspace: Path,
    floor_model: FloorModel,
    cancel_event: Event | None = None,
    *,
    max_objects: int = 60,
    refinement: Literal["legacy", "multiview_v1"] = "legacy",
) -> list[np.ndarray]:
    """Hạt giống từng vật (chỉ số vào `rows`) từ SAMPro3D; bỏ khối không phải vật (kệ dài, mảnh vụn)."""
    low, high = centers.min(axis=0)[:2] - _CROP_MARGIN_M, centers.max(axis=0)[:2] + _CROP_MARGIN_M
    trace = EvidenceRecorder(workspace / "evidence", "seeds")
    work = gaussian_split.working_set(rows, low, high, _CROP_Z)
    trace.emit(
        "working_set",
        total_gaussians=len(rows),
        retained=len(work),
        low_xy=low.tolist(),
        high_xy=high.tolist(),
        z_range=list(_CROP_Z),
        min_opacity=0.3,
        max_objects=max_objects,
    )
    points = gaussian_split.positions(rows)[work]
    try:
        instances = segment(
            run_sam2(
                points,
                frames,
                runtime,
                workspace / "sampro3d",
                floor_model=floor_model,
                evidence_dir=workspace / "evidence",
                **({"refinement": refinement} if refinement != "legacy" else {}),
                cancel_event=cancel_event,
            ),
            points,
            floor_model,
            Sampro3dConfig(refinement=refinement),
            evidence=EvidenceRecorder(workspace / "evidence", "segmentation"),
        )
    except Sampro3dInputError as error:
        raise ObjectifyError(f"SAMPro3D lỗi: {error}", retryable=False) from error
    except ValueError as error:
        raise ObjectifyError(f"SAMPro3D lỗi: {error}") from error
    limits = GeometricConfig()
    kept = []
    floor_allowed = None
    if refinement == "multiview_v1":
        mask_labels = np.full(len(rows), -1, dtype=np.int32)
        for members in instances:
            mask_labels[work[members]] = 0
        floor_allowed = (
            gaussian_split.assign_floor_gaussians_to_background(rows, mask_labels, floor_model, refinement=True) >= 0
        )
    for members in instances:
        selected = members
        if floor_allowed is not None:
            selected = members[floor_allowed[work[members]]]
            if len(selected) < Sampro3dConfig().min_instance_points:
                trace.emit(
                    "seed_decision",
                    instance_key=hashlib.sha256(members.astype("<i8").tobytes()).hexdigest(),
                    accepted=False,
                    seed=None,
                    reason="insufficient_points_after_floor_shape_guard",
                )
                continue
        box = box_from_points(points[selected], len(selected))
        footprint = max(box.dimensions[0], box.dimensions[1])
        small_supported = False
        if refinement == "multiview_v1" and footprint < limits.min_footprint_m:
            xyz = points[selected]
            spread = np.linalg.svd(xyz - xyz.mean(axis=0), compute_uv=False) / np.sqrt(len(xyz))
            noise = floor_model.robust_noise_sigma_m
            small_supported = noise is not None and spread.min() > noise
        if (
            (limits.min_footprint_m <= footprint or small_supported)
            and footprint <= limits.max_footprint_m
            and box.dimensions[2] <= limits.max_object_height_m
        ):
            kept.append(work[selected])
            reason = None if len(kept) <= max_objects else "object_limit"
        else:
            reason = "footprint_or_height_limits"
        trace.emit(
            "seed_decision",
            instance_key=hashlib.sha256(members.astype("<i8").tobytes()).hexdigest(),
            points=len(members),
            dimensions=list(box.dimensions),
            refinement=refinement,
            floor_shape_removed=len(members) - len(selected),
            small_candidate_supported=small_supported,
            seed=len(kept) - 1 if reason is None else None,
            accepted=reason is None,
            reason=reason,
        )
    return kept[:max_objects]


@dataclass(frozen=True)
class CorrectedMembership:
    """Explicit immutable source frame for regeneration, bypassing segmentation."""

    membership: ObjectMembershipArtifact
    labels: np.ndarray
    source_poses: dict[str, Transform]
    evidence_ref: ProductArtifactRef | None = None


def _publish_draft(
    job_id: str,
    bundle: ReconstructionBundle,
    parts: list[gaussian_split.ObjectPart],
    seeds: list[np.ndarray],
    lift: dict,
    publish: Publish,
    publish_membership: Callable[[], ObjectMembershipArtifact],
    config: ObjectifyConfig,
    floor_model: FloorModel,
    floor_fit: JsonObject,
    cancel_event: Event | None,
) -> ObjectifyResult:
    """Publish review previews without creating collision geometry or filling the background."""
    membership = publish_membership()
    objects: list[SceneObject] = []
    for number, part in enumerate(parts, start=1):
        _ensure_not_cancelled(cancel_event)
        object_id = membership.label_to_object_id[str(part.index)]
        gaussians = gaussian_split.write_gaussian_ply(part.rows)
        visual = publish(
            _reference(job_id, "objects/{digest}.ply", "ObjectGaussians", StageId.SCENE_DECOMPOSE, gaussians), gaussians
        )
        transform = Transform(
            parent_frame="world",
            local_frame=object_id,
            translation_xyz=part.center,
            rotation_quaternion_xyzw=_IDENTITY,
        )
        provenance = {
            "method": METHOD,
            "gaussians": len(part.rows),
            "seed_gaussians": len(seeds[part.index]),
            "masks": int(
                lift["masks_per_object"][str(part.index)]
                if isinstance(lift["masks_per_object"], dict)
                else lift["masks_per_object"][part.index]
            ),
            "note": "ứng viên, cần người xác nhận",
            "source_transform": transform.model_dump(mode="json"),
        }
        try:
            # split() already returns object-local rows; the source centre must not be subtracted again.
            shell = build_gaussian_shell(
                gaussian_split.positions(part.rows),
                part.rows["opacity"],
                ShellParams(voxel_m=0.05, smooth_iterations=0),
            )
            mesh = trimesh.Trimesh(shell.vertices, shell.faces, process=False)
            provenance["shell_preview"] = {"voxel_m": 0.05, "checksum": shell.checksum, "statistics": shell.statistics}
        except GaussianShellError as error:
            mesh = trimesh.creation.box(extents=part.dimensions)
            provenance.update(shell_error=str(error), shell_display="bounding_box_placeholder")
        payload = mesh.export(file_type="glb")
        geometry = publish(
            _reference(job_id, "objects/shells/{digest}.glb", "ObjectShellMesh", StageId.SCENE_DECOMPOSE, payload),
            payload,
        )
        objects.append(
            SceneObject(
                id=object_id,
                name=f"Vật thể {number}",
                state=SceneObjectState.CANDIDATE,
                origin=SceneObjectOrigin.RECONSTRUCTED,
                active=False,
                local_frame=object_id,
                transform=transform,
                visual_ref=visual,
                geometry_ref=geometry,
                surface_mesh_ref=None,
                collider=None,
                primitive_dimensions_xyz_m=part.dimensions,
                tags=["objectify_v1"],
                provenance=provenance,
            )
        )
    observations: dict[str, object] = {}
    if config.scene.geometry_method == "objectgs":
        # Quan sát được đóng gói bất biến để build dùng lại; danh sách rỗng vẫn được ghi và build sẽ từ chối rõ ràng.
        payload = package_observations(lift.get("objectgs_views", []))
        observations_ref = publish(
            _reference(
                job_id,
                "objects/observations/{digest}.tar",
                "ObjectGSObservations",
                StageId.SCENE_DECOMPOSE,
                payload,
            ),
            payload,
        )
        observations["objectgs_observations_ref"] = observations_ref.model_dump(mode="json")
    return ObjectifyResult(
        environment=SceneEnvironment(
            visual_ref=bundle.visual_artifact_ref,
            geometry_ref=bundle.canonical_geometry_ref,
            membership=membership,
        ),
        objects=objects,
        provenance={
            "object_extraction": METHOD,
            "objectify_retryable": True,
            "object_geometry": "awaiting_review",
            "geometry_method": config.scene.geometry_method,
            "geometry_review": "required",
            "object_gaussians": sum(len(part.rows) for part in parts),
            "background_gaussians": membership.gaussian_count - sum(len(part.rows) for part in parts),
            "lift_views": int(lift["views"]),
            "segmentation_refinement": config.scene.refinement,
            "floor_model_status": floor_model.status,
            "floor_fallback_reason": floor_model.fallback_reason,
            "floor_profile_checksum": floor_model.profile_checksum,
            "floor_fit": floor_fit,
            **observations,
        },
    )


def objectgs_runtime_for(settings: Settings, config: ObjectifyConfig) -> ObjectGSRuntime:
    """Runtime ObjectGS cách ly theo cấu hình deployment; thiếu đường dẫn thì ném ObjectifyError."""
    paths = (
        settings.product_objectgs_runtime_python,
        settings.product_objectgs_repository,
        settings.product_objectgs_gsplat_repository,
    )
    if any(path is None for path in paths):
        raise ObjectifyError(
            "ObjectGS was selected but its isolated runtime/checkouts are not configured", retryable=False
        )
    return ObjectGSRuntime(
        python=paths[0].absolute(),
        repository=paths[1].resolve(),
        gsplat_repository=paths[2].resolve(),
        iterations=config.scene.objectgs_iterations,
        timeout_seconds=settings.product_objectgs_timeout_seconds,
        stall_seconds=settings.product_objectgs_stall_seconds,
        gpu_device=settings.product_objectgs_gpu_device,
        cuda_home=settings.product_objectgs_cuda_home,
        cxx=settings.product_objectgs_cxx,
        glm_repository=settings.product_objectgs_glm_repository,
        extension_cache_dir=settings.product_objectgs_extension_cache_dir,
    )


def objectify(
    registry: ProjectRegistry,
    job: JobManifest,
    bundle: ReconstructionBundle,
    settings: Settings,
    workspace: Path,
    publish: Publish,
    *,
    extraction_revision: str = "rev-001",
    cancel_event: Event | None = None,
    scene_config: dict[str, object] | None = None,
    correction: CorrectedMembership | None = None,
    progress: Callable[[str], None] | None = None,
) -> ObjectifyResult:
    """Chạy toàn bộ chặng 4–7 cho một bundle hệ mét; publish artifact và trả phần SceneIR."""
    config = ObjectifyConfig.model_validate({} if scene_config is None else scene_config)
    draft = (
        config.scene.geometry_review == "required"
        and config.scene.geometry_method in {"shell", "objectgs"}
        and correction is None
    )
    if correction is not None and config.scene.geometry_method != "objectgs":
        raise ObjectifyError("corrected membership requires strict ObjectGS geometry", retryable=False)
    report_progress = progress or (lambda stage: None)
    objectgs_runtime = None
    if config.scene.geometry_method == "objectgs" and not draft:
        objectgs_runtime = objectgs_runtime_for(settings, config)
    python, checkpoint = settings.product_scene_runtime_python, settings.product_sam2_checkpoint
    if python is None or (checkpoint is None and correction is None):
        raise ObjectifyError("chưa cấu hình runtime scene (PRODUCT_SCENE_RUNTIME_PYTHON / PRODUCT_SAM2_CHECKPOINT)")
    runtime = (
        Sam2Runtime(python, checkpoint, timeout_seconds=settings.product_scene_timeout_seconds)
        if correction is None
        else None
    )
    if correction is None and not runtime.available():
        raise ObjectifyError("runtime scene không tồn tại trên máy này")
    resolve = registry.runtime_resolver.require
    timeout = settings.product_scene_timeout_seconds
    workspace.mkdir(parents=True, exist_ok=True)

    source_visual_ref = correction.membership.source_visual_ref if correction else metric_visual_master(bundle, resolve)
    master = resolve(source_visual_ref)
    if isinstance(source_visual_ref, ProductArtifactRef):
        EvidenceRecorder(workspace / "evidence", "inputs").emit(
            "source_binding",
            source_visual_ref=source_visual_ref.model_dump(mode="json"),
            extraction_revision=extraction_revision,
        )
    rows = gaussian_split.read_gaussian_ply(master.read_bytes())
    source_points = gaussian_split.positions(rows)
    floor_model = fit_canonical_floor_model(source_points, point_cloud_checksum(source_points))
    floor_evidence_ref, floor_evidence = publish_floor_fit_evidence(job.job_id, source_visual_ref, floor_model, publish)
    floor_fit = scene_floor_fit_summary(floor_evidence_ref, floor_evidence)
    views = camera_views(bundle.camera_pose_refs[0], bundle.rgb_frame_refs, resolve)
    frames = [
        CameraFrame(view=view.model_dump(mode="json", exclude={"image"}), image_path=resolve(view.image))
        for view in views
    ]
    view_requests = [{**frame.view, "image_path": str(frame.image_path)} for frame in frames]
    _ensure_not_cancelled(cancel_event)
    if correction is None:
        try:
            seeds = _seeds(
                rows,
                frames,
                np.array([view.center for view in views]),
                runtime,
                workspace,
                floor_model,
                cancel_event,
                **({"max_objects": config.scene.max_objects} if scene_config is not None else {}),
                **({"refinement": config.scene.refinement} if config.scene.refinement != "legacy" else {}),
            )
        except ObjectifyError as error:
            error.floor_fit = floor_fit
            raise
        if not seeds:
            raise ObjectifyError("không tìm thấy vật nào để tách", retryable=False, floor_fit=floor_fit)

        np.savez(
            workspace / "seeds.npz",
            offsets=np.cumsum([0, *[len(seed) for seed in seeds]]),
            members=np.concatenate(seeds),
        )
        lift = _run(
            python,
            LIFT_RUNNER,
            {
                "gaussians_ply": str(master),
                "seeds_npz": str(workspace / "seeds.npz"),
                "sam2_config": runtime.model_config,
                "sam2_checkpoint": str(checkpoint.resolve()),
                "output_npz": str(workspace / "labels.npz"),
                "views": view_requests,
                # refinement is always explicit: the runner's own fallback is legacy.
                "config": {
                    **config.scene.model_dump(
                        exclude={
                            "max_objects",
                            "geometry_method",
                            "geometry_review",
                            "objectgs_iterations",
                            "objectgs_background_voxel_m",
                        },
                        exclude_unset=True,
                    ),
                    "refinement": config.scene.refinement,
                },
                **(
                    {"objectgs_observations_dir": str((workspace / "objectgs-observations").resolve())}
                    if config.scene.geometry_method == "objectgs"
                    else {}
                ),
            },
            workspace,
            "lift",
            timeout,
            cancel_event=cancel_event,
        )
        labels = np.load(workspace / "labels.npz")["labels"]
        trace = EvidenceRecorder(workspace / "evidence", "membership")
        before_floor_labels = labels
        labels = gaussian_split.assign_floor_gaussians_to_background(
            rows, labels, floor_model, **({"refinement": True} if config.scene.refinement == "multiview_v1" else {})
        )
        for label in np.unique(before_floor_labels[before_floor_labels >= 0]):
            trace.emit(
                "floor_filter",
                seed=int(label),
                before=int((before_floor_labels == label).sum()),
                returned_to_background=int(((before_floor_labels == label) & (labels < 0)).sum()),
                reason="floor_noise_and_covariance_guard"
                if config.scene.refinement == "multiview_v1"
                else "floor_protection",
                refinement=config.scene.refinement,
            )
    else:
        EvidenceRecorder(workspace / "evidence", "correction").emit(
            "corrected_membership",
            membership_checksum=correction.membership.labels_ref.artifact_checksum,
            evidence_ref=correction.evidence_ref.model_dump(mode="json") if correction.evidence_ref else None,
        )
        report_progress("observations")
        labels = correction.labels.copy()
        if len(labels) != len(rows):
            raise ObjectifyError("corrected source membership row count mismatch", retryable=False)
        source_labels_path = workspace / "corrected.i32le"
        source_labels_path.write_bytes(labels.astype("<i4").tobytes())
        seeds = {int(label): np.flatnonzero(labels == int(label)) for label in correction.membership.label_to_object_id}
        lift = _run(
            python,
            CORRECTION_OBSERVATIONS_RUNNER,
            {
                "gaussians_ply": str(master),
                "labels_path": str(source_labels_path),
                "label_to_object_id": correction.membership.label_to_object_id,
                "views": view_requests,
                "output_dir": str(workspace / "corrected-observations"),
            },
            workspace,
            "correction-observations",
            timeout,
            cancel_event=cancel_event,
        )
    trace = EvidenceRecorder(workspace / "evidence", "membership")
    background, parts = gaussian_split.split(rows, labels)
    if not parts:
        raise ObjectifyError("gán nhãn không cho ra vật nào đủ lớn")
    if correction is not None:
        if set(correction.membership.label_to_object_id) != {str(part.index) for part in parts}:
            raise ObjectifyError(
                "correction would discard an object; retain enough rows or delete it separately", retryable=False
            )
        adjusted = []
        for part in parts:
            object_id = correction.membership.label_to_object_id[str(part.index)]
            pose = correction.source_poses[object_id]
            if not np.allclose(pose.rotation_quaternion_xyzw, _IDENTITY):
                raise ObjectifyError("rotated immutable source frames require SH rotation support", retryable=False)
            local = rows[labels == part.index].copy()
            for axis, name in enumerate(("x", "y", "z")):
                local[name] -= pose.translation_xyz[axis]
            adjusted.append(replace(part, rows=local, center=pose.translation_xyz))
        parts = adjusted

    _ensure_not_cancelled(cancel_event)
    kept = np.isin(labels, [part.index for part in parts])
    (workspace / "objects_world.ply").write_bytes(gaussian_split.write_gaussian_ply(rows[kept]))
    (workspace / "background.ply").write_bytes(gaussian_split.write_gaussian_ply(background))
    for part in parts:
        (workspace / f"object_{part.index:03d}.ply").write_bytes(gaussian_split.write_gaussian_ply(part.rows))

    job_id = job.job_id
    label_to_object_id = (
        dict(correction.membership.label_to_object_id)
        if correction
        else {str(part.index): f"candidate-{number:03d}" for number, part in enumerate(parts, start=1)}
    )
    for label in np.unique(labels[labels >= 0]):
        object_id = label_to_object_id.get(str(label))
        trace.emit(
            "object_binding",
            seed=int(label),
            object_id=object_id,
            gaussian_count=int((labels == label).sum()),
            retained=object_id is not None,
            returned_to_background=0 if object_id else int((labels == label).sum()),
            reason=None if object_id else "too_few_object_gaussians",
        )
    trace.emit(
        "conservation",
        source=len(rows),
        background=len(background),
        object_gaussians=sum(len(part.rows) for part in parts),
    )
    membership_labels = membership_labels_for_parts(labels, [part.index for part in parts])
    membership_payload = encode_gaussian_membership_labels(
        membership_labels,
        gaussian_count=len(rows),
        label_to_object_id=label_to_object_id,
    )

    def publish_membership() -> ObjectMembershipArtifact:
        membership_labels_ref = publish(
            _reference(
                job_id,
                "objects/membership/{digest}.i32le",
                "ObjectMembershipLabels",
                StageId.SCENE_DECOMPOSE,
                membership_payload,
            ),
            membership_payload,
        )
        return ObjectMembershipArtifact(
            source_visual_ref=source_visual_ref,
            source_geometry_ref=bundle.canonical_geometry_ref,
            extraction_revision=correction.membership.extraction_revision if correction else extraction_revision,
            coordinate_system=CoordinateSystem(),
            gaussian_count=len(rows),
            labels_ref=membership_labels_ref,
            label_to_object_id=label_to_object_id,
        )

    if draft:
        return _publish_draft(
            job_id,
            bundle,
            parts,
            seeds,
            lift,
            publish,
            publish_membership,
            config,
            floor_model,
            floor_fit,
            cancel_event,
        )

    membership = publish_membership() if objectgs_runtime else None
    objectgs_receipt = None
    if objectgs_runtime is not None:
        mapped_views = []
        compact = {object_id: index + 1 for index, object_id in enumerate(sorted(label_to_object_id.values()))}
        for index, view in enumerate(lift.get("objectgs_views", [])):
            raw = np.load(view["mask_path"], allow_pickle=False)
            mask = np.zeros(raw.shape, dtype=np.uint8)
            for source_label, object_id in label_to_object_id.items():
                mask[raw == int(source_label)] = compact[object_id]
            path = (workspace / f"objectgs-mask-{index:06d}.png").resolve()
            Image.fromarray(mask).save(path)
            mapped_views.append({**view, "mask_path": str(path)})
        source_labels_path = (workspace / "source-membership.i32le").resolve()
        source_labels_path.write_bytes(membership_payload)
        source_poses = {
            label_to_object_id[str(part.index)]: Transform(
                parent_frame="world",
                local_frame=label_to_object_id[str(part.index)],
                translation_xyz=part.center,
                rotation_quaternion_xyzw=_IDENTITY,
            ).model_dump(mode="json")
            for part in parts
        }
        try:
            prepared = PreparedObjectGSRequest.model_validate(
                {
                    "job_id": job_id,
                    "source_ply": str(master.resolve()),
                    "source_labels": str(source_labels_path),
                    "membership": membership.model_dump(mode="json"),
                    "source_poses": source_poses,
                    "views": mapped_views,
                    "runtime": objectgs_runtime.model_dump(mode="json"),
                    "workspace": str((workspace / "objectgs-producer").resolve()),
                }
            )
            objectgs_receipt = run_prepared_objectgs(
                prepared,
                evidence_dir=workspace / "evidence",
                surface_artifact_callback=lambda object_id, item: publish_surface_artifacts(
                    job_id, object_id, item, publish
                ),
                cancel_event=cancel_event,
                progress=report_progress,
            )
        except (RuntimeError, ValueError, OSError) as error:
            if isinstance(error, ProcessCancelledError):
                raise
            raise ObjectifyError(f"ObjectGS required stage failed: {error}", retryable=False) from error
        if (
            objectgs_receipt.get("coordinate_frame") != "object_local"
            or objectgs_receipt.get("distance_unit") != "m"
            or objectgs_receipt.get("source_membership") != membership.model_dump(mode="json")
            or objectgs_receipt.get("source_poses") != source_poses
            or set(objectgs_receipt.get("objects", {})) != set(label_to_object_id.values())
            or any(
                item.get("quality_passed") is not True or not item.get("evidence_refs", {}).get("quality_report")
                for item in objectgs_receipt.get("objects", {}).values()
            )
        ):
            raise ObjectifyError("ObjectGS output frame/membership/source-pose receipt mismatch", retryable=False)

    report_progress("collider_and_background")
    # Collider chỉ dùng CPU, vá nền chỉ dùng GPU, và hai bước không đọc kết quả của nhau → chạy song song.
    coacd_config = config.coacd.model_dump(exclude_unset=True)
    inpaint_arguments = {
        "background_ply": workspace / "background.ply",
        "objects_ply": workspace / "objects_world.ply",
        "views": view_requests,
        "settings": settings,
        "inpaint_config": config.inpaint.model_dump(exclude_unset=True),
        "workspace": workspace,
        "timeout": timeout,
        "cancel_event": cancel_event,
    }
    convex_request = {
        "objects": [
            {
                "id": str(part.index),
                "gaussians_ply": str(workspace / f"object_{part.index:03d}.ply"),
                "output_glb": str(workspace / f"object_{part.index:03d}.glb"),
            }
            for part in parts
        ],
        "config": coacd_config,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        if objectgs_receipt is not None:
            inputs = [
                SurfaceInput(
                    key=str(part.index),
                    surface_path=Path(objectgs_receipt["objects"][label_to_object_id[str(part.index)]]["path"]),
                    surface_checksum=objectgs_receipt["objects"][label_to_object_id[str(part.index)]]["checksum"],
                    output_glb=workspace / f"object_{part.index:03d}.glb",
                )
                for part in parts
            ]
            convex_job = pool.submit(
                run_surface_colliders,
                python,
                inputs,
                coacd_config,
                workspace,
                timeout,
                cancel_event,
            )
        else:
            convex_job = pool.submit(
                _run,
                python,
                CONVEX_RUNNER,
                convex_request,
                workspace,
                "convex",
                timeout,
                cancel_event=cancel_event,
            )
        inpaint_job = pool.submit(run_inpaint, python, **inpaint_arguments)
        convex, inpaint = convex_job.result(), inpaint_job.result()
    colliders = (
        {int(key): item for key, item in convex.items()}
        if objectgs_receipt is not None
        else {int(item["id"]): item for item in convex["objects"]}
    )

    def ensure_membership() -> None:
        nonlocal membership
        if membership is None:
            membership = publish_membership()

    master_ref, visual_ref, inpaint = run_inpaint_and_package(
        python,
        **inpaint_arguments,
        publish=publish,
        job_id=job_id,
        inpaint_result=inpaint,
        before_publish=ensure_membership,
    )

    surface_refs: dict[str, ProductArtifactRef] = {}
    surface_manifests: dict[str, ProductArtifactRef] = {}
    if objectgs_receipt is not None:
        checkpoint_payload = Path(objectgs_receipt["checkpoint_path"]).read_bytes()
        if f"sha256:{hashlib.sha256(checkpoint_payload).hexdigest()}" != objectgs_receipt["checkpoint_checksum"]:
            raise ObjectifyError("ObjectGS checkpoint checksum mismatch", retryable=False)
        checkpoint_ref = publish(
            _reference(
                job_id,
                "objectgs/{digest}/checkpoint.tar.gz",
                "ObjectGSCheckpoint",
                StageId.SCENE_DECOMPOSE,
                checkpoint_payload,
            ),
            checkpoint_payload,
        )
        dataset_payload = Path(objectgs_receipt["dataset_path"]).read_bytes()
        if f"sha256:{hashlib.sha256(dataset_payload).hexdigest()}" != objectgs_receipt["dataset_checksum"]:
            raise ObjectifyError("ObjectGS dataset checksum mismatch", retryable=False)
        dataset_ref = publish(
            _reference(
                job_id, "objectgs/{digest}/dataset.tar.gz", "ObjectGSDataset", StageId.SCENE_DECOMPOSE, dataset_payload
            ),
            dataset_payload,
        )
        for object_id, info in objectgs_receipt["objects"].items():
            surface_provenance = {
                "upstream_commit": objectgs_receipt["upstream_commit"],
                "gsplat_commit": objectgs_receipt["gsplat_commit"],
                "glm_commit": objectgs_receipt.get("glm_commit"),
                "training_config_checksum": objectgs_receipt["config_checksum"],
                "export_config": objectgs_receipt["export_config"],
                "runtime": objectgs_receipt["runtime"],
                "source_world_from_object": source_poses[object_id],
                "surface_evidence": info.get("evidence_refs", {}),
            }
            surface_payload = Path(info["path"]).read_bytes()
            if f"sha256:{hashlib.sha256(surface_payload).hexdigest()}" != info["checksum"]:
                raise ObjectifyError("ObjectGS surface checksum mismatch", retryable=False)
            reference = ProductArtifactRef.model_validate(info["evidence_refs"]["surface"])
            if (
                reference.artifact_type != "ObjectSurfaceMesh"
                or reference.job_id != job_id
                or reference.artifact_checksum != info["checksum"]
            ):
                raise ObjectifyError("ObjectGS accepted surface evidence binding mismatch", retryable=False)
            surface_refs[object_id] = reference
            manifest = ObjectSurfaceManifest(
                object_id=object_id,
                objectgs_label_id=info["label"],
                surface_mesh_ref=surface_refs[object_id],
                source_checkpoint_ref=checkpoint_ref,
                source_dataset_ref=dataset_ref,
                source_membership=membership,
                upstream_commit=OBJECTGS_COMMIT,
                canonical_world_from_training=Transform(
                    parent_frame="world",
                    local_frame="objectgs_training",
                    translation_xyz=(0, 0, 0),
                    rotation_quaternion_xyzw=_IDENTITY,
                ),
                vertex_count=info["vertex_count"],
                triangle_count=info["triangle_count"],
                quality={
                    "watertight": info["watertight"],
                    "passed": info.get("quality_passed", False),
                    "report_ref": info.get("evidence_refs", {}).get("quality_report"),
                },
                provenance=surface_provenance,
            )
            manifest_payload = manifest.model_dump_json().encode()
            surface_manifests[object_id] = publish(
                _reference(
                    job_id,
                    "objectgs/surfaces/{digest}.json",
                    "ObjectSurfaceManifest",
                    StageId.SCENE_DECOMPOSE,
                    manifest_payload,
                ),
                manifest_payload,
            )

    objects: list[SceneObject] = []
    binding_trace = EvidenceRecorder(workspace / "evidence", "object_binding")
    for number, part in enumerate(parts, start=1):
        _ensure_not_cancelled(cancel_event)
        object_id = label_to_object_id[str(part.index)]
        gaussians = gaussian_split.write_gaussian_ply(part.rows)
        visual = publish(
            _reference(job_id, "objects/{digest}.ply", "ObjectGaussians", StageId.SCENE_DECOMPOSE, gaussians), gaussians
        )
        collider_info = colliders.get(part.index, {})
        collider_path = workspace / f"object_{part.index:03d}.glb"
        if collider_info.get("parts") and collider_path.is_file():
            collider_payload = collider_path.read_bytes()
            collider_type = ColliderType.CONVEX_DECOMPOSITION
        else:
            # Quá ít điểm để dựng mặt bao: dùng hộp bao làm hình học + collider.
            collider_payload = trimesh.creation.box(extents=part.dimensions).export(file_type="glb")
            collider_type = ColliderType.OBB
        geometry = publish(
            _reference(job_id, "colliders/{digest}.glb", "ObjectCollider", StageId.COLLIDER, collider_payload),
            collider_payload,
        )
        binding_trace.emit(
            "collider_binding",
            object_id=object_id,
            seed=part.index,
            method=str(collider_info.get("method", "coacd")) if collider_type != ColliderType.OBB else "aabb",
            parts=int(collider_info.get("parts", 1)) if collider_type != ColliderType.OBB else 1,
            fallback_reason=collider_info.get("fallback_reason") or collider_info.get("error"),
            collider_checksum=geometry.artifact_checksum,
        )
        objects.append(
            SceneObject(
                id=object_id,
                name=f"Vật thể {number}",
                state=SceneObjectState.CANDIDATE,
                origin=SceneObjectOrigin.RECONSTRUCTED,
                active=False,
                local_frame=object_id,
                transform=Transform(
                    parent_frame="world",
                    local_frame=object_id,
                    translation_xyz=part.center,
                    rotation_quaternion_xyzw=_IDENTITY,
                ),
                visual_ref=visual,
                geometry_ref=geometry,
                surface_mesh_ref=surface_refs.get(object_id),
                primitive_dimensions_xyz_m=part.dimensions,
                collider=ColliderSpec(
                    collider_id=f"{object_id}-collider",
                    collider_type=collider_type,
                    local_transform=Transform(
                        parent_frame=object_id,
                        local_frame=f"{object_id}-collider",
                        translation_xyz=(0.0, 0.0, 0.0),
                        rotation_quaternion_xyzw=_IDENTITY,
                    ),
                    dimensions_xyz_m=part.dimensions if collider_type == ColliderType.OBB else None,
                    geometry_ref=geometry,
                    parameters={
                        "parts": int(collider_info.get("parts", 1)) if collider_type != ColliderType.OBB else 1,
                        "volume_m3": float(collider_info.get("volume_m3", 0.0)),
                    },
                    provenance={
                        "generator": str(collider_info.get("method", "coacd"))
                        if collider_type == ColliderType.CONVEX_DECOMPOSITION
                        else "aabb",
                        "fallback_reason": collider_info.get("fallback_reason")
                        or (collider_info.get("error") if collider_type == ColliderType.OBB else None),
                        **(
                            {
                                "surface_mesh_ref": surface_refs[object_id].model_dump(mode="json"),
                                "coacd_config": config.coacd.model_dump(),
                                "strict_surface_input": True,
                            }
                            if object_id in surface_refs
                            else {}
                        ),
                    },
                ),
                tags=["objectify_v1"],
                provenance={
                    "method": METHOD,
                    "gaussians": int(len(part.rows)),
                    "seed_gaussians": int(len(seeds[part.index])),
                    "masks": int(
                        lift["masks_per_object"].get(str(part.index), 0)
                        if isinstance(lift["masks_per_object"], dict)
                        else lift["masks_per_object"][part.index]
                    ),
                    "note": "ứng viên, cần người xác nhận",
                    **(
                        {"surface_manifest_ref": surface_manifests[object_id].model_dump(mode="json")}
                        if object_id in surface_manifests
                        else {}
                    ),
                },
            )
        )
    provenance = {
        "object_extraction": METHOD,
        "objectify_retryable": True,
        "object_gaussians": int(kept.sum()),
        "background_gaussians": int(inpaint["original_gaussians"]),
        "inpainted_gaussians": int(inpaint["inpainted_gaussians"]),
        "inpaint_method": inpaint["method"],
        "inpaint_note": "Gaussian vá nằm cuối file nền; là hình suy đoán cho vùng chưa từng được quay",
        "lift_views": int(lift["views"]),
        "segmentation_refinement": config.scene.refinement,
        "floor_model_status": floor_model.status,
        "floor_fallback_reason": floor_model.fallback_reason,
        "floor_profile_checksum": floor_model.profile_checksum,
    }
    provenance["floor_fit"] = floor_fit
    environment = SceneEnvironment(
        visual_ref=visual_ref,
        geometry_ref=bundle.canonical_geometry_ref,
        visual_master_ref=master_ref,
        membership=membership,
    )
    if objectgs_receipt is not None:
        footprints = []
        for part in parts:
            if correction is None:
                low = np.asarray(part.center) - np.asarray(part.dimensions) / 2
                high = np.asarray(part.center) + np.asarray(part.dimensions) / 2
            else:
                anchors = source_points[membership_labels == part.index]
                low, high = anchors.min(axis=0), anchors.max(axis=0)
            footprints.append((low, high))
        active_ref, manifest_ref = build_environment_collision(
            source_points=source_points,
            membership_labels=membership_labels,
            label_to_object_id=label_to_object_id,
            footprints=footprints,
            footprint_centers=[part.center for part in parts],
            floor_model=floor_model,
            floor_fit=floor_fit,
            voxel_m=config.scene.objectgs_background_voxel_m,
            bundle=bundle,
            membership=membership,
            publish=publish,
            job_id=job_id,
        )
        environment = environment.model_copy(
            update={"collider_ref": active_ref, "object_aware_collision_ref": manifest_ref}
        )
        provenance.update(
            geometry_method="objectgs",
            objectgs_commit=OBJECTGS_COMMIT,
            object_extraction="objectify_v1(sam2+objectgs+object_aware_occupancy+coacd+seed_inpaint)",
        )
    return ObjectifyResult(environment=environment, objects=objects, provenance=provenance)


def job_requires_strict_geometry(registry: ProjectRegistry, job: JobManifest) -> bool:
    """Read the sealed job choice so required shell/ObjectGS failures cannot become a legacy success."""
    processing = load_job_config(job.job_id, job.config_checksum, registry.runtime_resolver)
    return processing is not None and processing.scene.get("geometry_method") in {"shell", "objectgs"}


def objectify_with_retry(
    registry: ProjectRegistry,
    job: JobManifest,
    bundle: ReconstructionBundle,
    settings: Settings,
    workspace: Path,
    publish: Publish,
    *,
    extraction_revision: str = "rev-001",
    cancel_event: Event | None = None,
    scene_config: dict[str, object] | None = None,
    geometry_method: Literal["legacy", "shell", "objectgs"] | None = None,
    refinement: Literal["legacy", "multiview_v1"] | None = None,
    correction: CorrectedMembership | None = None,
    progress: Callable[[str], None] | None = None,
) -> ObjectifyResult:
    """Thử `objectify` tối đa `product_objectify_attempts` lần, mỗi lần một workspace riêng (giữ log từng lần).

    Lỗi GPU thường thoáng qua (hết VRAM do tiến trình khác, driver) nên đáng thử lại; hết số lần thì ném
    `ObjectifyError` kèm lỗi cuối — nơi gọi **không** tự lùi về đường hộp mà để người dùng chọn.
    """
    if scene_config is None:
        processing = load_job_config(job.job_id, job.config_checksum, registry.runtime_resolver)
        if processing is not None and processing.scene:
            groups: dict[str, dict[str, object]] = {"scene": {}, "coacd": {}, "inpaint": {}}
            for key, value in processing.scene.items():
                group, name = key.split("_", 1) if key.startswith(("coacd_", "inpaint_")) else ("scene", key)
                groups[group][name] = value
            scene_config = ObjectifyConfig.model_validate(groups).model_dump(exclude_unset=True)
    if geometry_method is not None or refinement is not None:
        values = {} if scene_config is None else dict(scene_config)
        scene_values = dict(values.get("scene", {}))
        if geometry_method is not None:
            scene_values["geometry_method"] = geometry_method
        if refinement is not None:
            scene_values["refinement"] = refinement
        values["scene"] = scene_values
        scene_config = ObjectifyConfig.model_validate(values).model_dump(exclude_unset=True)
    attempts = settings.product_objectify_attempts
    last: Exception | None = None
    for number in range(1, attempts + 1):
        try:
            arguments = {"cancel_event": cancel_event} if cancel_event is not None else {}
            if scene_config is not None:
                arguments["scene_config"] = scene_config
            if correction is not None:
                arguments["correction"] = correction
                arguments["progress"] = progress
            attempt_workspace = workspace / f"attempt-{number}"
            return capture_attempt(
                lambda: objectify(
                    registry,
                    job,
                    bundle,
                    settings,
                    attempt_workspace,
                    publish,
                    extraction_revision=extraction_revision,
                    **arguments,
                ),
                job=job,
                bundle=bundle,
                workspace=attempt_workspace,
                publish=publish,
                input_revision=extraction_revision,
            )
        except ProcessCancelledError:
            raise
        except (ObjectifyError, ValueError, OSError) as error:
            logger.warning("Tách theo vật lỗi job=%s lần %d/%d: %s", job.job_id, number, attempts, error)
            if isinstance(error, ObjectifyError) and not error.retryable:
                raise
            last = error
    raise ObjectifyError(
        f"tách theo vật lỗi sau {attempts} lần: {last}",
        floor_fit=last.floor_fit if isinstance(last, ObjectifyError) else None,
    ) from last


def reobjectify(
    registry: ProjectRegistry,
    job_id: str,
    settings: Settings,
    workspace: Path,
    *,
    expected_revision: str | None = None,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
    geometry_method: Literal["legacy", "shell", "objectgs"] | None = None,
    refinement: Literal["legacy", "multiview_v1"] | None = None,
) -> str:
    """Chạy lại tách theo vật cho job đã có SceneIR; ghi **revision kế tiếp** (không sửa revision cũ).

    Dùng để nâng scene dựng bằng đường hộp (ADR 0006) lên scene theo vật mà không dựng lại từ video.
    Vật và trạng thái xác nhận của revision trước không mang sang: tập vật mới là ứng viên mới.
    """
    from src.services.orchestration.artifacts import FilesystemArtifactStore
    from src.services.orchestration.jobs.stage_views import job_bundle
    from src.services.scene.publisher import with_scene_checksum

    base_scene = registry.scene.current(job_id).scene
    if expected_revision is None:
        expected_revision = base_scene.scene_revision
    if base_scene.scene_revision != expected_revision:
        raise SceneRevisionConflictError(
            f"scene đã đổi: yêu cầu đang giữ {expected_revision}, revision hiện tại là {base_scene.scene_revision}"
        )
    if base_scene.environment.collision_selection_ref is not None:
        raise ObjectifyError(
            "Không thể thay tập object khi collision source đang được chọn; khôi phục revision trước khi chọn nguồn mới"
        )
    job = registry.get_job(job_id)
    bundle = job_bundle(registry, job)
    if bundle is None:
        raise ObjectifyError("job chưa có ReconstructionBundle hệ mét")
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        if registry.runtime_resolver.locate(reference.artifact_uri) is not None:
            return reference
        return store.publish(reference, payload)

    arguments = {"cancel_event": cancel_event} if cancel_event is not None else {}
    if geometry_method is not None:
        arguments["geometry_method"] = geometry_method
    if refinement is not None:
        arguments["refinement"] = refinement
    result = objectify_with_retry(
        registry,
        job,
        bundle,
        settings,
        workspace,
        publish,
        extraction_revision=expected_revision,
        **arguments,
    )
    # The new candidates replace the old set, so they own regions of the collision mesh just like extraction's.
    objects = bind_source_collision_ownership(result.objects, result.environment.geometry_ref, expected_revision)
    updated = base_scene.model_copy(
        update={
            "environment": result.environment,
            "objects": objects,
            "provenance": {
                **base_scene.provenance,
                **result.provenance,
                "note": "chạy lại tách theo vật",
                **({"geometry_method_override": geometry_method} if geometry_method is not None else {}),
            },
        }
    )
    published = registry.scene.publish_next(
        job_id,
        expected_revision,
        with_scene_checksum(updated),
        "objectify",
        commit_guard=commit_guard,
    )
    registry.runtime_resolver.sync_up(job_id)
    return published.revision.scene.scene_revision
