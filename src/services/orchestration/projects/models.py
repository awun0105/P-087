"""Input và state model của lớp project thuộc EX-PRODUCT.

Các model ở đây là **product-level**, không phải shared contract. Chúng chỉ mô tả
dữ liệu mà API nhận vào và trạng thái project mà API trả ra.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.contracts.artifacts import Checksum, Identifier, JsonObject, ProductArtifactRef
from src.models.contracts.manifests import PrivacyValidationReport, SourceType


class DataOrigin(StrEnum):
    """Ba nhóm dữ liệu MVP được phép dùng — PRD NFR-05."""

    PUBLIC_OR_SYNTHETIC = "public_or_synthetic"
    SELF_COLLECTED_NO_PII = "self_collected_no_pii"
    ANONYMIZED = "anonymized"


class SourceRightsAttestation(BaseModel):
    """Lời khai nguồn dữ liệu của người tạo project.

    PRD NFR-05: "Việc có quyền sử dụng dữ liệu không thay thế yêu cầu ẩn danh."
    Vì vậy `rights_to_use_confirmed` và `anonymization_confirmed` là hai field
    độc lập, không được gộp thành một câu xác nhận duy nhất.
    """

    model_config = ConfigDict(extra="forbid")

    data_origin: DataOrigin
    declared_owner: str = Field(min_length=1, max_length=200)
    declared_purpose: str = Field(min_length=1, max_length=500)
    rights_to_use_confirmed: bool
    anonymization_confirmed: bool
    retention_acknowledged: bool

    @model_validator(mode="after")
    def _require_complete_attestation(self) -> "SourceRightsAttestation":
        missing = [
            label
            for confirmed, label in (
                (self.rights_to_use_confirmed, "rights_to_use_confirmed"),
                (self.anonymization_confirmed, "anonymization_confirmed"),
                (self.retention_acknowledged, "retention_acknowledged"),
            )
            if not confirmed
        ]
        if missing:
            raise ValueError(f"attestation chưa đầy đủ: {', '.join(missing)}")
        return self


class ProjectCreateInput(BaseModel):
    """Yêu cầu tạo project, kèm input manifest đã có checksum."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    input_manifest_checksum: Checksum
    attestation: SourceRightsAttestation


class JobCreateInput(BaseModel):
    """Yêu cầu tạo job trong một project."""

    model_config = ConfigDict(extra="forbid")

    project_id: Identifier
    scene_revision: Identifier = "rev-001"


class InputVideoSummary(BaseModel):
    """Thông tin hiển thị của video đã upload; identity thật nằm ở InputManifest."""

    model_config = ConfigDict(extra="forbid")

    original_name: str = Field(min_length=1, max_length=255)
    media_type: Literal["video/mp4", "video/quicktime"]
    size_bytes: int = Field(gt=0)


class ProjectRecord(BaseModel):
    """Trạng thái project mà API trả ra. Không phải shared contract."""

    model_config = ConfigDict(extra="forbid")

    project_id: Identifier
    name: str
    source_type: SourceType
    input_manifest_checksum: Checksum
    source_rights_attestation: JsonObject
    privacy_report: PrivacyValidationReport
    #: `self_attested` chỉ gán cho project tạo từ upload khi deployment bật chế độ
    #: MVP (Settings.product_privacy_mode); project cũ/fixture giữ cổng QA.
    privacy_mode: Literal["qa_verified", "self_attested"] = "qa_verified"
    #: InputManifest đã publish (bytes checksum) để worker chuẩn bị input video.
    input_manifest_ref: ProductArtifactRef | None = None
    input_video: InputVideoSummary | None = None
    created_at: datetime | None = None
