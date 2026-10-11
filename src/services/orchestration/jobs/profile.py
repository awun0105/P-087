"""Profile runtime explicite; không mượn version/config của synthetic fixture."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.models.contracts.artifacts import Checksum
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import RuntimeManifest
from src.services.orchestration.artifacts import ArtifactChecksumError, sha256_file


class ExecutionProfile(BaseModel):
    """Identity đã khóa tại composition root, không do browser tự khai."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    config_checksum: Checksum
    runtime_manifest_checksum: Checksum
    seed: int | None = None

    @classmethod
    def load(cls, config: Path, runtime: Path, seed: int | None) -> "ExecutionProfile":
        """Runtime manifest dùng canonical checksum; config dùng exact bytes."""
        manifest = RuntimeManifest.model_validate_json(runtime.read_bytes())
        if manifest.runtime_manifest_checksum != canonical_content_checksum(manifest, "runtime_manifest_checksum"):
            raise ArtifactChecksumError("RuntimeManifest canonical checksum không khớp")
        return cls(
            config_checksum=sha256_file(config), runtime_manifest_checksum=manifest.runtime_manifest_checksum, seed=seed
        )
