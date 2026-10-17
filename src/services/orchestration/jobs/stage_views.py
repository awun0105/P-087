"""Bước nào của pipeline có gì để xem (ADR 0005) — danh sách do backend dựng từ JobManifest.

UI không tự suy đường dẫn artifact. Mỗi view chỉ trỏ tới artifact đã có trong allow-list
của job (stage artifacts, preview, bundle, ảnh frame); trình duyệt nạp một lớp mỗi lúc.
"""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobManifest, StageArtifact, StageId, StageStatus
from src.models.contracts.reconstruction import ReconstructionBundle
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction import CameraMarker, camera_markers, frame_images
from src.services.reconstruction.rgb.canonical.metric_math import compose_rotation
from src.services.reconstruction.rgb.canonical.metric_models import MetricConfirmation
from src.services.reconstruction.rgb.pose.camera_pose import Quaternion

ViewKind = Literal["frames", "cameras", "gaussian", "mesh"]

#: Ảnh frame trả về tối đa; trình duyệt nạp lười, không kéo cả trăm ảnh gốc một lúc.
MAX_FRAMES = 48


class StageView(BaseModel):
    """Một lớp xem được của một bước."""

    model_config = ConfigDict(extra="forbid")

    stage_id: StageId
    kind: ViewKind
    title: str
    note: str
    unit: Literal["meter", "arbitrary"]
    refs: list[ProductArtifactRef] = []
    cameras: list[CameraMarker] = []
    #: Rotation source→display Y-up, không scale/translation; chỉ preview đã có xác nhận khớp nguồn.
    display_rotation_xyzw: Quaternion | None = None
    #: Khoá của lớp LiDAR chồng lên scene (`GET /jobs/{id}/lidar-overlay`); None = scene không có LiDAR đã căn chỉnh.
    lidar_overlay: str | None = None


