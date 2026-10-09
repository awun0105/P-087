"""Project là state DB; JobManifest bất biến là authority, DB giữ con trỏ revision.

Publish artifact trước, commit con trỏ + event trong cùng transaction. Crash trước
commit chỉ để lại artifact mồ côi, không tạo job thành công giả hoặc ghi đè revision.
"""

from datetime import UTC, datetime

from src.models.contracts.artifacts import ArtifactRef, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.input_assembly import (
    CandidateState,
    InputAssemblySnapshot,
    InputRecipe,
    InputResolutionReport,
    RuntimeQualificationRegistry,
    VideoRecipeCandidate,
    verify_input_assembly_checksum,
    verify_input_recipe_checksum,
    verify_input_resolution_checksum,
    verify_runtime_registry_checksum,
)
from src.models.contracts.manifests import InputFile, JobManifest, JobStatus
from src.services.orchestration.artifacts import ArtifactChecksumError, ArtifactResolver
from src.services.orchestration.auth.quota_ledger import (
    GuestQuotaIntent,
    GuestQuotaIntentResult,
    accept_guest_quota_intent,
    lookup_guest_quota_intent,
)
from src.services.orchestration.inputs.assembly import InputResolutionRecord, StoredInputAssembly
from src.services.orchestration.inputs.runs import (
    InputAssemblyRunCommit,
    InputAssemblyRunRecord,
    InputAssemblyRunResult,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.errors import JobNotFoundError, ProjectNotFoundError
from src.services.orchestration.projects.models import ProjectRecord
from src.services.orchestration.projects.privacy import require_project_dispatch
from src.services.orchestration.uploads.assembly_models import StagedInputUploadRecord


class _InputRunReplayError(RuntimeError):
    """Private rollback signal when another request already committed this idempotency key."""

    def __init__(self, result: InputAssemblyRunResult) -> None:
        super().__init__("input run already accepted")
        self.result = result


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
        input_assembly_run: InputAssemblyRunCommit | None = None,
    ) -> GuestQuotaIntentResult | InputAssemblyRunResult | None:
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
        verified_input_chain: (
            tuple[InputAssemblySnapshot, InputResolutionReport, RuntimeQualificationRegistry] | None
        ) = None
        if input_assembly_run is not None:
            if project_to_create is None:
                raise ValueError("Input assembly runs require a new project in the same transaction")
            verified_input_chain = self._validate_input_run_artifacts(manifest, project_to_create, input_assembly_run)
        elif project_to_create is not None and project_to_create.input_recipe_ref is not None:
            raise ValueError("A project with an accepted input recipe requires its atomic run record")
        expected_upload_sources: dict[str, InputFile] = {}
        if input_assembly_run is not None and verified_input_chain is not None:
            from src.models.contracts.input_assembly import InputRole, RecipeGroup

            assembly, report, _ = verified_input_chain
            candidate = next(
                item
                for item in report.candidates
                if isinstance(item, VideoRecipeCandidate) and item.candidate_id == input_assembly_run.candidate_id
            )
            by_file_id = {item.file_id: item for item in assembly.files}
            role_bindings = {binding.role: binding.file_ids for binding in candidate.bindings}
            selected_file_ids = set(role_bindings.get(InputRole.RGB_VIDEO, []))
            if candidate.recipe_group == RecipeGroup.SUPPLIED_TRAJECTORY:
                selected_file_ids.update(role_bindings.get(InputRole.LIDAR_SCAN, []))
            for file_id in selected_file_ids:
                staged = by_file_id[file_id]
                existing = expected_upload_sources.setdefault(staged.upload_id, staged.source_file)
                if existing != staged.source_file:
                    raise ArtifactChecksumError("Assembly members disagree on their source upload identity")
            if set(expected_upload_sources) != set(upload_ids_to_link):
                raise ValueError("Linked product uploads must match the exact accepted recipe bindings")
        quota_result: GuestQuotaIntentResult | None = None
        try:
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

                if input_assembly_run is not None:
                    replay = self._input_run_result(tx, input_assembly_run)
                    if replay is not None:
                        raise _InputRunReplayError(replay)

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
                            expected_source = expected_upload_sources.get(upload_id)
                            if input_assembly_run is not None and (
                                expected_source is None
                                or upload.original_name != expected_source.original_name
                                or upload.media_type != expected_source.media_type
                                or upload.size_bytes != expected_source.size_bytes
                                or upload.checksum != expected_source.checksum
                                or upload.artifact_uri != expected_source.artifact_uri
                            ):
                                raise ArtifactChecksumError(
                                    "Legacy upload row changed after the accepted input assembly was resolved"
                                )
                            if project.project_id in upload.project_ids:
                                raise RuntimeStateConflictError("project đã được gắn với upload này")
                            linked = upload.model_copy(
                                update={"project_ids": [*upload.project_ids, project.project_id]}
                            )
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
                if input_assembly_run is not None:
                    if verified_input_chain is None:
                        raise AssertionError("validated input chain missing")
                    self._commit_input_assembly_run(
                        tx,
                        manifest,
                        project,
                        input_assembly_run,
                        verified_input_chain,
                    )
        except _InputRunReplayError as replay:
            return replay.result
        return quota_result

    def _validate_input_run_artifacts(
        self,
        manifest: JobManifest,
        project: ProjectRecord,
        commit: InputAssemblyRunCommit,
    ) -> tuple[InputAssemblySnapshot, InputResolutionReport, RuntimeQualificationRegistry]:
        """Validate every published artifact link before opening the atomic state transaction."""
        from src.models.contracts.input_assembly import RecipeGroup, RuntimeCapabilityKey, RuntimeQualificationStatus

        references = (
            project.input_assembly_ref,
            project.input_resolution_ref,
            project.input_recipe_ref,
            project.input_runtime_registry_ref,
        )
        if any(reference is None for reference in references):
            raise ValueError("Input assembly project is missing an immutable evidence reference")
        assembly_ref, resolution_ref, recipe_ref, runtime_ref = references
        if recipe_ref != commit.recipe_ref:
            raise ValueError("Input run commit does not name the project's exact recipe artifact")
        if any(reference.job_id != project.project_id for reference in references if reference is not None):
            raise ValueError("Input assembly artifacts must live in the project's immutable namespace")
        if manifest.config_checksum is None:
            raise ValueError("An accepted input recipe requires a checksummed job config")
        assembly = self.resolver.load_model(assembly_ref, InputAssemblySnapshot)
        report = self.resolver.load_model(resolution_ref, InputResolutionReport)
        recipe = self.resolver.load_model(recipe_ref, InputRecipe)
        runtime_registry = self.resolver.load_model(runtime_ref, RuntimeQualificationRegistry)
        verify_input_assembly_checksum(assembly)
        verify_input_resolution_checksum(report)
        verify_input_recipe_checksum(recipe)
        verify_runtime_registry_checksum(runtime_registry)
        if (
            assembly.assembly_id != commit.assembly_id
            or assembly.revision != commit.assembly_revision
            or assembly.assembly_checksum != commit.assembly_checksum
            or report.assembly_id != assembly.assembly_id
            or report.assembly_revision != assembly.revision
            or report.assembly_checksum != assembly.assembly_checksum
            or report.report_checksum != commit.resolution_checksum
            or report.runtime_registry_checksum != runtime_registry.registry_checksum
        ):
            raise ValueError("Input assembly, resolution, and runtime refs do not form one exact evidence chain")
        selected = next((item for item in report.candidates if item.candidate_id == commit.candidate_id), None)
        if not isinstance(selected, VideoRecipeCandidate) or selected.state != CandidateState.READY:
            raise ValueError("Input run requires one exact ready video recipe candidate")
        if (
            selected.recipe_group
            not in {
                RecipeGroup.RGB_ONLY,
                RecipeGroup.SUPPLIED_TRAJECTORY,
                RecipeGroup.ESTIMATED_TRAJECTORY,
                RecipeGroup.SENSOR_GUIDED,
            }
            or selected.runtime.status != RuntimeQualificationStatus.QUALIFIED
        ):
            raise ValueError("Input recipe has no qualified worker adapter")
        if (
            recipe.assembly_id != assembly.assembly_id
            or recipe.assembly_revision != assembly.revision
            or recipe.assembly_checksum != assembly.assembly_checksum
            or recipe.resolution_checksum != report.report_checksum
            or recipe.candidate_id != selected.candidate_id
            or recipe.recipe_group != selected.recipe_group
            or recipe.bindings != selected.bindings
            or recipe.excluded_file_ids != selected.excluded_file_ids
            or recipe.trajectory_origin != selected.trajectory_origin
            or recipe.recipe_checksum != commit.recipe_checksum
            or recipe.config_checksum != manifest.config_checksum
        ):
            raise ValueError("Accepted recipe does not match the ready candidate and queued job")
        if selected.recipe_group in {RecipeGroup.ESTIMATED_TRAJECTORY, RecipeGroup.SENSOR_GUIDED}:
            from src.services.reconstruction.lidar.odometry import (
                DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION,
                lidar_odometry_profile_checksum,
            )

            capabilities = {item.capability_key: item for item in runtime_registry.capabilities}
            odometry_runtime = capabilities.get(RuntimeCapabilityKey.R5)
            profile = next(
                (item for item in recipe.component_versions if item.component_id == "odometry-profile"), None
            )
            if (
                odometry_runtime is None
                or odometry_runtime.status != RuntimeQualificationStatus.QUALIFIED
                or profile is None
                or profile.version != DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION
                or profile.config_checksum != lidar_odometry_profile_checksum()
            ):
                raise ValueError("Estimated input recipe requires the exact qualified R5 runtime and odometry profile")
            if selected.recipe_group == RecipeGroup.SENSOR_GUIDED:
                odometry_component = next(
                    (
                        item
                        for item in recipe.component_versions
                        if item.component_id == f"runtime-R5-{odometry_runtime.runtime_id}"
                    ),
                    None,
                )
                if (
                    odometry_component is None
                    or odometry_component.version != odometry_runtime.runtime_version
                    or odometry_component.config_checksum != odometry_runtime.qualification_evidence_checksum
                ):
                    raise ValueError("R6 input recipe must bind its exact R5 odometry runtime")
        return assembly, report, runtime_registry

    @staticmethod
    def _input_run_result(tx: RuntimeTransaction, commit: InputAssemblyRunCommit) -> InputAssemblyRunResult | None:
        """Read an earlier key while holding the transaction write lock."""
        row = tx.execute(
            "SELECT request_fingerprint,job_id,project_id,payload FROM r2s_input_runs "
            "WHERE requester_id=? AND idempotency_key=?" + tx.lock_suffix(),
            (commit.requester_id, commit.idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row[0] != commit.request_fingerprint:
            raise RuntimeStateConflictError("Idempotency-Key đã được dùng cho input run khác")
        record = InputAssemblyRunRecord.model_validate_json(row[3])
        if record.job_id != row[1] or record.project_id != row[2]:
            raise ArtifactChecksumError("Input run key không khớp durable record identity")
        return InputAssemblyRunResult(job_id=record.job_id, project_id=record.project_id, replayed=True)

    def lookup_input_run(
        self, requester_id: str, idempotency_key: str, request_fingerprint: str
    ) -> InputAssemblyRunResult | None:
        """Resolve an already accepted input Run before mutable upload or runtime checks."""
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT request_fingerprint,job_id,project_id,payload FROM r2s_input_runs "
                "WHERE requester_id=? AND idempotency_key=?",
                (requester_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        if row[0] != request_fingerprint:
            raise RuntimeStateConflictError("Idempotency-Key đã được dùng cho input run khác")
        record = InputAssemblyRunRecord.model_validate_json(row[3])
        if record.job_id != row[1] or record.project_id != row[2]:
            raise ArtifactChecksumError("Input run key không khớp durable record identity")
        return InputAssemblyRunResult(job_id=record.job_id, project_id=record.project_id, replayed=True)

    def input_run_for_job(self, job_id: str) -> InputAssemblyRunRecord | None:
        """Resolve the immutable input lineage accepted for one exact job, if any."""
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT requester_id,idempotency_key,request_fingerprint,job_id,project_id,assembly_id,revision,"
                "report_checksum,recipe_checksum,recipe_ref,payload "
                "FROM r2s_input_runs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        record = InputAssemblyRunRecord.model_validate_json(row[10])
        recipe_ref = ProductArtifactRef.model_validate_json(row[9])
        expected = (
            record.requester_id,
            record.idempotency_key,
            record.request_fingerprint,
            record.job_id,
            record.project_id,
            record.assembly_id,
            record.assembly_revision,
            record.resolution_checksum,
            record.recipe_checksum,
        )
        if tuple(row[:9]) != expected or recipe_ref != record.recipe_ref or record.job_id != job_id:
            raise ArtifactChecksumError("Input run columns differ from the durable job-lineage record")
        return record

    def _commit_input_assembly_run(
        self,
        tx: RuntimeTransaction,
        manifest: JobManifest,
        project: ProjectRecord,
        commit: InputAssemblyRunCommit,
        verified_input_chain: tuple[InputAssemblySnapshot, InputResolutionReport, RuntimeQualificationRegistry],
    ) -> None:
        """Lock and link the immutable assembly evidence and staged uploads with its first job."""
        assembly, report, runtime_registry = verified_input_chain
        assembly_row = tx.execute(
            "SELECT owner_id,payload FROM r2s_input_assemblies WHERE assembly_id=? AND revision=?" + tx.lock_suffix(),
            (commit.assembly_id, commit.assembly_revision),
        ).fetchone()
        head = tx.execute(
            "SELECT revision FROM r2s_input_assembly_heads WHERE assembly_id=?" + tx.lock_suffix(),
            (commit.assembly_id,),
        ).fetchone()
        if assembly_row is None or head is None or int(head[0]) != commit.assembly_revision:
            raise RuntimeStateConflictError("Input assembly revision changed or disappeared before Run acceptance")
        stored_assembly = StoredInputAssembly.model_validate_json(assembly_row[1])
        if (
            assembly_row[0] != assembly.owner_id
            or stored_assembly.snapshot != assembly
            or assembly.assembly_id != commit.assembly_id
            or assembly.revision != commit.assembly_revision
            or assembly.assembly_checksum != commit.assembly_checksum
        ):
            raise ArtifactChecksumError("Input assembly artifact differs from its immutable database revision")
        resolution_row = tx.execute(
            "SELECT assembly_id,revision,owner_id,payload FROM r2s_input_resolutions WHERE report_checksum=?"
            + tx.lock_suffix(),
            (commit.resolution_checksum,),
        ).fetchone()
        if resolution_row is None:
            raise RuntimeStateConflictError("Input resolution disappeared before Run acceptance")
        stored_resolution = InputResolutionRecord.model_validate_json(resolution_row[3])
        if (
            stored_resolution.report != report
            or stored_resolution.runtime_registry != runtime_registry
            or resolution_row[0] != assembly.assembly_id
            or int(resolution_row[1]) != assembly.revision
            or resolution_row[2] != assembly.owner_id
            or report.report_checksum != commit.resolution_checksum
        ):
            raise ArtifactChecksumError("Input resolution row differs from the report/runtime artifacts")
        expected_upload_ids = tuple(sorted({item.upload_id for item in assembly.files}))
        if tuple(sorted(commit.staged_upload_ids)) != expected_upload_ids:
            raise ValueError("Run must bind every staged upload referenced by the exact assembly revision")
        probes_by_id = {item.file_id: item for item in stored_assembly.probes}
        for upload_id in expected_upload_ids:
            upload_row = tx.execute(
                "SELECT payload FROM r2s_input_uploads WHERE upload_id=?" + tx.lock_suffix(),
                (upload_id,),
            ).fetchone()
            if upload_row is None:
                raise ProjectNotFoundError(f"Không tìm thấy staged upload cần gắn project: {upload_id}")
            staged = StagedInputUploadRecord.model_validate_json(upload_row[0])
            expected_files = sorted(
                [item for item in assembly.files if item.upload_id == upload_id], key=lambda item: item.file_id
            )
            expected_probes = sorted(
                [probes_by_id[item.file_id] for item in expected_files], key=lambda item: item.file_id
            )
            if (
                not expected_files
                or staged.source_file != expected_files[0].source_file
                or sorted(staged.staged_files, key=lambda item: item.file_id) != expected_files
                or sorted(staged.probes, key=lambda item: item.file_id) != expected_probes
            ):
                raise ArtifactChecksumError("Staged upload record changed after the assembly revision was created")
            if project.project_id in staged.project_ids:
                raise RuntimeStateConflictError("project đã được gắn với staged upload này")
            linked = staged.model_copy(update={"project_ids": [*staged.project_ids, project.project_id]})
            tx.execute(
                "UPDATE r2s_input_uploads SET payload=? WHERE upload_id=?",
                (linked.model_dump_json(), upload_id),
            )
        record = InputAssemblyRunRecord(
            requester_id=commit.requester_id,
            idempotency_key=commit.idempotency_key,
            request_fingerprint=commit.request_fingerprint,
            job_id=manifest.job_id,
            project_id=project.project_id,
            assembly_id=commit.assembly_id,
            assembly_revision=commit.assembly_revision,
            assembly_checksum=commit.assembly_checksum,
            resolution_checksum=commit.resolution_checksum,
            candidate_id=commit.candidate_id,
            recipe_checksum=commit.recipe_checksum,
            recipe_ref=commit.recipe_ref,
            accepted_at=datetime.now(UTC),
        )
        inserted = tx.execute(
            "INSERT INTO r2s_input_runs "
            "(requester_id,idempotency_key,request_fingerprint,job_id,project_id,assembly_id,revision,"
            "report_checksum,recipe_checksum,recipe_ref,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (
                record.requester_id,
                record.idempotency_key,
                record.request_fingerprint,
                record.job_id,
                record.project_id,
                record.assembly_id,
                record.assembly_revision,
                record.resolution_checksum,
                record.recipe_checksum,
                record.recipe_ref.model_dump_json(),
                record.model_dump_json(),
            ),
        )
        if inserted.rowcount != 1:
            replay = self._input_run_result(tx, commit)
            if replay is not None:
                raise _InputRunReplayError(replay)
            raise RuntimeStateConflictError("Input run could not reserve its idempotency identity")

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
