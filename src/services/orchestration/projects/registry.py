"""Fixture-backed project and job registry for the mock-first product API.

EX-PRODUCT chạy trước khi có worker thật (PRODUCT-01 §3), nên registry đọc
`fixtures/mock_job/` và trả đúng response shape mà worker thật sẽ trả sau này.
Đổi nguồn dữ liệu không được đổi shape.
"""

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from src.models.contracts.artifacts import (
    ArtifactDataClass,
    ArtifactRef,
    Checksum,
    JsonObject,
    ProductArtifactRef,
)
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import (
    InputManifest,
    JobManifest,
    JobStatus,
    PrivacyInspectionScope,
    PrivacyResult,
    PrivacyValidationReport,
    RuntimeManifest,
    StageArtifact,
    StageId,
)
from src.models.contracts.release import ApprovalRecord
from src.models.contracts.validation import CandidatePackage, ValidationReport
from src.services.orchestration.artifacts import (
    ArtifactChecksumError,
    ArtifactNotFoundError,
    ArtifactResolver,
    FilesystemArtifactStore,
    sha256_file,
    with_canonical_checksum,
)
from src.services.orchestration.jobs.models import JobAttemptRecord, TransitionRequest
from src.services.orchestration.jobs.service import JobLifecycle
from src.services.orchestration.projects.errors import (
    JobNotFoundError,
    ProjectNotFoundError,
)
from src.services.orchestration.projects.models import (
    JobCreateInput,
    ProjectCreateInput,
    ProjectRecord,
)
from src.services.orchestration.projects.privacy import require_dispatch_allowed
from src.services.orchestration.scene.editor import SceneEditor

ContractT = TypeVar("ContractT", bound=BaseModel)

#: Repo root, tính từ `src/services/orchestration/projects/registry.py`.
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FIXTURE_ROOT = REPO_ROOT / "fixtures"
#: Nơi ghi revision JobManifest lúc chạy; khớp mặc định của `Settings.artifact_root`
#: và đã nằm trong `.gitignore`. Fixture là read-only, không ghi vào đó.
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "data" / "artifacts"

#: Chỉ hai data class được phép qua ranh giới product.
PRODUCT_VISIBLE_DATA_CLASSES: frozenset[ArtifactDataClass] = frozenset(
    {ArtifactDataClass.PRODUCT_INPUT, ArtifactDataClass.DERIVED}
)

_SCHEMA_VERSION = "1.0"
_FIXTURE_SEED = 7
#: Giá trị chỗ giữ chỗ; canonical checksum bỏ qua chính field này nên không ảnh hưởng digest.
_PLACEHOLDER_CHECKSUM = "sha256:" + "0" * 64


