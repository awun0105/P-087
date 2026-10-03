"""ADR 0004: upload nhận diện loại theo bytes ở cả đường stream qua API và upload thẳng."""

import io
import zipfile
from pathlib import Path

import pytest

from src.services.orchestration.artifacts import ArtifactRemote, ArtifactResolver
from src.services.orchestration.artifacts.remote import RangedObjectReader
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.uploads import DirectUploadService, UploadError, VideoUploadService
from tests.test_orchestration.memory_object_store import MemoryObjectStore
from tests.test_reconstruction.test_input_detection import COLMAP, _gaussian, _ply

MIB = 1024 * 1024
MP4 = b"\x00\x00\x00\x18ftypmp42"


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


@pytest.fixture
def streaming(tmp_path: Path) -> VideoUploadService:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    return VideoUploadService(database, ArtifactResolver(tmp_path / "artifacts"), 8 * MIB)


def _stream_upload(service: VideoUploadService, name: str, payload: bytes):  # noqa: ANN202
    pending = service.begin(name)
    try:
        pending.publication.write(payload)
        return service.finish(pending)
    finally:
        pending.publication.abort()


def test_stream_upload_records_kind_and_evidence(streaming: VideoUploadService) -> None:
    ply = _stream_upload(streaming, "scene.ply", _gaussian(count=4))
    assert ply.input_kind == "gaussian_ply" and ply.media_type == "application/x-ply"
    assert ply.detection is not None and ply.detection.gaussian.gaussian_count == 4  # type: ignore[union-attr]
    bundle = _stream_upload(streaming, "scene.zip", _zip_bytes({"s/point_cloud.ply": _gaussian(), **COLMAP}))
    assert bundle.input_kind == "gaussian_ply_colmap" and bundle.detection.colmap_dir == "scene/sparse/0"  # type: ignore[union-attr]
    video = _stream_upload(streaming, "kho.mp4", MP4 + b"payload")
    assert video.input_kind == "rgb_video"


@pytest.mark.parametrize(
    ("name", "payload", "message"),
    [
        ("scene.mp4", _gaussian(), "không khớp nội dung"),
        ("cloud.ply", _ply(("x", "y", "z")), "nộp riêng lẻ"),
        ("notes.ply", b"hello world, not a ply", "Không nhận diện"),
    ],
)
def test_stream_upload_rejects_without_storing(
    streaming: VideoUploadService, tmp_path: Path, name: str, payload: bytes, message: str
) -> None:
    with pytest.raises(UploadError, match=message):
        _stream_upload(streaming, name, payload)
    assert streaming.list() == []
    assert [path for path in (tmp_path / "artifacts").rglob("*") if path.is_file()] == []


@pytest.fixture
def store() -> MemoryObjectStore:
    return MemoryObjectStore()


@pytest.fixture
def direct(tmp_path: Path, store: MemoryObjectStore) -> DirectUploadService:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    return DirectUploadService(database, ArtifactResolver(tmp_path / "cache", ArtifactRemote(store)), 64 * MIB)


def _direct_upload(store: MemoryObjectStore, service: DirectUploadService, name: str, payload: bytes):  # noqa: ANN202
    session = service.begin(name, len(payload))
    multipart = service.get(session.upload_id).multipart_id
    for number in range(1, session.part_count + 1):
        chunk = payload[(number - 1) * session.part_size : number * session.part_size]
        store.upload_part(multipart, number, chunk)
    service.complete(session.upload_id)
    return service.verify(session.upload_id)


def test_direct_upload_detects_zip_and_rejects_wrong_content(
    store: MemoryObjectStore, direct: DirectUploadService
) -> None:
    ready = _direct_upload(store, direct, "scene.zip", _zip_bytes({"a.ply": _gaussian(), **COLMAP}))
    assert ready.status == "READY"
    record = VideoUploadService(direct.database, direct.resolver, direct.max_bytes).get(ready.upload_id)
    assert record.input_kind == "gaussian_ply_colmap"
    failed = _direct_upload(store, direct, "fake.ply", MP4 + b"not a scene")
    assert failed.status == "FAILED" and "không khớp nội dung" in (failed.error or "")
    assert not any(key.endswith("source.ply") for key in store.objects)


def test_direct_video_detection_reads_only_one_block(
    store: MemoryObjectStore, direct: DirectUploadService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched: list[int] = []
    original = store.read_range

    def counting(key: str, start: int, length: int) -> bytes:
        fetched.append(length)
        return original(key, start, length)

    monkeypatch.setattr(store, "read_range", counting)
    ready = _direct_upload(store, direct, "kho.mp4", MP4 + b"v" * (20 * MIB))
    assert ready.status == "READY"
    assert sum(fetched) <= RangedObjectReader.BLOCK  # không kéo 20 MiB về API server


def test_ranged_reader_matches_bytes_across_blocks() -> None:
    payload = bytes(range(256)) * 1000
    reader = RangedObjectReader(lambda start, length: payload[start : start + length], len(payload))
    reader.seek(RangedObjectReader.BLOCK - 10)
    assert reader.read(30) == payload[RangedObjectReader.BLOCK - 10 : RangedObjectReader.BLOCK + 20]
    reader.seek(-5, io.SEEK_END)
    assert reader.read(100) == payload[-5:] and reader.read(1) == b""
