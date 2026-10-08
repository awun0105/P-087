"""Durable persistence and lease fencing for automatic RGB–LiDAR registration."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.contracts.artifacts import Checksum, Identifier, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.rgb_lidar_registration import (
    RegistrationOperationState,
    RegistrationRequest,
    validate_registration_transition,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction

_COLUMNS = (
    "operation_id, requester_id, idempotency_key, target_job_id, request_checksum, state, "
    "worker_id, lease_token, fencing_token, lease_expires_at, heartbeat_at, created_at, updated_at, "
    "operation_checksum, payload"
)
_ZERO_CHECKSUM = "sha256:" + "0" * 64
_RESULT_STATES = frozenset(
    {
        RegistrationOperationState.PROPOSED,
        RegistrationOperationState.AMBIGUOUS,
        RegistrationOperationState.INSUFFICIENT,
        RegistrationOperationState.FAILED,
        RegistrationOperationState.CANCELLED,
    }
)


class RegistrationOperationNotFoundError(LookupError):
    """The requested durable registration operation does not exist."""


class RegistrationOperationLeaseLostError(RuntimeError):
    """The operation is no longer owned by the caller's lease and fencing token."""


class RegistrationOperationRecord(BaseModel):
    """Immutable request plus mutable queue/lease state, persisted as one versioned payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    operation_id: Identifier
    requester_id: Identifier
    idempotency_key: str = Field(min_length=1, max_length=128)
    target_job_id: Identifier
    request_checksum: Checksum
    request: RegistrationRequest
    state: RegistrationOperationState
    attempt: int = Field(ge=0)
    worker_id: Identifier | None = None
    lease_token: str | None = None
    fencing_token: int = Field(ge=0)
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    operation_checksum: Checksum
    proposal_ref: ProductArtifactRef | None = None
    qa_report_ref: ProductArtifactRef | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _bind_request_and_lease(self) -> "RegistrationOperationRecord":
        if (
            self.request.request_id != self.operation_id
            or self.request.requested_by != self.requester_id
            or self.request.target_job_id != self.target_job_id
            or self.request.request_checksum != self.request_checksum
        ):
            raise ValueError("registration operation identity differs from its sealed request")
        timestamps = (self.created_at, self.updated_at, self.lease_expires_at, self.heartbeat_at)
        if any(value is not None and (value.tzinfo is None or value.utcoffset() is None) for value in timestamps):
            raise ValueError("registration operation timestamps must include a timezone")
        if self.state == RegistrationOperationState.RUNNING:
            if not self.worker_id or not self.lease_token or self.lease_expires_at is None or self.heartbeat_at is None:
                raise ValueError("running registration operation requires a complete worker lease")
        elif any(
            value is not None for value in (self.worker_id, self.lease_token, self.lease_expires_at, self.heartbeat_at)
        ):
            raise ValueError("non-running registration operation cannot retain a worker lease")
        for reference, expected_type in (
            (self.proposal_ref, "RegistrationProposalArtifact"),
            (self.qa_report_ref, "RegistrationQAReport"),
        ):
            if reference is None:
                continue
            if (
                reference.artifact_type != expected_type
                or reference.job_id != self.target_job_id
                or not reference.artifact_uri.startswith(f"artifact://jobs/{self.target_job_id}/")
            ):
                raise ValueError("registration operation output must bind the target job and artifact type")
        if self.state in {RegistrationOperationState.PROPOSED, RegistrationOperationState.AMBIGUOUS} and (
            self.proposal_ref is None or self.qa_report_ref is None
        ):
            raise ValueError("proposal states require exact proposal and QA report references")
        if self.state == RegistrationOperationState.INSUFFICIENT and self.qa_report_ref is None:
            raise ValueError("insufficient registration state requires its QA report")
        return self


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("operation time must include a timezone")
    return current.astimezone(UTC)


def _replace_record(record: RegistrationOperationRecord, **updates: object) -> RegistrationOperationRecord:
    """Apply a state change and re-run payload invariants after model_copy."""
    candidate = RegistrationOperationRecord.model_validate(
        record.model_copy(update={**updates, "operation_checksum": _ZERO_CHECKSUM}).model_dump(mode="python")
    )
    return candidate.model_copy(
        update={"operation_checksum": canonical_content_checksum(candidate, "operation_checksum")}
    )


class RegistrationOperationStore:
    """Accept idempotent requests and fence every worker update by lease token and generation."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.database = database

    @staticmethod
    def _decode(row: tuple[object, ...] | None) -> RegistrationOperationRecord:
        if row is None:
            raise RegistrationOperationNotFoundError("registration operation not found")
        record = RegistrationOperationRecord.model_validate_json(str(row[14]))
        try:
            verify_content_checksum(record, "operation_checksum")
        except ValueError as error:
            raise RuntimeStateConflictError("registration operation checksum mismatch") from error
        expected = (
            record.operation_id,
            record.requester_id,
            record.idempotency_key,
            record.target_job_id,
            record.request_checksum,
            record.state.value,
            record.worker_id,
            record.lease_token,
            record.fencing_token,
            record.lease_expires_at.isoformat() if record.lease_expires_at else None,
            record.heartbeat_at.isoformat() if record.heartbeat_at else None,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.operation_checksum,
        )
        if tuple(row[:14]) != expected:
            raise RuntimeStateConflictError("registration operation columns differ from the sealed payload")
        return record

    @staticmethod
    def _read_by_idempotency(
        tx: RuntimeTransaction, requester_id: str, idempotency_key: str, *, lock: bool = False
    ) -> RegistrationOperationRecord | None:
        suffix = tx.lock_suffix() if lock else ""
        row = tx.execute(
            f"SELECT {_COLUMNS} FROM r2s_registration_operations WHERE requester_id=? AND idempotency_key=?{suffix}",
            (requester_id, idempotency_key),
        ).fetchone()
        return RegistrationOperationStore._decode(row) if row is not None else None

    @staticmethod
    def _read_by_id(tx: RuntimeTransaction, operation_id: str) -> RegistrationOperationRecord | None:
        row = tx.execute(
            f"SELECT {_COLUMNS} FROM r2s_registration_operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        return RegistrationOperationStore._decode(row) if row is not None else None

    @staticmethod
    def _write(tx: RuntimeTransaction, before: RegistrationOperationRecord, after: RegistrationOperationRecord) -> None:
        cursor = tx.execute(
            "UPDATE r2s_registration_operations SET state=?, worker_id=?, lease_token=?, fencing_token=?, "
            "lease_expires_at=?, heartbeat_at=?, updated_at=?, operation_checksum=?, payload=? "
            "WHERE operation_id=? AND state=? AND fencing_token=? AND COALESCE(lease_token, '')=? "
            "AND operation_checksum=?",
            (
                after.state.value,
                after.worker_id,
                after.lease_token,
                after.fencing_token,
                after.lease_expires_at.isoformat() if after.lease_expires_at else None,
                after.heartbeat_at.isoformat() if after.heartbeat_at else None,
                after.updated_at.isoformat(),
                after.operation_checksum,
                after.model_dump_json(),
                before.operation_id,
                before.state.value,
                before.fencing_token,
                before.lease_token or "",
                before.operation_checksum,
            ),
        )
        if cursor.rowcount != 1:
            raise RegistrationOperationLeaseLostError("registration operation changed before the update")

    @staticmethod
    def _require_lease(
        record: RegistrationOperationRecord, lease_token: str, fencing_token: int, now: datetime
    ) -> None:
        if (
            record.state != RegistrationOperationState.RUNNING
            or record.lease_token != lease_token
            or record.fencing_token != fencing_token
            or record.lease_expires_at is None
            or record.lease_expires_at <= now
        ):
            raise RegistrationOperationLeaseLostError("registration operation lease expired or was replaced")

    def enqueue(self, request: RegistrationRequest, idempotency_key: str) -> RegistrationOperationRecord:
        """Persist one exact sealed request; a reused key with different bytes is a conflict."""
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("registration idempotency key must contain 1–128 characters")
        verify_content_checksum(request, "request_checksum")
        validate_registration_transition(RegistrationOperationState.REQUESTED, RegistrationOperationState.QUEUED)
        now = datetime.now(UTC)
        queued = RegistrationOperationRecord(
            operation_id=request.request_id,
            requester_id=request.requested_by,
            idempotency_key=idempotency_key,
            target_job_id=request.target_job_id,
            request_checksum=request.request_checksum,
            request=request,
            state=RegistrationOperationState.QUEUED,
            attempt=0,
            fencing_token=0,
            created_at=now,
            updated_at=now,
            operation_checksum=_ZERO_CHECKSUM,
        )
        queued = _replace_record(queued)
        with self.database.transaction(write=True) as tx:
            existing = self._read_by_idempotency(tx, request.requested_by, idempotency_key, lock=True)
            if existing is not None:
                if existing.request_checksum != request.request_checksum:
                    raise RuntimeStateConflictError("Idempotency-Key đã được dùng cho registration request khác")
                return existing
            if self._read_by_id(tx, request.request_id) is not None:
                raise RuntimeStateConflictError("registration request ID đã được dùng")
            tx.execute(
                "INSERT INTO r2s_registration_operations(operation_id,requester_id,idempotency_key,target_job_id,"
                "request_checksum,state,worker_id,lease_token,fencing_token,lease_expires_at,heartbeat_at,created_at,"
                "updated_at,operation_checksum,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    queued.operation_id,
                    queued.requester_id,
                    queued.idempotency_key,
                    queued.target_job_id,
                    queued.request_checksum,
                    queued.state.value,
                    None,
                    None,
                    queued.fencing_token,
                    None,
                    None,
                    queued.created_at.isoformat(),
                    queued.updated_at.isoformat(),
                    queued.operation_checksum,
                    queued.model_dump_json(),
                ),
            )
            accepted = self._read_by_idempotency(tx, request.requested_by, idempotency_key, lock=True)
            if accepted is None:
                raise RuntimeStateConflictError("registration request ID đã được dùng với key khác")
            if accepted.request_checksum != request.request_checksum or accepted.operation_id != request.request_id:
                raise RuntimeStateConflictError("Idempotency-Key đã được dùng cho registration request khác")
            return accepted

    def get(self, operation_id: str) -> RegistrationOperationRecord:
        """Read and verify the row/payload identity for one operation."""
        with self.database.transaction() as tx:
            record = self._read_by_id(tx, operation_id)
        if record is None:
            raise RegistrationOperationNotFoundError(f"registration operation not found: {operation_id}")
        return record

    def claim_next(
        self, worker_id: str, *, lease_seconds: int, now: datetime | None = None
    ) -> RegistrationOperationRecord | None:
        """Claim one queued operation; expired work is failed before a new request is claimed."""
        if not worker_id or lease_seconds <= 0:
            raise ValueError("worker ID and positive lease duration are required")
        current = _utc_now(now)
        with self.database.transaction(write=True) as tx:
            expired_row = tx.execute(
                f"SELECT {_COLUMNS} FROM r2s_registration_operations WHERE state=? AND lease_expires_at<=? "
                "ORDER BY lease_expires_at, created_at LIMIT 1" + tx.lock_suffix(),
                (RegistrationOperationState.RUNNING.value, current.isoformat()),
            ).fetchone()
            if expired_row is not None:
                expired = self._decode(expired_row)
                validate_registration_transition(expired.state, RegistrationOperationState.FAILED)
                failed = _replace_record(
                    expired,
                    state=RegistrationOperationState.FAILED,
                    worker_id=None,
                    lease_token=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                    updated_at=current,
                    error="Worker lease expired; submit a new request to retry.",
                )
                self._write(tx, expired, failed)
            row = tx.execute(
                f"SELECT {_COLUMNS} FROM r2s_registration_operations WHERE state=? "
                "ORDER BY created_at, operation_id LIMIT 1" + tx.lock_suffix(),
                (RegistrationOperationState.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None
            queued = self._decode(row)
            validate_registration_transition(queued.state, RegistrationOperationState.RUNNING)
            claimed = _replace_record(
                queued,
                state=RegistrationOperationState.RUNNING,
                attempt=queued.attempt + 1,
                worker_id=worker_id,
                lease_token=uuid4().hex,
                fencing_token=queued.fencing_token + 1,
                lease_expires_at=current + timedelta(seconds=lease_seconds),
                heartbeat_at=current,
                updated_at=current,
            )
            self._write(tx, queued, claimed)
            return claimed

    def heartbeat(
        self,
        operation_id: str,
        *,
        lease_token: str,
        fencing_token: int,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> RegistrationOperationRecord:
        """Extend only the still-current, unexpired worker lease."""
        if lease_seconds <= 0:
            raise ValueError("lease duration must be positive")
        current = _utc_now(now)
        with self.database.transaction(write=True) as tx:
            record = self._read_by_id(tx, operation_id)
            if record is None:
                raise RegistrationOperationNotFoundError(f"registration operation not found: {operation_id}")
            self._require_lease(record, lease_token, fencing_token, current)
            renewed = _replace_record(
                record,
                lease_expires_at=current + timedelta(seconds=lease_seconds),
                heartbeat_at=current,
                updated_at=current,
            )
            self._write(tx, record, renewed)
            return renewed

    def finish(
        self,
        operation_id: str,
        *,
        lease_token: str,
        fencing_token: int,
        state: RegistrationOperationState,
        proposal_ref: ProductArtifactRef | None = None,
        qa_report_ref: ProductArtifactRef | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> RegistrationOperationRecord:
        """Commit a producer result only while the caller owns the current lease."""
        if state not in _RESULT_STATES:
            raise ValueError("worker can only finish with a terminal producer state")
        if state == RegistrationOperationState.FAILED and not error:
            raise ValueError("failed registration operation requires an error reason")
        current = _utc_now(now)
        with self.database.transaction(write=True) as tx:
            record = self._read_by_id(tx, operation_id)
            if record is None:
                raise RegistrationOperationNotFoundError(f"registration operation not found: {operation_id}")
            self._require_lease(record, lease_token, fencing_token, current)
            validate_registration_transition(record.state, state)
            finished = _replace_record(
                record,
                state=state,
                worker_id=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=None,
                updated_at=current,
                proposal_ref=proposal_ref,
                qa_report_ref=qa_report_ref,
                error=error,
            )
            self._write(tx, record, finished)
            return finished
