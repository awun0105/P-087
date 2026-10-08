"""Project là state DB; JobManifest bất biến là authority, DB giữ con trỏ revision.

Publish artifact trước, commit con trỏ + event trong cùng transaction. Crash trước
commit chỉ để lại artifact mồ côi, không tạo job thành công giả hoặc ghi đè revision.
"""

from src.models.contracts.artifacts import ArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import JobManifest, JobStatus
from src.services.orchestration.artifacts import ArtifactChecksumError, ArtifactResolver
from src.services.orchestration.auth.quota_ledger import (
    GuestQuotaIntent,
    GuestQuotaIntentResult,
    accept_guest_quota_intent,
    lookup_guest_quota_intent,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.errors import JobNotFoundError, ProjectNotFoundError
from src.services.orchestration.projects.models import ProjectRecord
from src.services.orchestration.projects.privacy import require_project_dispatch


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
                old_owner = expected.created_by.user_id if expected.created_by is not None else None
                new_owner = project.created_by.user_id if project.created_by is not None else None
                if old_owner != new_owner:
                    raise ValueError("Project creator không được thay đổi sau khi tạo")
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
        owner_user_id: str | None = None,
        quota_intent: GuestQuotaIntent | None = None,
        project_to_create: ProjectRecord | None = None,
        upload_ids_to_link: tuple[str, ...] = (),
    ) -> GuestQuotaIntentResult | None:
        """Commit quota, accepted job/CAS, and optional upload project atomically."""
        if self._job(reference.model_dump_json()) != manifest:
            raise ArtifactChecksumError("Published JobManifest khác state đang commit")
        if (
            event.job_manifest_uri != reference.artifact_uri
            or event.job_manifest_checksum != reference.artifact_checksum
            or event.status != manifest.status
            or event.current_stage != manifest.current_stage
        ):
            raise ValueError("Job event phải bind đúng revision đã publish")
        if project_to_create is not None and project_to_create.project_id != manifest.project_id:
            raise ValueError("New project identity must match the job")
        if upload_ids_to_link and project_to_create is None:
            raise ValueError("Upload links may only be committed with their new project")
        quota_result: GuestQuotaIntentResult | None = None
        with self.database.transaction(write=True) as tx:
            if quota_intent is not None:
                quota_result = accept_guest_quota_intent(
                    tx,
                    quota_intent,
                    result_kind="job",
                    result_id=manifest.job_id,
                    result_reference=reference.model_dump_json(),
                )
                if quota_result.replayed:
                    return quota_result

            if project_to_create is not None:
                self._project(project_to_create.model_dump_json())
                inserted_project = tx.execute(
                    "INSERT INTO r2s_projects(project_id,payload) VALUES (?,?) ON CONFLICT(project_id) DO NOTHING",
                    (project_to_create.project_id, project_to_create.model_dump_json()),
                )
                if inserted_project.rowcount != 1:
                    raise RuntimeStateConflictError("Project ID đã được process khác tạo")
                project = project_to_create
                if upload_ids_to_link:
                    from src.services.orchestration.uploads.models import UploadRecord

                    for upload_id in sorted(set(upload_ids_to_link)):
                        upload_row = tx.execute(
                            "SELECT payload FROM r2s_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
                        ).fetchone()
                        if upload_row is None:
                            raise ProjectNotFoundError(f"Không tìm thấy upload cần gắn project: {upload_id}")
                        upload = UploadRecord.model_validate_json(upload_row[0])
                        if project.project_id in upload.project_ids:
                            raise RuntimeStateConflictError("project đã được gắn với upload này")
                        linked = upload.model_copy(update={"project_ids": [*upload.project_ids, project.project_id]})
                        tx.execute(
                            "UPDATE r2s_uploads SET payload=? WHERE upload_id=?",
                            (linked.model_dump_json(), upload_id),
                        )
            else:
                project_row = tx.execute(
                    "SELECT payload FROM r2s_projects WHERE project_id=?" + tx.lock_suffix(), (manifest.project_id,)
                ).fetchone()
                if project_row is None:
                    raise ProjectNotFoundError("Không tìm thấy project của job")
                project = self._project(project_row[0])
            if manifest.input_manifest_checksum != project.input_manifest_checksum:
                raise ValueError("Job không thuộc input của project")
            if manifest.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                require_project_dispatch(project)
            row = tx.execute(
                "SELECT version, manifest_ref, owner_user_id FROM r2s_jobs WHERE job_id=?" + tx.lock_suffix(),
                (manifest.job_id,),
            ).fetchone()
            if row is not None:
                if seed:
                    return
                if owner_user_id is not None and row[2] != owner_user_id:
                    raise RuntimeStateConflictError("Job owner không được thay đổi sau khi tạo")
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
                    require_project_dispatch(project)
                if event.attempt != 1:
                    raise ValueError("Job mới phải bắt đầu ở attempt 1")
                version = 1
                changed = tx.execute(
                    "INSERT INTO r2s_jobs(job_id,project_id,version,manifest_ref,owner_user_id) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(job_id) DO NOTHING",
                    (manifest.job_id, manifest.project_id, version, reference.model_dump_json(), owner_user_id),
                ).rowcount
                if not changed:
                    if seed:
                        return
                    raise RuntimeStateConflictError("Job ID đã được process khác tạo")
            tx.execute(
                "INSERT INTO r2s_job_events(job_id,version,payload) VALUES (?,?,?)",
                (manifest.job_id, version, event.model_dump_json()),
            )
        return quota_result

    def lookup_quota_intent(self, intent: GuestQuotaIntent) -> GuestQuotaIntentResult | None:
        """Resolve an accepted Guest submission before revalidating current job state."""
        return lookup_guest_quota_intent(self.database, intent)

    def get_job_owner_user_id(self, job_id: str) -> str | None:
        """Return the immutable owner of a job, or None for legacy/anonymous jobs."""
        with self.database.transaction() as tx:
            row = tx.execute("SELECT owner_user_id FROM r2s_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError("Không tìm thấy job")
        return str(row[0]) if row[0] is not None else None

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

    def job_ids_after(self, cursor: str = "", limit: int = 100) -> list[str]:
        """Queue discovery theo trang; một manifest hỏng không chặn job khác.

        Không giữ transaction khi chạy worker. Status vẫn đọc từ manifest đã
        commit, không thêm cột queue có thể lệch khỏi lifecycle authority.
        """
        if not 1 <= limit <= 1000:
            raise ValueError("Page size phải nằm trong 1..1000")
        with self.database.transaction() as tx:
            rows = tx.execute(
                "SELECT job_id FROM r2s_jobs WHERE job_id>? ORDER BY job_id LIMIT ?", (cursor, limit)
            ).fetchall()
        return [row[0] for row in rows]

    def list_attempts(self, job_id: str) -> list[JobAttemptRecord]:
        """Event journal nối thêm; restart không đánh số attempt lại từ một."""
        self.get_job(job_id)
        with self.database.transaction() as tx:
            rows = tx.execute(
                "SELECT payload FROM r2s_job_events WHERE job_id=? ORDER BY version", (job_id,)
            ).fetchall()
        return [JobAttemptRecord.model_validate_json(row[0]) for row in rows]
