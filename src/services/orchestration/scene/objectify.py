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
from dataclasses import dataclass
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
from src.models.contracts.object_geometry import ObjectAwareEnvironmentManifest, ObjectSurfaceManifest
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
from src.services.process_control import ProcessCancelledError, ProcessTimeoutError, run_cancellable_process
from src.services.reconstruction import camera_views, metric_visual_master, package_splat
from src.services.scene.collision_ownership import bind_source_collision_ownership
from src.services.scene.decomposition import gaussian_split
from src.services.scene.diagnostics import EvidenceRecorder
from src.services.scene.editing.membership import (
    encode_gaussian_membership_labels,
    membership_labels_for_parts,
)
from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.geometric import GeometricConfig, box_from_points
from src.services.scene.object_aware_geometry import build_background_collision
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
INPAINT_RUNNER = _REPO / "src/services/reconstruction/rgb/inpaint/inpaint_runner.py"
#: Vùng làm việc quanh quỹ đạo camera, cùng quy tắc với REC-05 (geometry_v1).
_CROP_MARGIN_M = 6.0
_CROP_Z = (-0.5, 4.0)
_IDENTITY = (0.0, 0.0, 0.0, 1.0)

Publish = Callable[[ProductArtifactRef, bytes], ProductArtifactRef]


