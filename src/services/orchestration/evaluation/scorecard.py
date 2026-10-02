"""Dựng bảng đánh giá của một job từ artifact đã publish.

Mỗi nhóm ứng với một bước của pipeline Studio. Số liệu lấy qua public port của EX-REC (`reconstruction.quality`),
`ReconstructionBundle`, SceneIR và journal của job — không tính lại kết quả pipeline và không dùng dữ liệu
evaluation-only. Kết luận đạt/không đạt chỉ gán khi ngưỡng đã có trong repo; chỉ số khác chỉ nêu số và ý nghĩa.
"""

import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobManifest, StageId, StageStatus
from src.models.contracts.scene import SceneIR, SceneObjectOrigin, SceneObjectState
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.evaluation.models import JobEvaluation, Metric, StageEvaluation, Verdict
from src.services.orchestration.jobs.progress import job_progress
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import SceneError
from src.services.reconstruction import (
    GeometryQuality,
    VisualQuality,
    geometry_quality,
    input_quality,
    metric_quality,
    pose_quality,
    visual_quality,
)

logger = logging.getLogger(__name__)

#: Phép kiểm mesh là hàm thuần của ba artifact bất biến nên nhớ theo checksum: API khỏi tải lại và quét lại mesh mỗi
#: lần mở trang. Nhớ trong tiến trình là đủ — tiến trình khác chỉ phải tính lại một lần.
_GEOMETRY_CACHE: OrderedDict[tuple[str, str, str], GeometryQuality] = OrderedDict()
_GEOMETRY_CACHE_SIZE = 64

#: Lỗi khi một artifact của bước không đọc được; nhóm đó thành `unavailable`, các nhóm khác vẫn có số.
_READ_ERRORS = (ArtifactStoreError, ValueError, KeyError, TypeError, OSError)


def _reference(job: JobManifest, stage_id: StageId, artifact_type: str) -> ProductArtifactRef | None:
    """Ref của artifact mới nhất đã thành công ở một bước (theo JobManifest, không quét thư mục)."""
    for stage in reversed(job.stage_artifacts):
        if (
            stage.stage_id == stage_id
            and stage.status == StageStatus.SUCCEEDED
            and stage.artifact_type == artifact_type
            and stage.artifact_uri
            and stage.artifact_checksum
            and stage.data_class
        ):
            return ProductArtifactRef(
                artifact_type=artifact_type,
                schema_version="1.0",
                artifact_uri=stage.artifact_uri,
                artifact_checksum=stage.artifact_checksum,
                data_class=stage.data_class,
                producer_stage=stage_id,
                job_id=job.job_id,
            )
    return None


def _number(value: float | int | None, digits: int, unit: str = "") -> str:
    if value is None:
        return "Chưa đo"
    text = f"{value:,.{digits}f}" if isinstance(value, float) else f"{value:,}"
    return f"{text} {unit}".strip()


