"""Chuẩn bị cho COLMAP dựng **bám theo quỹ đạo** (ADR 0009): model khởi đầu và ràng buộc vị trí.

Sau bước trích và ghép đặc trưng, COLMAP không tự dò pose (`mapper`) mà:

1. `point_triangulator` dựng điểm 3D tại pose đã cho (model TXT viết ở đây, chưa có điểm);
2. `pose_prior_mapper --input_path` tinh chỉnh pose và điểm với ràng buộc vị trí camera (bảng `pose_priors` ghi ở đây).

Kết quả nằm sẵn trong hệ mét của quỹ đạo và giữ được đủ ảnh thành một model. Đo trên Aisle_CW: xem ADR 0009.
Module chỉ đọc/ghi database và file text của COLMAP; mọi tính toán SfM vẫn do COLMAP làm.
"""

import hashlib
import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.reconstruction.rgb.pose.camera_pose import ColmapConfig

#: Model camera của COLMAP theo id trong database (đủ cho các model pipeline cho phép).
_CAMERA_MODELS = {0: "SIMPLE_PINHOLE", 1: "PINHOLE", 2: "SIMPLE_RADIAL", 3: "RADIAL", 4: "OPENCV"}
_OPENCV_MODEL_ID = 4
#: `SensorType::CAMERA` và `PosePrior::CoordinateSystem::CARTESIAN` của COLMAP 4.x.
_SENSOR_CAMERA = 0
_CARTESIAN = 1
_PRIOR_COLUMNS = {"corr_data_id", "corr_sensor_id", "corr_sensor_type", "position", "position_covariance", "gravity"}
PRIOR_MODEL_DIR = "prior_model"
TRIANGULATED_DIR = "prior_sparse"


class PosePriorError(ValueError):
    """Database COLMAP không nhận được ràng buộc pose (phiên bản khác, hoặc ảnh không khớp)."""


@dataclass(frozen=True)
class PosePrior:
    """`world_from_camera` của một ảnh trong hệ mét của quỹ đạo."""

    image_name: str
    translation: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]


