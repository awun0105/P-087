"""T-040 bước 1: khoá ghép job ↔ worker là checksum phần mềm, không kèm GPU/driver."""

from pathlib import Path

import pytest

from src.models.contracts.manifests import RuntimeComponent, RuntimeComponentStatus, RuntimeManifest
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import require_profile
from src.services.orchestration.jobs.profile import ExecutionProfile, software_runtime_checksum
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry

_PLACEHOLDER = "sha256:" + "0" * 64


def _manifest(
    *, colmap: str = "3.9.1", gpu: str = "NVIDIA A40", vram: str = "48", driver: str = "550.90"
) -> RuntimeManifest:
    def component(version: str) -> RuntimeComponent:
        return RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version=version)

    draft = RuntimeManifest(
        schema_version="1.0",
        components={
            "colmap": component(colmap),
            "brush": component("0.3.0"),
            "gpu_model": component(gpu),
            "vram": component(vram),
            "nvidia_driver": component(driver),
        },
        runtime_manifest_checksum=_PLACEHOLDER,
    )
    return with_canonical_checksum(draft, "runtime_manifest_checksum")


def _write_profile_inputs(root: Path, manifest: RuntimeManifest) -> tuple[Path, Path]:
    config = root / "processing.json"
    config.write_text('{"colmap": {}, "brush": {}}', encoding="utf-8")
    runtime = root / "runtime_manifest.json"
    runtime.write_text(manifest.model_dump_json(), encoding="utf-8")
    return config, runtime


def test_software_checksum_ignores_gpu_vram_and_driver() -> None:
    a40 = _manifest(gpu="NVIDIA A40", vram="48", driver="550.90")
    h100 = _manifest(gpu="NVIDIA H100", vram="80", driver="555.01")

    assert a40.runtime_manifest_checksum != h100.runtime_manifest_checksum
    assert software_runtime_checksum(a40) == software_runtime_checksum(h100)


def test_software_checksum_changes_when_a_tool_version_changes() -> None:
    assert software_runtime_checksum(_manifest()) != software_runtime_checksum(_manifest(colmap="3.10.0"))


def test_profile_load_exposes_software_and_full_checksums(tmp_path: Path) -> None:
    manifest = _manifest()
    config, runtime = _write_profile_inputs(tmp_path, manifest)

    profile = ExecutionProfile.load(config, runtime, seed=7)

    assert profile.runtime_manifest_checksum == manifest.runtime_manifest_checksum
    assert profile.software_runtime_checksum == software_runtime_checksum(manifest)
    assert profile.job_runtime_checksum == profile.software_runtime_checksum
    assert profile.accepts_runtime(manifest.runtime_manifest_checksum)


def test_worker_accepts_software_checksum_and_legacy_full_checksum(tmp_path: Path) -> None:
    """Job tạo trước T-040 mang checksum đầy đủ; worker khớp phần mềm vẫn phải nhận nó."""
    manifest = _manifest()
    profile = ExecutionProfile.load(*_write_profile_inputs(tmp_path, manifest), seed=7)
    registry = _registry(tmp_path, profile)
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    assert job.runtime_manifest_checksum == profile.software_runtime_checksum

    require_profile(job, profile)
    legacy = job.model_copy(update={"runtime_manifest_checksum": manifest.runtime_manifest_checksum})
    require_profile(legacy, profile)

    foreign = job.model_copy(update={"runtime_manifest_checksum": "sha256:" + "f" * 64})
    with pytest.raises(RuntimeStateConflictError, match="execution profile"):
        require_profile(foreign, profile)


def test_new_job_takes_software_checksum_not_the_hardware_bound_one(tmp_path: Path) -> None:
    manifest = _manifest()
    profile = ExecutionProfile.load(*_write_profile_inputs(tmp_path, manifest), seed=7)
    registry = _registry(tmp_path, profile)

    job = registry.create_job(JobCreateInput(project_id=_PROJECT))

    assert job.runtime_manifest_checksum == software_runtime_checksum(manifest)
    assert job.runtime_manifest_checksum != manifest.runtime_manifest_checksum


_PROJECT = "project-fixture-001"


def _registry(root: Path, profile: ExecutionProfile) -> ProjectRegistry:
    registry = ProjectRegistry(
        runtime_root=root / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}"),
        execution_profile=profile,
    )
    registry.seed_from_fixtures()
    return registry
