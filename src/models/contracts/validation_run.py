"""Versioned operational records for trusted simulation validation attempts.

`ValidationReport` remains the normative result contract. These records bind it
to the candidate, public policy, worker lease and immutable execution artifacts.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, FiniteFloat, PositiveInt, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, ProductArtifactRef, SchemaVersion


class ValidationRunStatus(StrEnum):
    """One persisted attempt's state, independent from the parent job lifecycle."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ValidationRunOrigin(StrEnum):
    """Explicitly distinguish worker output from test/demo evidence."""

    WORKER = "WORKER"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class ValidationPathPair(ContractModel):
    """Public start/goal request consumed by the validator; coordinates are metres."""

    pair_id: Identifier
    start_xyz_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    goal_xyz_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    required: bool


class ValidationConfig(ContractModel):
    """Public, checksum-bound validation policy for one immutable attempt."""

    schema_version: SchemaVersion
    policy_id: Identifier
    required_check_ids: list[Identifier] = Field(min_length=1)
    warning_check_ids: list[Identifier]
    path_pairs: list[ValidationPathPair]
    config_checksum: Checksum

    @model_validator(mode="after")
    def _require_unique_policy_ids(self) -> Self:
        required = self.required_check_ids
        warnings = self.warning_check_ids
        pairs = [pair.pair_id for pair in self.path_pairs]
        if len(required) != len(set(required)) or len(warnings) != len(set(warnings)):
            raise ValueError("validation policy check IDs must be unique")
        if set(required) & set(warnings):
            raise ValueError("a validation check cannot be both required and warning-only")
        if len(pairs) != len(set(pairs)):
            raise ValueError("validation path pair IDs must be unique")
        return self


class ValidationRunRecord(ContractModel):
    """Backend-owned attempt identity and the evidence committed by its producer."""

    schema_version: SchemaVersion
    run_id: Identifier
    attempt: PositiveInt
    job_id: Identifier
    scene_revision: Identifier
    scene_ir_checksum: Checksum
    candidate_checksum: Checksum
    validation_config_checksum: Checksum
    validation_config_ref: ProductArtifactRef
    origin: ValidationRunOrigin
    synthetic_fixture_id: Identifier | None = None
    status: ValidationRunStatus
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    worker_id: Identifier | None = None
    lease_id: Identifier | None = None
    fencing_token: PositiveInt | None = None
    runtime_manifest_ref: ProductArtifactRef | None = None
    report_ref: ProductArtifactRef | None = None
    report_checksum: Checksum | None = None
    execution_log_ref: ProductArtifactRef | None = None
    run_checksum: Checksum

    @model_validator(mode="after")
    def _validate_provenance_and_lifecycle(self) -> Self:
        timestamps = [self.requested_at, self.started_at, self.completed_at]
        for timestamp in (value for value in timestamps if value is not None):
            if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(timestamp):
                raise ValueError("validation run timestamps must be timezone-aware UTC")
        if self.started_at is not None and self.started_at < self.requested_at:
            raise ValueError("validation run cannot start before it was requested")
        if self.completed_at is not None and self.completed_at < (self.started_at or self.requested_at):
            raise ValueError("validation run cannot complete before it starts")

        if self.origin == ValidationRunOrigin.SYNTHETIC_FIXTURE:
            if not self.synthetic_fixture_id:
                raise ValueError("synthetic validation evidence must identify its fixture")
        elif self.synthetic_fixture_id is not None:
            raise ValueError("worker validation evidence cannot carry a synthetic fixture ID")

        assigned = (self.worker_id, self.lease_id, self.fencing_token)
        if any(value is not None for value in assigned) and not all(value is not None for value in assigned):
            raise ValueError("worker assignment requires worker_id, lease_id and fencing_token together")
        if self.origin == ValidationRunOrigin.WORKER and self.status in {
            ValidationRunStatus.RUNNING,
            ValidationRunStatus.COMPLETED,
            ValidationRunStatus.FAILED,
            ValidationRunStatus.CANCELLED,
        }:
            if not all(value is not None for value in assigned):
                raise ValueError("worker run requires its assigned worker lease")
        if self.status == ValidationRunStatus.QUEUED and (self.started_at is not None or any(assigned)):
            raise ValueError("queued validation run cannot have a worker assignment or start time")
        if self.status == ValidationRunStatus.RUNNING and (self.started_at is None or self.completed_at is not None):
            raise ValueError("running validation run requires started_at and no completed_at")
        if self.status in {ValidationRunStatus.COMPLETED, ValidationRunStatus.FAILED, ValidationRunStatus.CANCELLED}:
            if self.completed_at is None:
                raise ValueError("terminal validation run requires completed_at")
        if self.status == ValidationRunStatus.COMPLETED:
            if not all(
                value is not None
                for value in (
                    self.runtime_manifest_ref,
                    self.report_ref,
                    self.report_checksum,
                    self.execution_log_ref,
                )
            ):
                raise ValueError("completed validation run requires runtime, report and execution-log references")
        return self


class ValidationRunSelection(ContractModel):
    """CAS-updated pointer to the exact completed worker run selected for review."""

    schema_version: SchemaVersion
    job_id: Identifier
    candidate_checksum: Checksum
    validation_config_checksum: Checksum
    run_id: Identifier
    report_checksum: Checksum
    generation: PositiveInt
    selected_at: datetime
    selection_checksum: Checksum

    @model_validator(mode="after")
    def _require_utc_selection_time(self) -> Self:
        if self.selected_at.tzinfo is None or self.selected_at.utcoffset() != UTC.utcoffset(self.selected_at):
            raise ValueError("validation selection timestamp must be timezone-aware UTC")
        return self
