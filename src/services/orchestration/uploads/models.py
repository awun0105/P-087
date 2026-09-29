"""Model product-level cho video upload; không phải shared contract."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import ArtifactUri, Checksum, Identifier

VideoMediaType = Literal["video/mp4", "video/quicktime"]

#: Đuôi file được nhận → media type ghi vào InputManifest (PRD FR-01, Playbook §2.1).
VIDEO_EXTENSIONS: dict[str, VideoMediaType] = {".mp4": "video/mp4", ".mov": "video/quicktime"}


class UploadRecord(BaseModel):
    """Một video đã nhận đủ bytes, checksum xong, đang chờ được chọn để xử lý."""

    model_config = ConfigDict(extra="forbid")

    upload_id: Identifier
    original_name: str = Field(min_length=1, max_length=255)
    media_type: VideoMediaType
    size_bytes: int = Field(gt=0)
    checksum: Checksum
    artifact_uri: ArtifactUri
    received_at: datetime
    project_ids: list[Identifier] = Field(default_factory=list)
