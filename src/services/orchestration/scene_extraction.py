"""Bước tách vật thể sau REC bundle: SceneIR ứng viên cho người dùng xác nhận.

Đường chính là tách theo vật (pipeline v2, ADR 0007), thử tối đa `product_objectify_attempts` lần. Hết số
lần mà vẫn lỗi thì **không tự lùi về hộp**: publish SceneIR chỉ có môi trường, đánh dấu chờ người dùng chọn
"chạy lại" hoặc "dùng hộp ứng viên" (`scene_objectify_queue`). Máy không cấu hình runtime tách theo vật thì
đi thẳng đường hộp (ADR 0006: SAMPro3D + SAM2, rồi tách hình học). Bước này không làm hỏng job: tái dựng
đã xong, vật thể còn thêm tay được.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from src.config import Settings
from src.models.contracts.manifests import JobManifest, StageArtifact, StageId, StageStatus
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import SceneObject
from src.services.orchestration.artifacts import FilesystemArtifactStore
from src.services.orchestration.jobs.progress import metric_confirmation_stage
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene_objectify import AWAITING_CHOICE, ObjectifyError, Publish, objectify_with_retry
from src.services.orchestration.scene_objectify import METHOD as OBJECTIFY_METHOD
from src.services.reconstruction import camera_views, confirmation_summary, metric_gaussian_points
from src.services.scene.builder import scene_from_bundle
from src.services.scene.geometric import GeometricConfig, candidate_objects, collision_vertices, objects_from_candidates
from src.services.scene.publisher import with_scene_checksum
from src.services.scene.sampro3d.pipeline import METHOD as SAMPRO3D_METHOD
from src.services.scene.sampro3d.pipeline import CameraFrame, Sam2Runtime, extract

logger = logging.getLogger(__name__)

#: Vùng làm việc quanh quỹ đạo camera, cùng quy tắc với REC-05 (geometry_v1).
_CROP_MARGIN_M = 6.0
_CROP_Z = (-0.5, 4.0)


def _points_and_frames(
    registry: ProjectRegistry, job: JobManifest, bundle: ReconstructionBundle
) -> tuple[np.ndarray, list[CameraFrame]]:
    resolve = registry.runtime_resolver.require
    stage = metric_confirmation_stage(job)
    if stage is None or stage.artifact_uri is None or stage.artifact_checksum is None:
        raise ValueError("job chưa có xác nhận tỉ lệ mét")
    confirmation = confirmation_summary(stage.artifact_uri, stage.artifact_checksum, job.job_id, resolve).reference
    points = metric_gaussian_points(confirmation, resolve)
    views = camera_views(bundle.camera_pose_refs[0], bundle.rgb_frame_refs, resolve)
    centers = np.array([view.center for view in views])
    low, high = centers.min(axis=0)[:2] - _CROP_MARGIN_M, centers.max(axis=0)[:2] + _CROP_MARGIN_M
    inside = (
        (points[:, 0] > low[0])
        & (points[:, 0] < high[0])
        & (points[:, 1] > low[1])
        & (points[:, 1] < high[1])
        & (points[:, 2] > _CROP_Z[0])
        & (points[:, 2] < _CROP_Z[1])
    )
    frames = [
        CameraFrame(view=view.model_dump(mode="json", exclude={"image"}), image_path=resolve(view.image))
        for view in views
    ]
    return points[inside], frames


def _sam2_runtime(settings: Settings) -> Sam2Runtime | None:
    if not (settings.product_scene_runtime_python and settings.product_sam2_checkpoint):
        return None
    return Sam2Runtime(
        settings.product_scene_runtime_python,
        settings.product_sam2_checkpoint,
        timeout_seconds=settings.product_scene_timeout_seconds,
    )


def _idempotent_publish(registry: ProjectRegistry) -> Publish:
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(reference, payload):  # noqa: ANN001, ANN202 - writer idempotent theo nội dung
        if registry.runtime_resolver.resolve(reference.artifact_uri).is_file():
            return reference
        return store.publish(reference, payload)

    return publish


def box_candidates(
    registry: ProjectRegistry,
    job: JobManifest,
    bundle: ReconstructionBundle,
    settings: Settings,
    workspace: Path,
    publish: Publish,
) -> tuple[list[SceneObject], str, str]:
    """Đường hộp (ADR 0006): SAMPro3D + SAM2, lỗi/thiếu runtime thì tách hình học. Trả (vật, phương pháp, ghi chú)."""
    objects: list[SceneObject] = []
    method, note = "none", ""
    runtime = _sam2_runtime(settings)
    if runtime is not None and runtime.available():
        try:
            points, frames = _points_and_frames(registry, job, bundle)
            candidates = extract(points, frames, runtime, workspace / "sampro3d")
            objects = objects_from_candidates(job.job_id, candidates, publish, {"method": SAMPRO3D_METHOD})
            method = SAMPRO3D_METHOD
        except (ValueError, OSError) as error:
            logger.warning(
                "SAMPro3D thất bại job=%s cause=%s; dùng fallback hình học", job.job_id, type(error).__name__
            )
            note = f"SAMPro3D lỗi ({type(error).__name__}); dùng tách hình học"
    else:
        note = "chưa cấu hình runtime SAM2; dùng tách hình học"
    if method == "none":
        try:
            mesh = registry.runtime_resolver.require(bundle.canonical_geometry_ref).read_bytes()
            objects = candidate_objects(job.job_id, collision_vertices(mesh), publish, GeometricConfig())
            method = "geometric_voxel_components_v1"
        except (ValueError, OSError) as error:
            logger.warning("Tách hình học thất bại job=%s cause=%s", job.job_id, type(error).__name__)
            note = f"{note}; tách hình học lỗi ({type(error).__name__}), scene chỉ có môi trường"
    return objects, method, note


def extract_scene(
    registry: ProjectRegistry, job: JobManifest, bundle: ReconstructionBundle, settings: Settings, workspace: Path
) -> StageArtifact:
    """Tạo + publish SceneIR rev-001; trả StageArtifact OBJECT_EXTRACT (luôn SUCCEEDED, ghi phương pháp)."""
    started = datetime.now(UTC)
    publish = _idempotent_publish(registry)
    runtime = _sam2_runtime(settings)
    objects: list[SceneObject] = []
    environment, extra = None, {}
    if settings.product_objectify and runtime is not None and runtime.available():
        try:
            result = objectify_with_retry(registry, job, bundle, settings, workspace / "objectify", publish)
            objects, environment, extra = result.objects, result.environment, result.provenance
            method, note = OBJECTIFY_METHOD, ""
        except ObjectifyError as error:
            # Không tự lùi về hộp (owner quyết 2026-10-01): scene chỉ có môi trường, chờ người dùng chọn.
            method, note = AWAITING_CHOICE, f"{error}; chọn chạy lại hoặc dùng hộp ứng viên"
    else:
        objects, method, note = box_candidates(registry, job, bundle, settings, workspace, publish)
    scene = scene_from_bundle(bundle, objects, {"object_extraction": method, "note": note, **extra}, environment)
    revision = registry.scene.publish_initial(job.job_id, scene)
    reference = revision.scene_reference
    return StageArtifact(
        stage_id=StageId.OBJECT_EXTRACT,
        status=StageStatus.SUCCEEDED,
        started_at=started,
        completed_at=datetime.now(UTC),
        artifact_type=reference.artifact_type,
        artifact_uri=reference.artifact_uri,
        artifact_checksum=reference.artifact_checksum,
        data_class=reference.data_class,
    )


def use_boxes(registry: ProjectRegistry, job_id: str, settings: Settings, workspace: Path) -> str:
    """Người dùng chọn dùng hộp ứng viên: ghi **revision kế tiếp** với vật từ đường hộp, môi trường gốc của bundle.

    Vật của revision trước không mang sang (tập hộp mới là ứng viên mới); hoàn tác quay lại được.
    """
    from src.services.orchestration.stage_views import job_bundle

    job = registry.get_job(job_id)
    bundle = job_bundle(registry, job)
    if bundle is None:
        raise ValueError("job chưa có ReconstructionBundle hệ mét")
    objects, method, note = box_candidates(registry, job, bundle, settings, workspace, _idempotent_publish(registry))
    current = registry.scene.current(job_id).scene
    fresh = scene_from_bundle(bundle, objects, {})
    updated = current.model_copy(
        update={
            "environment": fresh.environment,
            "objects": objects,
            "provenance": {
                "bundle_checksum": current.provenance.get("bundle_checksum"),
                "object_extraction": method,
                "note": f"người dùng chọn dùng hộp ứng viên. {note}".strip(),
            },
        }
    )
    published = registry.scene.publish_next(job_id, current.scene_revision, with_scene_checksum(updated), "use_boxes")
    registry.runtime_resolver.sync_up(job_id)
    return published.revision.scene.scene_revision