class SceneObjectifyConfig(ContractModel):
    """Validated seed count and render-lift controls; defaults match the runners."""

    max_objects: int = Field(default=60, ge=1, strict=True)
    min_score: FiniteFloat = Field(default=0.6, ge=0, le=1)
    max_area: FiniteFloat = Field(default=0.35, gt=0, le=1)
    box_margin_m: FiniteFloat = Field(default=0.15, ge=0)
    sam_batch: int = Field(default=32, ge=1, strict=True)
    geometry_method: Literal["legacy", "objectgs"] = "legacy"
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
                cancel_event=cancel_event,
            ),
            points,
            floor_model,
            Sampro3dConfig(),
            evidence=EvidenceRecorder(workspace / "evidence", "segmentation"),
        )
    except Sampro3dInputError as error:
        raise ObjectifyError(f"SAMPro3D lỗi: {error}", retryable=False) from error
    except ValueError as error:
        raise ObjectifyError(f"SAMPro3D lỗi: {error}") from error
    limits = GeometricConfig()
    kept = []
    for members in instances:
        box = box_from_points(points[members], len(members))
        footprint = max(box.dimensions[0], box.dimensions[1])
        if (
            limits.min_footprint_m <= footprint <= limits.max_footprint_m
            and box.dimensions[2] <= limits.max_object_height_m
        ):
            kept.append(work[members])
            reason = None if len(kept) <= max_objects else "object_limit"
        else:
            reason = "footprint_or_height_limits"
        trace.emit(
            "seed_decision",
            instance_key=hashlib.sha256(members.astype("<i8").tobytes()).hexdigest(),
            points=len(members),
            dimensions=list(box.dimensions),
            seed=len(kept) - 1 if reason is None else None,
            accepted=reason is None,
            reason=reason,
        )
    return kept[:max_objects]


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
) -> ObjectifyResult:
    """Chạy toàn bộ chặng 4–7 cho một bundle hệ mét; publish artifact và trả phần SceneIR."""
    config = ObjectifyConfig.model_validate({} if scene_config is None else scene_config)
    objectgs_runtime = None
    if config.scene.geometry_method == "objectgs":
        paths = (
            settings.product_objectgs_runtime_python,
            settings.product_objectgs_repository,
            settings.product_objectgs_gsplat_repository,
        )
        if any(path is None for path in paths):
            raise ObjectifyError(
                "ObjectGS was selected but its isolated runtime/checkouts are not configured", retryable=False
            )
        objectgs_runtime = ObjectGSRuntime(
            python=paths[0].absolute(),
            repository=paths[1].resolve(),
            gsplat_repository=paths[2].resolve(),
            iterations=config.scene.objectgs_iterations,
            timeout_seconds=settings.product_objectgs_timeout_seconds,
            gpu_device=settings.product_objectgs_gpu_device,
            cuda_home=settings.product_objectgs_cuda_home,
            cxx=settings.product_objectgs_cxx,
            glm_repository=settings.product_objectgs_glm_repository,
        )
    python, checkpoint = settings.product_scene_runtime_python, settings.product_sam2_checkpoint
    if python is None or checkpoint is None:
        raise ObjectifyError("chưa cấu hình runtime scene (PRODUCT_SCENE_RUNTIME_PYTHON / PRODUCT_SAM2_CHECKPOINT)")
    runtime = Sam2Runtime(python, checkpoint, timeout_seconds=settings.product_scene_timeout_seconds)
    if not runtime.available():
        raise ObjectifyError("runtime scene không tồn tại trên máy này")
    resolve = registry.runtime_resolver.require
    timeout = settings.product_scene_timeout_seconds
    workspace.mkdir(parents=True, exist_ok=True)

    source_visual_ref = metric_visual_master(bundle, resolve)
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
            "config": config.scene.model_dump(
                exclude={"max_objects", "geometry_method", "objectgs_iterations", "objectgs_background_voxel_m"},
                exclude_unset=True,
            ),
            **(
                {"objectgs_observations_dir": str((workspace / "objectgs-observations").resolve())}
                if objectgs_runtime
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
    labels = gaussian_split.assign_floor_gaussians_to_background(rows, labels, floor_model)
    for label in np.unique(before_floor_labels[before_floor_labels >= 0]):
        trace.emit(
            "floor_filter",
            seed=int(label),
            before=int((before_floor_labels == label).sum()),
            returned_to_background=int(((before_floor_labels == label) & (labels < 0)).sum()),
            reason="floor_protection",
        )
    background, parts = gaussian_split.split(rows, labels)
    if not parts:
        raise ObjectifyError("gán nhãn không cho ra vật nào đủ lớn")

    _ensure_not_cancelled(cancel_event)
    kept = np.isin(labels, [part.index for part in parts])
    (workspace / "objects_world.ply").write_bytes(gaussian_split.write_gaussian_ply(rows[kept]))
    (workspace / "background.ply").write_bytes(gaussian_split.write_gaussian_ply(background))
    for part in parts:
        (workspace / f"object_{part.index:03d}.ply").write_bytes(gaussian_split.write_gaussian_ply(part.rows))

    job_id = job.job_id
    label_to_object_id = {str(part.index): f"candidate-{number:03d}" for number, part in enumerate(parts, start=1)}
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
            extraction_revision=extraction_revision,
            coordinate_system=CoordinateSystem(),
            gaussian_count=len(rows),
            labels_ref=membership_labels_ref,
            label_to_object_id=label_to_object_id,
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
                cancel_event=cancel_event,
                progress=lambda stage: logger.info("ObjectGS stage=%s job=%s", stage, job_id),
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
        ):
            raise ObjectifyError("ObjectGS output frame/membership/source-pose receipt mismatch", retryable=False)

    # Collider chỉ dùng CPU, vá nền chỉ dùng GPU, và hai bước không đọc kết quả của nhau → chạy song song.
    convex_request = {
        "objects": [
            {
                "id": str(part.index),
                "gaussians_ply": str(workspace / f"object_{part.index:03d}.ply"),
                "output_glb": str(workspace / f"object_{part.index:03d}.glb"),
            }
            for part in parts
        ],
        "config": config.coacd.model_dump(exclude_unset=True),
    }
    if objectgs_receipt is not None:
        convex_request["objects"] = [
            {
                "id": str(part.index),
                "surface_mesh": objectgs_receipt["objects"][label_to_object_id[str(part.index)]]["path"],
                "surface_checksum": objectgs_receipt["objects"][label_to_object_id[str(part.index)]]["checksum"],
                "coordinate_frame": "object_local",
                "distance_unit": "m",
                "output_glb": str(workspace / f"object_{part.index:03d}.glb"),
            }
            for part in parts
        ]
    inpaint_request = {
        "background_ply": str(workspace / "background.ply"),
        "objects_ply": str(workspace / "objects_world.ply"),
        "output_ply": str(workspace / "background_inpainted.ply"),
        "lama_checkpoint": str(settings.product_lama_checkpoint) if settings.product_lama_checkpoint else None,
        "views": view_requests,
        "config": config.inpaint.model_dump(exclude_unset=True),
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
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
        inpaint_job = pool.submit(
            _run,
            python,
            INPAINT_RUNNER,
            inpaint_request,
            workspace,
            "inpaint",
            timeout,
            cancel_event=cancel_event,
        )
        convex, inpaint = convex_job.result(), inpaint_job.result()
    colliders = {int(item["id"]): item for item in convex["objects"]}
    if objectgs_receipt is not None and any(
        not colliders.get(part.index, {}).get("parts")
        or colliders.get(part.index, {}).get("error")
        or not (workspace / f"object_{part.index:03d}.glb").is_file()
        for part in parts
    ):
        raise ObjectifyError(
            "ObjectGS surface collider generation failed; Gaussian/OBB fallback is forbidden", retryable=False
        )
    try:
        sog = package_splat(
            workspace / "background_inpainted.ply",
            workspace / "sog",
            settings.product_geometry_gpu_index,
            cancel_event=cancel_event,
        )
    except (ValueError, OSError) as error:
        raise ObjectifyError(f"nén SOG nền lỗi: {error}") from error

    if membership is None:
        membership = publish_membership()
    _ensure_not_cancelled(cancel_event)
    background_payload = (workspace / "background_inpainted.ply").read_bytes()
    master_ref = publish(
        _reference(
            job_id, "environment/{digest}/background.ply", "GaussianPLY", StageId.SCENE_DECOMPOSE, background_payload
        ),
        background_payload,
    )
    sog_payload = sog.read_bytes()
    visual_ref = publish(
        _reference(
            job_id, "environment/{digest}/background.sog", "VisualArtifact", StageId.SCENE_DECOMPOSE, sog_payload
        ),
        sog_payload,
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
            }
            surface_payload = Path(info["path"]).read_bytes()
            if f"sha256:{hashlib.sha256(surface_payload).hexdigest()}" != info["checksum"]:
                raise ObjectifyError("ObjectGS surface checksum mismatch", retryable=False)
            surface_refs[object_id] = publish(
                _reference(
                    job_id,
                    "objectgs/surfaces/{digest}.glb",
                    "ObjectSurfaceMesh",
                    StageId.SCENE_DECOMPOSE,
                    surface_payload,
                ).model_copy(update={"source_provenance": surface_provenance}),
                surface_payload,
            )
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
                quality={"watertight": info["watertight"]},
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
        object_id = f"candidate-{number:03d}"
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
                    "masks": int(lift["masks_per_object"][part.index]),
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
        voxel = config.scene.objectgs_background_voxel_m
        support = []
        # Inferred support never comes from inpaint rows or a current edited object pose.
        if floor_model.status in {"supported", "confirmed_prior_fallback"}:
            normal = np.asarray(floor_model.plane_normal_world)
            for part in parts:
                low = np.asarray(part.center) - np.asarray(part.dimensions) / 2
                high = np.asarray(part.center) + np.asarray(part.dimensions) / 2
                base = np.array([part.center[0], part.center[1], low[2]])
                if abs(float(normal @ base + floor_model.plane_offset_m)) > floor_model.floor_band_m + 2 * voxel:
                    continue
                xs = np.arange(low[0], high[0] + voxel, voxel)
                ys = np.arange(low[1], high[1] + voxel, voxel)
                if len(xs) * len(ys) > 1_000_000:
                    raise ObjectifyError("inferred support exceeds the geometry budget", retryable=False)
                for x in xs:
                    for y in ys:
                        z = -(normal[0] * x + normal[1] * y + floor_model.plane_offset_m) / normal[2]
                        support.append([x, y, z])
        background_mesh = build_background_collision(
            source_points,
            membership_labels,
            {int(label) for label in label_to_object_id},
            voxel_m=voxel,
            unknown=membership_labels < 0,
            inferred_support_points=np.asarray(support).reshape(-1, 3),
        )
        mesh = trimesh.Trimesh(background_mesh.vertices, background_mesh.faces, process=False)
        collision_payload = mesh.export(file_type="glb")
        active_ref = publish(
            _reference(
                job_id,
                "objectgs/environment/{digest}.glb",
                "ObjectAwareEnvironmentCollision",
                StageId.COLLIDER,
                collision_payload,
            ),
            collision_payload,
        )
        manifest = ObjectAwareEnvironmentManifest(
            source_geometry_ref=bundle.canonical_geometry_ref,
            collision_ref=active_ref,
            source_membership=membership,
            removed_object_ids=sorted(label_to_object_id.values()),
            occupancy_checksum=background_mesh.occupancy_checksum,
            provenance={
                "statistics": background_mesh.statistics,
                "voxel_m": voxel,
                "support_origin": "inferred_floor_plane_under_source_contact_footprints",
                "floor_fit": floor_fit,
                "watertight": bool(mesh.is_watertight),
                "inpaint_used_for_physics": False,
            },
        )
        manifest_payload = manifest.model_dump_json().encode()
        manifest_ref = publish(
            _reference(
                job_id,
                "objectgs/environment/{digest}.json",
                "ObjectAwareEnvironmentManifest",
                StageId.COLLIDER,
                manifest_payload,
            ),
            manifest_payload,
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


def job_requires_objectgs(registry: ProjectRegistry, job: JobManifest) -> bool:
    """Read the sealed job choice so required ObjectGS failures cannot become a legacy success."""
    processing = load_job_config(job.job_id, job.config_checksum, registry.runtime_resolver)
    return processing is not None and processing.scene.get("geometry_method") == "objectgs"


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
    geometry_method: Literal["legacy", "objectgs"] | None = None,
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
    if geometry_method is not None:
        values = {} if scene_config is None else dict(scene_config)
        scene_values = dict(values.get("scene", {}))
        scene_values["geometry_method"] = geometry_method
        values["scene"] = scene_values
        scene_config = ObjectifyConfig.model_validate(values).model_dump(exclude_unset=True)
    attempts = settings.product_objectify_attempts
    last: Exception | None = None
    for number in range(1, attempts + 1):
        try:
            arguments = {"cancel_event": cancel_event} if cancel_event is not None else {}
            if scene_config is not None:
                arguments["scene_config"] = scene_config
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
    geometry_method: Literal["legacy", "objectgs"] | None = None,
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
