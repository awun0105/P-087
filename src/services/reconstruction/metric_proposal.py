"""Đề xuất tỉ lệ mét và mặt sàn tự động cho video chỉ có RGB (ADR 0001 §2, AI Auto-Scale Assist).

Bộ ba của ADR: MoGe-2 đoán độ sâu mét (`adapters/moge_runner.py`, chạy trong runtime GPU qua
subprocess) → điểm thưa COLMAP cho cặp (độ sâu SfM, độ sâu mét) → giải một hệ số tỉ lệ. Kết quả là
artifact `MetricScaleProposal` trạng thái **ESTIMATED**: Studio điền sẵn vào bước xác nhận REC-06,
người dùng chấp nhận hoặc sửa bằng số đo thật. Đề xuất không bao giờ tự thành bản xác nhận.

Đây là public port cho PRODUCT: worker gọi `propose_metric` sau khi có 3DGS; API đọc bằng
`load_proposal`. Không cấu hình runtime MoGe thì không có đề xuất và luồng nhập tay giữ nguyên.
"""

import hashlib
import json
import logging
import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.manifests import StageId
from src.services.reconstruction.rgb.canonical.auto_scale import (
    align_scale,
    propose_floor,
    read_sparse,
    rotation_matrix,
    sparse_samples,
)
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver

logger = logging.getLogger(__name__)
Point = tuple[float, float, float]
RUNNER = Path(__file__).parent / "adapters" / "moge_runner.py"
#: Sai số chuẩn của trung vị so với độ phân tán từng phiếu (phân phối chuẩn): 1,2533 / √n.
_MEDIAN_STANDARD_ERROR = 1.2533
#: Đoạn A–B, C–D đề xuất phải dài ít nhất mức REC-06 yêu cầu (0,5 m) thì mới dùng được để xác nhận.
_MIN_SEGMENT_M = 0.5


class MogeSettings(BaseSettings):
    """Runtime MoGe-2 của worker; để trống `python` hoặc `model` nghĩa là không bật đề xuất tự động."""

    python: Path | None = None
    model: Path | None = None
    device: str = "cuda"
    timeout_seconds: float = Field(default=1800, gt=0, allow_inf_nan=False)
    #: Mỗi ảnh là một phiếu cho tỉ lệ; sai số của trung vị giảm theo căn số ảnh nên dùng nhiều ảnh.
    max_frames: int = Field(default=60, ge=3)
    max_points: int = Field(default=400, ge=20)
    model_config = SettingsConfigDict(env_prefix="REC06_MOGE_", extra="ignore")


class FloorProposal(BaseModel):
    """Mặt sàn đề xuất trong hệ gốc của file 3DGS (SfM): ba điểm trên sàn."""

    model_config = ConfigDict(extra="forbid")

    points: tuple[Point, Point, Point]
    residual_m: float = Field(ge=0)
    support_points: int = Field(ge=1)


class SegmentProposal(BaseModel):
    """Hai đoạn trên sàn để điền bước xác nhận; khoảng cách = độ dài SfM × tỉ lệ đề xuất."""

    model_config = ConfigDict(extra="forbid")

    point_a: Point
    point_b: Point
    distance_m: float = Field(gt=0)
    check_a: Point
    check_b: Point
    check_distance_m: float = Field(gt=0)


