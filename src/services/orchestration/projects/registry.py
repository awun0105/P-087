"""Registry project/job bền vững; synthetic fixtures là opt-in riêng cho demo.

API dùng database + immutable manifest. Constructor không DB được giữ như seam
unit/fixture cũ, không phải đường persistence của deployed API.
"""

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from src.config import get_settings
from src.models.contracts.artifacts import (
    ArtifactDataClass,
    ArtifactRef,
    Checksum,
    JsonObject,
    ProductArtifactRef,
)
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import (
    InputConfiguration,
    InputFile,
    InputManifest,
    JobManifest,
    JobStatus,
    LidarMetadata,
    PrivacyInspectionScope,
    PrivacyResult,
    PrivacyValidationReport,
    RuntimeManifest,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.models.contracts.preview import PreviewWorkerReceipt, ReconstructionPreview
from src.models.contracts.release import ApprovalRecord
from src.models.contracts.validation import CandidatePackage, ValidationReport
from src.services.orchestration.artifacts import (
    ArtifactChecksumError,
    ArtifactNotFoundError,
    ArtifactRemote,
    ArtifactResolver,
    FilesystemArtifactStore,
    sha256_bytes,
    sha256_file,
    with_canonical_checksum,
)
from src.services.orchestration.auth.models import Actor
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import JobAttemptRecord, PreparedInputReceipt, TransitionRequest
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.service import JobLifecycle
from src.services.orchestration.processing import JobProcessingConfig, config_bytes, job_config_reference
from src.services.orchestration.projects.errors import (
    JobNotFoundError,
    ProjectNotFoundError,
)
from src.services.orchestration.projects.models import (
    DemoBaseline,
    InputVideoSummary,
    JobCreateInput,
    ProjectCreateInput,
    ProjectRecord,
    UploadProjectInput,
)
from src.services.orchestration.projects.persistence import ProjectPersistence
from src.services.orchestration.projects.preview import load_job_preview
from src.services.orchestration.projects.privacy import require_project_dispatch
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.heads import SceneHeadRepository
from src.services.orchestration.storage import artifact_remote
from src.services.orchestration.uploads.models import UploadRecord

if TYPE_CHECKING:
    from src.services.reconstruction import FinalizeResult

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
    """Registry runtime; dictionaries chỉ dùng cho seam fixture/unit không có DB."""

    def __init__(
        self,
        fixture_root: Path = DEFAULT_FIXTURE_ROOT,
        runtime_root: Path = DEFAULT_RUNTIME_ROOT,
        database: RuntimeDatabase | None = None,
        execution_profile: ExecutionProfile | None = None,
        remote: ArtifactRemote | None = None,
    ) -> None:
        self.fixture_root = fixture_root
        self.job_fixture_dir = fixture_root / "mock_job"
        self.artifact_root = fixture_root / "artifact_store"
        self.validation_fixture_path = fixture_root / "validation_report" / "validation_report.json"
        self.approval_fixture_path = fixture_root / "mock_job" / "approval_record.json"
        self.candidate_fixture_path = fixture_root / "candidate" / "candidate_package.json"
        self.resolver = ArtifactResolver(self.artifact_root)
        self.runtime_resolver = ArtifactResolver(runtime_root, remote)
        self.persistence = ProjectPersistence(database, self.runtime_resolver) if database else None
        self.execution_profile = execution_profile
        self.store = FilesystemArtifactStore(self.resolver)
        self.lifecycle = JobLifecycle(self.runtime_resolver, self.resolver)
        self.scene = SceneEditor(
            fixture_root,
            self.runtime_resolver,
            SceneHeadRepository(database) if database is not None else None,
        )
        self._fixture_job_id: str | None = None
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
        self._fixture_job_id = job.job_id
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
        if self.persistence is not None:
            self.persistence.save_project(self._projects[job.project_id], seed=True)
            try:
                self.persistence.get_job(job.job_id)
            except JobNotFoundError:
                reference = self.lifecycle.store.publish_manifest(job)
                event = self._attempts[job.job_id][0].model_copy(
                    update={
                        "job_manifest_uri": reference.artifact_uri,
                        "job_manifest_checksum": reference.artifact_checksum,
                    }
                )
                self.persistence.save_job(job, reference, event, seed=True)
            self._projects.clear()
            self._jobs.clear()
            self._project_jobs.clear()
            self._attempts.clear()

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
        if job_id != self._fixture_job_id:
            raise ArtifactNotFoundError("Job chưa publish validation report")
        report = self._read_fixture_report(self.validation_fixture_path, ValidationReport, "report_checksum")
        if report.candidate_checksum != self._fixture_candidate_checksum():
            raise ArtifactChecksumError("validation report không gắn với candidate của fixture")
        return report

    def get_approval_record(self, job_id: str) -> ApprovalRecord:
        """Approval record của job. Đây là bản **synthetic**, không phải uỷ quyền thật."""
        self.get_job(job_id)
        if job_id != self._fixture_job_id:
            raise ArtifactNotFoundError("Job chưa publish approval record")
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
        if self.persistence is not None:
            self.persistence.save_project(record)
        else:
            self._projects[project_id] = record
            self._project_jobs[project_id] = []
        return record

    def create_project_from_upload(
        self,
        upload: UploadRecord,
        request: UploadProjectInput,
        privacy_mode: Literal["qa_verified", "self_attested"],
        lidar: UploadRecord | None = None,
        created_by: Actor | None = None,
    ) -> ProjectRecord:
        """Dựng InputManifest cho video đã upload, publish nó rồi tạo project.

        Manifest nằm trong namespace của project (immutable); video giữ nguyên ở
        namespace upload. `attested=True` là field mà EX-REC privacy gate đọc.
        `lidar` là gói LiDAR đi kèm (ADR 0009): manifest ghi cả hai file, khai cùng scene, và giữ bằng chứng nhận
        diện của gói để worker chọn luồng mà không nhận diện lại từ tên file.
        """
        if upload.upload_id != request.upload_id:
            raise ValueError("upload không khớp request")
        if (lidar is None) != (request.lidar is None) or (lidar and lidar.upload_id != request.lidar.upload_id):  # type: ignore[union-attr]
            raise ValueError("gói LiDAR không khớp request")
        if lidar is not None and (lidar.detection is None or lidar.detection.lidar is None):
            raise ValueError("file đính kèm không phải gói LiDAR đã nhận diện")
        project_id = f"project-{uuid4().hex[:12]}"
        attestation: JsonObject = {**request.attestation.model_dump(mode="json"), "attested": True}
        draft = InputManifest(
            schema_version=_SCHEMA_VERSION,
            source_type="upload",
            received_at=upload.received_at,
            files=[
                InputFile(
                    original_name=upload.original_name,
                    media_type=upload.media_type,
                    size_bytes=upload.size_bytes,
                    checksum=upload.checksum,
                    artifact_uri=upload.artifact_uri,
                    data_class=ArtifactDataClass.PRODUCT_INPUT,
                ),
                *(
                    [
                        InputFile(
                            original_name=lidar.original_name,
                            media_type=lidar.media_type,
                            size_bytes=lidar.size_bytes,
                            checksum=lidar.checksum,
                            artifact_uri=lidar.artifact_uri,
                            data_class=ArtifactDataClass.PRODUCT_INPUT,
                        )
                    ]
                    if lidar is not None
                    else []
                ),
            ],
            input_configuration=InputConfiguration(
                rgb_present=True,
                registered_lidar_present=lidar is not None,
                declared_same_scene=True if lidar is not None else None,
            ),
            lidar_metadata=(
                None
                if lidar is None
                else LidarMetadata(
                    unit="meter",
                    coordinate_frame="lidar_map",
                    # Scan thô chỉ thành đám mây đã đăng ký sau ST-LIDAR-INGEST; manifest ghi đúng dạng người dùng nộp.
                    registration_status=(
                        "registered" if lidar.input_kind == "registered_lidar" else "scan_sequence_with_trajectory"
                    ),
                )
            ),
            source_rights_attestation=attestation,
            preparation_provenance={
                "upload_id": upload.upload_id,
                **(
                    {
                        "lidar": {
                            "upload_id": lidar.upload_id,
                            "input_kind": lidar.input_kind,
                            "trajectory_origin": request.lidar.trajectory_origin,  # type: ignore[union-attr]
                            "evidence": lidar.detection.lidar.model_dump(mode="json"),  # type: ignore[union-attr]
                        }
                    }
                    if lidar is not None
                    else {}
                ),
            },
            input_manifest_checksum=_PLACEHOLDER_CHECKSUM,
        )
        manifest = with_canonical_checksum(draft, "input_manifest_checksum")
        payload = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
        reference = ProductArtifactRef(
            artifact_type="InputManifest",
            schema_version=_SCHEMA_VERSION,
            artifact_uri=f"artifact://jobs/{project_id}/input/input_manifest.json",
            artifact_checksum=sha256_bytes(payload),
            data_class=ArtifactDataClass.PRODUCT_INPUT,
            producer_stage=StageId.INPUT_VALIDATE,
            job_id=project_id,
        )
        FilesystemArtifactStore(self.runtime_resolver).publish(reference, payload)
        record = ProjectRecord(
            project_id=project_id,
            name=request.name,
            source_type="upload",
            input_manifest_checksum=manifest.input_manifest_checksum,
            source_rights_attestation=attestation,
            privacy_report=self._preliminary_privacy_report(manifest.input_manifest_checksum),
            privacy_mode=privacy_mode,
            input_manifest_ref=reference,
            input_video=InputVideoSummary(
                original_name=upload.original_name, media_type=upload.media_type, size_bytes=upload.size_bytes
            ),
            created_at=datetime.now(UTC),
            created_by=created_by,
        )
        if self.persistence is not None:
            self.persistence.save_project(record)
        else:
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
        if self.persistence is not None:
            return self.persistence.list_projects()
        return [self._projects[key] for key in sorted(self._projects)]

    def get_project(self, project_id: str) -> ProjectRecord:
        """Lấy một project, ném ProjectNotFoundError nếu không có."""
        if self.persistence is not None:
            return self.persistence.get_project(project_id)
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
        if report.report_checksum != canonical_content_checksum(report, "report_checksum"):
            raise ArtifactChecksumError("Privacy report canonical checksum không khớp")
        updated = current.model_copy(update={"privacy_report": report})
        if self.persistence is not None:
            self.persistence.save_project(updated, expected=current)
        else:
            self._projects[project_id] = updated
        return updated

    def set_demo_baseline(self, project_id: str, baseline: DemoBaseline | None) -> ProjectRecord:
        """Đặt hoặc bỏ mốc bản demo của project (compare-and-swap như mọi cập nhật project)."""
        current = self.get_project(project_id)
        updated = current.model_copy(update={"demo_baseline": baseline})
        if self.persistence is not None:
            self.persistence.save_project(updated, expected=current)
        else:
            self._projects[project_id] = updated
        return updated

    # --- jobs -------------------------------------------------------------

    def create_job(self, request: JobCreateInput, processing: JobProcessingConfig | None = None) -> JobManifest:
        """Tạo job QUEUED cho một project, sau khi qua privacy gate.

        `processing` (Studio) được publish thành `config/processing.json` của job và
        checksum bytes của nó là `config_checksum`; không có thì dùng profile chung.
        """
        project = self.get_project(request.project_id)
        require_project_dispatch(project)
        job_id = f"job-{uuid4().hex[:12]}"
        config_checksum = None
        if processing is not None:
            payload = config_bytes(processing)
            reference = job_config_reference(job_id, sha256_bytes(payload))
            FilesystemArtifactStore(self.runtime_resolver).publish(reference, payload)
            config_checksum = reference.artifact_checksum
        job = self._build_queued_job(project, request.scene_revision, job_id, config_checksum)
        reference = (
            self.lifecycle.store.publish_manifest(job) if self.persistence else self.lifecycle.persist_initial(job)
        )
        event = JobAttemptRecord(
            attempt=1,
            status=job.status,
            current_stage=job.current_stage,
            recorded_at=job.started_at,
            job_manifest_uri=reference.artifact_uri,
            job_manifest_checksum=reference.artifact_checksum,
        )
        if self.persistence is not None:
            self.persistence.save_job(job, reference, event)
        else:
            self._jobs[job.job_id] = job
            self._project_jobs.setdefault(project.project_id, []).append(job.job_id)
            self._attempts[job.job_id] = [event]
        return job

    def transition_job(
        self, job_id: str, request: TransitionRequest, *, expected_checksum: Checksum | None = None
    ) -> JobManifest:
        """Chuyển trạng thái job theo bảng chuyển, rồi publish revision mới."""
        current = self.get_job(job_id)
        if expected_checksum is not None and current.job_manifest_checksum != expected_checksum:
            raise RuntimeStateConflictError("Job revision khác command đang thực hiện; đọc lại trước khi thử lại")
        if self.persistence is not None:
            # Đọc history trước publication; CAS loại command nếu process khác đã đổi job.
            history = self.persistence.list_attempts(job_id)
            updated = self.lifecycle.prepare(current, request)
            reference = self.lifecycle.store.publish_manifest(updated)
            previous = history[-1].attempt if history else 1
            event = JobAttemptRecord(
                attempt=previous + (1 if request.target_status == JobStatus.QUEUED else 0),
                status=updated.status,
                current_stage=updated.current_stage,
                recorded_at=datetime.now(UTC),
                job_manifest_uri=reference.artifact_uri,
                job_manifest_checksum=reference.artifact_checksum,
                error=request.error,
            )
            self.persistence.save_job(updated, reference, event, expected=current)
            return updated
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
                recorded_at=datetime.now(UTC),
                job_manifest_uri=reference.artifact_uri,
                job_manifest_checksum=reference.artifact_checksum,
                error=request.error,
            )
        )

    def list_job_attempts(self, job_id: str) -> list[JobAttemptRecord]:
        """Lịch sử attempt của một job, cũ nhất trước."""
        if self.persistence is not None:
            return self.persistence.list_attempts(job_id)
        self.get_job(job_id)
        return list(self._attempts.get(job_id, []))

    def record_preview(
        self,
        expected: JobManifest,
        receipt: PreviewWorkerReceipt,
        *,
        verified_at: datetime | None = None,
    ) -> JobManifest:
        """Worker-only reducer; receipt phải đi qua public REC consumer verifier."""
        if self.persistence is None:
            raise RuntimeStateConflictError("Real worker cần durable registry")
        if (
            expected.status != JobStatus.RUNNING
            or receipt.job_id != expected.job_id
            or receipt.source_input_checksum != expected.input_manifest_checksum
        ):
            raise ValueError("Preview receipt khác job/input đang chạy")
        if receipt.result_ref.job_id != expected.job_id:
            raise ValueError("Preview result reference khác job")
        self.runtime_resolver.require(receipt.result_ref)
        stages = list(receipt.stage_artifacts)
        preview_verified_at = None
        if receipt.error is None:
            if receipt.preview_ref is None:
                raise ValueError("Worker thiếu preview publication")
            self.runtime_resolver.require(receipt.preview_ref)
            preview_verified_at = verified_at or datetime.now(UTC)
            stages.append(
                StageArtifact(
                    stage_id=StageId.VISUAL_RECON,
                    status="SUCCEEDED",
                    completed_at=preview_verified_at,
                    artifact_type="ReconstructionPreview",
                    artifact_uri=receipt.preview_ref.artifact_uri,
                    artifact_checksum=receipt.preview_ref.artifact_checksum,
                    data_class=receipt.preview_ref.data_class,
                )
            )
        updated = with_canonical_checksum(
            expected.model_copy(
                update={
                    "stage_artifacts": [*expected.stage_artifacts, *stages],
                    "status": JobStatus.FAILED if receipt.error else JobStatus.RUNNING,
                    "current_stage": receipt.error.stage_id if receipt.error else StageId.METRIC_CANONICALIZE,
                    "completed_at": datetime.now(UTC) if receipt.error else None,
                }
            ),
            "job_manifest_checksum",
        )
        if receipt.error is None:
            load_job_preview(updated, self.runtime_resolver)
        reference = self.lifecycle.store.publish_manifest(updated)
        history = self.persistence.list_attempts(expected.job_id)
        event = JobAttemptRecord(
            attempt=history[-1].attempt,
            status=updated.status,
            current_stage=updated.current_stage,
            recorded_at=datetime.now(UTC),
            error=receipt.error,
            job_manifest_uri=reference.artifact_uri,
            job_manifest_checksum=reference.artifact_checksum,
            preview_verified_at=preview_verified_at,
        )
        self.persistence.save_job(updated, reference, event, expected=expected)
        return updated

    def record_stage_progress(
        self,
        expected: JobManifest,
        stage_id: StageId,
        *,
        started_at: datetime | None = None,
    ) -> JobManifest:
        """Worker-only: ghi stage đang chạy và mốc start quan sát được (không thêm artifact).

        Dùng cho tiến trình quan sát được (REC stage event), không phải phần trăm
        ước đoán; có thể cập nhật start chính xác cho stage đã claim. CAS bảo đảm
        không ghi đè cancel/retry xảy ra song song.
        """
        if self.persistence is None:
            raise RuntimeStateConflictError("Real worker cần durable registry")
        if expected.status != JobStatus.RUNNING:
            raise ValueError("Chỉ job RUNNING mới đổi stage đang chạy")
        if expected.current_stage == stage_id and started_at is None:
            return expected
        updated = with_canonical_checksum(
            expected.model_copy(update={"current_stage": stage_id}), "job_manifest_checksum"
        )
        reference = self.lifecycle.store.publish_manifest(updated)
        history = self.persistence.list_attempts(expected.job_id)
        event = JobAttemptRecord(
            attempt=history[-1].attempt,
            status=updated.status,
            current_stage=stage_id,
            recorded_at=datetime.now(UTC),
            job_manifest_uri=reference.artifact_uri,
            job_manifest_checksum=reference.artifact_checksum,
            stage_started_at=started_at,
        )
        self.persistence.save_job(updated, reference, event, expected=expected)
        return updated

    def record_metric_confirmation(self, expected: JobManifest, reference: ProductArtifactRef) -> JobManifest:
        """Ghi xác nhận tỉ lệ mét (REC-06 anchor + frame) vào job đang chờ; CAS theo revision.

        Job vẫn RUNNING ở `ST-METRIC-CANONICALIZE` để worker tiếp tục REC-05/REC-10; stage
        artifact SUCCEEDED chỉ nói bước người xác nhận đã xong, không phải final REC-06.
        """
        if self.persistence is None:
            raise RuntimeStateConflictError("Xác nhận tỉ lệ cần durable registry")
        if expected.status != JobStatus.RUNNING or expected.current_stage != StageId.METRIC_CANONICALIZE:
            raise ValueError("Job không ở bước chờ xác nhận tỉ lệ mét")
        if any(stage.stage_id == StageId.METRIC_CANONICALIZE for stage in expected.stage_artifacts):
            raise RuntimeStateConflictError("Job đã có xác nhận tỉ lệ mét")
        if reference.job_id != expected.job_id or reference.artifact_type != "RGBMetricConfirmation":
            raise ValueError("Xác nhận tỉ lệ không thuộc job này")
        self.runtime_resolver.require(reference)
        stage = StageArtifact(
            stage_id=StageId.METRIC_CANONICALIZE,
            status="SUCCEEDED",
            completed_at=datetime.now(UTC),
            artifact_type=reference.artifact_type,
            artifact_uri=reference.artifact_uri,
            artifact_checksum=reference.artifact_checksum,
            data_class=reference.data_class,
        )
        updated = with_canonical_checksum(
            expected.model_copy(update={"stage_artifacts": [*expected.stage_artifacts, stage]}),
            "job_manifest_checksum",
        )
        manifest_ref = self.lifecycle.store.publish_manifest(updated)
        history = self.persistence.list_attempts(expected.job_id)
        event = JobAttemptRecord(
            attempt=history[-1].attempt,
            status=updated.status,
            current_stage=updated.current_stage,
            recorded_at=datetime.now(UTC),
            job_manifest_uri=manifest_ref.artifact_uri,
            job_manifest_checksum=manifest_ref.artifact_checksum,
        )
        self.persistence.save_job(updated, manifest_ref, event, expected=expected)
        return updated

    def record_finalize(
        self,
        expected: JobManifest,
        result: "FinalizeResult",
        result_ref: ProductArtifactRef,
        extra_stages: list[StageArtifact] | None = None,
    ) -> JobManifest:
        """Worker-only: ghi kết quả hoàn tất EX-REC (geometry + bundle) và kết thúc job.

        Kết quả đã qua consumer REC (`load_finalize_result`); ở đây chỉ kiểm đúng job/
        stage đang chạy rồi CAS. Lỗi → FAILED với ExecutionError của REC.
        """
        if self.persistence is None:
            raise RuntimeStateConflictError("Real worker cần durable registry")
        if expected.status != JobStatus.RUNNING or expected.current_stage not in {
            StageId.RGB_GEOMETRY,
            StageId.OBJECT_EXTRACT,
        }:
            raise ValueError("Job không ở bước hoàn tất hình học")
        # Bước tách vật thể (ADR 0006) chạy trong PRODUCT sau bundle; artifact của nó đi kèm.
        extra = list(extra_stages or [])
        if result.job_id != expected.job_id or result_ref.job_id != expected.job_id:
            raise ValueError("Kết quả hoàn tất khác job")
        self.runtime_resolver.require(result_ref)
        for stage in result.stage_artifacts:
            if stage.artifact_uri is not None and stage.artifact_checksum is not None:
                self.runtime_resolver.require_uri(stage.artifact_uri, stage.artifact_checksum)
        failed = result.error is not None
        now = datetime.now(UTC)
        updated = with_canonical_checksum(
            expected.model_copy(
                update={
                    "stage_artifacts": [*expected.stage_artifacts, *result.stage_artifacts, *extra],
                    "status": JobStatus.FAILED if failed else JobStatus.SUCCEEDED,
                    "current_stage": result.error.stage_id
                    if result.error
                    else (StageId.OBJECT_EXTRACT if extra else StageId.RGB_GEOMETRY),
                    "completed_at": now,
                }
            ),
            "job_manifest_checksum",
        )
        manifest_ref = self.lifecycle.store.publish_manifest(updated)
        history = self.persistence.list_attempts(expected.job_id)
        event = JobAttemptRecord(
            attempt=history[-1].attempt,
            status=updated.status,
            current_stage=updated.current_stage,
            recorded_at=now,
            error=result.error,
            job_manifest_uri=manifest_ref.artifact_uri,
            job_manifest_checksum=manifest_ref.artifact_checksum,
        )
        self.persistence.save_job(updated, manifest_ref, event, expected=expected)
        return updated

    def record_prepared_input(self, expected: JobManifest, receipt: PreparedInputReceipt) -> JobManifest:
        """Worker-only reducer cho bước chuẩn bị video; CAS trên revision RUNNING đã claim.

        Mọi stage SUCCEEDED phải resolve đúng checksum trước khi vào journal; lỗi
        stage kết thúc attempt ở FAILED với ExecutionError của REC.
        """
        if self.persistence is None:
            raise RuntimeStateConflictError("Real worker cần durable registry")
        if (
            expected.status != JobStatus.RUNNING
            or receipt.job_id != expected.job_id
            or receipt.input_manifest_checksum != expected.input_manifest_checksum
        ):
            raise ValueError("Prepare receipt khác job/input đang chạy")
        for stage in receipt.stage_artifacts:
            if stage.status != StageStatus.SUCCEEDED:
                continue
            if not (stage.artifact_uri or "").startswith(f"artifact://jobs/{expected.job_id}/"):
                raise ValueError("Prepared artifact phải thuộc namespace của job")
            self.runtime_resolver.require(self._to_product_ref(expected.job_id, stage))
        failed = receipt.error is not None
        updated = with_canonical_checksum(
            expected.model_copy(
                update={
                    "stage_artifacts": [*expected.stage_artifacts, *receipt.stage_artifacts],
                    "status": JobStatus.FAILED if failed else JobStatus.RUNNING,
                    "current_stage": receipt.error.stage_id if receipt.error else StageId.CAMERA_POSE,
                    "completed_at": datetime.now(UTC) if failed else None,
                }
            ),
            "job_manifest_checksum",
        )
        reference = self.lifecycle.store.publish_manifest(updated)
        history = self.persistence.list_attempts(expected.job_id)
        event = JobAttemptRecord(
            attempt=history[-1].attempt,
            status=updated.status,
            current_stage=updated.current_stage,
            recorded_at=datetime.now(UTC),
            error=receipt.error,
            job_manifest_uri=reference.artifact_uri,
            job_manifest_checksum=reference.artifact_checksum,
            actual_frame_count=receipt.extracted_frame_count,
        )
        self.persistence.save_job(updated, reference, event, expected=expected)
        return updated

    def record_lidar_ingest(self, expected: JobManifest, stage: StageArtifact) -> JobManifest:
        """Worker-only reducer cho `ST-LIDAR-INGEST` (ADR 0009); CAS trên revision RUNNING đã claim.

        Thành công: job đi tiếp sang dựng pose camera. Gói LiDAR lỗi: attempt kết thúc FAILED với lý do của REC —
        không lặng lẽ bỏ LiDAR để chạy như job chỉ có video (PRD §5.2).
        """
        if self.persistence is None:
            raise RuntimeStateConflictError("Real worker cần durable registry")
        if expected.status != JobStatus.RUNNING or stage.stage_id != StageId.LIDAR_INGEST:
            raise ValueError("LiDAR ingest receipt khác job/stage đang chạy")
        failed = stage.status != StageStatus.SUCCEEDED
        if not failed:
            if not (stage.artifact_uri or "").startswith(f"artifact://jobs/{expected.job_id}/"):
                raise ValueError("LiDAR artifact phải thuộc namespace của job")
            self.runtime_resolver.require(self._to_product_ref(expected.job_id, stage))
        updated = with_canonical_checksum(
            expected.model_copy(
                update={
                    "stage_artifacts": [*expected.stage_artifacts, stage],
                    "status": JobStatus.FAILED if failed else JobStatus.RUNNING,
                    "current_stage": StageId.LIDAR_INGEST if failed else StageId.CAMERA_POSE,
                    "completed_at": datetime.now(UTC) if failed else None,
                }
            ),
            "job_manifest_checksum",
        )
        reference = self.lifecycle.store.publish_manifest(updated)
        history = self.persistence.list_attempts(expected.job_id)
        event = JobAttemptRecord(
            attempt=history[-1].attempt,
            status=updated.status,
            current_stage=updated.current_stage,
            recorded_at=datetime.now(UTC),
            error=stage.error,
            job_manifest_uri=reference.artifact_uri,
            job_manifest_checksum=reference.artifact_checksum,
        )
        self.persistence.save_job(updated, reference, event, expected=expected)
        return updated

    def _build_queued_job(
        self, project: ProjectRecord, scene_revision: str, job_id: str, config_checksum: Checksum | None
    ) -> JobManifest:
        """Runtime job không được mang config/versions synthetic của fixture."""
        profile = self.execution_profile
        if profile is None:
            if self.persistence is not None and project.source_rights_attestation.get("fixture") is not True:
                raise RuntimeStateConflictError(
                    "Chưa cấu hình execution profile: cần PRODUCT_PROCESSING_CONFIG và PRODUCT_RUNTIME_MANIFEST"
                )
            profile = ExecutionProfile(
                config_checksum=self._fixture_config_checksum(),
                runtime_manifest_checksum=self._fixture_runtime_checksum(),
                seed=_FIXTURE_SEED,
            )
        draft = JobManifest(
            schema_version=_SCHEMA_VERSION,
            job_id=job_id,
            project_id=project.project_id,
            scene_revision=scene_revision,
            status=JobStatus.QUEUED,
            input_manifest_checksum=project.input_manifest_checksum,
            config_checksum=config_checksum or profile.config_checksum,
            runtime_manifest_checksum=profile.runtime_manifest_checksum,
            seed=profile.seed,
            started_at=datetime.now(UTC),
            completed_at=None,
            current_stage=StageId.INPUT_VALIDATE,
            stage_artifacts=[],
            job_manifest_checksum=_PLACEHOLDER_CHECKSUM,
        )
        return with_canonical_checksum(draft, "job_manifest_checksum")

    def list_jobs(self, project_id: str) -> list[JobManifest]:
        """Job của một project, sắp theo job_id."""
        if self.persistence is not None:
            return self.persistence.list_jobs(project_id)
        self.get_project(project_id)
        return [self._jobs[key] for key in sorted(self._project_jobs.get(project_id, []))]

    def get_job(self, job_id: str) -> JobManifest:
        """Lấy một job, ném JobNotFoundError nếu không có."""
        if self.persistence is not None:
            return self.persistence.get_job(job_id)
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise JobNotFoundError(f"không tìm thấy job: {job_id}") from error

    # --- artifacts --------------------------------------------------------

    def get_preview(self, job_id: str) -> ReconstructionPreview:
        """Raw 3DGS preview trước SceneIR; không ngụ ý metric đã confirmed."""
        return load_job_preview(self.get_job(job_id), self.runtime_resolver)

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
        return self.resolve_artifact(job_id, reference).read_bytes()

    def authorized_artifact(self, job_id: str, reference: ArtifactRef) -> ArtifactRef:
        """Ref canonical nếu URI thuộc allow-list của job và checksum khớp; không đọc bytes."""
        canonical = self._product_visible_references(job_id).get(reference.artifact_uri)
        if canonical is None:
            raise ArtifactNotFoundError("Artifact không thuộc allow-list của job")
        if canonical.artifact_checksum != reference.artifact_checksum:
            raise ArtifactChecksumError("Artifact checksum không khớp reference đã publish")
        return canonical

    def presigned_artifact_url(self, job_id: str, reference: ArtifactRef, expires_seconds: int) -> str | None:
        """Link tải thẳng từ kho file cho artifact đã kiểm quyền; None khi không có kho file
        hoặc object chưa lên kho (dữ liệu cũ) — khi đó API tự phục vụ file."""
        remote = self.runtime_resolver.remote
        if remote is None or job_id == self._fixture_job_id:
            return None
        canonical = self.authorized_artifact(job_id, reference)
        key = self.runtime_resolver.relative_key(canonical.artifact_uri)
        if remote.store.head(remote.key(key)) is None:
            return None
        return remote.presign(key, expires_seconds)

    def resolve_artifact(self, job_id: str, reference: ArtifactRef) -> Path:
        """Resolve ref canonical, không dùng checksum do client chọn làm authority."""
        canonical = self.authorized_artifact(job_id, reference)
        try:
            return self.runtime_resolver.require(canonical)
        except ArtifactNotFoundError:
            if job_id != self._fixture_job_id:
                raise
            return self.resolver.require(canonical)

    def _product_visible_references(self, job_id: str) -> dict[str, ArtifactRef]:
        """URI được phép tải: artifact của job cộng ref hình học trong SceneIR.

        Ref của SceneIR là `ProductArtifactRef` nên contract chỉ cho `product_input`
        hoặc `derived` đi qua — thêm chúng vào allow-list không mở đường cho
        `ground_truth`/`evaluation_only`.
        """
        references: list[ArtifactRef] = list(self.list_job_artifacts(job_id)[0])
        if any(reference.artifact_type == "ReconstructionPreview" for reference in references):
            preview = self.get_preview(job_id)
            references.extend((preview.source_visual_ref, preview.camera_pose_ref, preview.delivery_ref))
        references.extend(self.scene.artifact_references_for_job(job_id))
        if job_id != self._fixture_job_id:
            # Lớp xem từng bước (ADR 0005): ảnh frame và ref trong ReconstructionBundle.
            from src.services.orchestration.jobs.stage_views import view_references

            references.extend(view_references(self, self.get_job(job_id)))
        if job_id == self._fixture_job_id:
            visual = self.scene.visual_binding(job_id)
            if visual.reference is not None:
                references.append(visual.reference)
        indexed: dict[str, ArtifactRef] = {}
        for ref in references:
            if ref.data_class not in PRODUCT_VISIBLE_DATA_CLASSES:
                continue
            previous = indexed.get(ref.artifact_uri)
            if previous and previous.artifact_checksum != ref.artifact_checksum:
                raise ArtifactChecksumError("Một URI có nhiều checksum trong allow-list")
            indexed[ref.artifact_uri] = ref
        return indexed

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
    """API luôn dùng durable state; fixture phải được bật rõ trong Settings."""
    settings = get_settings()
    profile = (
        ExecutionProfile.load(
            settings.product_processing_config, settings.product_runtime_manifest, settings.product_seed
        )
        if settings.product_processing_config is not None and settings.product_runtime_manifest is not None
        else None
    )
    registry = ProjectRegistry(
        runtime_root=settings.artifact_root,
        database=RuntimeDatabase(settings.database_url),
        execution_profile=profile,
        remote=artifact_remote(settings),
    )
    if settings.product_fixture_mode:
        registry.seed_from_fixtures()
    return registry
