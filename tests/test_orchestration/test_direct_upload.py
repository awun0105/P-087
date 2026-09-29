"""Upload thẳng lên kho file: phiên, link theo phần, ghép, server tự kiểm checksum."""

import hashlib
from pathlib import Path

import pytest

from src.services.orchestration.artifacts import ArtifactRemote, ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads import (
    MAX_URLS_PER_REQUEST,
    DirectUploadService,
    UploadError,
    VideoUploadService,
    plan_parts,
)
from src.services.orchestration.uploads.direct import MIN_PART_BYTES
from tests.test_orchestration.memory_object_store import MemoryObjectStore

MIB = 1024 * 1024


@pytest.fixture
def store() -> MemoryObjectStore:
    return MemoryObjectStore()


@pytest.fixture
def service(tmp_path: Path, store: MemoryObjectStore) -> DirectUploadService:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    return DirectUploadService(database, ArtifactResolver(tmp_path / "cache", ArtifactRemote(store)), 64 * MIB)


def _upload_all(store: MemoryObjectStore, service: DirectUploadService, upload_id: str, payload: bytes) -> list:
    session = service.get(upload_id)
    parts = []
    for number in range(1, session.part_count + 1):
        chunk = payload[(number - 1) * session.part_size : number * session.part_size]
        parts.append((number, store.upload_part(session.multipart_id, number, chunk)))
    return parts


def test_plan_parts_respects_s3_limits() -> None:
    assert plan_parts(1) == (MIN_PART_BYTES, 1)
    assert plan_parts(MIN_PART_BYTES + 1) == (MIN_PART_BYTES, 2)
    size, count = plan_parts(400 * 1024**3)  # 400 GiB vẫn ≤ 10.000 phần
    assert count <= 10_000 and size % MIB == 0 and size * count >= 400 * 1024**3


def test_full_flow_records_server_checksum(store: MemoryObjectStore, service: DirectUploadService) -> None:
    payload = b"v" * (MIN_PART_BYTES + 123)
    session = service.begin("C:\\clips\\Kho A.MOV", len(payload))
    assert session.status == "UPLOADING" and session.part_count == 2
    assert session.artifact_uri == f"artifact://jobs/{session.upload_id}/input/source.mov"

    urls = service.part_urls(session.upload_id, [2, 1, 1], 600)
    assert sorted(urls) == [1, 2]
    _upload_all(store, service, session.upload_id, payload)
    assert service.uploaded_parts(service.get(session.upload_id)) == [1, 2]

    assert service.complete(session.upload_id).status == "VERIFYING"
    ready = service.verify(session.upload_id)
    assert ready.status == "READY"

    record = VideoUploadService(service.database, service.resolver, service.max_bytes).get(session.upload_id)
    assert record.checksum == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert record.size_bytes == len(payload) and record.original_name == "Kho A.MOV"
    assert record.media_type == "video/quicktime"


def test_begin_rejects_bad_input(service: DirectUploadService) -> None:
    with pytest.raises(UploadError):
        service.begin("notes.txt", 10)
    with pytest.raises(UploadError):
        service.begin("kho.mp4", 0)
    with pytest.raises(UploadError):
        service.begin("kho.mp4", 65 * MIB)


def test_part_urls_are_bounded(service: DirectUploadService) -> None:
    session = service.begin("kho.mp4", 10)
    for numbers in ([], [0], [2], list(range(1, MAX_URLS_PER_REQUEST + 2))):
        with pytest.raises(UploadError):
            service.part_urls(session.upload_id, numbers, 600)


def test_complete_needs_every_part(store: MemoryObjectStore, service: DirectUploadService) -> None:
    payload = b"x" * (MIN_PART_BYTES + 1)
    session = service.begin("kho.mp4", len(payload))
    multipart_id = service.get(session.upload_id).multipart_id
    store.upload_part(multipart_id, 1, payload[:MIN_PART_BYTES])
    with pytest.raises(UploadError):
        service.complete(session.upload_id)
    store.upload_part(multipart_id, 2, payload[MIN_PART_BYTES:])
    service.complete(session.upload_id)
    with pytest.raises(RuntimeStateConflictError):
        service.complete(session.upload_id)


def test_size_mismatch_fails_and_deletes_object(store: MemoryObjectStore, service: DirectUploadService) -> None:
    session = service.begin("kho.mp4", 100)
    store.upload_part(service.get(session.upload_id).multipart_id, 1, b"only-40-bytes".ljust(40, b"."))
    service.complete(session.upload_id)
    failed = service.verify(session.upload_id)
    assert failed.status == "FAILED" and "khác khai báo" in (failed.error or "")
    assert store.objects == {}
    with pytest.raises(LookupError):
        VideoUploadService(service.database, service.resolver, service.max_bytes).get(session.upload_id)


def test_abort_discards_parts(store: MemoryObjectStore, service: DirectUploadService) -> None:
    session = service.begin("kho.mp4", 10)
    assert service.abort(session.upload_id).status == "FAILED"
    assert store.multiparts == {}
    with pytest.raises(RuntimeStateConflictError):
        service.part_urls(session.upload_id, [1], 600)


def test_requires_object_store(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    with pytest.raises(UploadError):
        DirectUploadService(database, ArtifactResolver(tmp_path), 10)
