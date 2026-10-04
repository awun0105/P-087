"""Tỉ lệ mét và mặt sàn cho job có gói LiDAR (ADR 0009) — không cần người dùng chọn điểm.

Scene của job này được COLMAP dựng bám theo quỹ đạo (`adapters/colmap_priors.py`) nên hệ toạ độ của nó đã là hệ mét
của LiDAR, lệch một phép đồng dạng rất gần đơn vị. Module đo phép lệch đó (fit tâm camera cuối cùng vào quỹ đạo), lấy
mặt sàn từ bản ghi gói LiDAR, rồi ghi thành `MetricProposal` ở đúng chỗ bước xác nhận tỉ lệ (REC-06) vẫn đọc. Người
dùng xem độ lệch pose ↔ quỹ đạo và bấm xác nhận; không có bước chọn điểm.

Hai đoạn A–B, C–D và ba điểm sàn là điểm **hình học trên mặt sàn LiDAR**, sinh ra để đi qua đúng phép tính của REC-06;
chúng không phải số đo độc lập. Bằng chứng thật của tỉ lệ là `TrajectoryAlignment`.
"""

import hashlib
import math
from collections.abc import Callable
from pathlib import Path

import numpy as np

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_json_bytes
from src.services.reconstruction.alignment.similarity import SimilarityFit, fit_similarity, rotation_matrix
from src.services.reconstruction.lidar.camera_priors import camera_priors
from src.services.reconstruction.lidar.fusion import parse_trajectory
from src.services.reconstruction.lidar.package import LidarPackageRecord
from src.services.reconstruction.metric_proposal import (
    FloorProposal,
    MetricProposal,
    SegmentProposal,
    TrajectoryAlignment,
    _reference,
    proposal_uri,
)
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver

Point = tuple[float, float, float]
#: Vị trí (mét, theo hướng đi và phương ngang, tính từ dưới camera đầu) của A, B, C, D rồi ba điểm sàn: A–B dài
#: 2 m, C–D dài 1,5 m — đủ dài cho điều kiện của REC-06 (≥ 0,5 m, A–B không quá ngắn so với C–D).
_LAYOUT = ((1.5, 0.0), (3.5, 0.0), (1.5, 0.8), (3.0, 0.8), (1.2, -0.7), (3.8, -0.7), (2.5, 0.9))
_IDENTITY = (0.0, 0.0, 0.0, 1.0)


def _fit(final: list[Point], trajectory: list[Point]) -> SimilarityFit:
    """Phép đồng dạng scene → hệ quỹ đạo. Đường đi gần thẳng không xác định được phép quay: dùng phép đơn vị,
    đúng với cách scene được dựng (bám quỹ đạo), và độ lệch báo ra là độ lệch trực tiếp."""
    try:
        return fit_similarity(final, trajectory)
    except ValueError:
        residuals = [math.dist(a, b) for a, b in zip(final, trajectory, strict=True)]
        return SimilarityFit(
            scale=1.0,
            rotation_xyzw=_IDENTITY,
            translation=(0.0, 0.0, 0.0),
            pair_count=len(final),
            rms_residual=math.sqrt(sum(value**2 for value in residuals) / len(residuals)),
            max_residual=max(residuals),
            residuals=residuals,
        )


def _to_scene(fit: SimilarityFit, point: np.ndarray) -> Point:
    """Hệ quỹ đạo → hệ scene (nghịch đảo phép đồng dạng)."""
    local = rotation_matrix(fit.rotation_xyzw).T @ ((point - np.asarray(fit.translation)) / fit.scale)
    return (float(local[0]), float(local[1]), float(local[2]))