def _percent(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _group(group_id: str, title: str, build: Callable[[], list[Metric] | None]) -> StageEvaluation:
    """Chạy `build` của một nhóm; None = bước chưa có kết quả, lỗi đọc artifact = không khả dụng."""
    try:
        metrics = build()
    except _READ_ERRORS as error:
        logger.warning("Không đọc được chỉ số nhóm %s: %s", group_id, type(error).__name__)
        return StageEvaluation(
            group_id=group_id, title=title, status="unavailable", note="Không đọc được artifact của bước này."
        )
    if metrics is None:
        return StageEvaluation(group_id=group_id, title=title, status="pending", note="Bước này chưa có kết quả.")
    return StageEvaluation(group_id=group_id, title=title, status="measured", metrics=metrics)


def _input_metrics(registry: ProjectRegistry, job: JobManifest) -> list[Metric] | None:
    report = _reference(job, StageId.INPUT_VALIDATE, "RGBQualityReport")
    if report is None:
        return None
    quality = input_quality(report, registry.runtime_resolver.require)
    accepted = _percent(quality.accepted_frames, quality.inspected_frames)
    return [
        Metric(
            key="input.accepted_frames",
            label="Frame đạt chất lượng",
            value=accepted,
            unit="%",
            display=f"{_number(accepted, 1, '%')} ({quality.accepted_frames}/{quality.inspected_frames})",
            meaning="Tỉ lệ frame đủ nét để dựng 3D. Thấp nghĩa là video rung hoặc mờ, các bước sau thiếu dữ liệu.",
        ),
        Metric(
            key="input.blur_score_median",
            label="Độ nét trung vị",
            value=quality.blur_score_median,
            display=_number(quality.blur_score_median, 2),
            meaning="Điểm nét của frame điển hình (càng cao càng nét); dùng để so các video với nhau.",
        ),
        Metric(
            key="input.motion_active_ratio",
            label="Thời gian camera di chuyển",
            value=None if quality.motion_active_ratio is None else round(100 * quality.motion_active_ratio, 1),
            unit="%",
            display=_number(
                None if quality.motion_active_ratio is None else round(100 * quality.motion_active_ratio, 1), 1, "%"
            ),
            meaning="Phần video camera thật sự di chuyển. Đứng yên nhiều thì ít góc nhìn mới cho COLMAP.",
        ),
        Metric(
            key="input.warnings",
            label="Cảnh báo chuyển động",
            value=len(quality.warnings),
            display="Không có" if not quality.warnings else "; ".join(quality.warnings),
            meaning="Cảnh báo của bước kiểm video (đứng yên lâu, chuyển động quá nhanh).",
            verdict="ok" if not quality.warnings else "warn",
            threshold="Hồ sơ kiểm video `configs/product/upload_quality_v1.json`",
        ),
    ]


def _pose_metrics(registry: ProjectRegistry, job: JobManifest) -> list[Metric] | None:
    poses = _reference(job, StageId.CAMERA_POSE, "CameraPoseArtifact")
    if poses is None:
        return None
    quality = pose_quality(poses, registry.runtime_resolver.require)
    ratio = round(100 * quality.registered_ratio, 1)
    gate = quality.min_registered_ratio
    verdict: Verdict | None = None if gate is None else ("ok" if quality.registered_ratio >= gate else "fail")
    per_frame = round(quality.sparse_points / quality.registered_frames) if quality.sparse_points else None
    return [
        Metric(
            key="pose.registered_ratio",
            label="Ảnh COLMAP dựng được vị trí",
            value=ratio,
            unit="%",
            display=f"{_number(ratio, 1, '%')} ({quality.registered_frames}/{quality.input_frames})",
            meaning="Phần ảnh có vị trí camera. Ảnh không dựng được thì vùng nó nhìn thấy không vào scene.",
            verdict=verdict,
            threshold=None if gate is None else f"≥ {gate * 100:.0f}% (cấu hình COLMAP của job)",
        ),
        Metric(
            key="pose.mean_reprojection_error",
            label="Sai số reprojection trung bình",
            value=None if quality.mean_reprojection_error_px is None else round(quality.mean_reprojection_error_px, 3),
            unit="px",
            display=_number(quality.mean_reprojection_error_px, 2, "px"),
            meaning="Điểm 3D chiếu lại lệch ảnh bao nhiêu pixel. Càng nhỏ thì vị trí camera càng khớp ảnh.",
        ),
        Metric(
            key="pose.mean_track_length",
            label="Số ảnh thấy mỗi điểm 3D",
            value=None if quality.mean_track_length is None else round(quality.mean_track_length, 2),
            display=_number(quality.mean_track_length, 1, "ảnh"),
            meaning="Mỗi điểm 3D được bao nhiêu ảnh cùng thấy. Cao nghĩa là các ảnh chồng lấn tốt, pose ổn định.",
        ),
        Metric(
            key="pose.sparse_points_per_frame",
            label="Điểm 3D trên mỗi ảnh",
            value=per_frame,
            display=_number(per_frame, 0, "điểm"),
            meaning="Mật độ điểm đặc trưng dựng được. Thấp nghĩa là cảnh ít chi tiết hoặc ảnh mờ.",
        ),
    ]


def _visual_metrics(registry: ProjectRegistry, job: JobManifest) -> list[Metric] | None:
    visual = _reference(job, StageId.VISUAL_RECON, "BrushVisualArtifact")
    if visual is None:
        return None
    quality = visual_quality(visual, registry.runtime_resolver.require)
    return [
        *_visual_core(quality),
        *_held_out_metrics(quality),
    ]


def _held_out_metrics(quality: VisualQuality) -> list[Metric]:
    """PSNR/SSIM/LPIPS trên ảnh giữ lại không train (giao thức: eval/protocols/recon_visual_quality.md)."""
    label = "PSNR trên ảnh không train"
    meaning = "Scene có tái hiện đúng góc nhìn chưa từng thấy không; đây là thước đo chính của chất lượng 3DGS."
    if quality.held_out_frames is None or quality.held_out_psnr is None:
        reason = (
            "Chưa đo — scene này train trên mọi ảnh, không giữ lại ảnh để chấm"
            if quality.held_out_frames is None
            else "Chưa đo — lượt train này không in kết quả chấm ảnh giữ lại"
        )
        return [Metric(key="visual.novel_view_quality", label=label, value=None, display=reason, meaning=meaning)]
    views = f"trên {quality.held_out_frames} ảnh giữ lại"
    return [
        Metric(
            key="visual.novel_view_quality",
            label=label,
            value=round(quality.held_out_psnr, 2),
            unit="dB",
            display=f"{quality.held_out_psnr:.2f} dB {views}",
            meaning=meaning + " Cao hơn là tốt hơn.",
        ),
        Metric(
            key="visual.novel_view_ssim",
            label="SSIM trên ảnh không train",
            value=None if quality.held_out_ssim is None else round(quality.held_out_ssim, 4),
            display="Chưa đo" if quality.held_out_ssim is None else f"{quality.held_out_ssim:.3f} {views}",
            meaning="Độ giống về cấu trúc ảnh (0–1). Cao hơn là tốt hơn.",
        ),
        Metric(
            key="visual.novel_view_lpips",
            label="LPIPS trên ảnh không train",
            value=None if quality.held_out_lpips is None else round(quality.held_out_lpips, 4),
            display=(
                "Chưa đo — máy xử lý chưa cấu hình runtime LPIPS"
                if quality.held_out_lpips is None
                else f"{quality.held_out_lpips:.3f} {views} (mạng VGG)"
            ),
            meaning="Khác biệt theo cảm nhận của mắt người. Thấp hơn là tốt hơn.",
        ),
    ]


def _visual_core(quality: VisualQuality) -> list[Metric]:
    return [
        Metric(
            key="visual.gaussians",
            label="Số Gaussian",
            value=quality.gaussians,
            display=_number(quality.gaussians, 0),
            meaning="Kích thước scene 3DGS: ảnh hưởng dung lượng tải và tốc độ hiển thị, không phải thước đo độ đẹp.",
        ),
        Metric(
            key="visual.nonfinite_values",
            label="Giá trị hỏng trong file 3DGS",
            value=quality.nonfinite_values,
            display=_number(quality.nonfinite_values, 0),
            meaning="Số giá trị NaN/vô hạn. Khác 0 nghĩa là train bị hỏng và viewer có thể vẽ sai.",
            verdict=None if quality.nonfinite_values is None else ("ok" if quality.nonfinite_values == 0 else "fail"),
            threshold="= 0",
        ),
        Metric(
            key="visual.training",
            label="Cấu hình train",
            value=quality.train_iterations,
            unit="bước",
            display=f"{_number(quality.train_iterations, 0, 'bước')} trên {quality.training_frames} ảnh",
            meaning="Số bước tối ưu và số ảnh đã dùng; cần để so sánh công bằng giữa các lượt chạy.",
        ),
    ]


def _metric_metrics(registry: ProjectRegistry, job: JobManifest) -> list[Metric] | None:
    confirmation = _reference(job, StageId.METRIC_CANONICALIZE, "RGBMetricConfirmation")
    if confirmation is None:
        return None
    quality = metric_quality(confirmation, registry.runtime_resolver.require)
    error_cm = None if quality.check_error_m is None else round(quality.check_error_m * 100, 1)
    tolerance_cm = None if quality.check_tolerance_m is None else quality.check_tolerance_m * 100
    verdict: Verdict | None = None
    if quality.check_error_m is not None and quality.check_tolerance_m is not None:
        verdict = "ok" if quality.check_error_m <= quality.check_tolerance_m else "warn"
    sources = {"user_measured": "người dùng đo", "lidar": "LiDAR", "lidar_demo": "LiDAR của dataset mẫu"}
    return [
        Metric(
            key="metric.check_error",
            label="Sai lệch của đoạn kiểm C–D",
            value=error_cm,
            unit="cm",
            display=_number(error_cm, 1, "cm"),
            meaning="Tỉ lệ tính từ đoạn A–B đem đo đoạn C–D thì lệch số đo thật bao nhiêu. Lớn nghĩa là tỉ lệ mét "
            "không đáng tin.",
            verdict=verdict,
            threshold=None if tolerance_cm is None else f"≤ {tolerance_cm:.1f} cm (ngưỡng REC-06 theo sai số click)",
        ),
        Metric(
            key="metric.scale",
            label="Tỉ lệ đã áp",
            value=round(quality.scale_m_per_sfm_unit, 4),
            unit="m/đơn vị SfM",
            display=_number(quality.scale_m_per_sfm_unit, 4, "m/đơn vị SfM"),
            meaning="Hệ số đổi scene sang mét. Chỉ để truy vết; giá trị tự nó không tốt hay xấu.",
        ),
        Metric(
            key="metric.distance_source",
            label="Nguồn số đo",
            value=quality.distance_source,
            display=sources.get(quality.distance_source or "", quality.distance_source or "Không ghi"),
            meaning="Khoảng cách thật lấy từ đâu; số đo tay kém chính xác hơn LiDAR.",
        ),
    ]


def _geometry_metrics(registry: ProjectRegistry, job: JobManifest, geometry_config: Path) -> list[Metric] | None:
    bundle = job_bundle(registry, job)
    if bundle is None or not bundle.camera_pose_refs:
        return None
    profile_checksum = str(bundle.provenance.get("geometry_profile_checksum"))
    key = (
        bundle.canonical_geometry_ref.artifact_checksum,
        bundle.camera_pose_refs[0].artifact_checksum,
        profile_checksum,
    )
    quality = _GEOMETRY_CACHE.get(key)
    if quality is None:
        quality = geometry_quality(
            bundle.canonical_geometry_ref,
            bundle.camera_pose_refs[0],
            (geometry_config, profile_checksum),
            registry.runtime_resolver.require,
        )
        _GEOMETRY_CACHE[key] = quality
        while len(_GEOMETRY_CACHE) > _GEOMETRY_CACHE_SIZE:
            _GEOMETRY_CACHE.popitem(last=False)
    blocked = _percent(quality.blocked_positions, quality.camera_positions)
    return [
        Metric(
            key="geometry.blocked_camera_positions",
            label="Vị trí camera đã đi qua bị mesh chặn",
            value=blocked,
            unit="%",
            display=f"{_number(blocked, 1, '%')} ({quality.blocked_positions}/{quality.camera_positions})",
            meaning="Camera đã đi qua các điểm này nên chúng phải trống. Mesh chiếm chỗ ở đó là vật cản giả, "
            f"robot (bán kính {quality.robot_radius_m} m) sẽ bị chặn nhầm khi mô phỏng.",
        ),
        Metric(
            key="geometry.triangles",
            label="Số tam giác của collision mesh",
            value=quality.triangles,
            display=_number(quality.triangles, 0),
            meaning="Độ nặng của mesh va chạm đối với bộ mô phỏng.",
        ),
        Metric(
            key="geometry.voxel_resolution",
            label="Độ phân giải voxel",
            value=quality.voxel_resolution_m,
            unit="m",
            display=_number(quality.voxel_resolution_m, 3, "m"),
            meaning="Kích thước ô dùng để dựng mesh: chi tiết nhỏ hơn mức này không được giữ.",
        ),
    ]


def _object_metrics(scene: SceneIR | None) -> list[Metric] | None:
    if scene is None:
        return None
    proposed = [item for item in scene.objects if item.origin == SceneObjectOrigin.RECONSTRUCTED]
    # Xác nhận nằm ở `state`; loại/xoá chỉ ghi ở provenance vì SceneIR không có trạng thái "bị loại".
    confirmed = sum(item.state == SceneObjectState.CONFIRMED for item in proposed)
    rejected = sum(
        item.state != SceneObjectState.CONFIRMED and item.provenance.get("review") in {"IGNORED", "DELETED"}
        for item in proposed
    )
    pending = len(proposed) - confirmed - rejected
    added = sum(item.origin == SceneObjectOrigin.USER_ADDED for item in scene.objects)
    precision = _percent(confirmed, confirmed + rejected)
    reviewed = _percent(confirmed + rejected, len(proposed))
    return [
        Metric(
            key="objects.precision",
            label="Vật máy tách được người dùng xác nhận",
            value=precision,
            unit="%",
            display="Chưa có vật nào được duyệt"
            if precision is None
            else f"{_number(precision, 1, '%')} ({confirmed}/{confirmed + rejected} vật đã duyệt)",
            meaning="Trong các vật người dùng đã duyệt, bao nhiêu là vật thật. Đây là độ chính xác của bước tách, "
            "đo bằng chính quyết định của người dùng.",
        ),
        Metric(
            key="objects.reviewed",
            label="Tiến độ duyệt vật",
            value=reviewed,
            unit="%",
            display=f"{_number(reviewed, 1, '%')} ({confirmed + rejected}/{len(proposed)}; còn {pending} chưa duyệt)",
            meaning="Độ chính xác ở trên chỉ đáng tin khi phần lớn vật đã được duyệt.",
        ),
        Metric(
            key="objects.user_added",
            label="Vật người dùng phải thêm tay",
            value=added,
            unit="vật",
            display=_number(added, 0, "vật"),
            meaning="Vật cản có thật mà máy không tách ra. Nhiều nghĩa là bước tách bỏ sót.",
        ),
        Metric(
            key="objects.proposed",
            label="Vật máy đề xuất",
            value=len(proposed),
            unit="vật",
            display=_number(len(proposed), 0, "vật"),
            meaning="Tổng số ứng viên bước tách sinh ra; là mẫu số của các chỉ số trên.",
        ),
    ]


def _system_metrics(registry: ProjectRegistry, job: JobManifest) -> list[Metric] | None:
    attempts = registry.list_job_attempts(job.job_id)
    progress = job_progress(job, attempts, preview_ready=True)
    seconds = {
        stage.stage_id.value: (stage.completed_at - stage.started_at).total_seconds()
        for stage in progress.stages
        if stage.started_at and stage.completed_at
    }
    if not seconds:
        return None
    slowest = max(seconds, key=lambda stage_id: seconds[stage_id])
    total = sum(seconds.values())
    return [
        Metric(
            key="system.processing_time",
            label="Thời gian máy xử lý",
            value=round(total),
            unit="giây",
            display=f"{total / 60:,.1f} phút",
            meaning="Tổng thời gian các bước đã chạy trong lượt hiện tại, không tính lúc chờ người dùng.",
        ),
        Metric(
            key="system.slowest_stage",
            label="Bước lâu nhất",
            value=slowest,
            display=f"{slowest} ({seconds[slowest] / 60:,.1f} phút)",
            meaning="Nơi tốn thời gian nhất, tức nơi đáng tối ưu hoặc cần GPU mạnh hơn.",
        ),
        Metric(
            key="system.attempts",
            label="Số lượt chạy",
            value=progress.attempt,
            unit="lượt",
            display=_number(progress.attempt, 0, "lượt"),
            meaning="Lớn hơn 1 nghĩa là job từng lỗi và phải chạy lại.",
        ),
    ]


def evaluate_job(registry: ProjectRegistry, job_id: str, geometry_config: Path) -> JobEvaluation:
    """Bảng đánh giá hiện tại của một job; nhóm nào chưa có dữ liệu thì ghi rõ trạng thái thay vì bỏ qua.

    `geometry_config`: file thông số REC-05 của deployment (`PRODUCT_GEOMETRY_CONFIG`), nguồn kích thước robot.
    """
    job = registry.get_job(job_id)
    project = registry.get_project(job.project_id)
    try:
        scene: SceneIR | None = registry.scene.current(job_id).scene
    except (SceneError, ArtifactStoreError, ValueError):
        scene = None
    groups = [
        _group(StageId.INPUT_VALIDATE.value, "Video đầu vào", lambda: _input_metrics(registry, job)),
        _group(StageId.CAMERA_POSE.value, "Vị trí camera", lambda: _pose_metrics(registry, job)),
        _group(StageId.VISUAL_RECON.value, "Scene 3DGS", lambda: _visual_metrics(registry, job)),
        _group(StageId.METRIC_CANONICALIZE.value, "Tỉ lệ mét", lambda: _metric_metrics(registry, job)),
        _group(
            StageId.RGB_GEOMETRY.value, "Hình học và va chạm", lambda: _geometry_metrics(registry, job, geometry_config)
        ),
        _group(StageId.OBJECT_EXTRACT.value, "Tách vật thể", lambda: _object_metrics(scene)),
        _group("system", "Hệ thống", lambda: _system_metrics(registry, job)),
    ]
    return JobEvaluation(
        job_id=job.job_id,
        project_id=job.project_id,
        scene_name=project.name,
        job_status=job.status.value,
        scene_revision=scene.scene_revision if scene else None,
        generated_at=datetime.now(UTC),
        groups=groups,
    )
