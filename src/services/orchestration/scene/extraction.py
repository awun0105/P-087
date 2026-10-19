"""Bước tách vật thể sau REC bundle: SceneIR ứng viên cho người dùng xác nhận.

Đường chính là tách theo vật (pipeline v2, ADR 0007), thử tối đa `product_objectify_attempts` lần. Hết số
lần mà vẫn lỗi thì **không tự lùi về hộp**: publish SceneIR chỉ có môi trường, đánh dấu chờ người dùng chọn
"chạy lại" hoặc "dùng hộp ứng viên" (`scene/objectify_queue.py`). Máy không cấu hình runtime tách theo vật thì
đi thẳng đường hộp (ADR 0006: SAMPro3D + SAM2, rồi tách hình học). Bước này không làm hỏng job: tái dựng
đã xong, vật thể còn thêm tay được.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import numpy as np

from src.config import Settings
from src.models.contracts.artifacts import JsonObject, ProductArtifactRef
from src.models.contracts.floor_model import FloorModel
from src.models.contracts.manifests import JobManifest, StageArtifact, StageId, StageStatus
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import SceneObject
from src.services.orchestration.artifacts import ArtifactStoreError, FilesystemArtifactStore
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.jobs.progress import metric_confirmation_stage
from src.services.orchestration.processing.config import load_job_config
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import SceneError, SceneRevisionConflictError
from src.services.orchestration.scene.floor_evidence import publish_floor_fit_evidence, scene_floor_fit_summary
from src.services.orchestration.scene.objectify import (
    AWAITING_CHOICE,
    ObjectifyConfig,
    ObjectifyError,
    Publish,
    job_requires_strict_geometry,
    objectify_with_retry,
)
from src.services.orchestration.scene.objectify import METHOD as OBJECTIFY_METHOD
from src.services.process_control import ProcessCancelledError
from src.services.reconstruction import camera_views, confirmation_summary, metric_gaussian_points
from src.services.scene.builder import scene_from_bundle
from src.services.scene.collision_ownership import bind_source_collision_ownership
from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.geometric import GeometricConfig, candidate_objects, collision_vertices, objects_from_candidates
from src.services.scene.geometry_state import object_geometry_state
from src.services.scene.publisher import with_scene_checksum
from src.services.scene.sampro3d.pipeline import METHOD as SAMPRO3D_METHOD
from src.services.scene.sampro3d.pipeline import CameraFrame, Sam2Runtime, extract

logger = logging.getLogger(__name__)

#: Vùng làm việc quanh quỹ đạo camera, cùng quy tắc với REC-05 (geometry_v1).
_CROP_MARGIN_M = 6.0
_CROP_Z = (-0.5, 4.0)


def _points_and_frames(
    registry: ProjectRegistry, job: JobManifest, bundle: ReconstructionBundle
) -> tuple[np.ndarray, list[CameraFrame], FloorModel, ProductArtifactRef]:
    resolve = registry.runtime_resolver.require
    stage = metric_confirmation_stage(job)
    if stage is None or stage.artifact_uri is None or stage.artifact_checksum is None:
        raise ValueError("job chưa có xác nhận tỉ lệ mét")
    confirmation = confirmation_summary(stage.artifact_uri, stage.artifact_checksum, job.job_id, resolve).reference
    points = metric_gaussian_points(confirmation, resolve)
    floor_model = fit_canonical_floor_model(points, point_cloud_checksum(points))
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
    return points[inside], frames, floor_model, confirmation


def _sam2_runtime(settings: Settings) -> Sam2Runtime | None:
    if not (settings.product_scene_runtime_python and settings.product_sam2_checkpoint):
        return None
    return Sam2Runtime(
        settings.product_scene_runtime_python,
        settings.product_sam2_checkpoint,
        timeout_seconds=settings.product_scene_timeout_seconds,
    )


def box_candidates_require_gpu(settings: Settings) -> bool:
    """Whether the selected box-candidate path will actually enter SAMPro3D/SAM2."""
    runtime = _sam2_runtime(settings)
    return runtime is not None and runtime.available()


def _idempotent_publish(registry: ProjectRegistry) -> Publish:
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(reference, payload):  # noqa: ANN001, ANN202 - writer idempotent theo nội dung
        if registry.runtime_resolver.locate(reference.artifact_uri) is not None:
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
    *,
    cancel_event: Event | None = None,
) -> tuple[list[SceneObject], str, str, JsonObject | None]:
    """Đường hộp (ADR 0006): SAMPro3D + SAM2, lỗi/thiếu runtime thì tách hình học."""
    objects: list[SceneObject] = []
    method, note = "none", ""
    floor_fit: JsonObject | None = None
    runtime = _sam2_runtime(settings)
    if runtime is not None and runtime.available():
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ProcessCancelledError("Objectify operation was cancelled")
            points, frames, floor_model, source_ref = _points_and_frames(registry, job, bundle)
            evidence_ref, evidence = publish_floor_fit_evidence(job.job_id, source_ref, floor_model, publish)
            floor_fit = scene_floor_fit_summary(evidence_ref, evidence)
            candidates = extract(
                points,
                frames,
                runtime,
                workspace / "sampro3d",
                floor_model=floor_model,
                cancel_event=cancel_event,
            )
            objects = objects_from_candidates(
                job.job_id,
                candidates,
                publish,
                {"method": SAMPRO3D_METHOD, "floor_profile_checksum": floor_model.profile_checksum},
            )
            method = SAMPRO3D_METHOD
            if floor_model.status != "supported":
                note = f"SAMPro3D dùng trạng thái sàn {floor_model.status} ({floor_model.fallback_reason})"
        except ProcessCancelledError:
            raise
        except (ValueError, OSError) as error:
            logger.warning(
                "SAMPro3D thất bại job=%s cause=%s; dùng fallback hình học", job.job_id, type(error).__name__
            )
            note = f"SAMPro3D lỗi: {error}; dùng tách hình học"
    else:
        note = "chưa cấu hình runtime SAM2; dùng tách hình học"
    if method == "none":
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ProcessCancelledError("Objectify operation was cancelled")
            mesh = registry.runtime_resolver.require(bundle.canonical_geometry_ref).read_bytes()
            vertices = collision_vertices(mesh)
            floor_model = fit_canonical_floor_model(vertices, point_cloud_checksum(vertices))
            objects = candidate_objects(job.job_id, vertices, publish, floor_model, GeometricConfig())
            method = "geometric_voxel_components_v1"
            evidence_ref, evidence = publish_floor_fit_evidence(
                job.job_id, bundle.canonical_geometry_ref, floor_model, publish
            )
            floor_fit = scene_floor_fit_summary(evidence_ref, evidence)
            if floor_model.status != "supported":
                note = f"{note}; floor fit {floor_model.status} ({floor_model.fallback_reason})"
        except (ValueError, OSError) as error:
            logger.warning("Tách hình học thất bại job=%s cause=%s", job.job_id, type(error).__name__)
            note = f"{note}; tách hình học lỗi ({type(error).__name__}), scene chỉ có môi trường"
    return objects, method, note, floor_fit


def extract_scene(
    registry: ProjectRegistry, job: JobManifest, bundle: ReconstructionBundle, settings: Settings, workspace: Path
) -> StageArtifact:
    """Tạo + publish SceneIR rev-001; trả StageArtifact OBJECT_EXTRACT (luôn SUCCEEDED, ghi phương pháp)."""
    started = datetime.now(UTC)
    publish = _idempotent_publish(registry)
    runtime = _sam2_runtime(settings)
    objects: list[SceneObject] = []
    environment, extra = None, {}
    strict_geometry_required = job_requires_strict_geometry(registry, job)
    auto_geometry = False
    if strict_geometry_required and not (settings.product_objectify and runtime is not None and runtime.available()):
        raise ObjectifyError(
            "Job hình học nghiêm ngặt (shell/ObjectGS) cần runtime SAM2/objectify; không được lùi về legacy",
            retryable=False,
        )
    if settings.product_objectify and runtime is not None and runtime.available():
        processing = load_job_config(job.job_id, job.config_checksum, registry.runtime_resolver)
        auto_geometry = bool(
            processing is not None
            and processing.scene.get("geometry_review") == "auto"
            and processing.scene.get("geometry_method") in {"shell", "objectgs"}
        )
        arguments = {}
        if auto_geometry:
            # Auto still extracts a Draft first; the sealed choice and all other controls remain intact.
            groups: dict[str, dict] = {"scene": {}, "coacd": {}, "inpaint": {}}
            for key, value in processing.scene.items():
                group, name = key.split("_", 1) if key.startswith(("coacd_", "inpaint_")) else ("scene", key)
                groups[group][name] = value
            groups["scene"]["geometry_review"] = "required"
            arguments["scene_config"] = ObjectifyConfig.model_validate(groups).model_dump(exclude_unset=True)
        try:
            result = objectify_with_retry(
                registry, job, bundle, settings, workspace / "objectify", publish, **arguments
            )
            objects, environment, extra = result.objects, result.environment, result.provenance
            if auto_geometry:
                extra = {**extra, "geometry_review": "auto"}
            method, note = OBJECTIFY_METHOD, ""
        except ObjectifyError as error:
            if strict_geometry_required:
                raise
            # Không tự lùi về hộp (owner quyết 2026-10-01): scene chỉ có môi trường, chờ người dùng chọn.
            method, note = AWAITING_CHOICE, f"{error}; chọn chạy lại hoặc dùng hộp ứng viên"
            extra["objectify_retryable"] = error.retryable
            if error.floor_fit is not None:
                extra["floor_fit"] = error.floor_fit
    else:
        objects, method, note, floor_fit = box_candidates(registry, job, bundle, settings, workspace, publish)
        if floor_fit is not None:
            extra["floor_fit"] = floor_fit
    source_geometry_ref = environment.geometry_ref if environment is not None else bundle.canonical_geometry_ref
    objects = bind_source_collision_ownership(objects, source_geometry_ref, "rev-001")
    scene = scene_from_bundle(bundle, objects, {"object_extraction": method, "note": note, **extra}, environment)
    revision = registry.scene.publish_initial(job.job_id, scene)
    if auto_geometry and object_geometry_state(revision.scene) == "awaiting_review":
        from src.services.orchestration.scene import objectify_queue

        try:
            queued = objectify_queue.state(registry, settings, job.job_id)
            if not (
                queued.mode == "geometry"
                and queued.base_revision == revision.scene.scene_revision
                and queued.status in {"queued", "running"}
            ):
                objectify_queue.request(
                    registry,
                    settings,
                    job.job_id,
                    revision.scene.scene_revision,
                    "geometry",
                    actor_id="system",
                    origin="system",
                )
        except (objectify_queue.ObjectifyRequestError, SceneError, ArtifactStoreError) as error:
            logger.warning("Could not queue automatic geometry build for job %s: %s", job.job_id, error)
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


def use_boxes(
    registry: ProjectRegistry,
    job_id: str,
    settings: Settings,
    workspace: Path,
    *,
    expected_revision: str | None = None,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
) -> str:
    """Người dùng chọn dùng hộp ứng viên: ghi **revision kế tiếp** với vật từ đường hộp, môi trường gốc của bundle.

    Vật của revision trước không mang sang (tập hộp mới là ứng viên mới); hoàn tác quay lại được.
    """
    from src.services.orchestration.jobs.stage_views import job_bundle

    base_scene = registry.scene.current(job_id).scene
    if expected_revision is None:
        expected_revision = base_scene.scene_revision
    if base_scene.scene_revision != expected_revision:
        raise SceneRevisionConflictError(
            f"scene đã đổi: yêu cầu đang giữ {expected_revision}, revision hiện tại là {base_scene.scene_revision}"
        )
    if base_scene.environment.collision_selection_ref is not None:
        raise ValueError(
            "Không thể thay tập object khi collision source đang được chọn; khôi phục revision trước khi chọn nguồn mới"
        )
    job = registry.get_job(job_id)
    bundle = job_bundle(registry, job)
    if bundle is None:
        raise ValueError("job chưa có ReconstructionBundle hệ mét")
    objects, method, note, floor_fit = box_candidates(
        registry,
        job,
        bundle,
        settings,
        workspace,
        _idempotent_publish(registry),
        cancel_event=cancel_event,
    )
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCancelledError("Objectify operation was cancelled")
    if floor_fit is not None and floor_fit.get("status") == "uncertain":
        raise ObjectifyError(
            f"Mặt sàn chưa đủ tin cậy ({floor_fit.get('fallback_reason')}); chưa thể dựng hộp ứng viên. "
            "Cần kiểm tra dữ liệu, tỉ lệ và mốc sàn.",
            retryable=False,
            floor_fit=floor_fit,
        )
    fresh = scene_from_bundle(bundle, objects, {})
    objects = bind_source_collision_ownership(objects, fresh.environment.geometry_ref, expected_revision)
    updated = base_scene.model_copy(
        update={
            "environment": fresh.environment,
            "objects": objects,
            "provenance": {
                "bundle_checksum": base_scene.provenance.get("bundle_checksum"),
                "object_extraction": method,
                "note": f"người dùng chọn dùng hộp ứng viên. {note}".strip(),
                "floor_fit": floor_fit,
            },
        }
    )
    published = registry.scene.publish_next(
        job_id,
        expected_revision,
        with_scene_checksum(updated),
        "use_boxes",
        commit_guard=commit_guard,
    )
    registry.runtime_resolver.sync_up(job_id)
    return published.revision.scene.scene_revision
