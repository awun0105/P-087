"""Preview polling reuses byte verification only while local files are unchanged."""

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobManifest, StageArtifact
from src.models.contracts.preview import ReconstructionPreview
from src.services.orchestration.artifacts import (
    ArtifactChecksumError,
    ArtifactNotFoundError,
    ArtifactRemote,
    ArtifactResolver,
    FilesystemArtifactStore,
    InvalidArtifactUriError,
    sha256_bytes,
)
from src.services.orchestration.artifacts import store as store_module
from src.services.orchestration.projects.preview import load_job_preview
from src.services.orchestration.projects.registry import ProjectRegistry
from tests.test_orchestration.memory_object_store import MemoryObjectStore


def _reference(payload: bytes, name: str = "scene.sog") -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type="GaussianSOG",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/cache-preview/attempts/first/{name}",
        artifact_checksum=sha256_bytes(payload),
        data_class="derived",
        producer_stage="ST-VISUAL-RECON",
        job_id="cache-preview",
    )


@pytest.fixture
def verification_spy(monkeypatch: pytest.MonkeyPatch) -> Mock:
    spy = Mock(wraps=store_module.verify_file_checksum)
    monkeypatch.setattr(store_module, "verify_file_checksum", spy)
    return spy


def test_unchanged_preview_dependency_is_hashed_once_but_require_stays_strict(
    tmp_path: Path, verification_spy: Mock
) -> None:
    resolver = ArtifactResolver(tmp_path)
    reference = _reference(b"original")
    FilesystemArtifactStore(resolver).publish(reference, b"original")
    path = resolver.resolve(reference.artifact_uri)

    assert resolver.require_unchanged(reference) == path
    assert resolver.require_unchanged(reference) == path
    assert verification_spy.call_count == 1
    resolver.require(reference)
    resolver.require(reference)
    assert verification_spy.call_count == 3


@pytest.mark.parametrize("mutation", ["rewrite", "restore_mtime", "replace"])
def test_changed_dependency_revokes_verification_even_at_same_size(
    tmp_path: Path, verification_spy: Mock, mutation: str
) -> None:
    resolver = ArtifactResolver(tmp_path)
    reference = _reference(b"original")
    FilesystemArtifactStore(resolver).publish(reference, b"original")
    path = resolver.resolve(reference.artifact_uri)
    resolver.require_unchanged(reference)
    before = path.stat()
    if mutation == "replace":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(b"tampered")
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(path)
    else:
        path.write_bytes(b"tampered")
        if mutation == "restore_mtime":
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    with pytest.raises(ArtifactChecksumError):
        resolver.require_unchanged(reference)
    assert verification_spy.call_count == 2


def test_missing_dependency_does_not_keep_a_successful_cache_entry(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path)
    reference = _reference(b"original")
    FilesystemArtifactStore(resolver).publish(reference, b"original")
    path = resolver.resolve(reference.artifact_uri)
    resolver.require_unchanged(reference)
    path.unlink()
    with pytest.raises(ArtifactNotFoundError):
        resolver.require_unchanged(reference)


def test_checksum_and_resolver_root_are_part_of_verification_identity(tmp_path: Path) -> None:
    reference = _reference(b"original")
    first = ArtifactResolver(tmp_path / "first")
    FilesystemArtifactStore(first).publish(reference, b"original")
    first.require_unchanged(reference)
    with pytest.raises(ArtifactChecksumError):
        first.require_unchanged(reference.model_copy(update={"artifact_checksum": sha256_bytes(b"different")}))
    second = ArtifactResolver(tmp_path / "second")
    path = second.resolve(reference.artifact_uri)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")
    with pytest.raises(ArtifactChecksumError):
        second.require_unchanged(reference)


def test_cached_dependency_does_not_bypass_path_safety(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "store")
    reference = _reference(b"original")
    FilesystemArtifactStore(resolver).publish(reference, b"original")
    path = resolver.resolve(reference.artifact_uri)
    resolver.require_unchanged(reference)
    outside = tmp_path / "outside.sog"
    outside.write_bytes(b"original")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(InvalidArtifactUriError):
        resolver.require_unchanged(reference)


def test_failed_verification_is_never_cached(tmp_path: Path, verification_spy: Mock) -> None:
    resolver = ArtifactResolver(tmp_path)
    reference = _reference(b"original")
    path = resolver.resolve(reference.artifact_uri)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")
    for _ in range(2):
        with pytest.raises(ArtifactChecksumError):
            resolver.require_unchanged(reference)
    assert verification_spy.call_count == 2


def test_mutation_during_hash_is_rejected_and_does_not_seed_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = ArtifactResolver(tmp_path)
    reference = _reference(b"original")
    FilesystemArtifactStore(resolver).publish(reference, b"original")
    verify = store_module.verify_file_checksum

    def change_after_hash(target: Path, checksum: str) -> None:
        verify(target, checksum)
        target.write_bytes(b"tampered")

    monkeypatch.setattr(store_module, "verify_file_checksum", change_after_hash)
    with pytest.raises(ArtifactChecksumError):
        resolver.require_unchanged(reference)
    monkeypatch.setattr(store_module, "verify_file_checksum", verify)
    with pytest.raises(ArtifactChecksumError):
        resolver.require_unchanged(reference)


