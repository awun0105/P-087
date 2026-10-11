"""Phần dùng chung của các evaluator đối chứng trên TorWIC: pose ground truth, pose của job, ghi bản ghi.

**Chỉ dùng ở evaluator.** Ground truth (`traj_gt.txt`, `groundtruth_map.ply`) không bao giờ đi vào runtime sản phẩm
(DATASET_PLAYBOOK). Job được đọc qua registry của deployment đang cấu hình bằng biến môi trường, nên evaluator chạy
được trên máy local lẫn máy chủ có kho file từ xa.

Quy ước ghép frame: video demo được ghép từ các ảnh liên tiếp của một traversal, nên frame `i` của video là ảnh
`start + i` của traversal và dòng `start + i` của `traj_gt.txt`. `frame_id` của job là chỉ số frame gốc của video.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.reconstruction.lidar.camera_priors import camera_priors
from src.services.reconstruction.lidar.fusion import parse_trajectory
from src.services.reconstruction.lidar.package import parse_calibration

LABEL = re.compile(r"^[a-z0-9._-]+$")
ASSISTANCE = "evaluation_only_ground_truth"


@dataclass(frozen=True)
class PoseSet:
    """Pose `world_from_camera` của các frame đã đăng ký, theo thứ tự `frame_id`."""

    frame_ids: tuple[int, ...]
    centers: np.ndarray
    rotations: np.ndarray
    #: `world` (đã xác nhận tỉ lệ mét) hoặc `sfm` (chưa có đơn vị).
    frame: str


def _pose_set(payload: dict, frame: str) -> PoseSet:
    poses = sorted(payload["poses"], key=lambda item: item["frame_id"])
    return PoseSet(
        frame_ids=tuple(int(pose["frame_id"]) for pose in poses),
        centers=np.array([pose["translation"] for pose in poses], dtype=float),
        rotations=np.array([rotation_matrix(tuple(pose["rotation_xyzw"])) for pose in poses]),
        frame=frame,
    )


def job_poses(registry: ProjectRegistry, job_id: str) -> tuple[PoseSet, PoseSet | None]:
    """(pose hệ SfM của bước dựng pose, pose hệ mét sau khi xác nhận tỉ lệ hoặc None nếu job chưa hoàn tất)."""
    resolve = registry.runtime_resolver.require
    preview = registry.get_preview(job_id)
    sfm = _pose_set(json.loads(resolve(preview.camera_pose_ref).read_text()), "sfm")
    bundle = job_bundle(registry, registry.get_job(job_id))
    if bundle is None or not bundle.camera_pose_refs:
        return sfm, None
    return sfm, _pose_set(json.loads(resolve(bundle.camera_pose_refs[0]).read_text()), "world")


def ground_truth_poses(traversal: Path, calibration: Path, frame_ids: tuple[int, ...], start: int) -> PoseSet:
    """Pose camera ground truth của các frame đã đăng ký (quỹ đạo cảm biến × calibration camera ↔ LiDAR)."""
    trajectory = parse_trajectory((traversal / "traj_gt.txt").read_text(encoding="utf-8"))
    sensor_from_camera = parse_calibration(calibration.read_text(encoding="utf-8"), "torwic_txt")
    priors = camera_priors(trajectory, sensor_from_camera, tuple(start + frame_id for frame_id in frame_ids))
    return PoseSet(
        frame_ids=frame_ids,
        centers=np.array([prior.translation for prior in priors], dtype=float),
        rotations=np.array([rotation_matrix(prior.rotation_xyzw) for prior in priors]),
        frame="torwic_map",
    )


def percentiles(values: np.ndarray) -> dict[str, float]:
    """Trung vị và các phân vị dùng chung trong mọi bản ghi."""
    return {f"p{q}": round(float(np.percentile(values, q)), 4) for q in (50, 75, 90)}


def base_record(code: str, label: str, job_id: str, traversal: Path, start: int) -> dict:
    """Các trường mọi bản ghi đối chứng đều có."""
    if not LABEL.fullmatch(label):
        raise ValueError("nhãn chỉ gồm chữ thường, số, '.', '_', '-'")
    return {
        "benchmark": code,
        "label": label,
        "recorded_at": datetime.now(UTC).isoformat(),
        "job_id": job_id,
        "assistance": ASSISTANCE,
        "dataset": "TorWIC-SLAM",
        "traversal": traversal.name,
        "start_frame": start,
    }


def write_record(registry: ProjectRegistry, record: dict, out: Path | None) -> ProductArtifactRef:
    """Ghi bản ghi theo job (artifact bất biến, lượt kế tiếp) và, nếu có `out`, thêm một dòng JSONL tổng hợp."""
    job_id, code = record["job_id"], record["benchmark"]
    attempt = 1
    while registry.runtime_resolver.locate(f"artifact://jobs/{job_id}/benchmark/{code}/attempt-{attempt}.json"):
        attempt += 1
    payload = json.dumps({**record, "attempt": attempt}, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    reference = ProductArtifactRef(
        artifact_type="ReferenceBenchmark",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/benchmark/{code}/attempt-{attempt}.json",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="benchmark",
        job_id=job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return reference
