"""Bước tách vật thể sau REC bundle (ADR 0006): SceneIR ứng viên cho người dùng xác nhận.

Đường chính SAMPro3D + SAM2 (runtime riêng); không có runtime hoặc lỗi thì lùi về tách hình
học từ collision mesh; lỗi cả hai vẫn publish SceneIR chỉ có môi trường. Bước này không làm
hỏng job: tái dựng đã xong, vật thể còn thêm tay được.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from src.config import Settings
from src.models.contracts.manifests import JobManifest, StageArtifact, StageId, StageStatus
from src.models.contracts.reconstruction import ReconstructionBundle
from src.services.orchestration.artifacts import FilesystemArtifactStore
from src.services.orchestration.jobs.progress import metric_confirmation_stage
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene_objectify import METHOD as OBJECTIFY_METHOD
from src.services.orchestration.scene_objectify import ObjectifyError, objectify
from src.services.reconstruction import camera_views, confirmation_summary, metric_gaussian_points
from src.services.scene.builder import scene_from_bundle
from src.services.scene.geometric import GeometricConfig, candidate_objects, collision_vertices, objects_from_candidates
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


def extract_scene(
    registry: ProjectRegistry, job: JobManifest, bundle: ReconstructionBundle, settings: Settings, workspace: Path
) -> StageArtifact:
    """Tạo + publish SceneIR rev-001; trả StageArtifact OBJECT_EXTRACT (luôn SUCCEEDED, ghi phương pháp)."""
    started = datetime.now(UTC)
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(reference, payload):  # noqa: ANN001, ANN202 - writer idempotent theo nội dung
        if registry.runtime_resolver.resolve(reference.artifact_uri).is_file():
            return reference
        return store.publish(reference, payload)

    runtime = (
        Sam2Runtime(
            settings.product_scene_runtime_python,
            settings.product_sam2_checkpoint,
            timeout_seconds=settings.product_scene_timeout_seconds,
        )
        if settings.product_scene_runtime_python and settings.product_sam2_checkpoint
        else None
    )
    objects, method, note = [], "none", ""
    environment, extra = None, {}
    if settings.product_objectify and runtime is not None and runtime.available():
        # Pipeline v2 (ADR 0007): nền đã vá + Gaussian/collider từng vật. Lỗi → lùi về đường hộp.
        try:
            result = objectify(registry, job, bundle, settings, workspace / "objectify", publish)
            objects, environment, extra, method = (
                result.objects,
                result.environment,
                result.provenance,
                OBJECTIFY_METHOD,
            )
        except (ObjectifyError, ValueError, OSError) as error:
            logger.warning("Tách theo vật thất bại job=%s cause=%s; dùng đường hộp", job.job_id, error)
            note = f"tách theo vật lỗi ({type(error).__name__}); dùng hộp ứng viên"
    if method == "none" and runtime is not None and runtime.available():
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
    elif method == "none":
        note = "chưa cấu hình runtime SAM2; dùng tách hình học"
    if method == "none":
        try:
            mesh = registry.runtime_resolver.require(bundle.canonical_geometry_ref).read_bytes()
            objects = candidate_objects(job.job_id, collision_vertices(mesh), publish, GeometricConfig())
            method = "geometric_voxel_components_v1"
        except (ValueError, OSError) as error:
            logger.warning("Tách hình học thất bại job=%s cause=%s", job.job_id, type(error).__name__)
            note = f"{note}; tách hình học lỗi ({type(error).__name__}), scene chỉ có môi trường"
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