def _floor_layout(track: np.ndarray, floor_z: float) -> list[np.ndarray]:
    """Bảy điểm trên mặt sàn LiDAR, bố trí dọc hướng đi của camera (hệ quỹ đạo, Z hướng lên)."""
    start = track[0]
    ahead = next((point - start for point in track[1:] if np.linalg.norm((point - start)[:2]) >= 0.5), None)
    direction = np.array([1.0, 0.0, 0.0]) if ahead is None else np.array([ahead[0], ahead[1], 0.0])
    direction /= np.linalg.norm(direction)
    across = np.array([-direction[1], direction[0], 0.0])
    origin = np.array([start[0], start[1], floor_z])
    return [origin + forward * direction + side * across for forward, side in _LAYOUT]


def propose_metric_from_lidar(
    job_id: str,
    source_visual: ProductArtifactRef,
    lidar_package: ProductArtifactRef,
    resolve: Callable[[ProductArtifactRef], Path],
    writer: ArtifactWriter,
    locate: Callable[[str], Path | None],
) -> ProductArtifactRef:
    """Ghi (hoặc trả lại) đề xuất tỉ lệ + sàn từ gói LiDAR cho bản 3DGS `source_visual`."""
    existing = locate(proposal_uri(job_id, source_visual))
    if existing is not None:
        with existing.open("rb") as stream:
            return _reference(job_id, source_visual, "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest())
    record = LidarPackageRecord.model_validate_json(resolve(lidar_package).read_bytes())
    if record.job_id != job_id:
        raise ValueError("gói LiDAR thuộc job khác")
    pose_resolver = CameraPoseResolver(resolve, FrameSetResolver(resolve, resolve))
    visual = VisualResolver(resolve, pose_resolver).load(source_visual)
    poses = pose_resolver.load(visual.source_camera_poses)
    trajectory = parse_trajectory(resolve(record.trajectory_ref).read_text(encoding="utf-8"))
    registered = sorted(poses.poses, key=lambda pose: pose.frame_id)
    priors = camera_priors(trajectory, record.sensor_from_camera, tuple(pose.frame_id for pose in registered))
    final = [tuple(pose.translation) for pose in registered]
    target = [prior.translation for prior in priors]
    fit = _fit(final, target)  # type: ignore[arg-type]
    direct = sorted(math.dist(a, b) for a, b in zip(final, target, strict=True))
    track = np.asarray(target)
    path_length = float(np.linalg.norm(np.diff(track, axis=0), axis=1).sum())
    a, b, c, d, f1, f2, f3 = (_to_scene(fit, point) for point in _floor_layout(track, record.floor_z_m))
    scale = fit.scale
    proposal = MetricProposal(
        job_id=job_id,
        source_visual_checksum=source_visual.artifact_checksum,
        method="lidar_trajectory_alignment",
        model_checksum=lidar_package.artifact_checksum,
        scale_m_per_sfm_unit=scale,
        frame_dispersion=0.0,
        # Độ lệch pose so với chiều dài đường đi: cận trên thô của sai số tỉ lệ do pose lệch quỹ đạo.
        relative_uncertainty=fit.rms_residual / path_length if path_length > 0 else 0.0,
        frames_used=len(registered),
        pairs_used=len(registered),
        floor=FloorProposal(points=(f1, f2, f3), residual_m=0.0, support_points=record.floor_support_points),
        segments=SegmentProposal(
            point_a=a,
            point_b=b,
            distance_m=math.dist(a, b) * scale,
            check_a=c,
            check_b=d,
            check_distance_m=math.dist(c, d) * scale,
        ),
        alignment=TrajectoryAlignment(
            trajectory_origin=record.trajectory_origin,
            input_frames=len(poses.input_frame_ids),
            registered_frames=len(registered),
            offset_median_m=direct[len(direct) // 2],
            offset_p90_m=direct[min(len(direct) - 1, int(len(direct) * 0.9))],
            offset_max_m=direct[-1],
            path_length_m=path_length,
            lidar_package_checksum=lidar_package.artifact_checksum,
            camera_poses_checksum=visual.source_camera_poses.artifact_checksum,
        ),
    )
    payload = canonical_json_bytes(proposal)
    reference = _reference(job_id, source_visual, "sha256:" + hashlib.sha256(payload).hexdigest())
    writer.publish(reference, payload)
    return reference
