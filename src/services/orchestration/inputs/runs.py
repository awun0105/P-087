"""Atomic acceptance records for jobs created from a checksummed input assembly."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.contracts.artifacts import Checksum, Identifier, ProductArtifactRef


class InputAssemblyRunCommit(BaseModel):
    """Immutable acceptance identity passed into the project/job transaction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requester_id: Identifier
    idempotency_key: str = Field(min_length=1, max_length=128)
    request_fingerprint: Checksum
    assembly_id: Identifier
    assembly_revision: int = Field(ge=1)
    assembly_checksum: Checksum
    resolution_checksum: Checksum
    candidate_id: Identifier
    recipe_checksum: Checksum
    recipe_ref: ProductArtifactRef
    staged_upload_ids: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_uploads(self) -> "InputAssemblyRunCommit":
        if len(self.staged_upload_ids) != len(set(self.staged_upload_ids)):
            raise ValueError("input run cannot link a staged upload more than once")
        return self


class InputAssemblyRunRecord(BaseModel):
    """Durable run receipt linked to the exact job, project, revision, and recipe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requester_id: Identifier
    idempotency_key: str
    request_fingerprint: Checksum
    job_id: Identifier
    project_id: Identifier
    assembly_id: Identifier
    assembly_revision: int = Field(ge=1)
    assembly_checksum: Checksum
    resolution_checksum: Checksum
    candidate_id: Identifier
    recipe_checksum: Checksum
    recipe_ref: ProductArtifactRef
    accepted_at: datetime

    @model_validator(mode="after")
    def _accepted_at_is_utc(self) -> "InputAssemblyRunRecord":
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() != UTC.utcoffset(self.accepted_at):
            raise ValueError("accepted input run time must be timezone-aware UTC")
        return self


class InputAssemblyRunResult(BaseModel):
    """Job identity returned by first acceptance or an idempotent replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: Identifier
    project_id: Identifier
    replayed: bool
