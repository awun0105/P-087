"""Tách scene theo vật (pipeline v2, ADR 0007 chặng 4–7): nền đã vá + Gaussian/collider từng vật.

Điều phối các provider qua process riêng trong runtime GPU (`data/scene_runtime`):

    hạt giống SAMPro3D → gán nhãn theo đóng góp render (`lift_runner`) → cắt PLY (numpy)
    → collider phân rã lồi (`convex_runner`, CPU) ∥ vá nền (`inpaint_runner`, GPU) → nén SOG cho web

Mọi đầu ra publish thành artifact bất biến theo nội dung; module trả phần `SceneEnvironment` +
`SceneObject` để nơi gọi ghi revision SceneIR (revision đầu của job mới, hoặc revision kế tiếp khi
chạy lại cho job cũ). Thiếu runtime hoặc một provider lỗi → ném `ObjectifyError`; nơi gọi lùi về
đường hộp (ADR 0006) nên job không hỏng.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import numpy as np
import trimesh

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.floor_model import FloorModel
from src.models.contracts.manifests import JobManifest, StageId
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
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import SceneRevisionConflictError
from src.services.orchestration.scene.floor_evidence import publish_floor_fit_evidence, scene_floor_fit_summary
from src.services.process_control import ProcessCancelledError, ProcessTimeoutError, run_cancellable_process
from src.services.reconstruction import camera_views, metric_visual_master, package_splat
from src.services.scene.collision_ownership import bind_source_collision_ownership
from src.services.scene.decomposition import gaussian_split
from src.services.scene.editing.membership import (
    encode_gaussian_membership_labels,
    membership_labels_for_parts,
)
from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.geometric import GeometricConfig, box_from_points
from src.services.scene.sampro3d.consolidate import Sampro3dConfig, segment
from src.services.scene.sampro3d.pipeline import CameraFrame, Sam2Runtime, run_sam2

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
_MAX_OBJECTS = 60
_IDENTITY = (0.0, 0.0, 0.0, 1.0)

Publish = Callable[[ProductArtifactRef, bytes], ProductArtifactRef]


class ObjectifyError(RuntimeError):
    """Một bước tách scene theo vật không chạy được; nơi gọi lùi về đường hộp."""


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
            raise ObjectifyError(f"{name} quá thời gian cho phép") from error
    if returncode != 0 or not result_path.is_file():
        raise ObjectifyError(f"{name} lỗi (exit {returncode}); xem {name}.log")
    return json.loads(result_path.read_text(encoding="utf-8"))


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
) -> list[np.ndarray]:
    """Hạt giống từng vật (chỉ số vào `rows`) từ SAMPro3D; bỏ khối không phải vật (kệ dài, mảnh vụn)."""
    low, high = centers.min(axis=0)[:2] - _CROP_MARGIN_M, centers.max(axis=0)[:2] + _CROP_MARGIN_M
    work = gaussian_split.working_set(rows, low, high, _CROP_Z)
    points = gaussian_split.positions(rows)[work]
    try:
        instances = segment(
            run_sam2(
                points,
                frames,
                runtime,
                workspace / "sampro3d",
                floor_model=floor_model,
                cancel_event=cancel_event,
            ),
            points,
            floor_model,
            Sampro3dConfig(),
        )
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
    return kept[:_MAX_OBJECTS]


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
) -> ObjectifyResult:
    """Chạy toàn bộ chặng 4–7 cho một bundle hệ mét; publish artifact và trả phần SceneIR."""
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
    rows = gaussian_split.read_gaussian_ply(master.read_bytes())
    source_points = gaussian_split.positions(rows)
    floor_model = fit_canonical_floor_model(source_points, point_cloud_checksum(source_points))
    views = camera_views(bundle.camera_pose_refs[0], bundle.rgb_frame_refs, resolve)
    frames = [
        CameraFrame(view=view.model_dump(mode="json", exclude={"image"}), image_path=resolve(view.image))
        for view in views
    ]
    view_requests = [{**frame.view, "image_path": str(frame.image_path)} for frame in frames]
    _ensure_not_cancelled(cancel_event)
    seeds = _seeds(
        rows,
        frames,
        np.array([view.center for view in views]),
        runtime,
        workspace,
        floor_model,
        cancel_event,
    )
    if not seeds:
        raise ObjectifyError("không tìm thấy vật nào để tách")

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
        },
        workspace,
        "lift",
        timeout,
        cancel_event=cancel_event,
    )
    labels = np.load(workspace / "labels.npz")["labels"]
    labels = gaussian_split.assign_floor_gaussians_to_background(rows, labels, floor_model)
    background, parts = gaussian_split.split(rows, labels)
    if not parts:
        raise ObjectifyError("gán nhãn không cho ra vật nào đủ lớn")

    _ensure_not_cancelled(cancel_event)
    kept = np.isin(labels, [part.index for part in parts])
    (workspace / "objects_world.ply").write_bytes(gaussian_split.write_gaussian_ply(rows[kept]))
    (workspace / "background.ply").write_bytes(gaussian_split.write_gaussian_ply(background))
    for part in parts:
        (workspace / f"object_{part.index:03d}.ply").write_bytes(gaussian_split.write_gaussian_ply(part.rows))

    # Collider chỉ dùng CPU, vá nền chỉ dùng GPU, và hai bước không đọc kết quả của nhau → chạy song song.
    convex_request = {
        "objects": [
            {
                "id": str(part.index),
                "gaussians_ply": str(workspace / f"object_{part.index:03d}.ply"),
                "output_glb": str(workspace / f"object_{part.index:03d}.glb"),
            }
            for part in parts
        ]
    }
    inpaint_request = {
        "background_ply": str(workspace / "background.ply"),
        "objects_ply": str(workspace / "objects_world.ply"),
        "output_ply": str(workspace / "background_inpainted.ply"),
        "lama_checkpoint": str(settings.product_lama_checkpoint) if settings.product_lama_checkpoint else None,
        "views": view_requests,
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
    try:
        sog = package_splat(
            workspace / "background_inpainted.ply",
            workspace / "sog",
            settings.product_geometry_gpu_index,
            cancel_event=cancel_event,
        )
    except (ValueError, OSError) as error:
        raise ObjectifyError(f"nén SOG nền lỗi: {error}") from error

    job_id = job.job_id
    label_to_object_id = {str(part.index): f"candidate-{number:03d}" for number, part in enumerate(parts, start=1)}
    membership_labels = membership_labels_for_parts(labels, [part.index for part in parts])
    membership_payload = encode_gaussian_membership_labels(
        membership_labels,
        gaussian_count=len(rows),
        label_to_object_id=label_to_object_id,
    )
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
    membership = ObjectMembershipArtifact(
        source_visual_ref=source_visual_ref,
        source_geometry_ref=bundle.canonical_geometry_ref,
        extraction_revision=extraction_revision,
        coordinate_system=CoordinateSystem(),
        gaussian_count=len(rows),
        labels_ref=membership_labels_ref,
        label_to_object_id=label_to_object_id,
    )
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

    objects: list[SceneObject] = []
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
                        "parts": int(collider_info.get("parts", 1)),
                        "volume_m3": float(collider_info.get("volume_m3", 0.0)),
                    },
                    provenance={"generator": "coacd" if collider_type == ColliderType.CONVEX_DECOMPOSITION else "aabb"},
                ),
                tags=["objectify_v1"],
                provenance={
                    "method": METHOD,
                    "gaussians": int(len(part.rows)),
                    "seed_gaussians": int(len(seeds[part.index])),
                    "masks": int(lift["masks_per_object"][part.index]),
                    "note": "ứng viên, cần người xác nhận",
                },
            )
        )
    provenance = {
        "object_extraction": METHOD,
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
    floor_evidence_ref, floor_evidence = publish_floor_fit_evidence(job.job_id, source_visual_ref, floor_model, publish)
    provenance["floor_fit"] = scene_floor_fit_summary(floor_evidence_ref, floor_evidence)
    environment = SceneEnvironment(
        visual_ref=visual_ref,
        geometry_ref=bundle.canonical_geometry_ref,
        visual_master_ref=master_ref,
        membership=membership,
    )
    return ObjectifyResult(environment=environment, objects=objects, provenance=provenance)


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
) -> ObjectifyResult:
    """Thử `objectify` tối đa `product_objectify_attempts` lần, mỗi lần một workspace riêng (giữ log từng lần).

    Lỗi GPU thường thoáng qua (hết VRAM do tiến trình khác, driver) nên đáng thử lại; hết số lần thì ném
    `ObjectifyError` kèm lỗi cuối — nơi gọi **không** tự lùi về đường hộp mà để người dùng chọn.
    """
    attempts = settings.product_objectify_attempts
    last: Exception | None = None
    for number in range(1, attempts + 1):
        try:
            arguments = {"cancel_event": cancel_event} if cancel_event is not None else {}
            return objectify(
                registry,
                job,
                bundle,
                settings,
                workspace / f"attempt-{number}",
                publish,
                extraction_revision=extraction_revision,
                **arguments,
            )
        except ProcessCancelledError:
            raise
        except (ObjectifyError, ValueError, OSError) as error:
            logger.warning("Tách theo vật lỗi job=%s lần %d/%d: %s", job.job_id, number, attempts, error)
            last = error
    raise ObjectifyError(f"tách theo vật lỗi sau {attempts} lần: {last}") from last


def reobjectify(
    registry: ProjectRegistry,
    job_id: str,
    settings: Settings,
    workspace: Path,
    *,
    expected_revision: str | None = None,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
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
            "provenance": {**base_scene.provenance, **result.provenance, "note": "chạy lại tách theo vật"},
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
