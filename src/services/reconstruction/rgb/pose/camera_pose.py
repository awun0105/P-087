"""REC-03 nội bộ: SfM chưa có metric anchor; REC-06 mới canonicalize world."""

import hashlib
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, canonical_json_bytes
from src.services.reconstruction.rgb.frames.frame_set import frame_image_name

Finite = Annotated[float, Field(allow_inf_nan=False)]
Vector3 = tuple[Finite, Finite, Finite]
Quaternion = tuple[Finite, Finite, Finite, Finite]
CameraModel = Literal["SIMPLE_PINHOLE", "PINHOLE", "SIMPLE_RADIAL", "RADIAL", "OPENCV", "FULL_OPENCV"]
CAMERA_PARAMETER_COUNTS = {
    "SIMPLE_PINHOLE": 3,
    "PINHOLE": 4,
    "SIMPLE_RADIAL": 4,
    "RADIAL": 5,
    "OPENCV": 8,
    "FULL_OPENCV": 12,
}


class ColmapConfig(ContractModel):
    """Config explicit và hashable; threshold do caller khóa trước execution."""

    schema_version: Literal["1.0"] = "1.0"
    camera_model: CameraModel
    single_camera: bool
    use_gpu: bool
    num_threads: int = Field(gt=0)
    max_image_size: int = Field(ge=32)
    max_num_features: int = Field(ge=128)
    sequential_overlap: int = Field(ge=2)
    random_seed: int = Field(ge=0)
    min_registered_frames: int = Field(ge=2)
    min_registered_ratio: float = Field(gt=0, le=1, allow_inf_nan=False)
    vocab_tree: ProductArtifactRef | None = None
    # Omit unchanged defaults to keep existing schema-1.0 artifacts/checksums readable.
    matching_mode: Literal["sequential", "sequential_vocab_tree", "exhaustive"] = Field(
        default="sequential", exclude_if=lambda value: value == "sequential"
    )
    loop_detection_period: int = Field(default=10, ge=1, exclude_if=lambda value: value == 10)
    loop_detection_num_images: int = Field(default=50, ge=1, exclude_if=lambda value: value == 50)
    loop_detection_min_index_distance: int = Field(default=50, ge=0, exclude_if=lambda value: value == 50)

    def checksum(self) -> str:
        """Hash đầy đủ config, không thêm self-checksum field vào schema."""
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self)).hexdigest()


class CameraIntrinsics(ContractModel):
    """Giữ nguyên distortion model/parameter order do COLMAP công bố."""

    camera_id: int = Field(gt=0)
    model: CameraModel
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    parameters: list[Finite]

    @model_validator(mode="after")
    def _valid_parameters(self) -> "CameraIntrinsics":
        if len(self.parameters) != CAMERA_PARAMETER_COUNTS[self.model]:
            raise ValueError("COLMAP camera parameter count mismatch")
        focal_count = 2 if self.model in {"PINHOLE", "OPENCV", "FULL_OPENCV"} else 1
        if any(value <= 0 for value in self.parameters[:focal_count]):
            raise ValueError("COLMAP focal length must be positive")
        return self


class CameraPose(ContractModel):
    """parent_from_local: p_sfm_world = R * p_camera + translation."""

    frame_id: int = Field(ge=0)
    image_id: int = Field(gt=0)
    camera_id: int = Field(gt=0)
    image_name: str
    translation: Vector3
    rotation_xyzw: Quaternion

    @model_validator(mode="after")
    def _valid_rotation(self) -> "CameraPose":
        if not math.isclose(sum(x * x for x in self.rotation_xyzw), 1.0, abs_tol=1e-6):
            raise ValueError("camera quaternion must have unit norm")
        if self.image_name != frame_image_name(self.frame_id, Path(self.image_name)):
            raise ValueError("camera image name differs from normalized frame identity")
        return self


class SparseModelStats(ContractModel):
    """Thống kê model độc lập; không cộng ảnh từ các world frame khác nhau."""

    model_id: str = Field(pattern=r"^[0-9]+$")
    registered_frames: int = Field(ge=2)
    sparse_points: int = Field(gt=0)


class CameraPoseArtifact(ContractModel):
    """Manifest nội bộ cho REC-04/05/06, không phải canonical bundle REC-10."""

    schema_version: Literal["1.0"] = "1.0"
    source_frame_set: ProductArtifactRef
    frame_set_checksum: Checksum
    config: ColmapConfig
    config_checksum: Checksum
    colmap_version: str
    runtime_identity: str
    parent_frame: Literal["sfm_world"] = "sfm_world"
    camera_axes: Literal["x_right_y_down_z_forward"] = "x_right_y_down_z_forward"
    transform_semantics: Literal["parent_from_local"] = "parent_from_local"
    scale_status: Literal["arbitrary_sfm"] = "arbitrary_sfm"
    world_alignment_status: Literal["unconfirmed"] = "unconfirmed"
    input_frame_ids: list[int]
    unregistered_frame_ids: list[int]
    registered_ratio: Finite
    selected_model_id: str
    models: list[SparseModelStats]
    cameras: list[CameraIntrinsics]
    poses: list[CameraPose]
    sparse_files: dict[str, ProductArtifactRef]
    log_ref: ProductArtifactRef
    artifact_checksum: Checksum

    @model_validator(mode="after")
    def _validate_identity(self) -> "CameraPoseArtifact":
        ids = [pose.frame_id for pose in self.poses]
        if ids != sorted(set(ids)) or not set(ids) <= set(self.input_frame_ids):
            raise ValueError("camera poses must be unique, ordered and from input frame set")
        if self.input_frame_ids != sorted(set(self.input_frame_ids)) or not self.input_frame_ids:
            raise ValueError("invalid pose input frame inventory")
        if self.unregistered_frame_ids != sorted(set(self.input_frame_ids) - set(ids)):
            raise ValueError("unregistered inventory mismatch")
        if self.registered_ratio != len(ids) / len(self.input_frame_ids):
            raise ValueError("registered ratio mismatch")
        if len(ids) < self.config.min_registered_frames or self.registered_ratio < self.config.min_registered_ratio:
            raise ValueError("camera registration below configured threshold")
        camera_ids = [camera.camera_id for camera in self.cameras]
        if len(camera_ids) != len(set(camera_ids)) or any(p.camera_id not in camera_ids for p in self.poses):
            raise ValueError("pose references an absent or duplicate camera")
        self._validate_selection()
        if self.config.checksum() != self.config_checksum:
            raise ValueError("COLMAP config checksum mismatch")
        if canonical_content_checksum(self, "artifact_checksum") != self.artifact_checksum:
            raise ValueError("camera pose content checksum mismatch")
        return self

    def _validate_selection(self) -> None:
        if not self.models or len({m.model_id for m in self.models}) != len(self.models):
            raise ValueError("invalid sparse model inventory")
        best = min(self.models, key=lambda m: (-m.registered_frames, int(m.model_id)))
        if best.model_id != self.selected_model_id or best.registered_frames != len(self.poses):
            raise ValueError("selected sparse model does not match deterministic selection")
        if not {"cameras.txt", "images.txt", "points3D.txt"} <= self.sparse_files.keys():
            raise ValueError("sparse model files incomplete")
