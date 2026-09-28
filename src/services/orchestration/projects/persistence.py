"""Project là state DB; JobManifest bất biến là authority, DB giữ con trỏ revision.

Publish artifact trước, commit con trỏ + event trong cùng transaction. Crash trước
commit chỉ để lại artifact mồ côi, không tạo job thành công giả hoặc ghi đè revision.
"""

from src.models.contracts.artifacts import ArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import JobManifest, JobStatus
from src.services.orchestration.artifacts import ArtifactChecksumError, ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.errors import JobNotFoundError, ProjectNotFoundError
from src.services.orchestration.projects.models import ProjectRecord
from src.services.orchestration.projects.privacy import require_dispatch_allowed


class ProjectPersistence:
    """Read-through DB, không cache state process-local của project/job thật."""

    def __init__(self, database: RuntimeDatabase, resolver: ArtifactResolver) -> None:
        self.database = database
        self.resolver = resolver

    def save_project(
        self, project: ProjectRecord, *, expected: ProjectRecord | None = None, seed: bool = False
    ) -> None:
        """Insert mới hoặc compare-and-swap; seed không bao giờ đè dữ liệu đã tồn tại."""
        self._project(project.model_dump_json())
        if expected is not None and expected.project_id != project.project_id:
            raise ValueError("Project CAS identity không khớp")
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_projects WHERE project_id=?" + tx.lock_suffix(), (project.project_id,)
            ).fetchone()
            if expected is not None:
                if row is None or row[0] != expected.model_dump_json():
                    raise RuntimeStateConflictError("Project đã thay đổi; đọc lại trước khi cập nhật")
                tx.execute(
                    "UPDATE r2s_projects SET payload=? WHERE project_id=?",
                    (project.model_dump_json(), project.project_id),
                )
            elif row is None:
                changed = tx.execute(
                    "INSERT INTO r2s_projects(project_id,payload) VALUES (?,?) ON CONFLICT(project_id) DO NOTHING",
                    (project.project_id, project.model_dump_json()),
                ).rowcount
                if not changed and not seed:
                    raise RuntimeStateConflictError("Project ID đã được process khác tạo")
            elif not seed:
                raise RuntimeStateConflictError("Project ID đã tồn tại")

    def get_project(self, project_id: str) -> ProjectRecord:
        """Load typed state mới nhất, kể cả khi worker/API khác process đã cập nhật."""
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise ProjectNotFoundError("Không tìm thấy project")
        project = self._project(row[0])
        if project.project_id != project_id:
            raise ArtifactChecksumError("Project key khác payload identity")
        return project

    def list_projects(self) -> list[ProjectRecord]:
        """Danh sách xác định theo ID; không seed fixture lại trên mỗi GET."""
        with self.database.transaction() as tx:
            rows = tx.execute("SELECT payload FROM r2s_projects ORDER BY project_id").fetchall()
        return [self._project(row[0]) for row in rows]

    @staticmethod
    def _project(payload: str) -> ProjectRecord:
        project = ProjectRecord.model_validate_json(payload)
        report = project.privacy_report
        if report.report_checksum != canonical_content_checksum(report, "report_checksum"):
            raise ArtifactChecksumError("Privacy report checksum trong runtime database không khớp")
        if report.input_manifest_checksum != project.input_manifest_checksum:
            raise ArtifactChecksumError("Privacy report không thuộc input của project")
        return project

    def save_job(
        self,
        manifest: JobManifest,
        reference: ArtifactRef,
        event: JobAttemptRecord,
        *,
        expected: JobManifest | None = None,
        seed: bool = False,
    ) -> None:
        """CAS job pointer và append event atomically; không tự retry command stale."""
        if self._job(reference.model_dump_json()) != manifest:
            raise ArtifactChecksumError("Published JobManifest khác state đang commit")
        if (
            event.job_manifest_uri != reference.artifact_uri
            or event.job_manifest_checksum != reference.artifact_checksum
            or event.status != manifest.status
            or event.current_stage != manifest.current_stage
        ):
            raise ValueError("Job event phải bind đúng revision đã publish")
        with self.database.transaction(write=True) as tx:
            project_row = tx.execute(
                "SELECT payload FROM r2s_projects WHERE project_id=?" + tx.lock_suffix(), (manifest.project_id,)
            ).fetchone()
            if project_row is None:
                raise ProjectNotFoundError("Không tìm thấy project của job")
            project = self._project(project_row[0])
            if manifest.input_manifest_checksum != project.input_manifest_checksum:
                raise ValueError("Job không thuộc input của project")
            row = tx.execute(
                "SELECT version, manifest_ref FROM r2s_jobs WHERE job_id=?" + tx.lock_suffix(), (manifest.job_id,)
            ).fetchone()
            if row is not None:
                if seed:
                    return
                current = self._job(row[1])
                if (
                    expected is None
                    or current.job_manifest_checksum != expected.job_manifest_checksum
                    or current.project_id != manifest.project_id
                    or expected.job_id != manifest.job_id
                ):
                    raise RuntimeStateConflictError("Job đã thay đổi; command cần revision mới nhất")
                for field in (
                    "input_manifest_checksum",
                    "config_checksum",
                    "runtime_manifest_checksum",
                    "seed",
                    "started_at",
                ):
                    if getattr(current, field) != getattr(manifest, field):
                        raise ValueError("Job revision không được thay source/config/runtime identity")
                previous_row = tx.execute(
                    "SELECT payload FROM r2s_job_events WHERE job_id=? AND version=?", (manifest.job_id, row[0])
                ).fetchone()
                if previous_row is None:
                    raise RuntimeStateConflictError("Job thiếu event của revision hiện tại")
                previous = JobAttemptRecord.model_validate_json(previous_row[0])
                retry = current.status == JobStatus.FAILED and manifest.status == JobStatus.QUEUED
                if event.attempt != previous.attempt + int(retry):
                    raise ValueError("Attempt number không khớp journal/retry")
                version = row[0] + 1
                tx.execute(
                    "UPDATE r2s_jobs SET version=?, manifest_ref=? WHERE job_id=?",
                    (version, reference.model_dump_json(), manifest.job_id),
                )
            else:
                if expected is not None:
                    raise RuntimeStateConflictError("Job không còn tồn tại")
                if not seed:
                    require_dispatch_allowed(project.privacy_report.result)
                if event.attempt != 1:
                    raise ValueError("Job mới phải bắt đầu ở attempt 1")
                version = 1
                changed = tx.execute(
                    "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref) VALUES (?,?,?,?) ON CONFLICT(job_id) DO NOTHING",
                    (manifest.job_id, manifest.project_id, version, reference.model_dump_json()),
                ).rowcount
                if not changed:
                    if seed:
                        return
                    raise RuntimeStateConflictError("Job ID đã được process khác tạo")
            tx.execute(
                "INSERT INTO r2s_job_events(job_id,version,payload) VALUES (?,?,?)",
                (manifest.job_id, version, event.model_dump_json()),
            )

    def get_job(self, job_id: str) -> JobManifest:
        """Đọc manifest được DB commit và verify exact bytes trước khi phục vụ UI."""
        with self.database.transaction() as tx:
            row = tx.execute("SELECT manifest_ref FROM r2s_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError("Không tìm thấy job")
        job = self._job(row[0])
        if job.job_id != job_id:
            raise ArtifactChecksumError("Job key khác manifest identity")
        return job

    def _job(self, payload: str) -> JobManifest:
        reference = ArtifactRef.model_validate_json(payload)
        if reference.artifact_type != "JobManifest" or not reference.artifact_uri.startswith(
            f"artifact://jobs/{reference.job_id}/manifests/"
        ):
            raise ArtifactChecksumError("Job pointer không trỏ tới JobManifest thuộc job")
        job = self.resolver.load_model(reference, JobManifest)
        if reference.job_id != job.job_id or job.job_manifest_checksum != canonical_content_checksum(
            job, "job_manifest_checksum"
        ):
            raise ArtifactChecksumError("JobManifest identity/canonical checksum không khớp")
        return job

    def list_jobs(self, project_id: str) -> list[JobManifest]:
        """Chỉ lấy jobs thuộc project, không scan filesystem artifact."""
        self.get_project(project_id)
        with self.database.transaction() as tx:
            rows = tx.execute(
                "SELECT manifest_ref FROM r2s_jobs WHERE project_id=? ORDER BY job_id", (project_id,)
            ).fetchall()
        return [self._job(row[0]) for row in rows]

    def list_attempts(self, job_id: str) -> list[JobAttemptRecord]:
        """Event journal nối thêm; restart không đánh số attempt lại từ một."""
        self.get_job(job_id)
        with self.database.transaction() as tx:
            rows = tx.execute(
                "SELECT payload FROM r2s_job_events WHERE job_id=? ORDER BY version", (job_id,)
            ).fetchall()
        return [JobAttemptRecord.model_validate_json(row[0]) for row in rows]
