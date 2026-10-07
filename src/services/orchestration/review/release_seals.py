"""Persist the immutable intent that binds an approval to one release manifest."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.release import ReleaseManifest
from src.services.orchestration.artifacts.checksum import sha256_bytes
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction

ZERO = "sha256:" + "0" * 64


class ReleaseSealStatus(StrEnum):
    PENDING = "PENDING"
    SEALED = "SEALED"


class ReleaseSealFailureCode(StrEnum):
    """Non-sensitive diagnostic stored for a release attempt that needs reviewer retry."""

    SEAL_FAILED = "SEAL_FAILED"


class ReleaseSealError(ValueError):
    """Persisted seal intent is malformed or no longer matches its immutable identity."""


class ReleaseSealIntent(BaseModel):
    """Exact release payload and lifecycle metadata, separate from public ReleaseManifest."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    seal_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    candidate_checksum: str
    validation_report_checksum: str
    approval_record_checksum: str
    release_timestamp: datetime
    manifest_payload: str
    manifest_checksum: str
    manifest_byte_checksum: str
    archive_ref: ProductArtifactRef | None = None
    status: ReleaseSealStatus
    generation: int = Field(ge=1)
    intent_checksum: str

    @classmethod
    def freeze(
        cls,
        *,
        job_id: str,
        candidate_checksum: str,
        validation_report_checksum: str,
        approval_record_checksum: str,
        manifest: ReleaseManifest,
        archive_ref: ProductArtifactRef | None = None,
        manifest_payload_bytes: bytes | None = None,
    ) -> ReleaseSealIntent:
        """Serialize the manifest once and bind logical plus exact-byte identity."""
        payload_bytes = (
            manifest_payload_bytes
            if manifest_payload_bytes is not None
            else manifest.model_dump_json(indent=2).encode("utf-8")
        )
        payload = payload_bytes.decode("utf-8")
        if ReleaseManifest.model_validate_json(payload) != manifest:
            raise ReleaseSealError("Manifest payload bytes do not match the supplied manifest")
        draft = cls(
            schema_version="1.0",
            seal_id=uuid4().hex,
            job_id=job_id,
            candidate_checksum=candidate_checksum,
            validation_report_checksum=validation_report_checksum,
            approval_record_checksum=approval_record_checksum,
            release_timestamp=manifest.release_timestamp,
            manifest_payload=payload,
            manifest_checksum=manifest.release_manifest_checksum,
            manifest_byte_checksum=sha256_bytes(payload.encode("utf-8")),
            archive_ref=archive_ref,
            status=ReleaseSealStatus.PENDING,
            generation=1,
            intent_checksum=ZERO,
        )
        return _sealed(draft)


