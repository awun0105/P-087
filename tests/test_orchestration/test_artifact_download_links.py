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


def test_allow_list_is_cached_per_manifest_and_scene_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One Studio page requests hundreds of artifacts; the allow-list is rebuilt only when job or scene moves."""
    from types import SimpleNamespace

    registry, job_id = _world(tmp_path, None)
    builds: list[str] = []
    monkeypatch.setattr(registry, "_build_product_visible_references", lambda job: builds.append(job) or {})
    state = {"head": None, "manifest": "sha256:" + "1" * 64}
    monkeypatch.setattr(
        registry.scene.head_repository,
        "get",
        lambda job: None if state["head"] is None else SimpleNamespace(head_checksum=state["head"]),
    )
    monkeypatch.setattr(registry, "get_job", lambda job: SimpleNamespace(job_manifest_checksum=state["manifest"]))

    registry._product_visible_references(job_id)
    registry._product_visible_references(job_id)
    assert len(builds) == 2  # no committed scene head yet: never cached

    state["head"] = "sha256:" + "a" * 64
    registry._product_visible_references(job_id)
    registry._product_visible_references(job_id)
    assert len(builds) == 3

    state["head"] = "sha256:" + "b" * 64  # scene edited
    registry._product_visible_references(job_id)
    assert len(builds) == 4

    state["manifest"] = "sha256:" + "2" * 64  # job manifest advanced
    registry._product_visible_references(job_id)
    registry._product_visible_references(job_id)
    assert len(builds) == 5


# ── T-051: no rehash per download, stable presigned links ────────────────────


def test_resolve_artifact_does_not_rehash_unchanged_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.orchestration.artifacts import store as store_module

    registry, job_id = _world(tmp_path, None)
    reference = _published(registry, job_id, monkeypatch)
    hashed: list[Path] = []
    real = store_module.verify_file_checksum
    monkeypatch.setattr(
        store_module, "verify_file_checksum", lambda path, checksum: hashed.append(path) or real(path, checksum)
    )
    registry.resolve_artifact(job_id, reference)
    registry.resolve_artifact(job_id, reference)
    assert len(hashed) == 1


def test_changed_file_is_rechecked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from src.services.orchestration.artifacts import ArtifactChecksumError

    registry, job_id = _world(tmp_path, None)
    reference = _published(registry, job_id, monkeypatch)
    path = registry.resolve_artifact(job_id, reference)
    os.chmod(path, 0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(ArtifactChecksumError):
        registry.resolve_artifact(job_id, reference)


def test_presigned_url_is_reused_within_half_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.orchestration.artifacts import remote as remote_module

    store = MemoryObjectStore()
    signed: list[str] = []
    real = store.presign_get
    store.presign_get = lambda key, expires: signed.append(key) or real(key, expires)  # type: ignore[method-assign]
    clock = {"now": 1000.0}
    monkeypatch.setattr(remote_module.time, "monotonic", lambda: clock["now"])
    remote = ArtifactRemote(store)
    first = remote.presign("jobs/a/x.sog", 600)
    clock["now"] += 299
    assert remote.presign("jobs/a/x.sog", 600) == first and len(signed) == 1
    clock["now"] += 2  # past half of the lifetime
    remote.presign("jobs/a/x.sog", 600)
    assert len(signed) == 2


def test_head_result_is_cached_when_found() -> None:
    store = MemoryObjectStore()
    calls: list[str] = []
    real = store.head
    store.head = lambda key: calls.append(key) or real(key)  # type: ignore[method-assign]
    remote = ArtifactRemote(store)
    assert remote.head("jobs/a/missing.sog") is None
    assert remote.head("jobs/a/missing.sog") is None
    store.objects["jobs/a/x.sog"] = (b"x", "sha256:" + "0" * 64)
    assert remote.head("jobs/a/x.sog") is not None
    assert remote.head("jobs/a/x.sog") is not None
    assert calls == ["jobs/a/missing.sog", "jobs/a/missing.sog", "jobs/a/x.sog"]


def test_upload_sets_immutable_cache_control(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from src.services.orchestration.artifacts.remote import S3ObjectStore

    uploads: list[dict] = []
    store = S3ObjectStore.__new__(S3ObjectStore)
    store.bucket = "b"
    store.client = SimpleNamespace(upload_file=lambda path, bucket, key, **options: uploads.append(options["ExtraArgs"]))
    file = tmp_path / "x.sog"
    file.write_bytes(b"x")
    store.put_file("jobs/a/x.sog", file, "sha256:" + "0" * 64)
    assert uploads[0]["CacheControl"] == "private, max-age=31536000, immutable"
