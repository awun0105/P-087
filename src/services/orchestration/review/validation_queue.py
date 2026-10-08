"""Durable Studio requests and worker claims for exact Isaac validation attempts."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import RuntimeManifest
from src.models.contracts.validation_run import (
    IsaacValidationRuntimeProfile,
    ValidationConfig,
    ValidationRunOrigin,
    ValidationRunRecord,
    ValidationRunSelection,
    ValidationRunStatus,
)
from src.services.orchestration.artifacts import ArtifactAlreadyExistsError, ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.artifacts.checksum import sha256_bytes
from src.services.orchestration.jobs.admission import OperationAdmissionRequest, OperationResourceProfile
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction
from src.services.orchestration.review.validation_runs import ValidationRunError, ValidationRunRepository

_ZERO_CHECKSUM = "sha256:" + "0" * 64
_LEASE_TTL = timedelta(seconds=90)


class ValidationQueueError(ValueError):
    """A validation request cannot be accepted or advanced safely."""


class ValidationQueueNotFoundError(ValidationQueueError):
    """The requested validation run does not exist for this job."""


class ValidationOperationStatus(StrEnum):
    QUEUED = "QUEUED"
    WAITING_RESOURCES = "WAITING_RESOURCES"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ValidationOperationRecord(ContractModel):
    """Mutable queue/lease state, separate from immutable report and candidate artifacts."""

    schema_version: str = "1.0"
    run_id: Identifier
    job_id: Identifier
    requester_id: Identifier
    idempotency_key: str = Field(min_length=1, max_length=128)
    request_fingerprint: Checksum
    status: ValidationOperationStatus
    worker_id: Identifier | None = None
    lease_id: Identifier | None = None
    fencing_token: int = Field(default=0, ge=0)
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    retryable: bool = False
    error_code: Identifier | None = None
    created_at: datetime
    updated_at: datetime
    operation_checksum: Checksum

    @model_validator(mode="after")
    def _validate_lease(self) -> "ValidationOperationRecord":
        for value in (
            self.created_at,
            self.updated_at,
            self.lease_expires_at,
            self.heartbeat_at,
            self.cancel_requested_at,
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)):
                raise ValueError("validation operation timestamps must be timezone-aware UTC")
        leased = self.status in {
            ValidationOperationStatus.CLAIMED,
            ValidationOperationStatus.RUNNING,
            ValidationOperationStatus.CANCEL_REQUESTED,
        }
        if leased and not all(value is not None for value in (self.worker_id, self.lease_id, self.lease_expires_at)):
            raise ValueError("validation operation active status requires one complete worker lease")
        if not leased and self.lease_expires_at is not None:
            raise ValueError("terminal or waiting validation operation cannot retain a live lease")
        if (self.worker_id is None) != (self.lease_id is None):
            raise ValueError("validation operation worker and lease identity must be stored together")
        if self.status == ValidationOperationStatus.CANCEL_REQUESTED and self.cancel_requested_at is None:
            raise ValueError("cancel-requested operation needs its request timestamp")
        if self.status != ValidationOperationStatus.CANCEL_REQUESTED and self.cancel_requested_at is not None:
            raise ValueError("only a cancel-requested operation may carry its request timestamp")
        if self.retryable and self.status != ValidationOperationStatus.FAILED:
            raise ValueError("only a failed validation operation may be retryable")
        return self


class ValidationRunView(ContractModel):
    """Safe API projection that does not expose worker IDs, lease IDs or fencing tokens."""

    schema_version: str = "1.0"
    job_id: Identifier
    run_id: Identifier
    attempt: int = Field(ge=1)
    scene_revision: Identifier
    candidate_checksum: Checksum
    validation_config_checksum: Checksum
    run_status: ValidationRunStatus
    status: ValidationOperationStatus
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    report_checksum: Checksum | None = None
    selected: bool = False
    retryable: bool = False
    error_code: Identifier | None = None


class ValidationClaim(ContractModel):
    """Worker-only claim receipt; callers must pass it back for every mutation."""

    run: ValidationRunRecord
    worker_id: Identifier
    lease_id: Identifier
    fencing_token: int = Field(ge=1)
    lease_expires_at: datetime


class ValidationCandidateSnapshot(ContractModel):
    """Immutable current-package identity captured when Studio accepts a run."""

    job_id: Identifier
    scene_revision: Identifier
    scene_ir_checksum: Checksum
    candidate_checksum: Checksum


class ValidationQueue:
    """Persist attempts and operation leases in one RuntimeDatabase transaction."""

    def __init__(
        self, database: RuntimeDatabase, resolver: ArtifactResolver, *, lease_ttl: timedelta = _LEASE_TTL
    ) -> None:
        if lease_ttl.total_seconds() <= 0:
            raise ValueError("validation lease TTL must be positive")
        self.database = database
        self.resolver = resolver
        self.artifacts = FilesystemArtifactStore(resolver)
        self.runs = ValidationRunRepository(database, resolver)
        self.lease_ttl = lease_ttl

    def replay(
        self,
        *,
        job_id: str,
        candidate_checksum: str,
        config_checksum: str,
        requester_id: str,
        idempotency_key: str,
    ) -> ValidationRunView | None:
        """Return an identical accepted request even after the scene has since changed."""
        fingerprint = _request_fingerprint(job_id, candidate_checksum, config_checksum)
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT run_id,job_id,requester_id,idempotency_key,request_fingerprint,status,fencing_token,"
                "lease_expires_at,operation_checksum,payload FROM r2s_validation_operations "
                "WHERE requester_id=? AND idempotency_key=?",
                (requester_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        operation = self._parse_operation_row(row)
        if operation.request_fingerprint != fingerprint or operation.job_id != job_id:
            raise RuntimeStateConflictError("Idempotency-Key đã được dùng cho một yêu cầu validation khác")
        return self.get(job_id, operation.run_id)

    def submit(
        self,
        snapshot: ValidationCandidateSnapshot,
        config: ValidationConfig,
        *,
        requester_id: str,
        idempotency_key: str,
        profile: IsaacValidationRuntimeProfile | None = None,
    ) -> ValidationRunView:
        """Persist one candidate/config attempt; identical keys replay, new keys create attempts."""
        key = idempotency_key.strip()
        if not key or len(key) > 128:
            raise ValidationQueueError("Idempotency-Key phải dài 1..128 ký tự")
        if not requester_id.strip():
            raise ValidationQueueError("validation requester identity is required")
        if profile is not None:
            config = self.bind_profile(snapshot.job_id, config, profile)
        verify_content_checksum(config, "config_checksum")
        if config.runtime_profile_ref is None:
            raise ValidationQueueError("new Isaac validation runs must bind a runtime profile")
        replayed = self.replay(
            job_id=snapshot.job_id,
            candidate_checksum=snapshot.candidate_checksum,
            config_checksum=config.config_checksum,
            requester_id=requester_id,
            idempotency_key=key,
        )
        if replayed is not None:
            return replayed

        if profile is not None:
            profile_ref, profile_payload = self._profile_artifact(snapshot.job_id, profile)
            self._publish_immutable(profile_ref, profile_payload, "Isaac runtime profile")
        config_ref = self._publish_config(snapshot.job_id, config)
        fingerprint = _request_fingerprint(snapshot.job_id, snapshot.candidate_checksum, config.config_checksum)
        now = datetime.now(UTC)
        run_id = f"validation-{uuid4().hex}"
        draft = ValidationRunRecord(
            schema_version="1.0",
            run_id=run_id,
            attempt=1,
            job_id=snapshot.job_id,
            scene_revision=snapshot.scene_revision,
            scene_ir_checksum=snapshot.scene_ir_checksum,
            candidate_checksum=snapshot.candidate_checksum,
            validation_config_checksum=config.config_checksum,
            validation_config_ref=config_ref,
            origin=ValidationRunOrigin.WORKER,
            status=ValidationRunStatus.QUEUED,
            requested_at=now,
            run_checksum=_ZERO_CHECKSUM,
        )
        run = _seal_run(draft)
        operation = _seal_operation(
            ValidationOperationRecord(
                schema_version="1.0",
                run_id=run_id,
                job_id=snapshot.job_id,
                requester_id=requester_id,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                status=ValidationOperationStatus.QUEUED,
                created_at=now,
                updated_at=now,
                operation_checksum=_ZERO_CHECKSUM,
            )
        )
        try:
            with self.database.transaction(write=True) as tx:
                existing = tx.execute(
                    "SELECT run_id,job_id,requester_id,idempotency_key,request_fingerprint,status,fencing_token,"
                    "lease_expires_at,operation_checksum,payload FROM r2s_validation_operations "
                    "WHERE requester_id=? AND idempotency_key=?" + tx.lock_suffix(),
                    (requester_id, key),
                ).fetchone()
                if existing is not None:
                    previous = self._parse_operation_row(existing)
                    if previous.request_fingerprint != fingerprint or previous.job_id != snapshot.job_id:
                        raise RuntimeStateConflictError("Idempotency-Key đã được dùng cho một yêu cầu validation khác")
                    raise _DuplicateIdempotencyRaceError(previous.run_id)
                tx.execute(
                    "SELECT job_id FROM r2s_jobs WHERE job_id=?" + tx.lock_suffix(), (snapshot.job_id,)
                ).fetchone()
                attempt_row = tx.execute(
                    "SELECT COALESCE(MAX(attempt),0) FROM r2s_validation_runs "
                    "WHERE job_id=? AND candidate_checksum=? AND config_checksum=?",
                    (snapshot.job_id, snapshot.candidate_checksum, config.config_checksum),
                ).fetchone()
                attempt = int(attempt_row[0]) + 1 if attempt_row else 1
                if attempt != 1:
                    run = _seal_run(run.model_copy(update={"attempt": attempt, "run_checksum": _ZERO_CHECKSUM}))
                self.runs.save_run_in_transaction(tx, run)
                if not self._insert_operation(tx, operation):
                    raise _DuplicateIdempotencyRaceError()
        except _DuplicateIdempotencyRaceError as race:
            replayed = (
                self.get(snapshot.job_id, race.run_id)
                if race.run_id
                else self.replay(
                    job_id=snapshot.job_id,
                    candidate_checksum=snapshot.candidate_checksum,
                    config_checksum=config.config_checksum,
                    requester_id=requester_id,
                    idempotency_key=key,
                )
            )
            if replayed is not None:
                return replayed
            raise RuntimeStateConflictError("Validation request tranh chấp idempotency; hãy đọc lại trạng thái")
        return self.get(snapshot.job_id, run.run_id)

    def bind_profile(
        self,
        job_id: str,
        config: ValidationConfig,
        profile: IsaacValidationRuntimeProfile,
    ) -> ValidationConfig:
        """Publish server-owned runtime inputs immutably and bind their identity into policy."""
        verify_content_checksum(config, "config_checksum")
        verify_content_checksum(profile, "profile_checksum")
        if config.runtime_profile_ref is not None:
            raise ValidationQueueError("server validation policy must not supply a pre-bound profile ref")
        if profile.runtime_manifest_ref.artifact_type != "RuntimeManifest":
            raise ValidationQueueError("Isaac runtime profile must reference a RuntimeManifest")
        runtime = self.runs._load_model(profile.runtime_manifest_ref, RuntimeManifest, "runtime_manifest_checksum")
        simulator = runtime.components.get("isaac_sim")
        if simulator is None or simulator.status.value != "VERIFIED" or simulator.version != profile.runtime_identity:
            raise ValidationQueueError("Isaac runtime profile identity must match a VERIFIED runtime manifest")
        self.resolver.require(profile.robot_asset_ref)
        profile_ref, _ = self._profile_artifact(job_id, profile)
        draft = config.model_copy(update={"runtime_profile_ref": profile_ref, "config_checksum": _ZERO_CHECKSUM})
        return draft.model_copy(update={"config_checksum": canonical_content_checksum(draft, "config_checksum")})

    def list_for_job(self, job_id: str, *, limit: int = 100) -> list[ValidationRunView]:
        """List recent durable worker attempts without exposing their internal lease identity."""
        if not 1 <= limit <= 100:
            raise ValueError("validation history limit must be between 1 and 100")
        with self.database.transaction() as tx:
            rows = tx.execute(
                "SELECT run_id FROM r2s_validation_operations WHERE job_id=? ORDER BY created_at DESC,run_id DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        return [self.get(job_id, str(row[0])) for row in rows]

    def get(self, job_id: str, run_id: str) -> ValidationRunView:
        with self.database.transaction() as tx:
            run_row = tx.execute(
                "SELECT run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload "
                "FROM r2s_validation_runs WHERE run_id=? AND job_id=?" + tx.lock_suffix(),
                (run_id, job_id),
            ).fetchone()
            operation_row = self._operation_row(tx, run_id)
        if run_row is None or operation_row is None:
            raise ValidationQueueNotFoundError("Không tìm thấy validation run")
        run = self.runs._parse_run_row(run_row)
        self.runs._verify_references(run)
        self._verify_operation_run(operation_row, run)
        operation = self._parse_operation_row(operation_row)
        return self._view(run, operation)

    def claim_next(self, worker_id: str) -> ValidationClaim | None:
        """Claim the oldest queued/waiting attempt; DB row lock prevents two workers sharing it."""
        if not worker_id.strip():
            raise ValidationQueueError("validation worker identity is required")
        now = datetime.now(UTC)
        self.recover_expired(now=now)
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                """SELECT r.run_id,r.job_id,r.candidate_checksum,r.config_checksum,r.attempt,r.status,r.run_checksum,r.payload,
                          o.payload
                   FROM r2s_validation_runs r JOIN r2s_validation_operations o ON o.run_id=r.run_id
                   WHERE r.status=? AND o.status IN (?,?)
                   ORDER BY o.created_at,r.run_id LIMIT 1"""
                + tx.lock_suffix(),
                (
                    ValidationRunStatus.QUEUED.value,
                    ValidationOperationStatus.QUEUED.value,
                    ValidationOperationStatus.WAITING_RESOURCES.value,
                ),
            ).fetchone()
            if row is None:
                return None
            run = self.runs._parse_run_row(row[:8])
            operation = ValidationOperationRecord.model_validate_json(row[8])
            self._verify_operation(operation)
            if operation.run_id != run.run_id or operation.job_id != run.job_id:
                raise ValidationQueueError("validation operation does not bind the claimed run")
            lease_id = f"lease-{uuid4().hex}"
            expires_at = now + self.lease_ttl
            claimed = _seal_operation(
                operation.model_copy(
                    update={
                        "status": ValidationOperationStatus.CLAIMED,
                        "worker_id": worker_id,
                        "lease_id": lease_id,
                        "fencing_token": operation.fencing_token + 1,
                        "lease_expires_at": expires_at,
                        "heartbeat_at": now,
                        "updated_at": now,
                        "error_code": None,
                        "retryable": False,
                        "operation_checksum": _ZERO_CHECKSUM,
                    }
                )
            )
            self._save_operation(tx, claimed, expected_checksum=operation.operation_checksum)
        return ValidationClaim(
            run=run,
            worker_id=worker_id,
            lease_id=lease_id,
            fencing_token=claimed.fencing_token,
            lease_expires_at=expires_at,
        )

    def admission_request(
        self, claim: ValidationClaim, resources: OperationResourceProfile
    ) -> OperationAdmissionRequest:
        """Build the shared AUD-07 reservation request for this exact leased candidate/config."""
        return OperationAdmissionRequest(
            operation_kind="isaac_validate",
            operation_id=claim.run.run_id,
            parent_kind="job",
            parent_id=claim.run.job_id,
            input_checksum=claim.run.candidate_checksum,
            config_checksum=claim.run.validation_config_checksum,
            resources=resources,
            lease_token=claim.lease_id,
            lease_generation=claim.fencing_token,
        )

    def wait_for_resources(self, claim: ValidationClaim) -> ValidationRunView:
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            run, operation = self._leased_rows(tx, claim, expected={ValidationOperationStatus.CLAIMED})
            waiting = _seal_operation(
                operation.model_copy(
                    update={
                        "status": ValidationOperationStatus.WAITING_RESOURCES,
                        "worker_id": None,
                        "lease_id": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                        "updated_at": now,
                        "operation_checksum": _ZERO_CHECKSUM,
                    }
                )
            )
            self._save_operation(tx, waiting, expected_checksum=operation.operation_checksum)
        return self._view(run, waiting)

    def start(self, claim: ValidationClaim, *, current_candidate_checksum: str) -> ValidationRunRecord:
        """Bind worker assignment only after current candidate is rechecked and admission succeeded."""
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            run, operation = self._leased_rows(tx, claim, expected={ValidationOperationStatus.CLAIMED})
            if run.candidate_checksum != current_candidate_checksum:
                cancelled = _seal_run(
                    run.model_copy(
                        update={
                            "status": ValidationRunStatus.CANCELLED,
                            "completed_at": now,
                            "run_checksum": _ZERO_CHECKSUM,
                        }
                    )
                )
                stale = _seal_operation(
                    operation.model_copy(
                        update={
                            "status": ValidationOperationStatus.CANCELLED,
                            "worker_id": None,
                            "lease_id": None,
                            "lease_expires_at": None,
                            "heartbeat_at": None,
                            "updated_at": now,
                            "error_code": "STALE_CANDIDATE",
                            "operation_checksum": _ZERO_CHECKSUM,
                        }
                    )
                )
                self.runs.save_run_in_transaction(tx, cancelled, expected_run_checksum=run.run_checksum)
                self._save_operation(tx, stale, expected_checksum=operation.operation_checksum)
                return cancelled
            running = _seal_run(
                run.model_copy(
                    update={
                        "status": ValidationRunStatus.RUNNING,
                        "started_at": now,
                        "worker_id": claim.worker_id,
                        "lease_id": claim.lease_id,
                        "fencing_token": claim.fencing_token,
                        "run_checksum": _ZERO_CHECKSUM,
                    }
                )
            )
            operation_running = _seal_operation(
                operation.model_copy(
                    update={
                        "status": ValidationOperationStatus.RUNNING,
                        "heartbeat_at": now,
                        "lease_expires_at": now + self.lease_ttl,
                        "updated_at": now,
                        "operation_checksum": _ZERO_CHECKSUM,
                    }
                )
            )
            self.runs.save_run_in_transaction(tx, running, expected_run_checksum=run.run_checksum)
            self._save_operation(tx, operation_running, expected_checksum=operation.operation_checksum)
        return running

    def heartbeat(self, claim: ValidationClaim) -> bool:
        """Renew a live lease; return true when a user requested cancellation."""
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            _, operation = self._leased_rows(
                tx,
                claim,
                expected={ValidationOperationStatus.RUNNING, ValidationOperationStatus.CANCEL_REQUESTED},
            )
            renewed = _seal_operation(
                operation.model_copy(
                    update={
                        "heartbeat_at": now,
                        "lease_expires_at": now + self.lease_ttl,
                        "updated_at": now,
                        "operation_checksum": _ZERO_CHECKSUM,
                    }
                )
            )
            self._save_operation(tx, renewed, expected_checksum=operation.operation_checksum)
        return renewed.status == ValidationOperationStatus.CANCEL_REQUESTED

    def fail(self, claim: ValidationClaim, *, error_code: str, retryable: bool) -> ValidationRunView:
        """Record a worker failure under its lease; retryability is an explicit worker decision."""
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            run, operation = self._leased_rows(
                tx,
                claim,
                expected={ValidationOperationStatus.RUNNING, ValidationOperationStatus.CANCEL_REQUESTED},
            )
            if operation.status == ValidationOperationStatus.CANCEL_REQUESTED:
                raise RuntimeStateConflictError("Đã yêu cầu hủy validation; worker phải kết thúc CANCELLED")
            failed = _seal_run(
                run.model_copy(
                    update={"status": ValidationRunStatus.FAILED, "completed_at": now, "run_checksum": _ZERO_CHECKSUM}
                )
            )
            failed_operation = _seal_operation(
                operation.model_copy(
                    update={
                        "status": ValidationOperationStatus.FAILED,
                        "lease_expires_at": None,
                        "heartbeat_at": now,
                        "updated_at": now,
                        "retryable": retryable,
                        "error_code": error_code,
                        "operation_checksum": _ZERO_CHECKSUM,
                    }
                )
            )
            self.runs.save_run_in_transaction(tx, failed, expected_run_checksum=run.run_checksum)
            self._save_operation(tx, failed_operation, expected_checksum=operation.operation_checksum)
        return self._view(failed, failed_operation)

    def finish_cancelled(self, claim: ValidationClaim) -> ValidationRunView:
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            run, operation = self._leased_rows(
                tx,
                claim,
                expected={ValidationOperationStatus.RUNNING, ValidationOperationStatus.CANCEL_REQUESTED},
            )
            cancelled = _seal_run(
                run.model_copy(
                    update={
                        "status": ValidationRunStatus.CANCELLED,
                        "completed_at": now,
                        "run_checksum": _ZERO_CHECKSUM,
                    }
                )
            )
            cancelled_operation = _seal_operation(
                operation.model_copy(
                    update={
                        "status": ValidationOperationStatus.CANCELLED,
                        "lease_expires_at": None,
                        "heartbeat_at": now,
                        "updated_at": now,
                        "cancel_requested_at": None,
                        "retryable": False,
                        "error_code": "CANCELLED_BY_USER",
                        "operation_checksum": _ZERO_CHECKSUM,
                    }
                )
            )
            self.runs.save_run_in_transaction(tx, cancelled, expected_run_checksum=run.run_checksum)
            self._save_operation(tx, cancelled_operation, expected_checksum=operation.operation_checksum)
        return self._view(cancelled, cancelled_operation)

    def cancel(self, job_id: str, run_id: str) -> ValidationRunView:
        now = datetime.now(UTC)
        result_run: ValidationRunRecord
        result_operation: ValidationOperationRecord
        with self.database.transaction(write=True) as tx:
            run, operation = self._rows_for_update(tx, job_id, run_id)
            if operation.status in {ValidationOperationStatus.COMPLETED, ValidationOperationStatus.FAILED}:
                raise RuntimeStateConflictError("Validation run đã kết thúc và không thể hủy")
            if operation.status == ValidationOperationStatus.CANCELLED:
                result_run, result_operation = run, operation
            elif operation.status in {ValidationOperationStatus.RUNNING, ValidationOperationStatus.CANCEL_REQUESTED}:
                if operation.status == ValidationOperationStatus.CANCEL_REQUESTED:
                    result_run, result_operation = run, operation
                else:
                    requested = _seal_operation(
                        operation.model_copy(
                            update={
                                "status": ValidationOperationStatus.CANCEL_REQUESTED,
                                "cancel_requested_at": now,
                                "updated_at": now,
                                "operation_checksum": _ZERO_CHECKSUM,
                            }
                        )
                    )
                    self._save_operation(tx, requested, expected_checksum=operation.operation_checksum)
                    result_run, result_operation = run, requested
            else:
                if run.status != ValidationRunStatus.QUEUED:
                    raise RuntimeStateConflictError("Validation run và queue state không nhất quán")
                cancelled = _seal_run(
                    run.model_copy(
                        update={
                            "status": ValidationRunStatus.CANCELLED,
                            "completed_at": now,
                            "run_checksum": _ZERO_CHECKSUM,
                        }
                    )
                )
                cancelled_operation = _seal_operation(
                    operation.model_copy(
                        update={
                            "status": ValidationOperationStatus.CANCELLED,
                            "worker_id": None,
                            "lease_id": None,
                            "lease_expires_at": None,
                            "heartbeat_at": None,
                            "updated_at": now,
                            "error_code": "CANCELLED_BY_USER",
                            "operation_checksum": _ZERO_CHECKSUM,
                        }
                    )
                )
                self.runs.save_run_in_transaction(tx, cancelled, expected_run_checksum=run.run_checksum)
                self._save_operation(tx, cancelled_operation, expected_checksum=operation.operation_checksum)
                result_run, result_operation = cancelled, cancelled_operation
        return self._view(result_run, result_operation)

    def retry(
        self,
        job_id: str,
        run_id: str,
        *,
        requester_id: str,
        idempotency_key: str,
        current_candidate_checksum: str,
    ) -> ValidationRunView:
        previous = self._get_records(job_id, run_id)
        run, operation = previous
        if operation.status != ValidationOperationStatus.FAILED or not operation.retryable:
            raise RuntimeStateConflictError("Chỉ validation failure được worker đánh dấu transient mới retry được")
        if run.candidate_checksum != current_candidate_checksum:
            raise RuntimeStateConflictError("Candidate đã thay đổi; không retry validation của scene cũ")
        config_path = self.resolver.require(run.validation_config_ref)
        config = ValidationConfig.model_validate_json(config_path.read_bytes())
        verify_content_checksum(config, "config_checksum")
        snapshot = ValidationCandidateSnapshot(
            job_id=run.job_id,
            scene_revision=run.scene_revision,
            scene_ir_checksum=run.scene_ir_checksum,
            candidate_checksum=run.candidate_checksum,
        )
        return self.submit(snapshot, config, requester_id=requester_id, idempotency_key=idempotency_key)

    def recover_expired(self, *, now: datetime | None = None) -> int:
        """Reclaim pre-start claims and fail/retry-enable workers whose heartbeat lease expired."""
        timestamp = now or datetime.now(UTC)
        count = 0
        with self.database.transaction(write=True) as tx:
            rows = tx.execute(
                "SELECT run_id,job_id,requester_id,idempotency_key,request_fingerprint,status,fencing_token,"
                "lease_expires_at,operation_checksum,payload FROM r2s_validation_operations "
                "WHERE status IN (?,?,?) AND lease_expires_at IS NOT NULL AND lease_expires_at<?" + tx.lock_suffix(),
                (
                    ValidationOperationStatus.CLAIMED.value,
                    ValidationOperationStatus.RUNNING.value,
                    ValidationOperationStatus.CANCEL_REQUESTED.value,
                    timestamp.isoformat(),
                ),
            ).fetchall()
            for row in rows:
                operation = self._parse_operation_row(row)
                if operation.status == ValidationOperationStatus.CLAIMED:
                    recovered = _seal_operation(
                        operation.model_copy(
                            update={
                                "status": ValidationOperationStatus.QUEUED,
                                "worker_id": None,
                                "lease_id": None,
                                "lease_expires_at": None,
                                "heartbeat_at": None,
                                "updated_at": timestamp,
                                "operation_checksum": _ZERO_CHECKSUM,
                            }
                        )
                    )
                    self._save_operation(tx, recovered, expected_checksum=operation.operation_checksum)
                    count += 1
                    continue
                run_row = tx.execute(
                    "SELECT run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload "
                    "FROM r2s_validation_runs WHERE run_id=?" + tx.lock_suffix(),
                    (operation.run_id,),
                ).fetchone()
                if run_row is None:
                    raise ValidationRunError("expired validation operation has no durable run")
                run = self.runs._parse_run_row(run_row)
                cancelled = operation.status == ValidationOperationStatus.CANCEL_REQUESTED
                terminal_status = ValidationRunStatus.CANCELLED if cancelled else ValidationRunStatus.FAILED
                terminal = _seal_run(
                    run.model_copy(
                        update={"status": terminal_status, "completed_at": timestamp, "run_checksum": _ZERO_CHECKSUM}
                    )
                )
                operation_status = (
                    ValidationOperationStatus.CANCELLED if cancelled else ValidationOperationStatus.FAILED
                )
                recovered = _seal_operation(
                    operation.model_copy(
                        update={
                            "status": operation_status,
                            "lease_expires_at": None,
                            "heartbeat_at": timestamp,
                            "cancel_requested_at": None,
                            "updated_at": timestamp,
                            "retryable": not cancelled,
                            "error_code": "CANCELLED_WORKER_EXITED" if cancelled else "WORKER_LEASE_EXPIRED",
                            "operation_checksum": _ZERO_CHECKSUM,
                        }
                    )
                )
                self.runs.save_run_in_transaction(tx, terminal, expected_run_checksum=run.run_checksum)
                self._save_operation(tx, recovered, expected_checksum=operation.operation_checksum)
                count += 1
        return count

    def _publish_config(self, job_id: str, config: ValidationConfig) -> ProductArtifactRef:
        payload = config.model_dump_json(indent=2).encode("utf-8")
        reference = ProductArtifactRef(
            schema_version="1.0",
            artifact_type="ValidationConfig",
            data_class="derived",
            artifact_uri=self.runs.config_uri(job_id, config.config_checksum),
            artifact_checksum=sha256_bytes(payload),
            producer_stage="ST-ISAAC-VALIDATE",
            job_id=job_id,
        )
        self._publish_immutable(reference, payload, "validation config")
        return reference

    def _profile_artifact(
        self, job_id: str, profile: IsaacValidationRuntimeProfile
    ) -> tuple[ProductArtifactRef, bytes]:
        payload = profile.model_dump_json(indent=2).encode("utf-8")
        reference = ProductArtifactRef(
            schema_version="1.0",
            artifact_type="IsaacValidationRuntimeProfile",
            data_class="derived",
            artifact_uri=self.runs.profile_uri(job_id, profile.profile_checksum),
            artifact_checksum=sha256_bytes(payload),
            producer_stage="ST-ISAAC-VALIDATE",
            job_id=job_id,
        )
        return reference, payload

    def _publish_immutable(self, reference: ProductArtifactRef, payload: bytes, label: str) -> None:
        try:
            self.artifacts.publish(reference, payload)
        except ArtifactAlreadyExistsError:
            existing = self.resolver.require(reference)
            if existing.read_bytes() != payload:
                raise ValidationQueueError(f"{label} URI đã tồn tại với bytes khác")

    def _view(self, run: ValidationRunRecord, operation: ValidationOperationRecord) -> ValidationRunView:
        selection: ValidationRunSelection | None = self.runs.get_selection(
            run.job_id, run.candidate_checksum, run.validation_config_checksum
        )
        return ValidationRunView(
            job_id=run.job_id,
            run_id=run.run_id,
            attempt=run.attempt,
            scene_revision=run.scene_revision,
            candidate_checksum=run.candidate_checksum,
            validation_config_checksum=run.validation_config_checksum,
            run_status=run.status,
            status=operation.status,
            requested_at=run.requested_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            report_checksum=run.report_checksum,
            selected=selection is not None and selection.run_id == run.run_id,
            retryable=operation.retryable,
            error_code=operation.error_code,
        )

    def _get_records(self, job_id: str, run_id: str) -> tuple[ValidationRunRecord, ValidationOperationRecord]:
        with self.database.transaction() as tx:
            return self._rows_for_update(tx, job_id, run_id)

    def _rows_for_update(
        self, tx: RuntimeTransaction, job_id: str, run_id: str
    ) -> tuple[ValidationRunRecord, ValidationOperationRecord]:
        run_row = tx.execute(
            "SELECT run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload "
            "FROM r2s_validation_runs WHERE run_id=? AND job_id=?" + tx.lock_suffix(),
            (run_id, job_id),
        ).fetchone()
        operation_row = self._operation_row(tx, run_id, lock=True)
        if run_row is None or operation_row is None:
            raise ValidationQueueNotFoundError("Không tìm thấy validation run")
        run = self.runs._parse_run_row(run_row)
        self._verify_operation_run(operation_row, run)
        return run, self._parse_operation_row(operation_row)

    def _leased_rows(
        self,
        tx: RuntimeTransaction,
        claim: ValidationClaim,
        *,
        expected: set[ValidationOperationStatus],
    ) -> tuple[ValidationRunRecord, ValidationOperationRecord]:
        run, operation = self._rows_for_update(tx, claim.run.job_id, claim.run.run_id)
        if (
            operation.status not in expected
            or operation.worker_id != claim.worker_id
            or operation.lease_id != claim.lease_id
            or operation.fencing_token != claim.fencing_token
            or operation.lease_expires_at is None
            or operation.lease_expires_at <= datetime.now(UTC)
        ):
            raise RuntimeStateConflictError("Validation worker lease is stale or fenced")
        return run, operation

    @staticmethod
    def _operation_row(tx: RuntimeTransaction, run_id: str, *, lock: bool = False) -> tuple | None:
        statement = (
            "SELECT run_id,job_id,requester_id,idempotency_key,request_fingerprint,status,fencing_token,"
            "lease_expires_at,operation_checksum,payload FROM r2s_validation_operations WHERE run_id=?"
        )
        return tx.execute(statement + (tx.lock_suffix() if lock else ""), (run_id,)).fetchone()

    def _parse_operation_row(self, row: tuple) -> ValidationOperationRecord:
        operation = ValidationOperationRecord.model_validate_json(row[9])
        self._verify_operation(operation)
        indexed = (
            operation.run_id,
            operation.job_id,
            operation.requester_id,
            operation.idempotency_key,
            operation.request_fingerprint,
            operation.status.value,
            operation.fencing_token,
            operation.lease_expires_at.isoformat() if operation.lease_expires_at else None,
            operation.operation_checksum,
        )
        database_indexed = (*row[:7], row[7], row[8])
        if indexed != database_indexed:
            raise ValidationQueueError("validation operation indexed columns do not match checksummed payload")
        return operation

    @staticmethod
    def _verify_operation(operation: ValidationOperationRecord) -> None:
        if operation.operation_checksum != canonical_content_checksum(operation, "operation_checksum"):
            raise ValidationQueueError("validation operation checksum mismatch")

    def _verify_operation_run(self, operation_row: tuple, run: ValidationRunRecord) -> None:
        operation = self._parse_operation_row(operation_row)
        if operation.run_id != run.run_id or operation.job_id != run.job_id:
            raise ValidationQueueError("validation operation does not bind the indexed run")

    def _insert_operation(self, tx: RuntimeTransaction, operation: ValidationOperationRecord) -> bool:
        return bool(
            tx.execute(
                """INSERT INTO r2s_validation_operations
                   (run_id,job_id,requester_id,idempotency_key,request_fingerprint,status,worker_id,lease_id,
                    fencing_token,lease_expires_at,heartbeat_at,cancel_requested_at,retryable,error_code,created_at,
                    updated_at,operation_checksum,payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                _operation_values(operation),
            ).rowcount
        )

    def _save_operation(
        self,
        tx: RuntimeTransaction,
        operation: ValidationOperationRecord,
        *,
        expected_checksum: str,
    ) -> None:
        previous_row = self._operation_row(tx, operation.run_id, lock=True)
        if previous_row is None:
            raise RuntimeStateConflictError("Validation operation disappeared during update")
        previous = self._parse_operation_row(previous_row)
        if previous.operation_checksum != expected_checksum:
            raise RuntimeStateConflictError("Validation operation changed; read current state before updating")
        changed = tx.execute(
            """UPDATE r2s_validation_operations SET
               status=?,worker_id=?,lease_id=?,fencing_token=?,lease_expires_at=?,heartbeat_at=?,cancel_requested_at=?,
               retryable=?,error_code=?,updated_at=?,operation_checksum=?,payload=?
               WHERE run_id=? AND operation_checksum=?""",
            (
                operation.status.value,
                operation.worker_id,
                operation.lease_id,
                operation.fencing_token,
                operation.lease_expires_at.isoformat() if operation.lease_expires_at else None,
                operation.heartbeat_at.isoformat() if operation.heartbeat_at else None,
                operation.cancel_requested_at.isoformat() if operation.cancel_requested_at else None,
                int(operation.retryable),
                operation.error_code,
                operation.updated_at.isoformat(),
                operation.operation_checksum,
                operation.model_dump_json(),
                operation.run_id,
                previous.operation_checksum,
            ),
        ).rowcount
        if changed != 1:
            raise RuntimeStateConflictError("Validation operation CAS failed")


