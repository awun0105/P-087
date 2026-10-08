"""Durable, run-specific validation evidence and selection protocol."""

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import RuntimeManifest
from src.models.contracts.validation import ValidationReport
from src.models.contracts.validation_run import (
    IsaacValidationRuntimeProfile,
    ValidationConfig,
    ValidationRunOrigin,
    ValidationRunRecord,
    ValidationRunSelection,
    ValidationRunStatus,
)
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction

ModelT = TypeVar("ModelT", bound=BaseModel)
SCHEMA_VERSION = "1.0"


class ValidationRunError(ValueError):
    """Persisted validation state is malformed or does not match its identity."""


class ValidationRunRepository:
    """Database-backed attempt history with immutable artifacts and CAS selection."""

    def __init__(self, database: RuntimeDatabase, resolver: ArtifactResolver) -> None:
        self.database = database
        self.resolver = resolver

    @staticmethod
    def config_uri(job_id: str, config_checksum: str) -> str:
        return _uri(job_id, "validation", "configs", _hex(config_checksum), "validation_config.json")

    @staticmethod
    def profile_uri(job_id: str, profile_checksum: str) -> str:
        return _uri(job_id, "validation", "profiles", _hex(profile_checksum), "isaac_validation_profile.json")

    @staticmethod
    def report_uri(job_id: str, candidate_checksum: str, config_checksum: str, run_id: str) -> str:
        return _uri(
            job_id,
            "validation",
            _hex(candidate_checksum),
            _hex(config_checksum),
            run_id,
            "validation_report.json",
        )

    @staticmethod
    def execution_log_uri(job_id: str, candidate_checksum: str, config_checksum: str, run_id: str) -> str:
        return _uri(
            job_id,
            "validation",
            _hex(candidate_checksum),
            _hex(config_checksum),
            run_id,
            "execution.log",
        )

    @staticmethod
    def runtime_manifest_uri(job_id: str, candidate_checksum: str, config_checksum: str, run_id: str) -> str:
        return _uri(
            job_id,
            "validation",
            _hex(candidate_checksum),
            _hex(config_checksum),
            run_id,
            "runtime_manifest.json",
        )

    def save_run(self, record: ValidationRunRecord, *, expected_run_checksum: str | None = None) -> None:
        """Insert a queued attempt or CAS-update it through its one-way lifecycle."""
        self._verify_model_checksum(record, "run_checksum")
        self._verify_references(record)
        with self.database.transaction(write=True) as tx:
            self.save_run_in_transaction(tx, record, expected_run_checksum=expected_run_checksum)

    def save_run_in_transaction(
        self,
        tx: RuntimeTransaction,
        record: ValidationRunRecord,
        *,
        expected_run_checksum: str | None = None,
    ) -> None:
        """Save a run inside its caller's transaction so queue and run state commit together."""
        self._verify_model_checksum(record, "run_checksum")
        self._verify_references(record)
        payload = record.model_dump_json()
        row = tx.execute(
            """SELECT run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload
               FROM r2s_validation_runs WHERE run_id=?"""
            + tx.lock_suffix(),
            (record.run_id,),
        ).fetchone()
        if row is None:
            if expected_run_checksum is not None:
                raise RuntimeStateConflictError("Validation run không tồn tại để cập nhật")
            if record.status != ValidationRunStatus.QUEUED:
                raise RuntimeStateConflictError("Validation run phải được tạo ở trạng thái QUEUED")
            changed = tx.execute(
                """INSERT INTO r2s_validation_runs
                   (run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload)
                   VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                (
                    record.run_id,
                    record.job_id,
                    record.candidate_checksum,
                    record.validation_config_checksum,
                    record.attempt,
                    record.status.value,
                    record.run_checksum,
                    payload,
                ),
            ).rowcount
            if not changed:
                raise RuntimeStateConflictError("Validation run ID hoặc attempt đã tồn tại")
            return

        previous = self._parse_run_row(row)
        if expected_run_checksum != previous.run_checksum:
            raise RuntimeStateConflictError("Validation run đã thay đổi; đọc lại trước khi cập nhật")
        self._validate_transition(previous, record)
        changed = tx.execute(
            """UPDATE r2s_validation_runs
               SET status=?,run_checksum=?,payload=? WHERE run_id=? AND run_checksum=?""",
            (record.status.value, record.run_checksum, payload, record.run_id, previous.run_checksum),
        ).rowcount
        if changed != 1:
            raise RuntimeStateConflictError("Validation run CAS thất bại")

    def get_run(self, run_id: str) -> ValidationRunRecord:
        with self.database.transaction() as tx:
            row = tx.execute(
                """SELECT run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload
                   FROM r2s_validation_runs WHERE run_id=?""",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ValidationRunError("Không tìm thấy validation run")
        record = self._parse_run_row(row)
        self._verify_references(record)
        return record

    def list_runs(self, job_id: str, candidate_checksum: str, config_checksum: str) -> list[ValidationRunRecord]:
        with self.database.transaction() as tx:
            rows = tx.execute(
                """SELECT run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload
                   FROM r2s_validation_runs
                   WHERE job_id=? AND candidate_checksum=? AND config_checksum=? ORDER BY attempt,run_id""",
                (job_id, candidate_checksum, config_checksum),
            ).fetchall()
        records = [self._parse_run_row(row) for row in rows]
        for record in records:
            self._verify_references(record)
        return records

    def select_run(
        self,
        job_id: str,
        candidate_checksum: str,
        config_checksum: str,
        run_id: str,
        *,
        expected_selected_run_id: str | None = None,
        selected_at: datetime | None = None,
    ) -> ValidationRunSelection:
        """Select only a completed worker run; retries never overwrite report bytes."""
        record = self.get_run(run_id)
        if (
            record.job_id != job_id
            or record.candidate_checksum != candidate_checksum
            or record.validation_config_checksum != config_checksum
        ):
            raise ValidationRunError("Validation run không khớp job/candidate/config được chọn")
        if record.origin != ValidationRunOrigin.WORKER or record.status != ValidationRunStatus.COMPLETED:
            raise ValidationRunError("Chỉ completed worker validation mới có thể được chọn")
        if not record.report_checksum:
            raise ValidationRunError("Validation run không có report checksum")

        identity = (job_id, candidate_checksum, config_checksum)
        with self.database.transaction(write=True) as tx:
            # Production jobs persist in r2s_jobs. Lock the stable parent row so
            # concurrent first selections with different policies cannot both win.
            tx.execute("SELECT job_id FROM r2s_jobs WHERE job_id=?" + tx.lock_suffix(), (job_id,)).fetchone()
            rows = tx.execute(
                """SELECT job_id,candidate_checksum,config_checksum,run_id,report_checksum,generation,
                          selection_checksum,payload FROM r2s_validation_selections
                   WHERE job_id=? AND candidate_checksum=?"""
                + tx.lock_suffix(),
                (job_id, candidate_checksum),
            ).fetchall()
            if len(rows) > 1:
                raise RuntimeStateConflictError("Có nhiều validation selection cho cùng một candidate")
            current = self._parse_selection_row(rows[0]) if rows else None
            if current is None:
                if expected_selected_run_id is not None:
                    raise RuntimeStateConflictError("Validation selection đã bị xóa hoặc thay đổi")
                generation = 1
            elif (
                current.validation_config_checksum == config_checksum
                and current.run_id == run_id
                and current.report_checksum == record.report_checksum
            ):
                return current
            else:
                if expected_selected_run_id != current.run_id:
                    raise RuntimeStateConflictError("Validation selection đã thay đổi; đọc lại trước khi cập nhật")
                generation = current.generation + 1

            selection = ValidationRunSelection(
                schema_version=SCHEMA_VERSION,
                job_id=job_id,
                candidate_checksum=candidate_checksum,
                validation_config_checksum=config_checksum,
                run_id=run_id,
                report_checksum=record.report_checksum,
                generation=generation,
                selected_at=selected_at or datetime.now(UTC),
                selection_checksum="sha256:" + "0" * 64,
            )
            selection = selection.model_copy(
                update={"selection_checksum": canonical_content_checksum(selection, "selection_checksum")}
            )
            payload = selection.model_dump_json()
            if current is not None and current.validation_config_checksum == config_checksum:
                changed = tx.execute(
                    """UPDATE r2s_validation_selections SET run_id=?,report_checksum=?,generation=?,
                       selection_checksum=?,payload=? WHERE job_id=? AND candidate_checksum=? AND config_checksum=?
                       AND run_id=? AND generation=?""",
                    (
                        run_id,
                        record.report_checksum,
                        generation,
                        selection.selection_checksum,
                        payload,
                        *identity,
                        current.run_id,
                        current.generation,
                    ),
                ).rowcount
            else:
                if current is not None:
                    changed = tx.execute(
                        """DELETE FROM r2s_validation_selections
                           WHERE job_id=? AND candidate_checksum=? AND config_checksum=? AND run_id=?
                           AND generation=? AND selection_checksum=?""",
                        (
                            current.job_id,
                            current.candidate_checksum,
                            current.validation_config_checksum,
                            current.run_id,
                            current.generation,
                            current.selection_checksum,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise RuntimeStateConflictError("Validation selection CAS thất bại")
                changed = tx.execute(
                    """INSERT INTO r2s_validation_selections
                       (job_id,candidate_checksum,config_checksum,run_id,report_checksum,generation,selection_checksum,payload)
                       VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                    (*identity, run_id, record.report_checksum, generation, selection.selection_checksum, payload),
                ).rowcount
            if changed != 1:
                raise RuntimeStateConflictError("Validation selection CAS thất bại")
        return selection

    def get_selection(
        self, job_id: str, candidate_checksum: str, config_checksum: str
    ) -> ValidationRunSelection | None:
        with self.database.transaction() as tx:
            row = tx.execute(
                """SELECT job_id,candidate_checksum,config_checksum,run_id,report_checksum,generation,
                          selection_checksum,payload FROM r2s_validation_selections
                   WHERE job_id=? AND candidate_checksum=? AND config_checksum=?""",
                (job_id, candidate_checksum, config_checksum),
            ).fetchone()
        if row is None:
            return None
        selection = self._parse_selection_row(row)
        if (
            selection.job_id != job_id
            or selection.candidate_checksum != candidate_checksum
            or selection.validation_config_checksum != config_checksum
        ):
            raise ValidationRunError("Validation selection database identity không khớp payload")
        record = self.get_run(selection.run_id)
        if (
            record.origin != ValidationRunOrigin.WORKER
            or record.status != ValidationRunStatus.COMPLETED
            or record.job_id != job_id
            or record.candidate_checksum != candidate_checksum
            or record.validation_config_checksum != config_checksum
            or record.report_checksum != selection.report_checksum
        ):
            raise ValidationRunError("Validation selection không trỏ tới completed worker report chính xác")
        return selection

    def get_selection_for_candidate(self, job_id: str, candidate_checksum: str) -> ValidationRunSelection | None:
        """Return the one active policy/run selection for a candidate, failing on ambiguity."""
        with self.database.transaction() as tx:
            rows = tx.execute(
                """SELECT job_id,candidate_checksum,config_checksum,run_id,report_checksum,generation,
                          selection_checksum,payload FROM r2s_validation_selections
                   WHERE job_id=? AND candidate_checksum=?""",
                (job_id, candidate_checksum),
            ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValidationRunError("Có nhiều validation selection cho cùng một candidate")
        selection = self._parse_selection_row(rows[0])
        return self.get_selection(job_id, candidate_checksum, selection.validation_config_checksum)

    def _verify_references(self, record: ValidationRunRecord) -> None:
        self._require_ref(
            record.validation_config_ref,
            artifact_type="ValidationConfig",
            uri=self.config_uri(record.job_id, record.validation_config_checksum),
        )
        config = self._load_model(record.validation_config_ref, ValidationConfig, "config_checksum")
        if config.config_checksum != record.validation_config_checksum:
            raise ValidationRunError("Validation config ref/checksum không khớp run")
        if config.runtime_profile_ref is not None:
            profile_ref = config.runtime_profile_ref
            self._require_ref(
                profile_ref,
                artifact_type="IsaacValidationRuntimeProfile",
                uri=profile_ref.artifact_uri,
            )
            profile = self._load_model(profile_ref, IsaacValidationRuntimeProfile, "profile_checksum")
            if profile_ref.artifact_uri != self.profile_uri(record.job_id, profile.profile_checksum):
                raise ValidationRunError("Isaac runtime profile ref/checksum không khớp job/profile")
            if profile.runtime_manifest_ref.artifact_type != "RuntimeManifest":
                raise ValidationRunError("Isaac runtime profile must reference a RuntimeManifest")
            runtime = self._load_model(profile.runtime_manifest_ref, RuntimeManifest, "runtime_manifest_checksum")
            simulator = runtime.components.get("isaac_sim")
            if (
                simulator is None
                or simulator.status.value != "VERIFIED"
                or simulator.version != profile.runtime_identity
            ):
                raise ValidationRunError("Isaac runtime profile identity does not match a VERIFIED runtime manifest")
            self.resolver.require(profile.robot_asset_ref)
        if record.status != ValidationRunStatus.COMPLETED:
            return
        report_ref = record.report_ref
        runtime_ref = record.runtime_manifest_ref
        log_ref = record.execution_log_ref
        if report_ref is None or runtime_ref is None or log_ref is None or record.report_checksum is None:
            raise ValidationRunError("Completed validation run thiếu artifact reference")
        self._require_ref(
            report_ref,
            artifact_type="ValidationReport",
            uri=self.report_uri(
                record.job_id, record.candidate_checksum, record.validation_config_checksum, record.run_id
            ),
        )
        report = self._load_model(report_ref, ValidationReport, "report_checksum")
        if report.report_checksum != record.report_checksum or report.candidate_checksum != record.candidate_checksum:
            raise ValidationRunError("Validation report không khớp run candidate/checksum")
        self._require_ref(
            runtime_ref,
            artifact_type="RuntimeManifest",
            uri=self.runtime_manifest_uri(
                record.job_id, record.candidate_checksum, record.validation_config_checksum, record.run_id
            ),
        )
        self._load_model(runtime_ref, RuntimeManifest, "runtime_manifest_checksum")
        self._require_ref(
            log_ref,
            artifact_type="ValidationExecutionLog",
            uri=self.execution_log_uri(
                record.job_id, record.candidate_checksum, record.validation_config_checksum, record.run_id
            ),
        )
        self.resolver.require(log_ref)

    def _require_ref(self, reference: ProductArtifactRef, *, artifact_type: str, uri: str) -> None:
        if reference.job_id != uri.removeprefix("artifact://jobs/").split("/", 1)[0]:
            raise ValidationRunError(f"{artifact_type} ref belongs to a different job")
        if reference.artifact_type != artifact_type or reference.artifact_uri != uri:
            raise ValidationRunError(f"{artifact_type} ref type or run-specific URI does not match")

    def _load_model(self, reference: ProductArtifactRef, model_type: type[ModelT], checksum_field: str) -> ModelT:
        try:
            model = model_type.model_validate_json(self.resolver.require(reference).read_bytes())
            verify_content_checksum(model, checksum_field)
        except (ValidationError, ValueError) as error:
            raise ValidationRunError(f"Invalid {model_type.__name__} artifact: {error}") from error
        return model

    @staticmethod
    def _verify_model_checksum(model: BaseModel, checksum_field: str) -> None:
        try:
            verify_content_checksum(model, checksum_field)
        except ValueError as error:
            raise ValidationRunError(str(error)) from error

    @classmethod
    def _parse_run(cls, payload: str | bytes, *, expected_run_id: str | None = None) -> ValidationRunRecord:
        try:
            record = ValidationRunRecord.model_validate_json(payload)
            cls._verify_model_checksum(record, "run_checksum")
        except (ValidationError, ValidationRunError) as error:
            raise ValidationRunError(f"Invalid persisted validation run: {error}") from error
        if expected_run_id is not None and record.run_id != expected_run_id:
            raise ValidationRunError("Validation run database key does not match payload")
        return record

    @classmethod
    def _parse_run_row(cls, row: tuple) -> ValidationRunRecord:
        record = cls._parse_run(row[7], expected_run_id=str(row[0]))
        indexed = (
            record.run_id,
            record.job_id,
            record.candidate_checksum,
            record.validation_config_checksum,
            record.attempt,
            record.status.value,
            record.run_checksum,
        )
        if tuple(row[:7]) != indexed:
            raise ValidationRunError("Validation run indexed columns do not match checksummed payload")
        return record

    @classmethod
    def _parse_selection(cls, payload: str | bytes) -> ValidationRunSelection:
        try:
            selection = ValidationRunSelection.model_validate_json(payload)
            cls._verify_model_checksum(selection, "selection_checksum")
        except (ValidationError, ValidationRunError) as error:
            raise ValidationRunError(f"Invalid persisted validation selection: {error}") from error
        return selection

    @classmethod
    def _parse_selection_row(cls, row: tuple) -> ValidationRunSelection:
        selection = cls._parse_selection(row[7])
        indexed = (
            selection.job_id,
            selection.candidate_checksum,
            selection.validation_config_checksum,
            selection.run_id,
            selection.report_checksum,
            selection.generation,
            selection.selection_checksum,
        )
        if tuple(row[:7]) != indexed:
            raise ValidationRunError("Validation selection indexed columns do not match checksummed payload")
        return selection

    @staticmethod
    def _validate_transition(previous: ValidationRunRecord, current: ValidationRunRecord) -> None:
        immutable_fields = (
            "run_id",
            "attempt",
            "job_id",
            "scene_revision",
            "scene_ir_checksum",
            "candidate_checksum",
            "validation_config_checksum",
            "validation_config_ref",
            "origin",
            "synthetic_fixture_id",
            "requested_at",
        )
        if any(getattr(previous, field) != getattr(current, field) for field in immutable_fields):
            raise RuntimeStateConflictError("Validation run identity/worker provenance cannot change")
        if previous.worker_id is not None and (previous.worker_id, previous.lease_id, previous.fencing_token) != (
            current.worker_id,
            current.lease_id,
            current.fencing_token,
        ):
            raise RuntimeStateConflictError("Validation run worker lease/fencing token cannot change")
        if previous.started_at is not None and previous.started_at != current.started_at:
            raise RuntimeStateConflictError("Validation run started_at cannot change after worker assignment")
        allowed = {
            ValidationRunStatus.QUEUED: {
                ValidationRunStatus.RUNNING,
                ValidationRunStatus.FAILED,
                ValidationRunStatus.CANCELLED,
            },
            ValidationRunStatus.RUNNING: {
                ValidationRunStatus.COMPLETED,
                ValidationRunStatus.FAILED,
                ValidationRunStatus.CANCELLED,
            },
        }
        if current.status not in allowed.get(previous.status, set()):
            raise RuntimeStateConflictError("Validation run terminal state or transition is immutable")


def _hex(checksum: str) -> str:
    return checksum.removeprefix("sha256:")


def _uri(job_id: str, *parts: str) -> str:
    # ProductArtifactRef validates every URI segment; keep this helper pure for stable paths.
    return "artifact://jobs/" + PurePosixPath(job_id, *parts).as_posix()
