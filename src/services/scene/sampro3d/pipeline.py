"""Chạy SAMPro3D + SAM2 cho một scene: chuẩn bị prompt → runtime SAM2 (subprocess) → gộp instance.

Runtime SAM2 là tiến trình riêng (`data/scene_runtime`, PyTorch + sam2) để app không kéo torch
vào API/worker; giao tiếp bằng file request JSON + kết quả npz trong workspace.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import numpy as np

from src.models.contracts.floor_model import FloorModel
from src.services.process_control import ProcessTimeoutError, run_cancellable_process
from src.services.scene.geometric import Candidate, GeometricConfig, box_from_points
from src.services.scene.sampro3d.consolidate import Proposal, Sampro3dConfig, segment, select_prompts

RUNNER = Path(__file__).with_name("sam2_runner.py")
METHOD = "sampro3d_sam2_v1"


class Sampro3dInputError(ValueError):
    """Invalid scene input cannot recover by repeating the same SAM2 request."""


@dataclass(frozen=True)
class Sam2Runtime:
    """Đường dẫn runtime do deployment cấu hình (Settings), không default ngầm."""

    python: Path
    checkpoint: Path
    model_config: str = "configs/sam2.1/sam2.1_hiera_t.yaml"
    timeout_seconds: float = 1800

    def available(self) -> bool:
        """Có đủ python runtime và checkpoint để chạy."""
        return self.python.is_file() and self.checkpoint.is_file()


@dataclass(frozen=True)
class CameraFrame:
    """Một frame cho runtime: tham số camera COLMAP + pose world_from_camera + đường dẫn ảnh."""

    view: dict
    image_path: Path


def run_sam2(
    points: np.ndarray,
    frames: list[CameraFrame],
    runtime: Sam2Runtime,
    workspace: Path,
    *,
    floor_model: FloorModel,
    cancel_event: Event | None = None,
) -> Proposal:
    """Gọi runtime SAM2 trên toàn bộ frame; lỗi/timeout → ValueError có ngữ cảnh."""
    workspace.mkdir(parents=True, exist_ok=True)
    if floor_model.status == "uncertain":
        reason = floor_model.fallback_reason
        detail = f"mặt sàn chưa đủ tin cậy ({reason})"
        if reason == "excessive_noise" and floor_model.robust_noise_sigma_m is not None:
            detail += (
                f": độ nhiễu {floor_model.robust_noise_sigma_m * 100:.2f} cm"
                f" vượt ngưỡng {floor_model.profile.max_noise_sigma_m * 100:.2f} cm"
            )
        raise Sampro3dInputError(f"{detail}; cần kiểm tra dữ liệu, tỉ lệ và mốc sàn trước khi chạy lại")
    if not len(points):
        raise Sampro3dInputError("vùng tách vật không có điểm đủ điều kiện; cần kiểm tra vùng quan sát và độ đục")
    prompts = select_prompts(points, floor_model)
    if not len(prompts):
        raise Sampro3dInputError("không có điểm phía trên dải bảo vệ sàn để đặt prompt")
    np.savez(workspace / "points.npz", points=points.astype(np.float32), prompts=prompts)
    request = {
        "points_npz": str(workspace / "points.npz"),
        "config": runtime.model_config,
        "checkpoint": str(runtime.checkpoint.resolve()),
        "zbuffer_cell_px": 4,
        "depth_tolerance_m": 0.1,
        "batch": 64,
        "views": [{**frame.view, "image_path": str(frame.image_path)} for frame in frames],
    }
    (workspace / "request.json").write_text(json.dumps(request))
    output = workspace / "result.npz"
    with (workspace / "sam2.log").open("w") as log:
        try:
            returncode = run_cancellable_process(
                [
                    str(runtime.python),
                    str(RUNNER),
                    "--request",
                    str(workspace / "request.json"),
                    "--output",
                    str(output),
                ],
                cwd=workspace,
                timeout_seconds=runtime.timeout_seconds,
                output=log,
                cancel_event=cancel_event,
            )
        except ProcessTimeoutError as error:
            raise ValueError("SAM2 quá thời gian cho phép") from error
    if returncode != 0 or not output.is_file():
        raise ValueError(f"SAM2 runtime lỗi (exit {returncode}); xem sam2.log")
    return Proposal.load(str(output))


def candidates_from_instances(
    points: np.ndarray, instances: list[np.ndarray], limits: GeometricConfig = GeometricConfig()
) -> list[Candidate]:
    """Hộp OBB cho từng instance; bỏ khối cỡ không phải vật (tường/kệ dài, mảnh quá nhỏ)."""
    kept = []
    for members in instances:
        box = box_from_points(points[members], len(members))
        footprint = max(box.dimensions[0], box.dimensions[1])
        if not (limits.min_footprint_m <= footprint <= limits.max_footprint_m):
            continue
        if box.dimensions[2] > limits.max_object_height_m:
            continue
        kept.append(box)
    return kept[: limits.max_candidates]


def extract(
    points: np.ndarray,
    frames: list[CameraFrame],
    runtime: Sam2Runtime,
    workspace: Path,
    *,
    floor_model: FloorModel,
    cancel_event: Event | None = None,
) -> list[Candidate]:
    """Toàn bộ SAMPro3D: prompt → SAM2 → lọc/bỏ phiếu/gộp → hộp ứng viên."""
    proposal = run_sam2(points, frames, runtime, workspace, floor_model=floor_model, cancel_event=cancel_event)
    return candidates_from_instances(points, segment(proposal, points, floor_model, Sampro3dConfig()))
