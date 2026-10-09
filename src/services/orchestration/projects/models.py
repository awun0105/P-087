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
from src.services.orchestration.auth.models import Actor


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


class LidarAttachment(BaseModel):
    """Gói LiDAR người dùng gắn vào scene và hai lời khai contract bắt buộc cho đầu vào RGB + LiDAR."""

    model_config = ConfigDict(extra="forbid")

    upload_id: Identifier
    #: Nguồn pose có thể là đoán, chuẩn dataset hoặc TUM được người dùng cung cấp.
    trajectory_origin: Literal["estimated", "ground_truth", "supplied"]
    #: Video và LiDAR cùng một không gian, cùng lượt quay; đơn vị mét, trục Z hướng lên.
    same_scene_confirmed: bool

    @model_validator(mode="after")
    def _require_same_scene(self) -> "LidarAttachment":
        if not self.same_scene_confirmed:
            raise ValueError("cần xác nhận video và LiDAR cùng một không gian")
        return self


class UploadProjectInput(BaseModel):
    """Tạo scene/project từ một video đã upload, kèm lời khai nguồn dữ liệu."""

    model_config = ConfigDict(extra="forbid")

    upload_id: Identifier
    name: str = Field(min_length=1, max_length=200)
    attestation: SourceRightsAttestation
    #: Thông số xử lý theo file cấu hình chung; None → preset "tối thiểu cho chất lượng tốt".
    processing: dict[str, int | float | str] | None = None
    #: Tự động che khuôn mặt/biển số trên frame trước khi dựng 3D (AUD-18); chỉ nhận khi deployment có anonymizer.
    anonymize: bool = False
    #: Gói LiDAR đi kèm video (ADR 0009); None = job chỉ có video.
    lidar: "LidarAttachment | None" = None


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


class DemoBaseline(BaseModel):
    """Mốc "bản demo gốc" của một scene: revision SceneIR mà nút Khôi phục bản demo đưa scene trở về.

    Scene demo vẫn chỉnh sửa và tương tác được như scene thường; khôi phục chỉ tạo revision mới mang nội dung của mốc
    này (lịch sử revision chỉ tiến, không xoá), không chạy lại bước xử lý nào.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: Identifier
    scene_revision: Identifier
    marked_at: datetime
    marked_by: Actor | None = None


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
    #: New grouped-input evidence is omitted for legacy projects to preserve old JSON/CAS bytes.
    input_assembly_ref: ProductArtifactRef | None = Field(default=None, exclude_if=lambda value: value is None)
    input_resolution_ref: ProductArtifactRef | None = Field(default=None, exclude_if=lambda value: value is None)
    input_recipe_ref: ProductArtifactRef | None = Field(default=None, exclude_if=lambda value: value is None)
    input_runtime_registry_ref: ProductArtifactRef | None = Field(default=None, exclude_if=lambda value: value is None)
    input_video: InputVideoSummary | None = None
    created_at: datetime | None = None
    #: Người tạo scene; None với project cũ, fixture hoặc khi không bật đăng nhập.
    created_by: Actor | None = None
    #: Scene được đánh dấu là bản demo; không ghi vào JSON khi None để bản ghi cũ giữ nguyên bytes (CAS so bytes).
    demo_baseline: DemoBaseline | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def _bind_input_assembly_evidence(self) -> "ProjectRecord":
        references = (
            self.input_assembly_ref,
            self.input_resolution_ref,
            self.input_recipe_ref,
            self.input_runtime_registry_ref,
        )
        if any(reference is not None for reference in references) and any(
            reference is None for reference in references
        ):
            raise ValueError("grouped input evidence refs must be present as one complete set")
        for reference in references:
            if reference is not None and reference.job_id != self.project_id:
                raise ValueError("grouped input evidence must belong to the project namespace")
        return self