class ReleaseSealRepository:
    """CAS-backed release intent keyed by the exact candidate/report/approval tuple."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.database = database

    def get_or_create(
        self,
        job_id: str,
        candidate_checksum: str,
        validation_report_checksum: str,
        approval_record_checksum: str,
        create: Callable[[], ReleaseSealIntent],
    ) -> ReleaseSealIntent:
        identity = (job_id, candidate_checksum, validation_report_checksum, approval_record_checksum)
        with self.database.transaction(write=True) as tx:
            row = self._select(tx, identity, lock=True)
            if row is not None:
                return self._parse_row(row)

            intent = create()
            self._validate_identity(intent, identity)
            changed = tx.execute(
                """INSERT INTO r2s_release_seals
                   (job_id,candidate_checksum,validation_report_checksum,approval_record_checksum,
                    generation,intent_checksum,payload)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                (*identity, intent.generation, intent.intent_checksum, intent.model_dump_json()),
            ).rowcount
            if changed == 1:
                return intent

            row = self._select(tx, identity, lock=True)
            if row is None:
                raise RuntimeStateConflictError("Release seal intent insert conflicted without a visible winner")
            return self._parse_row(row)

    def get(
        self, job_id: str, candidate_checksum: str, validation_report_checksum: str, approval_record_checksum: str
    ) -> ReleaseSealIntent | None:
        identity = (job_id, candidate_checksum, validation_report_checksum, approval_record_checksum)
        with self.database.transaction() as tx:
            row = self._select(tx, identity)
        return self._parse_row(row) if row is not None else None

    def has_failure(
        self, job_id: str, candidate_checksum: str, validation_report_checksum: str, approval_record_checksum: str
    ) -> bool:
        identity = (job_id, candidate_checksum, validation_report_checksum, approval_record_checksum)
        with self.database.transaction() as tx:
            row = tx.execute(
                """SELECT 1 FROM r2s_release_seal_failures
                   WHERE job_id=? AND candidate_checksum=? AND validation_report_checksum=?
                     AND approval_record_checksum=?""",
                identity,
            ).fetchone()
        return row is not None

    def record_failure(
        self,
        job_id: str,
        candidate_checksum: str,
        validation_report_checksum: str,
        approval_record_checksum: str,
    ) -> None:
        """Persist a safe failure code and attempt count; never store provider error text or secrets."""
        with self.database.transaction(write=True) as tx:
            tx.execute(
                """INSERT INTO r2s_release_seal_failures
                   (job_id,candidate_checksum,validation_report_checksum,approval_record_checksum,
                    failure_code,attempts,updated_at)
                   VALUES (?,?,?,?,?,1,?)
                   ON CONFLICT(job_id,candidate_checksum,validation_report_checksum,approval_record_checksum)
                   DO UPDATE SET failure_code=excluded.failure_code,attempts=r2s_release_seal_failures.attempts+1,
                     updated_at=excluded.updated_at""",
                (
                    job_id,
                    candidate_checksum,
                    validation_report_checksum,
                    approval_record_checksum,
                    ReleaseSealFailureCode.SEAL_FAILED.value,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def clear_failure(
        self, job_id: str, candidate_checksum: str, validation_report_checksum: str, approval_record_checksum: str
    ) -> None:
        identity = (job_id, candidate_checksum, validation_report_checksum, approval_record_checksum)
        with self.database.transaction(write=True) as tx:
            tx.execute(
                """DELETE FROM r2s_release_seal_failures
                   WHERE job_id=? AND candidate_checksum=? AND validation_report_checksum=?
                     AND approval_record_checksum=?""",
                identity,
            )

    def record_archive(self, intent: ReleaseSealIntent, archive_ref: ProductArtifactRef) -> ReleaseSealIntent:
        if intent.archive_ref is not None:
            if intent.archive_ref != archive_ref:
                raise ReleaseSealError("Release archive identity changed after it was recorded")
            return intent
        if intent.status == ReleaseSealStatus.SEALED:
            raise ReleaseSealError("Sealed release intent is missing its archive reference")
        return self._replace(intent, archive_ref=archive_ref)

    def mark_sealed(self, intent: ReleaseSealIntent) -> ReleaseSealIntent:
        if intent.status == ReleaseSealStatus.SEALED:
            return intent
        if intent.archive_ref is None:
            raise ReleaseSealError("Cannot seal a release intent without its archive reference")
        return self._replace(intent, status=ReleaseSealStatus.SEALED)

    def _replace(
        self,
        current: ReleaseSealIntent,
        *,
        archive_ref: ProductArtifactRef | None = None,
        status: ReleaseSealStatus | None = None,
    ) -> ReleaseSealIntent:
        identity = self._identity(current)
        next_intent = _sealed(
            current.model_copy(
                update={
                    "archive_ref": archive_ref if archive_ref is not None else current.archive_ref,
                    "status": status or current.status,
                    "generation": current.generation + 1,
                    "intent_checksum": ZERO,
                }
            )
        )
        with self.database.transaction(write=True) as tx:
            row = self._select(tx, identity, lock=True)
            if row is None:
                raise RuntimeStateConflictError("Release seal intent disappeared before update")
            persisted = self._parse_row(row)
            if persisted.intent_checksum != current.intent_checksum:
                if persisted == next_intent:
                    return persisted
                raise RuntimeStateConflictError("Release seal intent changed; reload before retry")
            changed = tx.execute(
                """UPDATE r2s_release_seals SET generation=?,intent_checksum=?,payload=?
                   WHERE job_id=? AND candidate_checksum=? AND validation_report_checksum=?
                     AND approval_record_checksum=? AND intent_checksum=?""",
                (
                    next_intent.generation,
                    next_intent.intent_checksum,
                    next_intent.model_dump_json(),
                    *identity,
                    current.intent_checksum,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeStateConflictError("Release seal intent CAS failed")
        return next_intent

    @staticmethod
    def _identity(intent: ReleaseSealIntent) -> tuple[str, str, str, str]:
        return (
            intent.job_id,
            intent.candidate_checksum,
            intent.validation_report_checksum,
            intent.approval_record_checksum,
        )

    @staticmethod
    def _validate_identity(intent: ReleaseSealIntent, identity: tuple[str, str, str, str]) -> None:
        if ReleaseSealRepository._identity(intent) != identity:
            raise ReleaseSealError("Release seal intent does not match candidate/report/approval identity")
        _verify_intent(intent)

    @classmethod
    def _parse_row(cls, row: tuple) -> ReleaseSealIntent:
        try:
            intent = ReleaseSealIntent.model_validate_json(row[6])
            _verify_intent(intent)
        except (ValidationError, ValueError) as error:
            raise ReleaseSealError(f"Invalid persisted release seal intent: {error}") from error
        indexed = (*cls._identity(intent), intent.generation, intent.intent_checksum)
        if tuple(row[:6]) != indexed:
            raise ReleaseSealError("Release seal intent indexed columns do not match payload")
        return intent

    @staticmethod
    def _select(tx: RuntimeTransaction, identity: tuple[str, str, str, str], *, lock: bool = False) -> tuple | None:
        return tx.execute(
            """SELECT job_id,candidate_checksum,validation_report_checksum,approval_record_checksum,
                      generation,intent_checksum,payload FROM r2s_release_seals
               WHERE job_id=? AND candidate_checksum=? AND validation_report_checksum=?
                 AND approval_record_checksum=?"""
            + (tx.lock_suffix() if lock else ""),
            identity,
        ).fetchone()


def _sealed(intent: ReleaseSealIntent) -> ReleaseSealIntent:
    return intent.model_copy(update={"intent_checksum": canonical_content_checksum(intent, "intent_checksum")})


def _verify_intent(intent: ReleaseSealIntent) -> None:
    try:
        verify_content_checksum(intent, "intent_checksum")
        manifest_bytes = intent.manifest_payload.encode("utf-8")
        if sha256_bytes(manifest_bytes) != intent.manifest_byte_checksum:
            raise ValueError("manifest byte checksum mismatch")
        manifest = ReleaseManifest.model_validate_json(manifest_bytes)
        verify_content_checksum(manifest, "release_manifest_checksum")
        if (
            manifest.release_manifest_checksum != intent.manifest_checksum
            or manifest.release_timestamp != intent.release_timestamp
            or manifest.candidate_checksum != intent.candidate_checksum
            or manifest.validation_report_checksum != intent.validation_report_checksum
            or manifest.approval_record.record_checksum != intent.approval_record_checksum
        ):
            raise ValueError("manifest payload does not match the frozen seal identity")
        if intent.archive_ref is not None and (
            intent.archive_ref.job_id != intent.job_id
            or intent.archive_ref.artifact_type != "ReleaseArchive"
            or intent.archive_ref.artifact_uri
            != f"artifact://jobs/{intent.job_id}/release/{intent.candidate_checksum.removeprefix('sha256:')}/release.zip"
        ):
            raise ValueError("archive reference does not match the frozen seal identity")
        if intent.status == ReleaseSealStatus.SEALED and intent.archive_ref is None:
            raise ValueError("sealed intent has no archive reference")
    except (ValidationError, ValueError) as error:
        raise ReleaseSealError(str(error)) from error
