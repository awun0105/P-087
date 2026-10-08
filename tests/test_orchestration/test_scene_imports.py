"""Gói 5 (ADR 0004 §3): scene import từ PLY 3DGS — chỉ xem/chỉnh sửa, không phải job."""

from pathlib import Path

import pytest

from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.uploads import VideoUploadService
from src.services.orchestration.uploads import scene_imports as imports_module
from src.services.orchestration.uploads.scene_imports import ImportService, SceneImportError
from tests.test_reconstruction.support.sog_fixtures import sog_archive
from tests.test_reconstruction.test_input_detection import _gaussian

MP4 = b"\x00\x00\x00\x18ftypmp42"


@pytest.fixture
def world(tmp_path: Path):  # noqa: ANN201
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    resolver = ArtifactResolver(tmp_path / "artifacts")
    uploads = VideoUploadService(database, resolver, 8 * 1024 * 1024)
    return uploads, ImportService(database, resolver, tmp_path / "work")


def _upload(uploads: VideoUploadService, name: str, payload: bytes):  # noqa: ANN202
    pending = uploads.begin(name)
    pending.publication.write(payload)
    return uploads.finish(pending)


def test_video_upload_cannot_become_import(world) -> None:  # noqa: ANN001
    uploads, service = world
    with pytest.raises(SceneImportError, match="3DGS"):
        service.create(_upload(uploads, "kho.mp4", MP4 + b"x"), "Kho", None)


def test_ply_import_packages_to_sog_and_becomes_ready(world, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    uploads, service = world

    def fake_package(source: Path, workspace: Path, gpu_index: int | None) -> Path:
        workspace.mkdir(parents=True)
        (workspace / "scene.sog").write_bytes(b"sog:" + source.read_bytes()[:16])
        return workspace / "scene.sog"

    monkeypatch.setattr(imports_module, "package_splat", fake_package)
    upload = _upload(uploads, "scene.ply", _gaussian(count=4))
    record = service.create(upload, "Scene thử", "user-1", "Minh An", "reviewer")
    assert record.status == "PACKAGING" and record.input_kind == "gaussian_ply"
    assert record.created_by_name == "Minh An" and record.created_by_role == "reviewer"
    assert service.get(record.import_id).created_by_role == "reviewer"
    ready = service.package(record.import_id, upload, None)
    assert ready.status == "READY" and ready.delivery_ref is not None
    assert ready.delivery_ref.source_provenance == {
        "visual_source": "user_import",
        "source_format": "gaussian_ply",
        "upload_checksum": upload.checksum,
    }
    assert ready.operation is not None and ready.operation.status == "SUCCEEDED"
    assert service.content_path(record.import_id).read_bytes().startswith(b"sog:")
    assert [item.import_id for item in service.list()] == [record.import_id]


def test_packaging_failure_is_recorded(world, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    uploads, service = world

    def broken(*_: object) -> Path:
        raise ValueError("splat-transform lỗi")

    monkeypatch.setattr(imports_module, "package_splat", broken)
    upload = _upload(uploads, "scene.ply", _gaussian(count=2))
    record = service.create(upload, "Scene lỗi", None)
    failed = service.package(record.import_id, upload, None)
    assert failed.status == "FAILED" and failed.error and failed.delivery_ref is None
    with pytest.raises(SceneImportError):
        service.content_path(record.import_id)


def test_imported_sog_is_copied_byte_for_byte_without_recompression(world, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    uploads, service = world
    payload = sog_archive(model="2dgs")
    upload = _upload(uploads, "export.sog", payload)
    source = service.resolver.require_uri(upload.artifact_uri, upload.checksum)

    def should_not_recompress(*_: object) -> Path:
        raise AssertionError("uploaded SOG must not be round-tripped through PLY")

    monkeypatch.setattr(imports_module, "package_splat", should_not_recompress)
    record = service.create(upload, "External SOG", "user-1")
    ready = service.package(record.import_id, upload, None)

    assert ready.status == "READY" and ready.input_kind == "gaussian_sog"
    assert ready.delivery_ref is not None
    assert ready.delivery_ref.source_provenance["source_format"] == "gaussian_sog"
    assert service.content_path(record.import_id).read_bytes() == source.read_bytes() == payload
