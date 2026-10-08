"""Model product-level cho upload (video, PLY 3DGS, ZIP, LiDAR); không phải shared contract."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import ArtifactUri, Checksum, Identifier
from src.models.contracts.video_preparation import ClientVideoPreparationManifest, ServerVideoPreparationVerification
from src.services.orchestration.auth.models import Actor
from src.services.reconstruction import InputDetection, InputKind

VideoMediaType = Literal["video/mp4", "video/quicktime"]
UploadMediaType = Literal[
    "video/mp4", "video/quicktime", "application/x-ply", "application/x-sog", "application/x-pcd", "application/zip"
]

#: Đuôi file video → media type ghi vào InputManifest (PRD FR-01, Playbook §2.1).
VIDEO_EXTENSIONS: dict[str, VideoMediaType] = {".mp4": "video/mp4", ".mov": "video/quicktime"}
#: Mọi đuôi file được nhận (ADR 0004). Đuôi chỉ để chọn media type ban đầu; loại thật
#: do server nhận diện theo bytes và phải khớp `KIND_MEDIA_TYPES`.
UPLOAD_EXTENSIONS: dict[str, UploadMediaType] = {
    **VIDEO_EXTENSIONS,
    ".ply": "application/x-ply",
    ".sog": "application/x-sog",
    ".pcd": "application/x-pcd",
    ".zip": "application/zip",
}
KIND_MEDIA_TYPES: dict[str, frozenset[str]] = {
    "rgb_video": frozenset({"video/mp4", "video/quicktime"}),
    "gaussian_ply": frozenset({"application/x-ply"}),
    "gaussian_ply_colmap": frozenset({"application/zip"}),
    "gaussian_sog": frozenset({"application/x-sog"}),
    # ADR 0009: LiDAR đi kèm video — luôn là gói ZIP có quỹ đạo + calibration + thời điểm frame.
    "registered_lidar": frozenset({"application/zip"}),
    "lidar_scan_sequence": frozenset({"application/zip"}),
}
UNSUPPORTED_EXTENSION = (
    "Hỗ trợ video .mp4/.mov; scene 3DGS .ply, .sog hoặc .zip (PLY 3DGS + model COLMAP); "
    "gói LiDAR .zip (scan .pcd hoặc đám mây đã đăng ký, kèm quỹ đạo + calibration + thời điểm frame)"
)


class UploadRecord(BaseModel):
    """Một file đã nhận đủ bytes, checksum xong và nhận diện loại, chờ được chọn để xử lý.

    Record cũ (trước ADR 0004) không có `input_kind`: chỉ nhận video nên mặc định video.
    """

    model_config = ConfigDict(extra="forbid")

    upload_id: Identifier
    original_name: str = Field(min_length=1, max_length=255)
    media_type: UploadMediaType
    size_bytes: int = Field(gt=0)
    checksum: Checksum
    artifact_uri: ArtifactUri
    received_at: datetime
    project_ids: list[Identifier] = Field(default_factory=list)
    input_kind: InputKind = "rgb_video"
    detection: InputDetection | None = None
    #: Người tải file lên; None với record cũ hoặc khi không bật đăng nhập.
    uploaded_by: Actor | None = None
    #: Client declaration is untrusted until a server verification report is attached.
    video_preparation_manifest: ClientVideoPreparationManifest | None = None
    video_preparation: ServerVideoPreparationVerification | None = None


UploadSessionStatus = Literal["UPLOADING", "VERIFYING", "READY", "FAILED"]


class UploadSession(BaseModel):
    """Phiên upload thẳng từ trình duyệt lên kho file (multipart, nối lại được).

    `multipart_id` là id nội bộ của kho file, không trả cho client. Chỉ thành
    `UploadRecord` khi server tự tính checksum/kích thước xong (`READY`).
    """

    model_config = ConfigDict(extra="forbid")

    upload_id: Identifier
    original_name: str = Field(min_length=1, max_length=255)
    media_type: UploadMediaType
    size_bytes: int = Field(gt=0)
    part_size: int = Field(gt=0)
    part_count: int = Field(ge=1, le=10000)
    artifact_uri: ArtifactUri
    multipart_id: str = Field(min_length=1, repr=False)
    status: UploadSessionStatus
    error: str | None = None
    created_at: datetime
    uploaded_by: Actor | None = None