class ProjectRegistry:
    """In-memory project/job registry seeded from the shared handoff fixtures."""

    def __init__(
        self,
        fixture_root: Path = DEFAULT_FIXTURE_ROOT,
        runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    ) -> None:
        self.fixture_root = fixture_root
        self.job_fixture_dir = fixture_root / "mock_job"
        self.artifact_root = fixture_root / "artifact_store"
        self.validation_fixture_path = fixture_root / "validation_report" / "validation_report.json"
        self.approval_fixture_path = fixture_root / "mock_job" / "approval_record.json"
        self.candidate_fixture_path = fixture_root / "candidate" / "candidate_package.json"
        self.resolver = ArtifactResolver(self.artifact_root)
        self.store = FilesystemArtifactStore(self.resolver)
        self.lifecycle = JobLifecycle(ArtifactResolver(runtime_root), ArtifactResolver(self.artifact_root))
        self.scene = SceneEditor(fixture_root, ArtifactResolver(runtime_root))
        self._projects: dict[str, ProjectRecord] = {}
        self._jobs: dict[str, JobManifest] = {}
        self._project_jobs: dict[str, list[str]] = {}
        self._attempts: dict[str, list[JobAttemptRecord]] = {}

    # --- seeding ----------------------------------------------------------

    def seed_from_fixtures(self) -> None:
        """Nạp project/job mẫu để API có dữ liệu trước khi có worker thật.

        `source_rights_attestation` của project mẫu được giữ **nguyên văn** từ
        fixture (`{"attested": true, "fixture": true}`), không được nâng thành
        attestation do người dùng khai — fixture không phải sự đồng ý thật.
        """
        job = self._load_fixture_model("job_manifest.json", JobManifest)
        input_manifest = self._load_fixture_model("input_manifest.json", InputManifest)
        self._projects[job.project_id] = ProjectRecord(
            project_id=job.project_id,
            name="Fixture warehouse project",
            source_type=input_manifest.source_type,
            input_manifest_checksum=input_manifest.input_manifest_checksum,
            source_rights_attestation=input_manifest.source_rights_attestation,
            privacy_report=self._fixture_privacy_report(input_manifest.input_manifest_checksum),
        )
        self._jobs[job.job_id] = job
        self._project_jobs.setdefault(job.project_id, []).append(job.job_id)
        self._attempts[job.job_id] = [
            JobAttemptRecord(
                attempt=1,
                status=job.status,
                current_stage=job.current_stage,
                recorded_at=job.completed_at or job.started_at,
            )
        ]

    def _fixture_privacy_report(self, input_manifest_checksum: Checksum) -> PrivacyValidationReport:
        """Báo cáo privacy suy ra từ chính fixture, không phải một phê duyệt mới.

        Job mẫu có `status: SUCCEEDED`, nghĩa là `ST-PRIVACY-GATE` đã cho input đi
        qua trong lần chạy mẫu; dataset mẫu là synthetic nên không có khuôn mặt hay
        biển số thật để xử lý. Đây là suy luận từ fixture, **không** phải QA ký.
        """
        draft = PrivacyValidationReport(
            schema_version=_SCHEMA_VERSION,
            input_manifest_checksum=input_manifest_checksum,
            inspection_scope=PrivacyInspectionScope.APPROVED_COPY,
            selected_frame_count=1,
            inspected_frame_count=1,
            unresolved_findings=[],
            result=PrivacyResult.VERIFIED_ANONYMIZED,
            report_checksum=_PLACEHOLDER_CHECKSUM,
        )
        return with_canonical_checksum(draft, "report_checksum")

    # --- validation and review (read-only fixture state) ------------------

    def get_validation_report(self, job_id: str) -> ValidationReport:
        """Báo cáo validation của job, đọc từ fixture và verify self-checksum."""
        self.get_job(job_id)
        report = self._read_fixture_report(self.validation_fixture_path, ValidationReport, "report_checksum")
        if report.candidate_checksum != self._fixture_candidate_checksum():
            raise ArtifactChecksumError("validation report không gắn với candidate của fixture")
        return report

    def get_approval_record(self, job_id: str) -> ApprovalRecord:
        """Approval record của job. Đây là bản **synthetic**, không phải uỷ quyền thật."""
        self.get_job(job_id)
        return self._read_fixture_report(self.approval_fixture_path, ApprovalRecord, "record_checksum")

    def _read_fixture_report(self, path: Path, model_type: type[ContractT], checksum_field: str) -> ContractT:
        """Đọc một report fixture và từ chối nếu self-checksum canonical không khớp."""
        model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
        if getattr(model, checksum_field) != canonical_content_checksum(model, checksum_field):
            raise ArtifactChecksumError(f"{model_type.__name__} fixture có checksum không khớp canonical content")
        return model

    def _fixture_candidate_checksum(self) -> Checksum:
        """Candidate checksum mà validation report và approval record phải cùng trỏ tới."""
        package = CandidatePackage.model_validate_json(self.candidate_fixture_path.read_text(encoding="utf-8"))
        return package.candidate_checksum

    def _load_fixture_model(self, name: str, model_type: type[ContractT]) -> ContractT:
        """Đọc một manifest mẫu và ép đúng shared contract."""
        return model_type.model_validate_json((self.job_fixture_dir / name).read_text(encoding="utf-8"))

    def _fixture_config_checksum(self) -> Checksum:
        """`config_checksum` là checksum **byte** của processing config, không phải canonical."""
        return sha256_file(self.job_fixture_dir / "processing_config.json")

    def _fixture_runtime_checksum(self) -> Checksum:
        """`runtime_manifest_checksum` là checksum **canonical content** của RuntimeManifest."""
        return self._load_fixture_model("runtime_manifest.json", RuntimeManifest).runtime_manifest_checksum

    # --- projects ---------------------------------------------------------

    def create_project(self, request: ProjectCreateInput) -> ProjectRecord:
        """Tạo project mới; input mới chỉ ở mức sàng lọc sơ bộ, chưa được dispatch."""
        project_id = f"project-{uuid4().hex[:12]}"
        attestation: JsonObject = request.attestation.model_dump(mode="json")
        record = ProjectRecord(
            project_id=project_id,
            name=request.name,
            source_type=request.source_type,
            input_manifest_checksum=request.input_manifest_checksum,
            source_rights_attestation=attestation,
            privacy_report=self._preliminary_privacy_report(request.input_manifest_checksum),
        )
        self._projects[project_id] = record
        self._project_jobs[project_id] = []
        return record

    def _preliminary_privacy_report(self, input_manifest_checksum: Checksum) -> PrivacyValidationReport:
        """Trạng thái mặc định của input mới: chưa QA xác nhận ẩn danh."""
        draft = PrivacyValidationReport(
            schema_version=_SCHEMA_VERSION,
            input_manifest_checksum=input_manifest_checksum,
            inspection_scope=PrivacyInspectionScope.SAMPLED,
            selected_frame_count=0,
            inspected_frame_count=0,
            unresolved_findings=[],
            result=PrivacyResult.PRELIMINARY_SCREENED,
            report_checksum=_PLACEHOLDER_CHECKSUM,
        )
        return with_canonical_checksum(draft, "report_checksum")

    def list_projects(self) -> list[ProjectRecord]:
        """Toàn bộ project đang giữ, sắp theo project_id để kết quả ổn định."""
        return [self._projects[key] for key in sorted(self._projects)]

    def get_project(self, project_id: str) -> ProjectRecord:
        """Lấy một project, ném ProjectNotFoundError nếu không có."""
        try:
            return self._projects[project_id]
        except KeyError as error:
            raise ProjectNotFoundError(f"không tìm thấy project: {project_id}") from error

    def record_privacy_report(self, project_id: str, report: PrivacyValidationReport) -> ProjectRecord:
        """Ghi privacy report đã có thẩm quyền cho một project.

        Đây là seam để PRODUCT-03/08 cắm `ST-PRIVACY-GATE` thật vào; không đường
        nào khác được tự nâng privacy state.
        """
        current = self.get_project(project_id)
        if report.input_manifest_checksum != current.input_manifest_checksum:
            raise ValueError("privacy report phải gắn đúng input manifest của project")
        updated = current.model_copy(update={"privacy_report": report})
        self._projects[project_id] = updated
        return updated

    # --- jobs -------------------------------------------------------------

    def create_job(self, request: JobCreateInput) -> JobManifest:
        """Tạo job QUEUED cho một project, sau khi qua privacy gate."""
        project = self.get_project(request.project_id)
        require_dispatch_allowed(project.privacy_report.result)
        job = self._build_queued_job(project, request.scene_revision)
        reference = self.lifecycle.persist_initial(job)
        self._jobs[job.job_id] = job
        self._project_jobs.setdefault(project.project_id, []).append(job.job_id)
        self._attempts[job.job_id] = [
            JobAttemptRecord(
                attempt=1,
                status=job.status,
                current_stage=job.current_stage,
                recorded_at=job.started_at,
                job_manifest_uri=reference.artifact_uri,
                job_manifest_checksum=reference.artifact_checksum,
            )
        ]
        return job

    def transition_job(self, job_id: str, request: TransitionRequest) -> JobManifest:
        """Chuyển trạng thái job theo bảng chuyển, rồi publish revision mới."""
        current = self.get_job(job_id)
        sequence = len(self._attempts.get(job_id, [])) + 1
        updated, reference = self.lifecycle.apply(current, request, sequence)
        self._jobs[job_id] = updated
        self._record_attempt(job_id, updated, request, reference)
        return updated

    def _record_attempt(
        self,
        job_id: str,
        job: JobManifest,
        request: TransitionRequest,
        reference: ArtifactRef,
    ) -> None:
        """Nối thêm một attempt; không sửa attempt cũ.

        Số attempt chỉ tăng ở cạnh retry (`FAILED → QUEUED`) — đó là lúc một lần
        chạy mới thật sự bắt đầu, không phải mỗi lần đổi trạng thái.
        """
        history = self._attempts.setdefault(job_id, [])
        previous = history[-1] if history else None
        is_retry = request.target_status == JobStatus.QUEUED and previous is not None
        history.append(
            JobAttemptRecord(
                attempt=(previous.attempt + 1) if is_retry and previous else (previous.attempt if previous else 1),
                status=job.status,
                current_stage=job.current_stage,
                recorded_at=job.completed_at or job.started_at,
                job_manifest_uri=reference.artifact_uri,
                job_manifest_checksum=reference.artifact_checksum,
                error=request.error,
            )
        )

    def list_job_attempts(self, job_id: str) -> list[JobAttemptRecord]:
        """Lịch sử attempt của một job, cũ nhất trước."""
        self.get_job(job_id)
        return list(self._attempts.get(job_id, []))

    def _build_queued_job(self, project: ProjectRecord, scene_revision: str) -> JobManifest:
        """Job mới chưa chạy stage nào, dùng đúng config/runtime đã khoá của fixture."""
        draft = JobManifest(
            schema_version=_SCHEMA_VERSION,
            job_id=f"job-{uuid4().hex[:12]}",
            project_id=project.project_id,
            scene_revision=scene_revision,
            status=JobStatus.QUEUED,
            input_manifest_checksum=project.input_manifest_checksum,
            config_checksum=self._fixture_config_checksum(),
            runtime_manifest_checksum=self._fixture_runtime_checksum(),
            seed=_FIXTURE_SEED,
            started_at=datetime.now(UTC),
            completed_at=None,
            current_stage=StageId.INPUT_VALIDATE,
            stage_artifacts=[],
            job_manifest_checksum=_PLACEHOLDER_CHECKSUM,
        )
        return with_canonical_checksum(draft, "job_manifest_checksum")

    def list_jobs(self, project_id: str) -> list[JobManifest]:
        """Job của một project, sắp theo job_id."""
        self.get_project(project_id)
        return [self._jobs[key] for key in sorted(self._project_jobs.get(project_id, []))]

    def get_job(self, job_id: str) -> JobManifest:
        """Lấy một job, ném JobNotFoundError nếu không có."""
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise JobNotFoundError(f"không tìm thấy job: {job_id}") from error

    # --- artifacts --------------------------------------------------------

    def list_job_artifacts(self, job_id: str) -> tuple[list[ProductArtifactRef], int]:
        """Ref artifact được phép hiện ra product, kèm số ref bị loại.

        Quyền dùng đọc từ `data_class` có type trong `JobManifest.stage_artifacts`.
        URI hay tên thư mục **không** quyết định quyền dùng (PRODUCT-04 §5), nên
        registry không bao giờ liệt kê nội dung `artifact_store/`.
        """
        job = self.get_job(job_id)
        visible: list[ProductArtifactRef] = []
        excluded = 0
        for stage in job.stage_artifacts:
            if stage.artifact_uri is None or stage.data_class is None or stage.artifact_checksum is None:
                continue
            if stage.data_class not in PRODUCT_VISIBLE_DATA_CLASSES:
                excluded += 1
                continue
            visible.append(self._to_product_ref(job.job_id, stage))
        return visible, excluded

    def read_artifact_bytes(self, job_id: str, reference: ArtifactRef) -> bytes:
        """Đọc bytes của một artifact **đã nằm trong allow-list** của job.

        Không nhận URI tuỳ ý: `job_id` + `artifact_uri` được đối chiếu với allow-list
        của chính job đó trước, nên `evaluation_only` hay `ground_truth` nằm cùng
        thư mục cũng không gọi tới được. Checksum trong `reference` vẫn được
        resolver verify trên bytes thật.
        """
        if reference.artifact_uri not in self._product_visible_uris(job_id):
            raise ArtifactNotFoundError(f"artifact không thuộc job {job_id}: {reference.artifact_uri}")
        return self.resolver.require(reference).read_bytes()

    def _product_visible_uris(self, job_id: str) -> set[str]:
        """URI được phép tải: artifact của job cộng ref hình học trong SceneIR.

        Ref của SceneIR là `ProductArtifactRef` nên contract chỉ cho `product_input`
        hoặc `derived` đi qua — thêm chúng vào allow-list không mở đường cho
        `ground_truth`/`evaluation_only`.
        """
        uris = {item.artifact_uri for item in self.list_job_artifacts(job_id)[0]}
        uris.update(
            reference.artifact_uri for reference in self.scene.artifact_references(self.scene.current(job_id).scene)
        )
        return uris

    @staticmethod
    def _to_product_ref(job_id: str, stage: StageArtifact) -> ProductArtifactRef:
        """Chuyển một stage artifact đã publish thành ref an toàn cho product."""
        return ProductArtifactRef(
            artifact_type=stage.artifact_type or "unknown",
            schema_version=_SCHEMA_VERSION,
            artifact_uri=stage.artifact_uri,
            artifact_checksum=stage.artifact_checksum,
            data_class=stage.data_class,
            producer_stage=stage.stage_id,
            job_id=job_id,
        )


@lru_cache
def get_project_registry() -> ProjectRegistry:
    """Registry dùng chung, nạp fixture một lần (theo khuôn `get_settings`)."""
    registry = ProjectRegistry()
    registry.seed_from_fixtures()
    return registry
