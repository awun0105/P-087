"""SanitizationManifest: bản ghi của một lượt che khuôn mặt/biển số trên frame (AUD-18, ADR 0019).

Manifest mô tả đúng byte đã xuất: detector và trọng số nào, cấu hình nào, frame nào đã che vùng nào, frame
nào lỗi. Nó **không** phải kết luận "đã ẩn danh": không phát hiện gì không chứng minh video sạch, và trạng
thái `VERIFIED_ANONYMIZED` vẫn chỉ đến từ QA acceptance của cổng privacy hiện có.
"""

import hashlib
from typing import Literal, Self

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier

RegionKind = Literal["face", "license_plate"]
RegionOrigin = Literal["detected", "propagated", "manual"]


class SanitizedRegion(ContractModel):
    """Một vùng đã che trên một frame."""

    kind: RegionKind
    #: Hộp detector trả về (x1, y1, x2, y2) theo pixel frame gốc.
    box: tuple[float, float, float, float]
    #: Hộp đã tô thật sau khi nới và cắt về biên ảnh.
    applied_box: tuple[int, int, int, int]
    #: Điểm của detector; None cho vùng lan theo thời gian hoặc vùng reviewer thêm tay.
    score: float | None = Field(default=None, ge=0, le=1)
    origin: RegionOrigin

    @model_validator(mode="after")
    def _score_matches_origin(self) -> Self:
        if (self.origin == "detected") != (self.score is not None):
            raise ValueError("only detected regions carry a detector score")
        x1, y1, x2, y2 = self.applied_box
        if x1 < 0 or y1 < 0 or x2 < x1 or y2 < y1:
            raise ValueError("applied_box must be a non-negative, ordered pixel box")
        return self


class SanitizedFrame(ContractModel):
    """Một frame đã xử lý xong: checksum của byte gốc và byte đã xuất."""

    frame_name: Identifier
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    source_checksum: Checksum
    sanitized_checksum: Checksum
    regions: list[SanitizedRegion]

    @model_validator(mode="after")
    def _bytes_match_regions(self) -> Self:
        if not self.regions and self.sanitized_checksum != self.source_checksum:
            raise ValueError("a frame without regions must be a byte-identical copy of its source")
        if any(x2 > self.width or y2 > self.height for _, _, x2, y2 in (r.applied_box for r in self.regions)):
            raise ValueError("applied_box exceeds the frame")
        if self.sanitized_checksum == self.source_checksum and any(
            x2 > x1 and y2 > y1 for x1, y1, x2, y2 in (r.applied_box for r in self.regions)
        ):
            raise ValueError("a frame with a non-empty redaction cannot keep its source bytes")
        return self


class SanitizationDetector(ContractModel):
    """Danh tính detector: đổi bất kỳ giá trị nào là QA cũ không còn áp dụng."""

    name: Literal["egoblur-gen2"]
    package_version: Identifier
    torch_version: Identifier
    torchvision_version: Identifier
    face_weights_checksum: Checksum
    plate_weights_checksum: Checksum


class SanitizationConfig(ContractModel):
    """Cấu hình đã dùng cho lượt che."""

    face_threshold: float = Field(ge=0, le=1)
    license_plate_threshold: float = Field(ge=0, le=1)
    nms_iou: float = Field(ge=0, le=1)
    resize_short_edge: int = Field(gt=0)
    resize_max: int = Field(gt=0)
    expand_scale: float = Field(ge=1)
    propagate_radius: int = Field(ge=0)
    propagate_growth: float = Field(ge=0)
    fill_bgr: tuple[int, int, int]


def inventory_checksum(frames: list[SanitizedFrame]) -> str:
    """Checksum của toàn bộ bộ frame đã xuất: tên và checksum byte, theo thứ tự tên."""
    lines = "".join(
        f"{frame.frame_name}\t{frame.sanitized_checksum}\n" for frame in sorted(frames, key=lambda f: f.frame_name)
    )
    return f"sha256:{hashlib.sha256(lines.encode('utf-8')).hexdigest()}"


class SanitizationManifest(ContractModel):
    """Kết quả một lượt che trên bộ frame của một input."""

    schema_version: Literal["1.0"] = "1.0"
    #: Checksum của frame set nguồn (bản gốc, nằm trong vùng truy cập hạn chế).
    source_frame_set_checksum: Checksum
    detector: SanitizationDetector
    config: SanitizationConfig
    requested_frame_count: int = Field(gt=0)
    frames: list[SanitizedFrame]
    #: Frame không xử lý được; chúng không có file ở bản đã che và không được tính là đã phủ.
    failures: list[Identifier]
    sanitized_inventory_checksum: Checksum
    manifest_checksum: Checksum

    @model_validator(mode="after")
    def _coverage_is_accounted_for(self) -> Self:
        names = [frame.frame_name for frame in self.frames] + self.failures
        if len(names) != len(set(names)):
            raise ValueError("a frame appears more than once")
        if len(names) != self.requested_frame_count:
            raise ValueError("every requested frame must be either processed or listed as a failure")
        if self.sanitized_inventory_checksum != inventory_checksum(self.frames):
            raise ValueError("sanitized_inventory_checksum does not match the frames")
        return self

    @property
    def complete(self) -> bool:
        """Mọi frame yêu cầu đều đã xử lý. Chỉ bản đầy đủ mới được đưa sang QA và dispatch."""
        return not self.failures
