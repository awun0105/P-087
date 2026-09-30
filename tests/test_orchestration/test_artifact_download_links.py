"""Tải artifact thẳng từ kho file bằng link có hạn, sau khi kiểm allow-list (ADR 0003)."""

from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef
from src.services.orchestration.artifacts import (
    ArtifactNotFoundError,
    ArtifactRemote,
    ArtifactStoreError,
    FilesystemArtifactStore,
    sha256_bytes,
)
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.projects.models import JobCreateInput, UploadProjectInput
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.uploads import VideoUploadService
from tests.test_orchestration.memory_object_store import MemoryObjectStore

ATTESTATION = {
    "data_origin": "self_collected_no_pii",
    "declared_owner": "QA",
    "declared_purpose": "Kiểm link tải",
    "rights_to_use_confirmed": True,
    "anonymization_confirmed": True,
    "retention_acknowledged": True,
}


def _published(registry: ProjectRegistry, job_id: str, monkeypatch: pytest.MonkeyPatch) -> ArtifactRef:
    """Một SOG đã publish và nằm trong allow-list của job (như sau khi worker chạy xong)."""
    payload = b"sog-bytes"
    reference = ArtifactRef(
        artifact_type="GaussianSOG",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/attempts/a1/rec04/scene.sog",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="ST-VISUAL-RECON",
        job_id=job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)
    monkeypatch.setattr(registry, "_product_visible_references", lambda _: {reference.artifact_uri: reference})
    return reference


def _world(tmp_path: Path, remote: ArtifactRemote | None) -> tuple[ProjectRegistry, str]:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    probe = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry = ProjectRegistry(
        runtime_root=tmp_path / "artifacts",
        database=database,
        execution_profile=ExecutionProfile(
            config_checksum=probe._fixture_config_checksum(),
            runtime_manifest_checksum=probe._fixture_runtime_checksum(),
            seed=7,
        ),
        remote=remote,
    )
    uploads = VideoUploadService(database, registry.runtime_resolver, 1024)
    pending = uploads.begin("kho.mp4")
    pending.publication.write(b"\x00\x00\x00\x14ftypqt  " + b"video")
    upload = uploads.finish(pending)
    project = registry.create_project_from_upload(
        upload, UploadProjectInput(upload_id=upload.upload_id, name="Kho", attestation=ATTESTATION), "self_attested"
    )
    job = registry.create_job(JobCreateInput(project_id=project.project_id))
    return registry, job.job_id


def test_allowed_artifact_gets_presigned_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryObjectStore()
    registry, job_id = _world(tmp_path, ArtifactRemote(store))
    reference = _published(registry, job_id, monkeypatch)
    link = registry.presigned_artifact_url(job_id, reference, 300)
    assert link == f"https://store.invalid/jobs/{job_id}/attempts/a1/rec04/scene.sog?expires=300"
    # Checksum client gửi sai → không cấp link.
    with pytest.raises(ArtifactStoreError):
        registry.presigned_artifact_url(
            job_id, reference.model_copy(update={"artifact_checksum": "sha256:" + "1" * 64}), 300
        )


def test_object_missing_in_store_falls_back_to_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryObjectStore()
    registry, job_id = _world(tmp_path, ArtifactRemote(store))
    reference = _published(registry, job_id, monkeypatch)
    store.objects.clear()  # dữ liệu cũ chỉ có trên đĩa
    assert registry.presigned_artifact_url(job_id, reference, 300) is None
    assert registry.resolve_artifact(job_id, reference).read_bytes() == b"sog-bytes"


def test_artifact_outside_allow_list_is_refused(tmp_path: Path) -> None:
    registry, job_id = _world(tmp_path, ArtifactRemote(MemoryObjectStore()))
    foreign = ArtifactRef(
        artifact_type="Secret",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/evaluation_only/gt.ply",
        artifact_checksum="sha256:" + "0" * 64,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="x",
    )
    with pytest.raises(ArtifactNotFoundError):
        registry.presigned_artifact_url(job_id, foreign, 300)


def test_without_object_store_api_serves_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job_id = _world(tmp_path, None)
    reference = _published(registry, job_id, monkeypatch)
    assert registry.presigned_artifact_url(job_id, reference, 300) is None
    assert registry.resolve_artifact(job_id, reference).is_file()