class MetricProposal(BaseModel):
    """Ước lượng tự động, chưa được ai xác nhận; mọi con số đi kèm độ không chắc chắn."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["MetricScaleProposal"] = "MetricScaleProposal"
    status: Literal["ESTIMATED"] = "ESTIMATED"
    job_id: str
    source_visual_checksum: str
    method: Literal["moge2_sparse_depth_scale_only"] = "moge2_sparse_depth_scale_only"
    #: Checksum của trọng số mô hình đã dùng (đổi mô hình là đổi đề xuất).
    model_checksum: str
    scale_m_per_sfm_unit: float = Field(gt=0)
    #: Độ phân tán tương đối của tỉ lệ giữa các ảnh (1,4826·MAD / trung vị).
    frame_dispersion: float = Field(ge=0)
    #: Sai số chuẩn tương đối của trung vị = 1,2533 · độ phân tán / √số ảnh; chỉ phản ánh nhiễu giữa
    #: các ảnh, không gồm sai lệch có hệ thống của mô hình.
    relative_uncertainty: float = Field(ge=0)
    frames_used: int = Field(ge=1)
    pairs_used: int = Field(ge=1)
    floor: FloorProposal | None = None
    segments: SegmentProposal | None = None


def proposal_uri(job_id: str, source_visual: ProductArtifactRef) -> str:
    """URI cố định theo bản 3DGS: API tìm được đề xuất mà không cần ghi vào JobManifest."""
    digest = source_visual.artifact_checksum.removeprefix("sha256:")
    return f"artifact://jobs/{job_id}/rec06/auto/{digest}/metric_proposal.json"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def _reference(job_id: str, source_visual: ProductArtifactRef, checksum: str) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type="MetricScaleProposal",
        schema_version="1.0",
        artifact_uri=proposal_uri(job_id, source_visual),
        artifact_checksum=checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )


def load_proposal(
    job_id: str, source_visual: ProductArtifactRef, locate: Callable[[str], Path | None]
) -> MetricProposal | None:
    """Đề xuất của đúng bản 3DGS này; None khi worker chưa/không tạo. Bản ghi lệch job/visual bị từ chối."""
    path = locate(proposal_uri(job_id, source_visual))
    if path is None:
        return None
    proposal = MetricProposal.model_validate_json(path.read_bytes())
    if proposal.job_id != job_id or proposal.source_visual_checksum != source_visual.artifact_checksum:
        raise ValueError("đề xuất tỉ lệ thuộc job hoặc bản 3DGS khác")
    return proposal


def _point(values: np.ndarray) -> Point:
    return (float(values[0]), float(values[1]), float(values[2]))


def _run_moge(request: dict, workspace: Path, settings: MogeSettings) -> dict[str, np.ndarray]:
    """Chạy runner trong runtime GPU; log nằm trong workspace, lỗi/timeout thành ValueError có ngữ cảnh."""
    workspace.mkdir(parents=True, exist_ok=True)
    request_path, result_path = workspace / "moge.request.json", workspace / "moge.result.npz"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    command = [str(settings.python), str(RUNNER), "--request", str(request_path), "--result", str(result_path)]
    with (workspace / "moge.log").open("w") as log:
        try:
            completed = subprocess.run(  # noqa: S603 - lệnh cố định, đường dẫn từ Settings
                command, stdout=log, stderr=subprocess.STDOUT, timeout=settings.timeout_seconds, check=False
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("MoGe quá thời gian cấu hình") from error
        except OSError as error:
            raise ValueError("Không chạy được runtime MoGe") from error
    if completed.returncode != 0 or not result_path.is_file():
        raise ValueError(f"MoGe lỗi (exit {completed.returncode}); xem moge.log của attempt")
    with np.load(result_path) as data:
        return {key: data[key] for key in data.files}


def propose_metric(
    job_id: str,
    source_visual: ProductArtifactRef,
    resolve: Callable[[ProductArtifactRef], Path],
    writer: ArtifactWriter,
    locate: Callable[[str], Path | None],
    workspace: Path,
    settings: MogeSettings | None = None,
) -> ProductArtifactRef | None:
    """Tạo (hoặc trả lại) đề xuất cho bản 3DGS `source_visual`; None khi không bật hoặc không đủ dữ liệu.

    Không đủ cặp độ sâu hợp lệ thì **không** công bố tỉ lệ. Lỗi runtime ném ValueError: nơi gọi (worker)
    ghi log và để job đi tiếp theo luồng nhập tay.
    """
    settings = settings or MogeSettings()
    if settings.python is None or settings.model is None:
        return None
    existing = locate(proposal_uri(job_id, source_visual))
    if existing is not None:
        load_proposal(job_id, source_visual, locate)
        return _reference(job_id, source_visual, _sha256(existing))
    frames = FrameSetResolver(resolve, resolve)
    pose_resolver = CameraPoseResolver(resolve, frames)
    visual = VisualResolver(resolve, pose_resolver).load(source_visual)
    poses = pose_resolver.load(visual.source_camera_poses)
    sparse = read_sparse(
        pose_resolver.require(poses.sparse_files["points3D.txt"]),
        pose_resolver.require(poses.sparse_files["images.txt"]),
    )
    samples = sparse_samples(poses.poses, sparse, max_frames=settings.max_frames, max_points=settings.max_points)
    if not samples:
        logger.info("Không có ảnh đủ điểm thưa để đề xuất tỉ lệ job=%s", job_id)
        return None
    images = {frame_id: path for frame_id, path, _ in frames.materialize(frames.load(poses.source_frame_set))}
    cameras = {camera.camera_id: camera for camera in poses.cameras}
    camera_of = {pose.frame_id: cameras[pose.camera_id] for pose in poses.poses}
    request = {
        "model": str(settings.model),
        "device": settings.device,
        "frames": [
            {
                "frame_id": sample.frame_id,
                "image": str(images[sample.frame_id]),
                # Tiêu cự ngang là tham số đầu của mọi camera model COLMAP mà pipeline dùng.
                "fov_x_degrees": math.degrees(
                    2 * math.atan(camera_of[sample.frame_id].width / (2 * camera_of[sample.frame_id].parameters[0]))
                ),
                "pixels": sample.pixels.tolist(),
            }
            for sample in samples
        ],
    }
    result = _run_moge(request, workspace, settings)
    pairs, points, normals = [], [], []
    for sample in samples:
        key = str(sample.frame_id)
        valid = result[f"{key}_valid"].astype(bool)
        pairs.append((sample.depth_sfm[valid], result[f"{key}_depth"][valid].astype(float)))
        points.append(sample.points[valid])
        normals.append(result[f"{key}_normal"][valid].astype(float) @ sample.rotation.T)
    estimate = align_scale(pairs)
    if estimate is None:
        logger.info("Không đủ cặp độ sâu hợp lệ để đề xuất tỉ lệ job=%s", job_id)
        return None
    centers = np.array([pose.translation for pose in poses.poses])
    down = np.mean([rotation_matrix(pose.rotation_xyzw)[:, 1] for pose in poses.poses], axis=0)
    floor = propose_floor(np.vstack(points), np.vstack(normals), centers, down, estimate.scale_m_per_sfm_unit)
    floor_model, segments = None, None
    if floor is not None:
        scale = estimate.scale_m_per_sfm_unit
        distance = float(np.linalg.norm(floor.segment_ab[1] - floor.segment_ab[0]) * scale)
        check = float(np.linalg.norm(floor.segment_cd[1] - floor.segment_cd[0]) * scale)
        p1, p2, p3 = floor.floor_points
        floor_model = FloorProposal(
            points=(_point(p1), _point(p2), _point(p3)),
            residual_m=floor.residual_m,
            support_points=floor.support_points,
        )
        if distance >= _MIN_SEGMENT_M and check >= _MIN_SEGMENT_M:
            segments = SegmentProposal(
                point_a=_point(floor.segment_ab[0]),
                point_b=_point(floor.segment_ab[1]),
                distance_m=distance,
                check_a=_point(floor.segment_cd[0]),
                check_b=_point(floor.segment_cd[1]),
                check_distance_m=check,
            )
    proposal = MetricProposal(
        job_id=job_id,
        source_visual_checksum=source_visual.artifact_checksum,
        model_checksum=_sha256(settings.model),
        scale_m_per_sfm_unit=estimate.scale_m_per_sfm_unit,
        frame_dispersion=estimate.dispersion,
        relative_uncertainty=_MEDIAN_STANDARD_ERROR * estimate.dispersion / math.sqrt(estimate.frames_used),
        frames_used=estimate.frames_used,
        pairs_used=estimate.pairs_used,
        floor=floor_model,
        segments=segments,
    )
    payload = canonical_json_bytes(proposal)
    reference = _reference(job_id, source_visual, "sha256:" + hashlib.sha256(payload).hexdigest())
    writer.publish(reference, payload)
    return reference
