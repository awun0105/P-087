"""Chỉ số tự kiểm của các bước EX-REC, đọc từ chính artifact đã publish (không cần ground truth).

Public read-only port cho hệ thống đánh giá của PRODUCT (`orchestration/evaluation`): mỗi hàm nhận ref của một artifact
REC và trả vài con số có ý nghĩa với chất lượng bước đó. Không tính lại kết quả của pipeline, không đọc dữ liệu
evaluation-only; số nào artifact không mang thì trả None thay vì ước lượng.
"""

import json
import math
import statistics
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ContractModel, ProductArtifactRef

Resolve = Callable[[ProductArtifactRef], Path]
#: Số GPU tối đa trên một máy worker khi đối chiếu checksum của thông số hình học.
_MAX_GPU_INDEX = 15


class InputQuality(ContractModel):
    """REC-02: chất lượng video đầu vào trên các frame đã giải mã."""

    inspected_frames: int
    accepted_frames: int
    excluded_frames: int
    blur_score_median: float | None
    motion_active_ratio: float | None
    motion_p90_px: float | None
    warnings: list[str]


class PoseQuality(ContractModel):
    """REC-03: COLMAP dựng được camera tin cậy tới đâu."""

    input_frames: int
    registered_frames: int
    registered_ratio: float
    min_registered_ratio: float | None
    sparse_points: int | None
    mean_reprojection_error_px: float | None
    mean_track_length: float | None
    #: Số bậc thang thử lại COLMAP đã chạy trong lượt này (T-071 C1); 0 = ghép lần đầu đã đạt.
    retry_steps: int = 0
    #: Mô hình dưới ngưỡng thường được nhận sau thang thử lại: vùng thiếu ảnh có thể mờ hoặc thủng (T-071 C3).
    registration_warning: bool = False
    #: Ngưỡng tối thiểu để nhận mô hình kèm cảnh báo; None = config không cho nhận.
    accept_registered_ratio: float | None = None


class VisualQuality(ContractModel):
    """REC-04: kích thước và tính hợp lệ của 3DGS đã train."""

    gaussians: int | None
    nonfinite_values: int | None
    training_frames: int
    train_iterations: int | None
    #: Số ảnh giữ lại không train; None = scene train trên mọi ảnh (không có phép đo góc nhìn mới).
    held_out_frames: int | None = None
    #: Điểm trên ảnh giữ lại ở bước train cuối; None = chưa đo.
    held_out_psnr: float | None = None
    held_out_ssim: float | None = None
    held_out_lpips: float | None = None


class MetricQuality(ContractModel):
    """REC-06: tỉ lệ mét và phép kiểm chéo bằng đoạn C–D."""

    scale_m_per_sfm_unit: float
    anchor_distance_m: float
    check_distance_m: float | None
    check_error_m: float | None
    check_tolerance_m: float | None
    distance_source: str | None


class GeometryQuality(ContractModel):
    """REC-05: collision mesh so với những nơi camera đã thật sự đi qua."""

    triangles: int
    camera_positions: int
    blocked_positions: int
    robot_radius_m: float
    voxel_resolution_m: float


def _load(reference: ProductArtifactRef, resolve: Resolve) -> dict:
    document = json.loads(resolve(reference).read_bytes())
    if not isinstance(document, dict):
        raise ValueError(f"{reference.artifact_type} không phải JSON object")
    return document


def input_quality(report: ProductArtifactRef, resolve: Resolve) -> InputQuality:
    """Đọc RGBQualityReport: số frame đạt/loại, độ nét trung vị và chuyển động camera."""
    document = _load(report, resolve)
    frames = document["frames"]
    motion = document.get("motion") or {}
    scores = [frame["blur_score"] for frame in frames if isinstance(frame.get("blur_score"), int | float)]
    return InputQuality(
        inspected_frames=len(frames),
        accepted_frames=sum(frame.get("quality") == "accepted" for frame in frames),
        excluded_frames=len(document.get("excluded_frame_ids", [])),
        blur_score_median=statistics.median(scores) if scores else None,
        motion_active_ratio=motion.get("active_ratio"),
        motion_p90_px=motion.get("motion_p90_px"),
        warnings=[str(item) for item in motion.get("warnings", [])],
    )


