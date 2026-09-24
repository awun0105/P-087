"""DTO của product API (EX-PRODUCT).

**Bất di bất dịch:** response chỉ mang `artifact://jobs/<job_id>/<path>`, checksum
và `data_class`. Không bao giờ trả `artifact_root`, `Path`, hay tên file trên đĩa.
`ProductArtifactRef` đã ép điều đó ở tầng contract nên response tái dùng thẳng nó
thay vì dựng model song song.

Request model nằm ở tầng service (`orchestration.projects.models`) vì đó là input
của domain, không phải của HTTP — route import thẳng từ đó, không re-export ở đây.
"""

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import Checksum, Identifier, JsonObject, ProductArtifactRef
from src.models.contracts.manifests import (
    JobManifest,
    PrivacyInspectionScope,
    PrivacyResult,
    PrivacyValidationReport,
    SourceType,
)
from src.models.contracts.release import ApprovalRecord
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import ValidationReport
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.models import ProjectRecord
from src.services.orchestration.projects.privacy import block_reason, dispatch_allowed
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


class ProjectResponse(ApiModel):
    """Project kèm input identity, attestation và privacy state."""

    project_id: Identifier
    name: str
    source_type: SourceType
    input_manifest_checksum: Checksum
    source_rights_attestation: JsonObject
    privacy: PrivacyStateResponse


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


def privacy_state(report: PrivacyValidationReport) -> PrivacyStateResponse:
    """Chiếu PrivacyValidationReport thành state mà UI tiêu thụ."""
    return PrivacyStateResponse(
        result=report.result,
        input_manifest_checksum=report.input_manifest_checksum,
        inspection_scope=report.inspection_scope,
        unresolved_finding_count=len(report.unresolved_findings),
        dispatch_allowed=dispatch_allowed(report.result),
        block_reason=block_reason(report.result),
    )


def project_response(record: ProjectRecord) -> ProjectResponse:
    """Chiếu ProjectRecord thành DTO trả ra ngoài."""
    return ProjectResponse(
        project_id=record.project_id,
        name=record.name,
        source_type=record.source_type,
        input_manifest_checksum=record.input_manifest_checksum,
        source_rights_attestation=record.source_rights_attestation,
        privacy=privacy_state(record.privacy_report),
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