@dataclass(frozen=True)
class PoseGuidance:
    """Đầu vào của chế độ bám quỹ đạo cho một lần chạy REC-03."""

    priors: tuple[PosePrior, ...]
    #: Nội tham số theo calibration: (rộng, cao lúc hiệu chuẩn, tham số `OPENCV` fx fy cx cy k1 k2 p1 p2).
    #: None = để COLMAP tự ước lượng. Ảnh đầu vào có thể đã thu nhỏ; tiêu cự và tâm ảnh được quy đổi theo tỉ lệ.
    calibration: tuple[int, int, tuple[float, ...]] | None
    #: Độ lệch chuẩn cho phép giữa tâm camera và quỹ đạo (mét). 5 cm bám LiDAR sát hơn 20 cm (lệch trung vị 8 so
    #: với 10–14 cm trên Aisle_CW) còn độ nét 3DGS chênh trong mức nhiễu (ADR 0009); PROPOSAL, chưa khoá.
    position_std_m: float = 0.05

    def checksum(self) -> str:
        """Định danh nội dung, đi vào khoá resume để sparse model cũ không bị dùng lại cho quỹ đạo khác."""
        payload = json.dumps(
            {
                "priors": [(p.image_name, p.translation, p.rotation_xyzw) for p in self.priors],
                "calibration": self.calibration,
                "position_std_m": self.position_std_m,
            },
            sort_keys=True,
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _scaled(calibration: tuple[int, int, tuple[float, ...]], width: int, height: int) -> list[float]:
    """Tham số `OPENCV` ở độ phân giải ảnh đầu vào; hệ số méo không đổi theo kích thước ảnh."""
    calibrated_width, calibrated_height, values = calibration
    scale_x, scale_y = width / calibrated_width, height / calibrated_height
    if len(values) != 8 or abs(scale_x - scale_y) > 0.01 * scale_x:
        raise PosePriorError(
            f"Ảnh {width}×{height} khác tỉ lệ khung hình của calibration {calibrated_width}×{calibrated_height}; "
            "video phải được quay bằng đúng camera đã hiệu chuẩn và không bị cắt"
        )
    fx, fy, cx, cy, *distortion = values
    return [fx * scale_x, fy * scale_y, cx * scale_x, cy * scale_y, *distortion]


def prepare_guidance(workspace: Path, guidance: PoseGuidance) -> None:
    """Viết model khởi đầu (`prior_model/`) và bảng `pose_priors` cho `database.db` đã có feature + match."""
    database = sqlite3.connect(workspace / "database.db")
    try:
        columns = {row[1] for row in database.execute("PRAGMA table_info(pose_priors)")}
        if not _PRIOR_COLUMNS <= columns:
            raise PosePriorError("COLMAP runtime không có bảng pose_priors dạng 4.x; cần COLMAP ≥ 4.0")
        images = {
            name: (image_id, camera_id)
            for image_id, name, camera_id in database.execute("SELECT image_id, name, camera_id FROM images")
        }
        by_name = {prior.image_name: prior for prior in guidance.priors}
        if set(images) != set(by_name):
            raise PosePriorError("Danh sách ảnh trong database khác danh sách pose từ quỹ đạo")
        cameras = database.execute("SELECT camera_id, model, width, height, params FROM cameras").fetchall()
        if len(cameras) != 1:
            raise PosePriorError("Chế độ bám quỹ đạo cần đúng một camera (single_camera)")
        camera_id, model_id, width, height, blob = cameras[0]
        if guidance.calibration is not None:
            parameters = _scaled(guidance.calibration, width, height)
            model_id = _OPENCV_MODEL_ID
            database.execute(
                "UPDATE cameras SET model=?, params=?, prior_focal_length=1 WHERE camera_id=?",
                (model_id, np.asarray(parameters, dtype="<f8").tobytes(), camera_id),
            )
        else:
            parameters = [float(value) for value in np.frombuffer(blob, dtype="<f8")]
        if model_id not in _CAMERA_MODELS:
            raise PosePriorError("Model camera của COLMAP không được hỗ trợ cho chế độ bám quỹ đạo")
        database.execute("DELETE FROM pose_priors")
        nan3, nan9 = struct.pack("<3d", *[float("nan")] * 3), struct.pack("<9d", *[float("nan")] * 9)
        lines = []
        for name in sorted(images):
            image_id, image_camera = images[name]
            prior = by_name[name]
            database.execute(
                "INSERT INTO pose_priors(corr_data_id, corr_sensor_id, corr_sensor_type, position, "
                "position_covariance, gravity, coordinate_system) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    image_id,
                    image_camera,
                    _SENSOR_CAMERA,
                    struct.pack("<3d", *prior.translation),
                    nan9,
                    nan3,
                    _CARTESIAN,
                ),
            )
            # COLMAP lưu `camera_from_world`: nghịch đảo của pose `world_from_camera`.
            rotation = rotation_matrix(prior.rotation_xyzw).T
            offset = [float(value) for value in -rotation @ np.asarray(prior.translation)]
            x, y, z, w = prior.rotation_xyzw
            lines.append(
                f"{image_id} {w!r} {-x!r} {-y!r} {-z!r} {offset[0]!r} {offset[1]!r} {offset[2]!r} {image_camera} {name}\n\n"
            )
        database.commit()
    finally:
        database.close()
    model = workspace / PRIOR_MODEL_DIR
    model.mkdir()
    text = " ".join(repr(value) for value in parameters)
    (model / "cameras.txt").write_text(f"{camera_id} {_CAMERA_MODELS[model_id]} {width} {height} {text}\n")
    (model / "images.txt").write_text("".join(lines))
    (model / "points3D.txt").write_text("")
    # COLMAP yêu cầu thư mục đích tồn tại sẵn.
    (workspace / TRIANGULATED_DIR).mkdir()


def guided_commands(config: ColmapConfig, guidance: PoseGuidance) -> list[list[str]]:
    """Hai lệnh thay cho `mapper`: dựng điểm tại pose đã cho, rồi tinh chỉnh có ràng buộc vị trí vào `sparse/0`."""
    sigma = repr(guidance.position_std_m)
    triangulate = ["point_triangulator", "--database_path", "database.db", "--image_path", "images"]
    triangulate += ["--input_path", PRIOR_MODEL_DIR, "--output_path", TRIANGULATED_DIR]
    triangulate += ["--clear_points", "1", "--refine_intrinsics", "0"]
    refine = ["pose_prior_mapper", "--database_path", "database.db", "--image_path", "images"]
    refine += ["--input_path", TRIANGULATED_DIR, "--output_path", "sparse/0"]
    refine += ["--Mapper.num_threads", str(config.num_threads), "--random_seed", str(config.random_seed)]
    if guidance.calibration is not None:
        # Nội tham số đến từ calibration của gói: giữ nguyên, không để bundle adjustment kéo lệch.
        refine += ["--Mapper.ba_refine_focal_length", "0", "--Mapper.ba_refine_extra_params", "0"]
    refine += ["--overwrite_priors_covariance", "1"]
    for axis in ("x", "y", "z"):
        refine += [f"--prior_position_std_{axis}", sigma]
    return [triangulate, refine]
