"""Profile runtime explicite; không mượn version/config của synthetic fixture."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.models.contracts.artifacts import Checksum
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import RuntimeManifest
from src.services.orchestration.artifacts import ArtifactChecksumError, sha256_file
from src.services.orchestration.artifacts.checksum import with_canonical_checksum

#: Thành phần phần cứng: không tham gia khoá ghép job ↔ worker (T-040, quyết định Q3).
#: Chúng vẫn nằm trong manifest đầy đủ để ghi nhận, nhưng đổi GPU/driver không làm job lệch worker.
HARDWARE_COMPONENTS = frozenset({"gpu_model", "vram", "nvidia_driver"})

_PLACEHOLDER_CHECKSUM = "sha256:" + "0" * 64


def software_runtime_checksum(manifest: RuntimeManifest) -> str:
    """Checksum canonical của manifest sau khi bỏ thành phần phần cứng.

    Hai máy cùng image (cùng phiên bản công cụ) cho cùng một giá trị dù khác GPU hay driver.
    """
    components = {name: value for name, value in manifest.components.items() if name not in HARDWARE_COMPONENTS}
    draft = RuntimeManifest(
        schema_version=manifest.schema_version,
        components=components,
        runtime_manifest_checksum=_PLACEHOLDER_CHECKSUM,
    )
    return with_canonical_checksum(draft, "runtime_manifest_checksum").runtime_manifest_checksum


def load_runtime_manifest(runtime: Path) -> RuntimeManifest:
    """Đọc manifest và kiểm canonical checksum; file bị sửa tay thì từ chối."""
    manifest = RuntimeManifest.model_validate_json(runtime.read_bytes())
    if manifest.runtime_manifest_checksum != canonical_content_checksum(manifest, "runtime_manifest_checksum"):
        raise ArtifactChecksumError("RuntimeManifest canonical checksum không khớp")
    return manifest


class ExecutionProfile(BaseModel):
    """Identity đã khóa tại composition root, không do browser tự khai."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    config_checksum: Checksum
    #: Checksum đầy đủ (kể cả phần cứng). Job tạo trước T-040 mang giá trị này.
    runtime_manifest_checksum: Checksum
    #: Khoá ghép job ↔ worker cho job mới. None chỉ khi profile dựng tay (test, fixture).
    software_runtime_checksum: Checksum | None = None
    seed: int | None = None

    @classmethod
    def load(cls, config: Path, runtime: Path, seed: int | None) -> "ExecutionProfile":
        """Runtime manifest dùng canonical checksum; config dùng exact bytes."""
        manifest = load_runtime_manifest(runtime)
        return cls(
            config_checksum=sha256_file(config),
            runtime_manifest_checksum=manifest.runtime_manifest_checksum,
            software_runtime_checksum=software_runtime_checksum(manifest),
            seed=seed,
        )

    @property
    def job_runtime_checksum(self) -> Checksum:
        """Giá trị ghi vào `JobManifest.runtime_manifest_checksum` khi tạo job mới."""
        return self.software_runtime_checksum or self.runtime_manifest_checksum

    def accepts_runtime(self, job_runtime_checksum: str) -> bool:
        """Job mang checksum phần mềm (mới) hoặc checksum đầy đủ (tạo trước T-040) đều được nhận."""
        return job_runtime_checksum in {self.job_runtime_checksum, self.runtime_manifest_checksum}
