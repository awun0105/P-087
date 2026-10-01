"""DTO của product API (EX-PRODUCT).

**Bất di bất dịch:** response chỉ mang `artifact://jobs/<job_id>/<path>`, checksum
và `data_class`. Không bao giờ trả `artifact_root`, `Path`, hay tên file trên đĩa.
`ProductArtifactRef` đã ép điều đó ở tầng contract nên response tái dùng thẳng nó
thay vì dựng model song song.

Request model nằm ở tầng service (`orchestration.projects.models`) vì đó là input
của domain, không phải của HTTP — route import thẳng từ đó, không re-export ở đây.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import Checksum, Identifier, JsonObject, ProductArtifactRef
from src.models.contracts.manifests import (
    JobManifest,
    PrivacyInspectionScope,
    PrivacyResult,
    SourceType,
)
from src.models.contracts.release import ApprovalRecord
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import ValidationReport
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.models import InputVideoSummary, ProjectRecord
from src.services.orchestration.projects.privacy import project_block_reason
from src.services.orchestration.scene.models import SceneEditResult, SceneRevision, VisualBinding

__all__ = [
    "ApiErrorResponse",
    "ApiModel",
    "ArtifactListResponse",
    "JobAttemptListResponse",
    "JobCreateRequest",
    "JobListResponse",
    "PrivacyStateResponse",
    "ProjectListResponse",
    "ProjectResponse",
    "ReviewStateResponse",
    "SceneEditResponse",
    "SceneResponse",
    "ValidationStateResponse",
    "privacy_state",
    "project_response",
    "review_state",
    "scene_edit_response",
    "ObjectifyRequest",
    "scene_response",
    "validation_state",
]


class ApiModel(BaseModel):
    """Base DTO nghiêm ngặt cho ranh giới HTTP của product."""

    model_config = ConfigDict(extra="forbid")


class JobCreateRequest(ApiModel):
    """Body tạo job. `project_id` lấy từ path nên không lặp lại ở đây."""

    scene_revision: Identifier = "rev-001"


class PrivacyStateResponse(ApiModel):
    """Privacy state cho PRODUCT-02 và PRODUCT-05 hiển thị."""

    result: PrivacyResult
    input_manifest_checksum: Checksum
    inspection_scope: PrivacyInspectionScope
    unresolved_finding_count: int = Field(ge=0)
    dispatch_allowed: bool
    block_reason: str | None = None
    #: `self_attested`: MVP — người upload tự xác nhận, chưa có QA kiểm tra.
    privacy_mode: Literal["qa_verified", "self_attested"] = "qa_verified"


class ProjectResponse(ApiModel):
    """Project kèm input identity, attestation và privacy state."""

    project_id: Identifier
    name: str
    source_type: SourceType
    input_manifest_checksum: Checksum
    source_rights_attestation: JsonObject
    privacy: PrivacyStateResponse
    input_video: InputVideoSummary | None = None
    created_at: datetime | None = None


class ProjectListResponse(ApiModel):
    """Danh sách project."""

    projects: list[ProjectResponse]


class JobListResponse(ApiModel):
    """Danh sách job của một project."""

    project_id: Identifier
    jobs: list[JobManifest]


class JobAttemptListResponse(ApiModel):
    """Lịch sử attempt của một job (PRODUCT-02)."""

    job_id: Identifier
    attempts: list[JobAttemptRecord]


class ArtifactListResponse(ApiModel):
    """Artifact product được phép thấy, kèm số ref đã bị loại."""

    job_id: Identifier
    artifacts: list[ProductArtifactRef]
    excluded_artifact_count: int = Field(ge=0)


class SceneResponse(ApiModel):
    """SceneIR hiện tại + ref để client bind checksum (PRODUCT-06).

    SceneIR đi kèm `scene_uri`/`scene_checksum` của bản đã publish, nên UI đối
    chiếu được nội dung đang vẽ với đúng artifact trên đĩa. Phần tử thay đổi được
    là `scene_revision`, không phải `scene_id`.
    """

    job_id: Identifier
    scene_id: Identifier
    scene_revision: Identifier
    scene_uri: str
    scene_checksum: Checksum
    supersedes_revision: Identifier | None = None
    scene: SceneIR
    visual: VisualBinding


class SceneEditResponse(ApiModel):
    """Kết quả một lần sửa transform: revision mới đã persist."""

    job_id: Identifier
    previous_scene_revision: Identifier
    scene_revision: Identifier
    scene_uri: str
    scene_checksum: Checksum
    scene: SceneIR


class ValidationStateResponse(ApiModel):
    """Trạng thái validation của job (PRODUCT-05 màn hình validation).

    `isaac_runtime_proof` là false khi `environment_versions` chưa xác nhận được
    Isaac/GPU. Không có nó thì một report PASS của fixture rất dễ bị đọc thành
    "đã chạy simulator thật".
    """

    job_id: Identifier
    report: ValidationReport
    report_checksum_verified: bool
    isaac_runtime_proof: bool


class ReviewStateResponse(ApiModel):
    """Trạng thái review của job (PRODUCT-05 màn hình mock review).

    `synthetic_authorization` là true khi approval đến từ fixture. Đây **không**
    phải uỷ quyền của Reviewer thật, nên UI phải hiện cờ này chứ không được chỉ
    hiển thị "APPROVED".
    """

    job_id: Identifier
    approval: ApprovalRecord
    synthetic_authorization: bool
    note: str


class ApiErrorResponse(ApiModel):
    """Envelope lỗi thống nhất, cùng shape với lỗi gốc của FastAPI."""

    detail: str


class ObjectActionRequest(ApiModel):
    """Body cho các object action: confirm/ignore/hide/delete/rename (PRODUCT-07)."""

    expected_scene_revision: Identifier
    active: bool | None = None
    name: str | None = None
    # action = label (ADR 0007): nhãn lớp; khối lượng người dùng nhập (bỏ trống = mặc định của nhãn).
    semantic_class: str | None = Field(default=None, max_length=64)
    mass_kg: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class ObjectifyRequest(ApiModel):
    """Body yêu cầu dựng lại tập vật trên đúng revision đang hiển thị.

    `objectify` = chạy lại tách theo vật; `boxes` = dùng hộp ứng viên (người dùng chọn lùi).
    """

    expected_scene_revision: Identifier
    mode: Literal["objectify", "boxes"] = "objectify"


class AddCatalogObjectRequest(ApiModel):
    """Body thêm vật từ danh mục asset Isaac (ADR 0007); `position_xyz` là điểm đặt trên sàn."""

    expected_scene_revision: Identifier
    family: str = Field(min_length=1, max_length=128)
    position_xyz: tuple[float, float, float]
    name: str = ""


class RestoreRevisionRequest(ApiModel):
    """Body hoàn tác về một revision cũ (publish thành revision kế tiếp)."""

    expected_scene_revision: Identifier
    target_revision: Identifier


class CatalogEntryResponse(ApiModel):
    """Một họ asset đặt được."""

    family: str
    semantic_class: str | None
    size_xyz_m: tuple[float, float, float]
    dynamic: bool
    default_mass_kg: float | None


class SceneCatalogResponse(ApiModel):
    """Danh mục nhãn và asset cho Studio."""

    classes: list[str]
    entries: list[CatalogEntryResponse]
    physics_note: str


class LabelSuggestionResponse(ApiModel):
    """Nhãn gợi ý cho một vật theo kích thước; người dùng phải xác nhận."""

    object_id: Identifier
    suggestions: list[str]
    basis: str


class AddObjectRequest(ApiModel):
    """Body thêm user-added obstacle (PRODUCT-07A)."""

    expected_scene_revision: Identifier
    name: str
    origin: str = "user_added"
    dimensions_xyz_m: tuple[float, float, float]
    collider_type: str = "AABB"
    position_xyz: tuple[float, float, float]


class ReviewActionRequest(ApiModel):
    """Body submit/approve/reject review (PRODUCT-10)."""

    reviewer_id: Identifier
    reason: str | None = None
    candidate_checksum: Checksum
    validation_report_checksum: Checksum
    accepted_warning_ids: list[str] = []


class ReleaseRequest(ApiModel):
    """Body seal exact candidate → ReleaseManifest (PRODUCT-11)."""

    approval_record_checksum: Checksum
    candidate_checksum: Checksum
    validation_report_checksum: Checksum


class ReleaseResponse(ApiModel):
    """Kết quả release fake stub."""

    release_id: Identifier
    release_checksum: Checksum
    released_at: str


def privacy_state(record: ProjectRecord) -> PrivacyStateResponse:
    """Chiếu privacy report + chế độ dispatch của project thành state mà UI tiêu thụ."""
    report = record.privacy_report
    reason = project_block_reason(record)
    return PrivacyStateResponse(
        result=report.result,
        input_manifest_checksum=report.input_manifest_checksum,
        inspection_scope=report.inspection_scope,
        unresolved_finding_count=len(report.unresolved_findings),
        dispatch_allowed=reason is None,
        block_reason=reason,
        privacy_mode=record.privacy_mode,
    )


def project_response(record: ProjectRecord) -> ProjectResponse:
    """Chiếu ProjectRecord thành DTO trả ra ngoài."""
    return ProjectResponse(
        project_id=record.project_id,
        name=record.name,
        source_type=record.source_type,
        input_manifest_checksum=record.input_manifest_checksum,
        source_rights_attestation=record.source_rights_attestation,
        privacy=privacy_state(record),
        input_video=record.input_video,
        created_at=record.created_at,
    )


def scene_response(revision: SceneRevision, visual: VisualBinding) -> SceneResponse:
    """Chiếu SceneRevision đã publish thành DTO cho viewer."""
    return SceneResponse(
        job_id=revision.job_id,
        scene_id=revision.scene.scene_id,
        scene_revision=revision.scene.scene_revision,
        scene_uri=revision.scene_reference.artifact_uri,
        scene_checksum=revision.scene_reference.artifact_checksum,
        supersedes_revision=revision.supersedes_revision,
        scene=revision.scene,
        visual=visual,
    )


def validation_state(job_id: str, report: ValidationReport) -> ValidationStateResponse:
    """Chiếu ValidationReport thành state mà màn hình validation tiêu thụ."""
    versions = report.environment_versions
    return ValidationStateResponse(
        job_id=job_id,
        report=report,
        report_checksum_verified=report.report_checksum.startswith("sha256:"),
        isaac_runtime_proof=versions.get("isaac_sim", "UNVERIFIED") != "UNVERIFIED",
    )


def review_state(job_id: str, approval: ApprovalRecord) -> ReviewStateResponse:
    """Chiếu approval record thành state, kèm cờ nói rõ nó là bản synthetic."""
    return ReviewStateResponse(
        job_id=job_id,
        approval=approval,
        synthetic_authorization=True,
        note="Approval lấy từ fixture mock_job; không phải uỷ quyền của Reviewer thật (PRODUCT-10).",
    )


def scene_edit_response(result: SceneEditResult) -> SceneEditResponse:
    """Chiếu SceneEditResult thành DTO của lần sửa vừa persist."""
    return SceneEditResponse(
        job_id=result.job_id,
        previous_scene_revision=result.previous_scene_revision,
        scene_revision=result.revision.scene.scene_revision,
        scene_uri=result.revision.scene_reference.artifact_uri,
        scene_checksum=result.revision.scene_reference.artifact_checksum,
        scene=result.revision.scene,
    )
