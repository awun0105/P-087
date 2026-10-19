"""Checksummed release capabilities available before the first worker boots."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.contracts.input_assembly import RuntimeQualificationRegistry, verify_runtime_registry_checksum
from src.services.orchestration.jobs.profile import ExecutionProfile


class ReleaseProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    image: str = Field(pattern=r"^\S+@sha256:[a-f0-9]{64}$")
    execution: ExecutionProfile
    kinds: frozenset[str]
    gpu_types: tuple[str, ...] = Field(min_length=1)
    cuda_versions: tuple[str, ...] = Field(min_length=1)
    scene_boxes_require_gpu: bool = True
    min_vram_gb: float = Field(gt=0, allow_inf_nan=False)
    min_ram_gb: float = Field(gt=0, allow_inf_nan=False)
    min_cpus: int = Field(ge=1)
    scratch_gb: int = Field(ge=10)
    qualification_reference: str = Field(min_length=1)
    # Operator-approved estimate, separate from provider quote and native qualification.
    storage_hourly_usd: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def supported_kinds(self) -> "ReleaseProfile":
        if not self.kinds or not self.kinds <= {"pipeline", "scene", "registration", "validation", "import"}:
            raise ValueError("Invalid release workload kinds")
        return self


class ReleaseCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profiles: tuple[ReleaseProfile, ...] = Field(min_length=1)
    checksum: str
    input_registry: RuntimeQualificationRegistry | None = None

    @model_validator(mode="after")
    def verified_input_registry(self) -> "ReleaseCatalog":
        if len({p.name for p in self.profiles}) != len(self.profiles):
            raise ValueError("Release profile names must be unique")
        if self.input_registry is not None:
            verify_runtime_registry_checksum(self.input_registry)
        return self

    def compatible(self, kind: str, runtime: str | None = None) -> list[ReleaseProfile]:
        return [
            p for p in self.profiles if kind in p.kinds and (runtime is None or p.execution.accepts_runtime(runtime))
        ]


def seal(payload: dict) -> dict:
    data = {key: value for key, value in payload.items() if key != "checksum"}
    checksum = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**data, "checksum": "sha256:" + checksum}


def load_catalog(path: Path) -> ReleaseCatalog:
    data = json.loads(path.read_bytes())
    if data.get("checksum") != seal(data)["checksum"]:
        raise ValueError("GPU release catalog checksum mismatch")
    return ReleaseCatalog.model_validate(data)
