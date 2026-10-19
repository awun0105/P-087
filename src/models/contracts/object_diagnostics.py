"""Immutable diagnostics for one producer attempt, including unsuccessful attempts."""

from typing import Literal

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, JsonObject, ProductArtifactRef


class ObjectPipelineEvidence(ContractModel):
    artifact_type: Literal["ObjectPipelineEvidence"] = "ObjectPipelineEvidence"
    schema_version: Literal["1.0"] = "1.0"
    job_id: Identifier
    run_id: Identifier
    input_revision: Identifier
    status: Literal["produced", "failed", "cancelled"]
    config_checksum: Checksum | None = None
    bundle_checksum: Checksum
    source_refs: list[ProductArtifactRef] = Field(default_factory=list)
    events: list[JsonObject] = Field(default_factory=list)
    coverage: list[JsonObject] = Field(default_factory=list)
    samples: dict[str, str] = Field(default_factory=dict)
    log_tails: dict[str, str] = Field(default_factory=dict)
    truncated: bool = False
    collection_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def same_job_sources(self) -> "ObjectPipelineEvidence":
        if any(reference.job_id != self.job_id for reference in self.source_refs):
            raise ValueError("diagnostic sources must belong to the same job")
        return self