def _sparse_statistics(document: dict, resolve: Resolve) -> tuple[float | None, float | None]:
    """Sai số reprojection trung bình (px) và độ dài track trung bình từ `points3D.txt` của COLMAP."""
    entry = (document.get("sparse_files") or {}).get("points3D.txt")
    if not isinstance(entry, dict):
        return None, None
    errors: list[float] = []
    observations = 0
    with resolve(ProductArtifactRef.model_validate(entry)).open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("#"):
                continue
            # POINT3D_ID X Y Z R G B ERROR TRACK[] với mỗi quan sát là một cặp (IMAGE_ID, POINT2D_IDX).
            fields = line.split()
            if len(fields) >= 8:
                errors.append(float(fields[7]))
                observations += (len(fields) - 8) // 2
    if not errors:
        return None, None
    return statistics.fmean(errors), observations / len(errors)


def pose_quality(poses: ProductArtifactRef, resolve: Resolve) -> PoseQuality:
    """Đọc CameraPoseArtifact (SfM): tỉ lệ ảnh đăng ký được và chất lượng điểm thưa của model được chọn."""
    document = _load(poses, resolve)
    registered = len(document["poses"])
    selected = next(
        (model for model in document.get("models", []) if model.get("model_id") == document.get("selected_model_id")),
        None,
    )
    reprojection, track = _sparse_statistics(document, resolve)
    return PoseQuality(
        input_frames=len(document["input_frame_ids"]),
        registered_frames=registered,
        registered_ratio=float(document["registered_ratio"]),
        min_registered_ratio=(document.get("config") or {}).get("min_registered_ratio"),
        sparse_points=selected.get("sparse_points") if selected else None,
        mean_reprojection_error_px=reprojection,
        mean_track_length=track,
        retry_steps=len(document.get("retry_ladder") or []),
        registration_warning=document.get("registration_warning") is True,
        accept_registered_ratio=(document.get("config") or {}).get("accept_registered_ratio_after_retry"),
    )


def visual_quality(visual: ProductArtifactRef, resolve: Resolve) -> VisualQuality:
    """Đọc BrushVisualArtifact: số Gaussian, giá trị không hữu hạn và cấu hình train đã dùng."""
    document = _load(visual, resolve)
    inspection = document.get("inspection") or {}
    held_out = document.get("held_out_frame_ids")
    holdout = document.get("holdout_quality") or {}
    return VisualQuality(
        held_out_frames=None if held_out is None else len(held_out),
        held_out_psnr=holdout.get("psnr"),
        held_out_ssim=holdout.get("ssim"),
        held_out_lpips=holdout.get("lpips"),
        gaussians=inspection.get("num_gaussians"),
        nonfinite_values=inspection.get("nonfinite_count"),
        training_frames=len(document.get("training_frame_ids", [])),
        train_iterations=(document.get("config") or {}).get("total_train_iters"),
    )


def metric_quality(confirmation: ProductArtifactRef, resolve: Resolve) -> MetricQuality:
    """Đọc RGBMetricConfirmation và bản khai số đo của nó: tỉ lệ đã áp và sai lệch của đoạn kiểm C–D."""
    from src.services.reconstruction.metric_port import check_tolerance_m

    document = _load(confirmation, resolve)
    preview = document["preview"]
    scale = float(preview["transform"]["scale_m_per_sfm_unit"])
    anchor = preview["request"]["anchor"]
    anchor_distance = float(anchor["distance_m"])
    declared = _load(ProductArtifactRef.model_validate(anchor["measurement_ref"]), resolve).get("input") or {}
    check_distance = declared.get("check_distance_m")
    error = tolerance = None
    if check_distance is not None and declared.get("check_a") and declared.get("check_b"):
        measured = scale * math.dist(declared["check_a"], declared["check_b"])
        error = abs(measured - float(check_distance))
        tolerance = check_tolerance_m(anchor_distance, float(check_distance))
    return MetricQuality(
        scale_m_per_sfm_unit=scale,
        anchor_distance_m=anchor_distance,
        check_distance_m=check_distance,
        check_error_m=error,
        check_tolerance_m=tolerance,
        distance_source=declared.get("distance_source"),
    )


