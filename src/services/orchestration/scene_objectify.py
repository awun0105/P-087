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
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import JobManifest, StageId
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import (
    ColliderSpec,
    ColliderType,
    SceneEnvironment,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
)
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction import camera_views, metric_visual_master, package_splat
from src.services.scene.decomposition import gaussian_split
from src.services.scene.geometric import GeometricConfig, box_from_points
from src.services.scene.sampro3d.consolidate import Sampro3dConfig, segment
from src.services.scene.sampro3d.pipeline import CameraFrame, Sam2Runtime, run_sam2

logger = logging.getLogger(__name__)

METHOD = "objectify_v1(sampro3d_sam2+render_lift+coacd+seed_inpaint)"
_REPO = Path(__file__).resolve().parents[3]
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


def _run(python: Path, script: Path, request: dict, workspace: Path, name: str, timeout: float) -> dict:
    """Chạy một provider trong runtime; lỗi/timeout → ObjectifyError có ngữ cảnh, log nằm trong workspace."""
    workspace.mkdir(parents=True, exist_ok=True)
    request_path, result_path = workspace / f"{name}.request.json", workspace / f"{name}.result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    with (workspace / f"{name}.log").open("w") as log:
        try:
            completed = subprocess.run(
                [str(python), str(script), "--request", str(request_path), "--result", str(result_path)],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ObjectifyError(f"{name} quá thời gian cho phép") from error
    if completed.returncode != 0 or not result_path.is_file():
        raise ObjectifyError(f"{name} lỗi (exit {completed.returncode}); xem {name}.log")
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
    rows: np.ndarray, frames: list[CameraFrame], centers: np.ndarray, runtime: Sam2Runtime, workspace: Path
) -> list[np.ndarray]:
    """Hạt giống từng vật (chỉ số vào `rows`) từ SAMPro3D; bỏ khối không phải vật (kệ dài, mảnh vụn)."""
    low, high = centers.min(axis=0)[:2] - _CROP_MARGIN_M, centers.max(axis=0)[:2] + _CROP_MARGIN_M
    work = gaussian_split.working_set(rows, low, high, _CROP_Z)
    points = gaussian_split.positions(rows)[work]
    try:
        instances = segment(run_sam2(points, frames, runtime, workspace / "sampro3d"), points, Sampro3dConfig())
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

    master = resolve(metric_visual_master(bundle, resolve))
    rows = gaussian_split.read_gaussian_ply(master.read_bytes())
    views = camera_views(bundle.camera_pose_refs[0], bundle.rgb_frame_refs, resolve)
    frames = [
        CameraFrame(view=view.model_dump(mode="json", exclude={"image"}), image_path=resolve(view.image))
        for view in views
    ]
    view_requests = [{**frame.view, "image_path": str(frame.image_path)} for frame in frames]
    seeds = _seeds(rows, frames, np.array([view.center for view in views]), runtime, workspace)
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
    )
    labels = np.load(workspace / "labels.npz")["labels"]
    background, parts = gaussian_split.split(rows, labels)
    if not parts:
        raise ObjectifyError("gán nhãn không cho ra vật nào đủ lớn")

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
        convex_job = pool.submit(_run, python, CONVEX_RUNNER, convex_request, workspace, "convex", timeout)
        inpaint_job = pool.submit(_run, python, INPAINT_RUNNER, inpaint_request, workspace, "inpaint", timeout)
        convex, inpaint = convex_job.result(), inpaint_job.result()
    colliders = {int(item["id"]): item for item in convex["objects"]}
    try:
        sog = package_splat(
            workspace / "background_inpainted.ply", workspace / "sog", settings.product_geometry_gpu_index
        )
    except (ValueError, OSError) as error:
        raise ObjectifyError(f"nén SOG nền lỗi: {error}") from error

    job_id = job.job_id
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
    }
    environment = SceneEnvironment(
        visual_ref=visual_ref, geometry_ref=bundle.canonical_geometry_ref, visual_master_ref=master_ref
    )
    return ObjectifyResult(environment=environment, objects=objects, provenance=provenance)


def reobjectify(registry: ProjectRegistry, job_id: str, settings: Settings, workspace: Path) -> str:
    """Chạy lại tách theo vật cho job đã có SceneIR; ghi **revision kế tiếp** (không sửa revision cũ).

    Dùng để nâng scene dựng bằng đường hộp (ADR 0006) lên scene theo vật mà không dựng lại từ video.
    Vật và trạng thái xác nhận của revision trước không mang sang: tập vật mới là ứng viên mới.
    """
    from src.services.orchestration.artifacts import FilesystemArtifactStore
    from src.services.orchestration.stage_views import job_bundle
    from src.services.scene.publisher import with_scene_checksum

    job = registry.get_job(job_id)
    bundle = job_bundle(registry, job)
    if bundle is None:
        raise ObjectifyError("job chưa có ReconstructionBundle hệ mét")
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        if registry.runtime_resolver.resolve(reference.artifact_uri).is_file():
            return reference
        return store.publish(reference, payload)

    result = objectify(registry, job, bundle, settings, workspace, publish)
    current = registry.scene.current(job_id).scene
    updated = current.model_copy(
        update={
            "environment": result.environment,
            "objects": result.objects,
            "provenance": {**current.provenance, **result.provenance, "note": "chạy lại tách theo vật"},
        }
    )
    published = registry.scene.publish_next(job_id, current.scene_revision, with_scene_checksum(updated), "objectify")
    registry.runtime_resolver.sync_up(job_id)
    return published.revision.scene.scene_revision