class StageViewList(BaseModel):
    """Các lớp xem được của job, theo thứ tự pipeline."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    views: list[StageView]


def _stage(job: JobManifest, stage_id: StageId, artifact_type: str) -> StageArtifact | None:
    return next(
        (
            stage
            for stage in reversed(job.stage_artifacts)
            if stage.stage_id == stage_id
            and stage.status == StageStatus.SUCCEEDED
            and stage.artifact_type == artifact_type
        ),
        None,
    )


def job_bundle(registry: ProjectRegistry, job: JobManifest) -> ReconstructionBundle | None:
    """ReconstructionBundle cuối của job (nếu bước hoàn tất đã chạy xong)."""
    stage = _stage(job, StageId.METRIC_CANONICALIZE, "ReconstructionBundle")
    if stage is None or stage.artifact_uri is None or stage.artifact_checksum is None:
        return None
    path = registry.runtime_resolver.require_uri(stage.artifact_uri, stage.artifact_checksum)
    return ReconstructionBundle.model_validate_json(path.read_bytes())


def job_frame_images(registry: ProjectRegistry, job: JobManifest) -> list[ProductArtifactRef]:
    """Ảnh frame đã trích (REC-02A) của job, qua public port REC."""
    stage = _stage(job, StageId.FRAME_EXTRACT, "NormalizedRGBFrameSet")
    if stage is None or stage.artifact_uri is None or stage.artifact_checksum is None or stage.data_class is None:
        return []
    reference = ProductArtifactRef(
        artifact_type="NormalizedRGBFrameSet",
        schema_version="1.0",
        artifact_uri=stage.artifact_uri,
        artifact_checksum=stage.artifact_checksum,
        data_class=stage.data_class,
        producer_stage=StageId.FRAME_EXTRACT,
        job_id=job.job_id,
    )
    return frame_images(reference, registry.runtime_resolver.require)


def stage_views(registry: ProjectRegistry, job_id: str) -> StageViewList:
    """Dựng danh sách lớp xem được; bước chưa có kết quả thì không có view."""
    job = registry.get_job(job_id)
    resolve = registry.runtime_resolver.require
    views: list[StageView] = []
    frames = job_frame_images(registry, job)
    if frames:
        views.append(
            StageView(
                stage_id=StageId.FRAME_EXTRACT,
                kind="frames",
                title="Frame đã chọn",
                note=f"{len(frames)} ảnh sau lọc chất lượng; hiện tối đa {MAX_FRAMES}.",
                unit="arbitrary",
                refs=frames[:MAX_FRAMES],
            )
        )
    try:
        preview = registry.get_preview(job_id)
    except (ArtifactStoreError, ValueError):
        preview = None
    if preview is not None:
        cameras = camera_markers(preview.camera_pose_ref, resolve)
        display_rotation = None
        confirmation = _stage(job, StageId.METRIC_CANONICALIZE, "RGBMetricConfirmation")
        if confirmation is not None and confirmation.artifact_uri and confirmation.artifact_checksum:
            path = registry.runtime_resolver.require_uri(confirmation.artifact_uri, confirmation.artifact_checksum)
            record = MetricConfirmation.model_validate_json(path.read_bytes())
            if (
                record.preview.request.source_visual == preview.source_visual_ref
                and record.preview.source_camera_poses == preview.camera_pose_ref
            ):
                # Display Y-up ← canonical Z-up ← raw SfM. Giữ nguyên đơn vị/bytes preview.
                display_rotation = compose_rotation(
                    (-math.sqrt(0.5), 0, 0, math.sqrt(0.5)), record.preview.transform.rotation_xyzw
                )
        views.append(
            StageView(
                stage_id=StageId.CAMERA_POSE,
                kind="cameras",
                title="Vị trí camera (COLMAP)",
                note="Quỹ đạo camera nhìn từ trên xuống; đơn vị SfM tùy ý, chưa quy đổi mét.",
                unit="arbitrary",
                cameras=cameras,
            )
        )
        views.append(
            StageView(
                stage_id=StageId.VISUAL_RECON,
                kind="gaussian",
                title="3DGS (Brush)",
                note="Preview dựng từ ảnh, đơn vị tùy ý.",
                unit="arbitrary",
                refs=[preview.delivery_ref],
                cameras=cameras,
                display_rotation_xyzw=display_rotation,
            )
        )
    bundle = job_bundle(registry, job)
    if bundle is not None:
        overlay = None
        if bundle.alignment_record is not None and bundle.lidar_geometry_ref is not None:
            overlay = bundle.alignment_record.artifact_checksum.removeprefix("sha256:")
        if bundle.visual_artifact_ref is not None:
            views.append(
                StageView(
                    stage_id=StageId.METRIC_CANONICALIZE,
                    kind="gaussian",
                    title="3DGS hệ mét",
                    note="Đã quy đổi mét: sàn z = 0, trục Z hướng lên.",
                    unit="meter",
                    refs=[bundle.visual_artifact_ref],
                    cameras=camera_markers(bundle.camera_pose_refs[0], resolve) if bundle.camera_pose_refs else [],
                    lidar_overlay=overlay,
                )
            )
        views.append(
            StageView(
                stage_id=StageId.RGB_GEOMETRY,
                kind="mesh",
                title="Collision mesh (REC-05)",
                note="Mesh va chạm thô cho Isaac; sàn là mặt phẳng z = 0 do Isaac tạo, không nằm trong mesh.",
                unit="meter",
                refs=[bundle.canonical_geometry_ref],
            )
        )
    return StageViewList(job_id=job_id, views=views)


def view_references(registry: ProjectRegistry, job: JobManifest) -> list[ProductArtifactRef]:
    """Ref cần thêm vào allow-list tải artifact để hiển thị các view trên."""
    references = list(job_frame_images(registry, job))
    bundle = job_bundle(registry, job)
    if bundle is not None:
        references.extend(bundle.camera_pose_refs)
        references.extend(
            ref
            for ref in (
                bundle.visual_artifact_ref,
                bundle.rgb_geometry_ref,
                bundle.lidar_geometry_ref,
                bundle.canonical_geometry_ref,
            )
            if ref
        )
        if bundle.alignment_record is not None:
            alignment = bundle.alignment_record
            references.append(
                ProductArtifactRef(
                    artifact_type=alignment.artifact_type,
                    schema_version=alignment.schema_version,
                    artifact_uri=alignment.artifact_uri,
                    artifact_checksum=alignment.artifact_checksum,
                    data_class="derived",
                    producer_stage=alignment.producer_stage,
                    job_id=alignment.job_id,
                    source_provenance=alignment.provenance,
                )
            )
    return references