class GeometryProfileMismatchError(ValueError):
    """Thông số REC-05 hiện tại của deployment không phải bản đã dựng mesh của job.

    Không phải artifact hỏng: mesh vẫn đọc được, nhưng số đo sẽ không đúng với robot/cấu hình đã dùng, nên từ chối.
    Muốn đo thì phải dựng lại bước hình học của job.
    """


def geometry_quality(
    collision_mesh: ProductArtifactRef,
    metric_poses: ProductArtifactRef,
    profile: tuple[Path | dict, str],
    resolve: Resolve,
) -> GeometryQuality:
    """Đếm vị trí camera (hệ mét) mà collision mesh chiếm chỗ trong khối robot đặt tại đó.

    Camera đã đi qua các vị trí này nên mesh chiếm chỗ ở đó là vật cản giả. Cùng phép kiểm với benchmark
    `collision_path_clearance` (eval/path), nhưng trên chính mesh đã publish của job, không dựng lại mesh.

    `profile` = (snapshot của job hoặc file REC-05 của deployment, checksum bundle đã ghi). Kích thước robot phải đúng
    bản đã dùng khi dựng mesh. Job cũ được đối chiếu profile legacy đóng gói khi deployment chuyển sang indoor.
    """
    import numpy as np

    from src.services.reconstruction.adapters.collision_glb import read_collision_glb, topology
    from src.services.reconstruction.finalize import GeometryProfile, load_geometry_profile

    source, expected_checksum = profile
    geometry = GeometryProfile.model_validate(source) if isinstance(source, dict) else load_geometry_profile(source)
    if isinstance(source, dict):
        if geometry.checksum() != expected_checksum:
            raise GeometryProfileMismatchError("snapshot profile checksum differs from the job")
    elif source.name == "geometry_indoor_v1.json":
        # Pre-snapshot jobs retain their packaged geometry_v1 profile across indoor deployment upgrades.
        legacy_path = Path(__file__).resolve().parents[3] / "configs/product/geometry_v1.json"
        candidates = [geometry, load_geometry_profile(legacy_path)]
        geometry = next(
            (
                candidate
                for candidate in candidates
                if any(
                    candidate.model_copy(update={"gpu_index": index}).checksum() == expected_checksum
                    for index in range(_MAX_GPU_INDEX + 1)
                )
            ),
            geometry,
        )
    # `gpu_index` do từng máy worker ghi đè và không ảnh hưởng hình học, nhưng nằm trong checksum của bundle: thử các
    # chỉ số GPU để vẫn kiểm được đúng từng thông số hình học còn lại.
    candidates = (geometry.model_copy(update={"gpu_index": index}) for index in range(_MAX_GPU_INDEX + 1))
    if not any(candidate.checksum() == expected_checksum for candidate in candidates):
        raise GeometryProfileMismatchError("thông số hình học của deployment khác bản đã dùng để dựng mesh của job")
    radius, height = geometry.capsule_radius_m, geometry.capsule_height_m
    mesh = read_collision_glb(resolve(collision_mesh))
    vertices = np.asarray(mesh.positions, dtype=float).reshape(-1, 3)
    # Chỉ đỉnh nằm trong tầm cao của robot mới chặn được nó; sàn (z ≈ 0) không tính.
    body = vertices[(vertices[:, 2] > 0.03) & (vertices[:, 2] < height)]
    centers = [pose["translation"] for pose in _load(metric_poses, resolve)["poses"]]
    blocked = sum(bool((np.hypot(body[:, 0] - center[0], body[:, 1] - center[1]) < radius).any()) for center in centers)
    return GeometryQuality(
        triangles=topology(mesh)["triangles"],
        camera_positions=len(centers),
        blocked_positions=blocked,
        robot_radius_m=radius,
        voxel_resolution_m=geometry.resolution_m,
    )