def test_remote_dependency_is_downloaded_once_and_reverified_after_local_eviction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote_store = MemoryObjectStore()
    download = Mock(wraps=remote_store.get_file)
    monkeypatch.setattr(remote_store, "get_file", download)
    remote = ArtifactRemote(remote_store)
    writer = ArtifactResolver(tmp_path / "worker", remote)
    reference = _reference(b"original")
    FilesystemArtifactStore(writer).publish(reference, b"original")
    reader = ArtifactResolver(tmp_path / "api", remote)
    path = reader.require_unchanged(reference)
    assert reader.require_unchanged(reference).read_bytes() == b"original"
    assert download.call_count == 1
    path.unlink()
    remote_store.objects[remote.key(reader.relative_key(reference.artifact_uri))] = (
        b"tampered",
        reference.artifact_checksum,
    )
    with pytest.raises(ArtifactChecksumError):
        reader.require_unchanged(reference)


def test_verification_cache_is_bounded_and_evicted_entries_are_rechecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verification_spy: Mock
) -> None:
    monkeypatch.setattr(store_module, "_VERIFIED_CACHE_MAX", 2)
    resolver = ArtifactResolver(tmp_path)
    references = [_reference(b"original", f"{number}.sog") for number in range(3)]
    for reference in references:
        FilesystemArtifactStore(resolver).publish(reference, b"original")
        resolver.require_unchanged(reference)
    resolver.require_unchanged(references[-1])
    assert verification_spy.call_count == 3
    resolver.require_unchanged(references[0])
    assert verification_spy.call_count == 4


@pytest.fixture
def published_preview(tmp_path: Path) -> tuple[ProjectRegistry, JobManifest, ReconstructionPreview]:
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    writer = FilesystemArtifactStore(registry.runtime_resolver)
    visual = _reference(b"source", "scene.ply").model_copy(update={"artifact_type": "BrushVisualArtifact"})
    poses = _reference(b"poses", "poses.json").model_copy(
        update={"artifact_type": "CameraPoseArtifact", "producer_stage": "ST-CAMERA-POSE"}
    )
    delivery = _reference(b"original")
    for reference, payload in [(visual, b"source"), (poses, b"poses"), (delivery, b"original")]:
        writer.publish(reference, payload)
    fixture = Path("fixtures/mock_job/job_manifest.json")
    job = JobManifest.model_validate_json(fixture.read_bytes())
    preview = ReconstructionPreview(
        job_id="cache-preview",
        attempt_id="first",
        source_input_checksum=job.input_manifest_checksum,
        source_visual_ref=visual,
        camera_pose_ref=poses,
        delivery_ref=delivery,
        producer_version="synthetic-cache-test",
    )
    payload = preview.model_dump_json().encode()
    reference = _reference(payload, "rec11/preview.json").model_copy(update={"artifact_type": "ReconstructionPreview"})
    writer.publish(reference, payload)
    stage = StageArtifact(
        stage_id="ST-VISUAL-RECON",
        status="SUCCEEDED",
        artifact_type=reference.artifact_type,
        artifact_uri=reference.artifact_uri,
        artifact_checksum=reference.artifact_checksum,
        data_class=reference.data_class,
        completed_at=datetime.now(UTC),
    )
    job = job.model_copy(update={"job_id": preview.job_id, "stage_artifacts": [stage]})
    registry._jobs[job.job_id] = job
    return registry, job, preview


def test_preview_reads_reuse_dependencies_but_verify_metadata_and_lineage_each_time(
    published_preview: tuple[ProjectRegistry, JobManifest, ReconstructionPreview], verification_spy: Mock
) -> None:
    registry, job, preview = published_preview
    assert registry.get_preview(job.job_id) == preview
    assert verification_spy.call_count == 4
    assert registry.get_preview(job.job_id) == preview
    assert verification_spy.call_count == 5
    registry._jobs[job.job_id] = job.model_copy(update={"input_manifest_checksum": sha256_bytes(b"other-input")})
    with pytest.raises(ArtifactChecksumError):
        registry.get_preview(job.job_id)
    assert verification_spy.call_count == 6


def test_publication_consumer_keeps_full_verification_after_polling_warmed_the_cache(
    published_preview: tuple[ProjectRegistry, JobManifest, ReconstructionPreview], verification_spy: Mock
) -> None:
    registry, job, preview = published_preview
    registry.get_preview(job.job_id)
    verification_spy.reset_mock()
    assert load_job_preview(job, registry.runtime_resolver) == preview
    assert verification_spy.call_count == 4


@pytest.mark.parametrize("dependency", ["source_visual_ref", "camera_pose_ref", "delivery_ref"])
def test_preview_read_rejects_corruption_of_any_warmed_dependency(
    published_preview: tuple[ProjectRegistry, JobManifest, ReconstructionPreview], dependency: str
) -> None:
    registry, job, preview = published_preview
    registry.get_preview(job.job_id)
    reference = getattr(preview, dependency)
    registry.runtime_resolver.resolve(reference.artifact_uri).write_bytes(b"tampered")
    with pytest.raises(ArtifactChecksumError):
        registry.get_preview(job.job_id)
