"""Regression cho runtime store, checksum authority và cách ly fixture; không phải GPU proof."""

from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageArtifact
from src.services.orchestration.artifacts import (
    ArtifactChecksumError,
    ArtifactNotFoundError,
    FilesystemArtifactStore,
    sha256_bytes,
)
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import SceneNotAvailableError


def runtime_job(tmp_path: Path) -> tuple[ProjectRegistry, ProductArtifactRef]:
    """Worker publication giả lập có checksum thật; không gán nhãn SOG đã render."""
    registry = ProjectRegistry(runtime_root=tmp_path)
    registry.seed_from_fixtures()
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    payload = b"synthetic worker publication"
    ref = ProductArtifactRef(
        artifact_type="FixturePayload",
        schema_version="1.0",
        job_id=job.job_id,
        artifact_uri=f"artifact://jobs/{job.job_id}/attempts/a1/fixture.bin",
        artifact_checksum=sha256_bytes(payload),
        data_class="derived",
        producer_stage="ST-VISUAL-RECON",
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(ref, payload)
    stage = StageArtifact(
        stage_id="ST-VISUAL-RECON",
        status="SUCCEEDED",
        completed_at=job.started_at,
        artifact_type=ref.artifact_type,
        artifact_uri=ref.artifact_uri,
        artifact_checksum=ref.artifact_checksum,
        data_class=ref.data_class,
    )
    registry._jobs[job.job_id] = job.model_copy(update={"stage_artifacts": [stage]})
    return registry, ref


def test_runtime_content_does_not_require_scene(tmp_path: Path) -> None:
    registry, ref = runtime_job(tmp_path)
    assert registry.read_artifact_bytes(ref.job_id, ref) == b"synthetic worker publication"
    assert not (tmp_path / "jobs" / ref.job_id / "scene").exists()
    with pytest.raises(SceneNotAvailableError):
        registry.scene.current(ref.job_id)


def test_client_checksum_cannot_replace_published_checksum(tmp_path: Path) -> None:
    registry, ref = runtime_job(tmp_path)
    registry.runtime_resolver.resolve(ref.artifact_uri).write_bytes(b"tampered")
    forged = ref.model_copy(update={"artifact_checksum": sha256_bytes(b"tampered")})
    with pytest.raises(ArtifactChecksumError, match="reference"):
        registry.read_artifact_bytes(ref.job_id, forged)
    with pytest.raises(ArtifactChecksumError):
        registry.read_artifact_bytes(ref.job_id, ref)


def test_real_job_cannot_download_fixture_artifact_or_approval(tmp_path: Path) -> None:
    registry, ref = runtime_job(tmp_path)
    fixture_ref = registry.list_job_artifacts("job-fixture-001")[0][0]
    with pytest.raises(ArtifactNotFoundError):
        registry.read_artifact_bytes(ref.job_id, fixture_ref)
    with pytest.raises(ArtifactNotFoundError):
        registry.get_approval_record(ref.job_id)
    assert registry.scene.visual_binding(ref.job_id).available is False
