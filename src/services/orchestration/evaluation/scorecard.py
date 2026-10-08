"""Dựng bảng đánh giá của một job từ artifact đã publish.

Mỗi nhóm ứng với một bước của pipeline Studio. Số liệu lấy qua public port của EX-REC (`reconstruction.quality`),
`ReconstructionBundle`, SceneIR và journal của job — không tính lại kết quả pipeline và không dùng dữ liệu
evaluation-only. Kết luận đạt/không đạt chỉ gán khi ngưỡng đã có trong repo; chỉ số khác chỉ nêu số và ý nghĩa.
"""

import json
import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobManifest, StageId, StageStatus
from src.models.contracts.scene import SceneIR, SceneObjectOrigin, SceneObjectState
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.benchmark import current_attempt_stage_timings
from src.services.orchestration.evaluation.advice import summarize
from src.services.orchestration.evaluation.models import JobEvaluation, Metric, StageEvaluation, Verdict
from src.services.orchestration.evaluation.reference import ReferenceSet, describe, load_reference
from src.services.orchestration.jobs.progress import job_progress
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.processing.observed import usage_vram
from src.services.orchestration.processing.telemetry import ResourceUsage
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import SceneError
from src.services.reconstruction import (
    GeometryQuality,
    LidarPackageRecord,
    VisualQuality,
    geometry_quality,
    input_quality,
    load_proposal,
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
            threshold="Hồ sơ kiểm video `configs/product/upload_quality_v2.json`",
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


def _visual_metrics(
    registry: ProjectRegistry, job: JobManifest, reference_config: Path | None = None
) -> list[Metric] | None:
    visual = _reference(job, StageId.VISUAL_RECON, "BrushVisualArtifact")
    if visual is None:
        return None
    quality = visual_quality(visual, registry.runtime_resolver.require)
    ref_set = load_reference(reference_config) if reference_config is not None else None
    return [
        *_visual_core(quality),
        *_held_out_metrics(quality, ref_set),
    ]


def _held_out_metrics(quality: VisualQuality, ref_set: ReferenceSet | None = None) -> list[Metric]:
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
    psnr_ref = (
        describe([s.psnr for s in ref_set.scenes if s.psnr is not None], unit="dB", digits=2)
        if ref_set is not None
        else None
    )
    ssim_ref = (
        describe([s.ssim for s in ref_set.scenes if s.ssim is not None], unit="", digits=3)
        if ref_set is not None
        else None
    )
    lpips_ref = (
        describe([s.lpips for s in ref_set.scenes if s.lpips is not None], unit="", digits=3)
        if ref_set is not None
        else None
    )
    return [
        Metric(
            key="visual.novel_view_quality",
            label=label,
            value=round(quality.held_out_psnr, 2),
            unit="dB",
            display=f"{quality.held_out_psnr:.2f} dB {views}",
            meaning=meaning + " Cao hơn là tốt hơn.",
            reference=psnr_ref,
        ),
        Metric(
            key="visual.novel_view_ssim",
            label="SSIM trên ảnh không train",
            value=None if quality.held_out_ssim is None else round(quality.held_out_ssim, 4),
            display="Chưa đo" if quality.held_out_ssim is None else f"{quality.held_out_ssim:.3f} {views}",
            meaning="Độ giống về cấu trúc ảnh (0–1). Cao hơn là tốt hơn.",
            reference=ssim_ref if quality.held_out_ssim is not None else None,
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
            reference=lpips_ref if quality.held_out_lpips is not None else None,
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
    sources = {
        "user_measured": "người dùng đo",
        "lidar": "LiDAR",
        "lidar_demo": "LiDAR của dataset mẫu",
        "lidar_trajectory": "căn chỉnh theo quỹ đạo của gói LiDAR",
        "ai_estimated": "mô hình ước lượng độ sâu",
    }
    scale_metrics = [
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
    if quality.distance_source == "lidar_trajectory":
        # Đoạn C–D của job LiDAR sinh từ chính phép căn chỉnh nên không phải phép kiểm độc lập: thay bằng độ lệch
        # pose ↔ quỹ đạo, là bằng chứng thật của tỉ lệ ở luồng này (ADR 0009).
        return [*_trajectory_metrics(registry, job), *scale_metrics]
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
        *scale_metrics,
    ]


def _lidar_metrics(registry: ProjectRegistry, job: JobManifest) -> list[Metric] | None:
    """Gói LiDAR của job (ADR 0009): bao nhiêu dữ liệu đã nhận và mặt sàn được ước lượng từ bao nhiêu điểm."""
    reference = _reference(job, StageId.LIDAR_INGEST, "LidarPackageRecord")
    if reference is None:
        return None
    record = LidarPackageRecord.model_validate_json(registry.runtime_resolver.require(reference).read_bytes())
    kinds = {"registered_lidar": "đám mây đã đăng ký", "lidar_scan_sequence": "scan thô + quỹ đạo (hệ thống ghép)"}
    origin = {"ground_truth": "quỹ đạo chuẩn của dataset", "estimated": "quỹ đạo do SLAM/odometry tính"}
    metrics = [
        Metric(
            key="lidar.kind",
            label="Dạng gói LiDAR",
            value=record.kind,
            display=kinds[record.kind],
            meaning="Gói có sẵn đám mây đã đăng ký, hay gồm các scan thô để hệ thống ghép theo quỹ đạo.",
        ),
        Metric(
            key="lidar.points",
            label="Số điểm của đám mây đã đăng ký",
            value=record.point_count,
            display=_number(record.point_count, 0, "điểm"),
            meaning="Đám mây dùng để lấy mặt sàn và để đối chiếu với scene.",
        ),
        Metric(
            key="lidar.poses",
            label="Số pose trong quỹ đạo",
            value=record.pose_count,
            display=_number(record.pose_count, 0, "pose"),
            meaning="Mỗi pose ứng với một frame của video; thiếu pose so với video thì bước dựng pose sẽ dừng.",
        ),
        Metric(
            key="lidar.floor_support",
            label="Số điểm làm căn cứ cho mặt sàn",
            value=record.floor_support_points,
            display=_number(record.floor_support_points, 0, "điểm"),
            meaning="Mặt sàn (z = 0 của scene) ước lượng từ các điểm LiDAR nằm dưới đường đi của cảm biến; càng nhiều "
            "điểm càng chắc.",
        ),
        Metric(
            key="lidar.trajectory_origin",
            label="Nguồn quỹ đạo",
            value=record.trajectory_origin,
            display=origin[record.trajectory_origin],
            meaning="Quỹ đạo chuẩn của dataset chỉ có ở dữ liệu mẫu; dữ liệu thật dùng quỹ đạo từ SLAM/odometry.",
        ),
    ]
    if record.fusion is not None:
        removed = _percent(record.fusion.removed_points, record.fusion.input_points)
        metrics[2:2] = [
            Metric(
                key="lidar.scans",
                label="Số scan đã ghép",
                value=record.fusion.scan_count,
                display=_number(record.fusion.scan_count, 0, "scan"),
                meaning="Số scan thô được đưa về chung một hệ theo quỹ đạo.",
            ),
            Metric(
                key="lidar.removed_points",
                label="Điểm bị loại khi ghép",
                value=removed,
                unit="%",
                display=_number(removed, 1, "%"),
                meaning="Điểm quá gần hoặc quá xa cảm biến, hoặc tia không có phản hồi. Vài chục phần trăm là bình thường; "
                "gần 100% là dấu hiệu sai đơn vị.",
            ),
        ]
    return metrics


def _trajectory_metrics(registry: ProjectRegistry, job: JobManifest) -> list[Metric]:
    """Độ lệch pose camera ↔ quỹ đạo của gói LiDAR, đọc từ đề xuất tỉ lệ mà người dùng đã xác nhận."""
    preview = registry.get_preview(job.job_id)
    proposal = load_proposal(job.job_id, preview.source_visual_ref, registry.runtime_resolver.locate)
    alignment = proposal.alignment if proposal is not None else None
    if alignment is None:
        return [
            Metric(
                key="metric.trajectory_offset_median",
                label="Độ lệch pose camera so với quỹ đạo LiDAR (trung vị)",
                value=None,
                display="Chưa đo",
                meaning="Không tìm thấy bản ghi căn chỉnh quỹ đạo của scene này.",
            )
        ]
    origin = {"ground_truth": "quỹ đạo chuẩn của dataset", "estimated": "quỹ đạo do SLAM/odometry tính"}
    median_cm, max_cm = round(alignment.offset_median_m * 100, 1), round(alignment.offset_max_m * 100, 1)
    return [
        Metric(
            key="metric.trajectory_offset_median",
            label="Độ lệch pose camera so với quỹ đạo LiDAR (trung vị)",
            value=median_cm,
            unit="cm",
            display=_number(median_cm, 1, "cm"),
            meaning="Scene được dựng bám theo quỹ đạo của gói LiDAR; số này cho biết pose camera cuối cùng nằm cách "
            f"quỹ đạo bao xa trên đường đi dài {alignment.path_length_m:.1f} m. Lớn nghĩa là video và gói LiDAR không "
            "khớp nhau (khác lượt quay, sai calibration, lệch thời gian).",
        ),
        Metric(
            key="metric.trajectory_offset_max",
            label="Độ lệch lớn nhất",
            value=max_cm,
            unit="cm",
            display=_number(max_cm, 1, "cm"),
            meaning="Frame lệch quỹ đạo nhiều nhất; đám mây LiDAR có thể nằm lệch scene tới mức này ở chỗ đó.",
        ),
        Metric(
            key="metric.trajectory_frames",
            label="Frame dựng được trên quỹ đạo",
            value=_percent(alignment.registered_frames, alignment.input_frames),
            unit="%",
            display=f"{alignment.registered_frames}/{alignment.input_frames}",
            meaning="Số frame có pose sau khi dựng bám quỹ đạo.",
        ),
        Metric(
            key="metric.trajectory_origin",
            label="Nguồn quỹ đạo",
            value=alignment.trajectory_origin,
            display=origin[alignment.trajectory_origin],
            meaning="Quỹ đạo chuẩn của dataset chỉ có ở dữ liệu mẫu; dữ liệu thật dùng quỹ đạo từ SLAM/odometry.",
        ),
    ]


#: Mã benchmark đối chứng mà evaluator ở `eval/` ghi theo job (`eval/protocols/BENCHMARKS.md`).
_REFERENCE_CODES = ("recon_pose", "metric_scale", "recon_geometry", "metric_scale_proposal")
REFERENCE_GROUP_ID = "reference"


def _reference_record(registry: ProjectRegistry, job_id: str, code: str) -> dict | None:
    """Bản ghi đối chứng mới nhất của một mã; None khi evaluator chưa chạy cho job này."""
    latest = None
    attempt = 1
    while path := registry.runtime_resolver.locate(f"artifact://jobs/{job_id}/benchmark/{code}/attempt-{attempt}.json"):
        latest, attempt = path, attempt + 1
    return None if latest is None else json.loads(latest.read_text(encoding="utf-8"))


def _reference_metrics(registry: ProjectRegistry, job: JobManifest) -> list[Metric] | None:
    """Chỉ số so với ground truth của dataset; chỉ có ở scene dựng từ dataset đã chạy evaluator."""
    records = {code: _reference_record(registry, job.job_id, code) for code in _REFERENCE_CODES}
    metrics: list[Metric] = []
    pose, scale, geometry, proposal = (records[code] for code in _REFERENCE_CODES)
    guided = " Scene này dựng bám theo chính quỹ đạo đó nên số đo mức bám, không phải độ chính xác độc lập."
    if pose is not None:
        note = guided if pose.get("job_used_this_trajectory") else ""
        ate_cm = round(pose["ate_similarity_m"]["rmse"] * 100, 1)
        metrics += [
            Metric(
                key="reference.ate",
                label="Sai số vị trí camera (ATE, RMSE)",
                value=ate_cm,
                unit="cm",
                display=_number(ate_cm, 1, "cm"),
                meaning=f"Tâm camera của scene so với quỹ đạo chuẩn trên {pose['registered_frames']} frame, sau khi "
                f"khớp hai quỹ đạo (đường đi dài {pose['path_length_m']:.1f} m).{note}",
                source="reference",
            ),
            Metric(
                key="reference.rpe_translation",
                label="Sai số dịch chuyển giữa hai frame liên tiếp (RPE, trung vị)",
                value=round(pose["rpe_translation_m"]["p50"] * 100, 1),
                unit="cm",
                display=_number(round(pose["rpe_translation_m"]["p50"] * 100, 1), 1, "cm"),
                meaning="Sai số cục bộ của chuyển động camera, không phụ thuộc trôi tích luỹ.",
                source="reference",
            ),
            Metric(
                key="reference.rpe_rotation",
                label="Sai số góc quay giữa hai frame liên tiếp (RPE, trung vị)",
                value=round(pose["rpe_rotation_deg"]["p50"], 2),
                unit="°",
                display=_number(round(pose["rpe_rotation_deg"]["p50"], 2), 2, "°"),
                meaning="Sai số hướng camera giữa hai frame đã dựng liên tiếp.",
                source="reference",
            ),
        ]
    if scale is not None:
        note = ""
        if scale.get("scale_is_independent") is False or scale.get("job_used_this_trajectory"):
            note = " Tỉ lệ của scene này được suy từ chính quỹ đạo chuẩn nên số này không phải số đo độc lập."
        metrics.append(
            Metric(
                key="reference.scale_error",
                label="Sai số tỉ lệ mét",
                value=scale["scale_error_percent"],
                unit="%",
                display=_number(float(scale["scale_error_percent"]), 2, "%"),
                meaning="Một mét trong scene dài hơn (+) hay ngắn hơn (−) một mét thật bao nhiêu phần trăm, tính từ "
                f"quỹ đạo chuẩn.{note}",
                source="reference",
            )
        )
    if proposal is not None:
        methods = {"moge2_sparse_depth_scale_only": "mô hình ước lượng độ sâu", "lidar_trajectory_alignment": "LiDAR"}
        note = "" if proposal.get("scale_is_independent") else " Đề xuất này suy từ chính quỹ đạo chuẩn, không độc lập."
        metrics.append(
            Metric(
                key="reference.scale_proposal_error",
                label="Sai số của đề xuất tỉ lệ tự động",
                value=proposal["proposal_error_percent"],
                unit="%",
                display=_number(float(proposal["proposal_error_percent"]), 2, "%"),
                meaning="Tỉ lệ mét hệ thống tự đề xuất ("
                f"{methods.get(proposal['proposal_method'], proposal['proposal_method'])}) lệch tỉ lệ thật bao "
                f"nhiêu, trước khi người dùng xác nhận hay sửa. Dương = scene bị phóng to.{note}",
                source="reference",
            )
        )
    if geometry is not None:
        accuracy_cm = round(geometry["accuracy_m"]["p50"] * 100, 1)
        at_10 = geometry["at_10cm"]
        metrics += [
            Metric(
                key="reference.surface_accuracy",
                label="Bề mặt 3DGS lệch bản đồ chuẩn (trung vị)",
                value=accuracy_cm,
                unit="cm",
                display=_number(accuracy_cm, 1, "cm"),
                meaning="Khoảng cách từ điểm bề mặt của scene tới điểm gần nhất của bản đồ ground truth, trong "
                f"{geometry['window_m']:.0f} m quanh đường camera. Đã gồm sai số khớp "
                f"({geometry['alignment_rms_m'] * 100:.1f} cm).",
                source="reference",
            ),
            Metric(
                key="reference.precision_10cm",
                label="Điểm của scene nằm trong 10 cm quanh bề mặt chuẩn (precision)",
                value=round(at_10["precision"] * 100, 1),
                unit="%",
                display=_number(round(at_10["precision"] * 100, 1), 1, "%"),
                meaning="Phần bề mặt scene dựng đúng chỗ.",
                source="reference",
            ),
            Metric(
                key="reference.recall_10cm",
                label="Bề mặt chuẩn được scene phủ trong 10 cm (recall)",
                value=round(at_10["recall"] * 100, 1),
                unit="%",
                display=_number(round(at_10["recall"] * 100, 1), 1, "%"),
                meaning="Phần bề mặt thật mà scene dựng lại được. Bản đồ chuẩn có cả chỗ camera không nhìn thấy nên "
                "đây là cận dưới.",
                source="reference",
            ),
        ]
    return metrics or None


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


def _ram_metric(completed: list[ResourceUsage]) -> Metric:
    ram_records = [(usage, usage.peak_ram_gb) for usage in completed if usage.peak_ram_gb is not None]
    if not ram_records:
        return Metric(
            key="system.peak_ram",
            label="RAM tối đa",
            value=None,
            unit="GB",
            display="Chưa đo — job này không có bản ghi tài nguyên",
            meaning="Lượng RAM lớn nhất tiến trình hệ thống đã sử dụng trong suốt quá trình chạy.",
        )
    best, peak_ram = max(ram_records, key=lambda item: item[1])
    val = round(peak_ram, 2)
    display = f"{val:.1f}".replace(".", ",") + f" GB (bước {best.tool})"
    return Metric(
        key="system.peak_ram",
        label="RAM tối đa",
        value=val,
        unit="GB",
        display=display,
        meaning="Lượng RAM lớn nhất tiến trình hệ thống đã sử dụng trong suốt quá trình chạy.",
    )


def _vram_metric(completed: list[ResourceUsage]) -> Metric:
    vram_records = [(u, usage_vram(u)) for u in completed]
    valid = [(u, v) for u, v in vram_records if v is not None]
    if not valid:
        return Metric(
            key="system.peak_vram",
            label="VRAM tối đa",
            value=None,
            unit="GB",
            display="Chưa đo — job này không có bản ghi tài nguyên",
            meaning="Lượng VRAM lớn nhất GPU đã sử dụng trong suốt quá trình chạy.",
        )
    best, vram_num = max(valid, key=lambda item: item[1])
    val = round(vram_num, 2)
    display = f"{val:.1f}".replace(".", ",") + f" GB (bước {best.tool})"
    return Metric(
        key="system.peak_vram",
        label="VRAM tối đa",
        value=val,
        unit="GB",
        display=display,
        meaning="Lượng VRAM lớn nhất GPU đã sử dụng trong suốt quá trình chạy.",
    )


def _config_metric(completed: list[ResourceUsage]) -> Metric:
    if not completed:
        return Metric(
            key="system.config",
            label="Cấu hình xử lý",
            value=None,
            display="Chưa đo — job này không có bản ghi tài nguyên",
            meaning="Thông số cấu hình giới hạn số frame, số splat và độ phân giải đã áp dụng cho job.",
        )
    latest = max(completed, key=lambda u: u.completed_at)
    if latest.params is None:
        return Metric(
            key="system.config",
            label="Cấu hình xử lý",
            value=None,
            display="Chưa đo — job này không có bản ghi tài nguyên",
            meaning="Thông số cấu hình giới hạn số frame, số splat và độ phân giải đã áp dụng cho job.",
        )
    params = latest.params or {}

    def formatted(key: str) -> str:
        value = params.get(key)
        return "—" if value is None else f"{int(value):,}".replace(",", ".")

    display = (
        f"tối đa {formatted('sampling.max_frames')} frame · "
        f"{formatted('brush.max_splats')} splat · "
        f"{formatted('brush.max_resolution')} px"
    )
    return Metric(
        key="system.config",
        label="Cấu hình xử lý",
        value=None,
        display=display,
        meaning="Thông số cấu hình giới hạn số frame, số splat và độ phân giải đã áp dụng cho job.",
    )


def _system_metrics(
    registry: ProjectRegistry, job: JobManifest, usages: list[ResourceUsage] | None = None
) -> list[Metric]:
    attempts = registry.list_job_attempts(job.job_id)
    progress = job_progress(job, attempts, preview_ready=True)
    seconds = {
        stage.stage_id: stage.seconds
        for stage in current_attempt_stage_timings(job, attempts, progress)
        if stage.seconds is not None
    }
    completed = [u for u in (usages or []) if u.job_id == job.job_id and u.outcome == "completed"]
    metrics: list[Metric] = []
    if seconds:
        slowest = max(seconds, key=lambda stage_id: seconds[stage_id])
        total = sum(seconds.values())
        metrics.extend(
            [
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
        )
    metrics.extend([_ram_metric(completed), _vram_metric(completed), _config_metric(completed)])
    return metrics


def evaluate_job(
    registry: ProjectRegistry,
    job_id: str,
    geometry_config: Path,
    reference_config: Path | None = None,
    usages: list[ResourceUsage] | None = None,
) -> JobEvaluation:
    """Bảng đánh giá hiện tại của một job; nhóm nào chưa có dữ liệu thì ghi rõ trạng thái thay vì bỏ qua.

    `geometry_config`: file thông số REC-05 của deployment (`PRODUCT_GEOMETRY_CONFIG`), nguồn kích thước robot.
    `reference_config`: file chứa khoảng tham chiếu PSNR/SSIM/LPIPS từ các scene đã chạy (`PRODUCT_EVALUATION_REFERENCE`).
    `usages`: danh sách bản ghi đo đạc tài nguyên từ database để đưa vào nhóm Hệ thống.
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
        _group(StageId.VISUAL_RECON.value, "Scene 3DGS", lambda: _visual_metrics(registry, job, reference_config)),
        _group(StageId.METRIC_CANONICALIZE.value, "Tỉ lệ mét", lambda: _metric_metrics(registry, job)),
        _group(
            StageId.RGB_GEOMETRY.value, "Hình học và va chạm", lambda: _geometry_metrics(registry, job, geometry_config)
        ),
        _group(StageId.OBJECT_EXTRACT.value, "Tách vật thể", lambda: _object_metrics(scene)),
        _group("system", "Hệ thống", lambda: _system_metrics(registry, job, usages)),
    ]
    # Bước nhận LiDAR chỉ có ở job có gói LiDAR; job chỉ có video không hiện một nhóm "chưa có kết quả" thừa.
    if any(stage.stage_id == StageId.LIDAR_INGEST for stage in job.stage_artifacts):
        lidar = _group(StageId.LIDAR_INGEST.value, "Dữ liệu LiDAR", lambda: _lidar_metrics(registry, job))
        groups.insert(1, lidar)
    # Khối đối chứng chỉ có khi evaluator ở `eval/` đã ghi bản ghi cho job (scene dựng từ dataset có ground truth);
    # scene của người dùng không có khối này thay vì hiện một khối "chưa có kết quả" không bao giờ có.
    reference = _group(REFERENCE_GROUP_ID, "So với dữ liệu đối chứng", lambda: _reference_metrics(registry, job))
    if reference.status != "pending":
        groups.append(
            reference.model_copy(
                update={"note": "So với ground truth của dataset TorWIC; không có cho dữ liệu người dùng tự quay."}
            )
            if reference.status == "measured"
            else reference
        )
    summary = summarize(groups)
    return JobEvaluation(
        job_id=job.job_id,
        project_id=job.project_id,
        scene_name=project.name,
        job_status=job.status.value,
        scene_revision=scene.scene_revision if scene else None,
        generated_at=datetime.now(UTC),
        summary=summary,
        groups=groups,
    )