class _DuplicateIdempotencyRaceError(Exception):
    """Rollback a losing concurrent insert before replaying the accepted request."""

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id


def _request_fingerprint(job_id: str, candidate_checksum: str, config_checksum: str) -> Checksum:
    payload = f"validation-request-v1\n{job_id}\n{candidate_checksum}\n{config_checksum}".encode()
    return sha256_bytes(payload)


def _seal_run(run: ValidationRunRecord) -> ValidationRunRecord:
    return run.model_copy(update={"run_checksum": canonical_content_checksum(run, "run_checksum")})


def _seal_operation(operation: ValidationOperationRecord) -> ValidationOperationRecord:
    return operation.model_copy(
        update={"operation_checksum": canonical_content_checksum(operation, "operation_checksum")}
    )


def _operation_values(operation: ValidationOperationRecord) -> tuple:
    return (
        operation.run_id,
        operation.job_id,
        operation.requester_id,
        operation.idempotency_key,
        operation.request_fingerprint,
        operation.status.value,
        operation.worker_id,
        operation.lease_id,
        operation.fencing_token,
        operation.lease_expires_at.isoformat() if operation.lease_expires_at else None,
        operation.heartbeat_at.isoformat() if operation.heartbeat_at else None,
        operation.cancel_requested_at.isoformat() if operation.cancel_requested_at else None,
        int(operation.retryable),
        operation.error_code,
        operation.created_at.isoformat(),
        operation.updated_at.isoformat(),
        operation.operation_checksum,
        operation.model_dump_json(),
    )
