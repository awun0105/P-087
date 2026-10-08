"""Durable upload metadata for files staged into an input assembly."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.contracts.input_assembly import StagedInputFile
from src.models.contracts.manifests import InputFile
from src.services.orchestration.auth.models import Actor
from src.services.reconstruction.inputs.input_probe import InputProbe


class StagedInputUploadRecord(BaseModel):
    """Checksummed uploaded bytes plus bounded content probes, before job acceptance."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    source_file: InputFile
    staged_files: list[StagedInputFile] = Field(min_length=1)
    probes: list[InputProbe] = Field(min_length=1)
    uploaded_by: Actor | None = None
    received_at: datetime
    project_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bind_probe_and_file_identity(self) -> "StagedInputUploadRecord":
        if self.received_at.tzinfo is None or self.received_at.utcoffset() != UTC.utcoffset(self.received_at):
            raise ValueError("staged upload timestamp must be timezone-aware UTC")
        staged_by_id = {item.file_id: item for item in self.staged_files}
        probes_by_id = {item.file_id: item for item in self.probes}
        if len(staged_by_id) != len(self.staged_files) or len(probes_by_id) != len(self.probes):
            raise ValueError("staged upload file and probe IDs must be unique")
        if staged_by_id.keys() != probes_by_id.keys():
            raise ValueError("every staged file requires exactly one matching content probe")
        for staged in self.staged_files:
            if staged.upload_id != self.upload_id or staged.source_file != self.source_file:
                raise ValueError("staged file must bind the upload ID and exact source ref")
            if probes_by_id[staged.file_id].source_checksum != self.source_file.checksum:
                raise ValueError("content probe must bind the source checksum")
        if len(self.project_ids) != len(set(self.project_ids)):
            raise ValueError("project links must be unique")
        return self
