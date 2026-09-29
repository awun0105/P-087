"""Kho file S3-compatible sau ArtifactResolver: cache cục bộ ↔ object store (ADR 0003).

Dùng object store in-memory cùng giao diện `ObjectStore`; bản S3 thật được kiểm ở
integration test với MinIO.
"""

import shutil
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef
from src.services.orchestration.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactChecksumError,
    ArtifactNotFoundError,
    ArtifactRemote,
    ArtifactResolver,
    FilesystemArtifactStore,
    InvalidArtifactUriError,
    StreamingPublication,
    sha256_bytes,
)
from tests.test_orchestration.memory_object_store import MemoryObjectStore


def _ref(uri: str, payload: bytes) -> ArtifactRef:
    return ArtifactRef(
        artifact_type="test_blob",
        schema_version="1.0",
        artifact_uri=uri,
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="test",
    )


@pytest.fixture
def store() -> MemoryObjectStore:
    return MemoryObjectStore()


def _machine(root: Path, store: MemoryObjectStore, prefix: str = "") -> ArtifactResolver:
    return ArtifactResolver(root, ArtifactRemote(store, prefix))


def test_publish_pushes_and_other_machine_fetches(tmp_path: Path, store: MemoryObjectStore) -> None:
    api = _machine(tmp_path / "api", store)
    gpu = _machine(tmp_path / "gpu", store)
    reference = _ref("artifact://jobs/job-a/input/manifest.json", b'{"ok": true}\n')

    FilesystemArtifactStore(api).publish(reference, b'{"ok": true}\n')

    assert store.objects["jobs/job-a/input/manifest.json"] == (b'{"ok": true}\n', reference.artifact_checksum)
    path = gpu.require(reference)
    assert path == tmp_path / "gpu/jobs/job-a/input/manifest.json"
    assert path.read_bytes() == b'{"ok": true}\n'


def test_fetch_rejects_wrong_bytes_and_leaves_nothing(tmp_path: Path, store: MemoryObjectStore) -> None:
    reference = _ref("artifact://jobs/job-a/out/data.bin", b"expected")
    store.objects["jobs/job-a/out/data.bin"] = (b"tampered", reference.artifact_checksum)
    gpu = _machine(tmp_path / "gpu", store)

    with pytest.raises(ArtifactChecksumError):
        gpu.require(reference)

    folder = tmp_path / "gpu/jobs/job-a/out"
    assert not (folder / "data.bin").exists()
    assert list(folder.iterdir()) == []  # không sót file tạm `.fetch-*`


def test_missing_everywhere_is_not_found(tmp_path: Path, store: MemoryObjectStore) -> None:
    with pytest.raises(ArtifactNotFoundError):
        _machine(tmp_path, store).require(_ref("artifact://jobs/job-a/none.json", b"x"))


def test_push_is_idempotent_but_never_overwrites(tmp_path: Path, store: MemoryObjectStore) -> None:
    remote = ArtifactRemote(store)
    first = tmp_path / "first.bin"
    first.write_bytes(b"same")
    remote.push("jobs/job-a/blob.bin", first)
    remote.push("jobs/job-a/blob.bin", first)
    assert store.puts == 1

    other = tmp_path / "other.bin"
    other.write_bytes(b"different")
    with pytest.raises(ArtifactAlreadyExistsError):
        remote.push("jobs/job-a/blob.bin", other)
    assert store.objects["jobs/job-a/blob.bin"][0] == b"same"


def test_sync_up_skips_temp_files_and_sync_down_restores(tmp_path: Path, store: MemoryObjectStore) -> None:
    gpu = _machine(tmp_path / "gpu", store)
    job_dir = tmp_path / "gpu/jobs/job-a"
    (job_dir / "frames").mkdir(parents=True)
    (job_dir / "frames/000001.jpg").write_bytes(b"frame-1")
    (job_dir / "frames/.upload-tmp").write_bytes(b"partial")
    (job_dir / "result.json").write_bytes(b"{}")

    assert gpu.sync_up("job-a") == 2
    assert gpu.sync_up("job-a") == 0  # lần hai không upload lại
    assert sorted(store.objects) == ["jobs/job-a/frames/000001.jpg", "jobs/job-a/result.json"]

    api = _machine(tmp_path / "api", store)
    assert api.sync_down("job-a") == 2
    assert (tmp_path / "api/jobs/job-a/frames/000001.jpg").read_bytes() == b"frame-1"
    assert api.sync_down("job-a") == 0


def test_sync_up_detects_changed_bytes(tmp_path: Path, store: MemoryObjectStore) -> None:
    gpu = _machine(tmp_path / "gpu", store)
    store.objects["jobs/job-a/result.json"] = (b"old-bytes", sha256_bytes(b"old-bytes"))
    (tmp_path / "gpu/jobs/job-a").mkdir(parents=True)
    (tmp_path / "gpu/jobs/job-a/result.json").write_bytes(b"new")
    with pytest.raises(ArtifactAlreadyExistsError):
        gpu.sync_up("job-a")


def test_streaming_publication_pushes_after_commit(tmp_path: Path, store: MemoryObjectStore) -> None:
    api = _machine(tmp_path / "api", store)
    publication = StreamingPublication(api, "artifact://jobs/upload-1/input/source.mp4", max_bytes=1024)
    publication.write(b"video-")
    publication.write(b"bytes")
    checksum = publication.commit()
    assert store.objects["jobs/upload-1/input/source.mp4"] == (b"video-bytes", checksum)


def test_prefix_is_applied_to_keys(tmp_path: Path, store: MemoryObjectStore) -> None:
    api = _machine(tmp_path / "api", store, prefix="/studio/")
    FilesystemArtifactStore(api).publish(_ref("artifact://jobs/job-a/x.json", b"1"), b"1")
    assert list(store.objects) == ["studio/jobs/job-a/x.json"]
    gpu = _machine(tmp_path / "gpu", store, prefix="studio")
    assert gpu.sync_down("job-a") == 1


def test_namespace_must_be_safe(tmp_path: Path, store: MemoryObjectStore) -> None:
    resolver = _machine(tmp_path, store)
    for namespace in ["../etc", "job/a", "", ".hidden"]:
        with pytest.raises(InvalidArtifactUriError):
            resolver.sync_down(namespace)


def test_without_remote_behaviour_is_unchanged(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path)
    reference = _ref("artifact://jobs/job-a/x.json", b"1")
    FilesystemArtifactStore(resolver).publish(reference, b"1")
    assert resolver.require(reference).read_bytes() == b"1"
    assert resolver.sync_up("job-a") == 0 and resolver.sync_down("job-a") == 0
    shutil.rmtree(tmp_path / "jobs")
    with pytest.raises(ArtifactNotFoundError):
        resolver.require(reference)
