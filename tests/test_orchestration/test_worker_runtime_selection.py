"""T-040 bước 3: API gắn job mới vào runtime GPU worker đã công bố (PRODUCT_RUNTIME_FROM_WORKERS)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.models.contracts.manifests import RuntimeComponent, RuntimeComponentStatus, RuntimeManifest
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile, software_runtime_checksum
from src.services.orchestration.jobs.worker_runtimes import publish
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry

_PROJECT = "project-fixture-001"
_CONFIG = "sha256:" + "c" * 64
_PLACEHOLDER = "sha256:" + "0" * 64


def _manifest(*, colmap: str = "3.9.1", gpu: str = "NVIDIA A40") -> RuntimeManifest:
    draft = RuntimeManifest(
        schema_version="1.0",
        components={
            "colmap": RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version=colmap),
            "gpu_model": RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version=gpu),
        },
        runtime_manifest_checksum=_PLACEHOLDER,
    )
    return with_canonical_checksum(draft, "runtime_manifest_checksum")


def _profile(manifest: RuntimeManifest, *, seed: int | None = 7) -> ExecutionProfile:
    return ExecutionProfile(
        config_checksum=_CONFIG,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software_runtime_checksum(manifest),
        seed=seed,
    )


def _worker_registry(
    root: Path, *, pinned: ExecutionProfile | None = None, from_workers: bool = True, seed: int = 7
) -> ProjectRegistry:
    registry = ProjectRegistry(
        runtime_root=root / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}"),
        execution_profile=pinned,
        runtime_from_workers=from_workers,
        processing_config_checksum=_CONFIG,
        job_seed=seed,
    )
    registry.seed_from_fixtures()
    return registry


def _publish_worker(registry: ProjectRegistry, manifest: RuntimeManifest, **kwargs: object) -> None:
    assert registry.persistence is not None
    publish(registry.persistence.database, _profile(manifest), manifest, **kwargs)


def test_new_job_takes_the_runtime_a_worker_published(tmp_path: Path) -> None:
    registry = _worker_registry(tmp_path)
    manifest = _manifest()
    _publish_worker(registry, manifest)

    job = registry.create_job(JobCreateInput(project_id=_PROJECT))

    assert job.runtime_manifest_checksum == software_runtime_checksum(manifest)
    assert job.seed == 7
    assert job.config_checksum == _CONFIG


def test_pinned_profile_wins_over_published_workers(tmp_path: Path) -> None:
    pinned_manifest = _manifest(colmap="3.8.0")
    pinned = _profile(pinned_manifest)
    registry = _worker_registry(tmp_path, pinned=pinned)
    _publish_worker(registry, _manifest(colmap="3.9.1"))

    assert registry.job_profile() == pinned


def test_no_worker_has_published_yet_means_no_runtime(tmp_path: Path) -> None:
    registry = _worker_registry(tmp_path)

    assert registry.job_profile() is None


def test_a_runtime_from_a_worker_that_went_away_is_still_used(tmp_path: Path) -> None:
    """Worker đã trả pod vẫn là runtime gần nhất: job được tạo, đang chờ GPU thay vì bị từ chối."""
    registry = _worker_registry(tmp_path)
    manifest = _manifest()
    _publish_worker(registry, manifest, now=datetime.now(UTC) - timedelta(hours=2))

    chosen = registry.job_profile()

    assert chosen is not None
    assert chosen.software_runtime_checksum == software_runtime_checksum(manifest)


def test_worker_runtime_for_another_seed_is_not_used(tmp_path: Path) -> None:
    registry = _worker_registry(tmp_path, seed=7)
    _publish_worker(registry, _manifest())
    other_seed = _worker_registry(tmp_path, seed=8)

    assert other_seed.job_profile() is None


def test_flag_off_ignores_published_workers(tmp_path: Path) -> None:
    registry = _worker_registry(tmp_path, from_workers=False)
    _publish_worker(registry, _manifest())

    assert registry.job_profile() is None


def test_worker_mode_needs_a_processing_config() -> None:
    with pytest.raises(ValidationError, match="PRODUCT_RUNTIME_FROM_WORKERS cần PRODUCT_PROCESSING_CONFIG"):
        Settings(_env_file=None, openai_api_key="test-key", product_runtime_from_workers=True)


def test_worker_mode_allows_missing_manifest_on_the_api(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        product_runtime_from_workers=True,
        product_processing_config=tmp_path / "processing.json",
    )

    assert settings.product_runtime_manifest is None


def test_pinned_pair_rule_is_unchanged_outside_worker_mode(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="phải khai báo cùng nhau"):
        Settings(_env_file=None, openai_api_key="test-key", product_processing_config=tmp_path / "processing.json")
    with pytest.raises(ValidationError, match="cần PRODUCT_PROCESSING_CONFIG"):
        Settings(_env_file=None, openai_api_key="test-key", product_runtime_manifest=tmp_path / "manifest.json")
