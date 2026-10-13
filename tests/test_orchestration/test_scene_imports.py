"""Gói 5 (ADR 0004 §3): scene import từ PLY 3DGS — chỉ xem/chỉnh sửa, không phải job."""

import io
import json
import math
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.uploads import VideoUploadService
from src.services.orchestration.uploads import scene_imports as imports_module
from src.services.orchestration.uploads.scene_imports import ImportService, SceneImportError
from src.services.reconstruction import extract_member
from src.services.reconstruction import imports as reconstruction_imports
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


class _Admission:
    def operation_profile_for_import(self, **kwargs: object):
        from src.services.orchestration.jobs.admission import OperationResourceProfile

        gpu_required = bool(kwargs["gpu_required"])
        return OperationResourceProfile(
            required_gb={"vram": 1.0 if gpu_required else 0.0, "ram": 2.0, "disk": 1.0},
            danger_ratio=0.9,
            measured=False,
            gpu_required=gpu_required,
        )

    def admit_operation(self, request):  # noqa: ANN001
        return SimpleNamespace(status="admitted")

    def touch_operation(self, request):  # noqa: ANN001
        return True

    def release_operation(self, request):  # noqa: ANN001
        return True


def _fake_package(source: Path, workspace: Path, gpu_index: int | None, **_: object) -> Path:
    workspace.mkdir(parents=True)
    output = workspace / "scene.sog"
    output.write_bytes(sog_archive(sh_bands=3, count=4))
    return output


def _fake_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports_module, "package_splat", _fake_package)
    monkeypatch.setattr(imports_module, "validate_sog_runtime", lambda *args, **kwargs: None)


def test_video_upload_cannot_become_import(world) -> None:  # noqa: ANN001
    uploads, service = world
    with pytest.raises(SceneImportError, match="3DGS"):
        service.create(_upload(uploads, "kho.mp4", MP4 + b"x"), "Kho", None)


def test_ply_import_packages_to_sog_and_becomes_ready(world, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    uploads, service = world
    _fake_runtime(monkeypatch)
    upload = _upload(uploads, "scene.ply", _gaussian(count=4))
    record = service.create(upload, "Scene thử", "user-1", "Minh An", "reviewer")
    assert record.status == "PACKAGING" and record.input_kind == "gaussian_ply"
    assert record.created_by_name == "Minh An" and record.created_by_role == "reviewer"
    assert service.get(record.import_id).created_by_role == "reviewer"
    assert service.process_next(admission=_Admission(), worker_id="test-worker") is True
    ready = service.get(record.import_id)
    assert ready.status == "READY" and ready.delivery_ref is not None
    assert ready.delivery_ref.source_provenance == {
        "visual_source": "user_import",
        "source_format": "gaussian_ply",
        "upload_checksum": upload.checksum,
    }
    assert ready.operation is not None and ready.operation.status == "SUCCEEDED"
    assert service.content_path(record.import_id).read_bytes() == sog_archive(sh_bands=3, count=4)
    assert [item.import_id for item in service.list()] == [record.import_id]


def test_packaging_failure_is_recorded(world, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    uploads, service = world

    def broken(*_: object, **__: object) -> Path:
        raise ValueError("splat-transform lỗi")

    monkeypatch.setattr(imports_module, "package_splat", broken)
    upload = _upload(uploads, "scene.ply", _gaussian(count=2))
    record = service.create(upload, "Scene lỗi", None)
    assert service.process_next(admission=_Admission(), worker_id="test-worker") is True
    failed = service.get(record.import_id)
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
    monkeypatch.setattr(imports_module, "validate_sog_runtime", lambda *args, **kwargs: None)
    record = service.create(upload, "External SOG", "user-1")
    assert service.process_next(admission=_Admission(), worker_id="test-worker") is True
    ready = service.get(record.import_id)

    assert ready.status == "READY" and ready.input_kind == "gaussian_sog"
    assert ready.delivery_ref is not None
    assert ready.delivery_ref.source_provenance["source_format"] == "gaussian_sog"
    assert service.content_path(record.import_id).read_bytes() == source.read_bytes() == payload


def test_zip_member_extraction_rejects_traversal_and_expansion_limit(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.ply", b"data")
    with pytest.raises(ValueError, match="không an toàn"):
        extract_member(traversal, "../escape.ply", tmp_path / "escape.ply", max_uncompressed_bytes=16)

    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w") as archive:
        archive.writestr("scene.ply", b"123456")
    with pytest.raises(ValueError, match="vượt giới hạn giải nén"):
        extract_member(oversized, "scene.ply", tmp_path / "oversized.ply", max_uncompressed_bytes=5)


def test_zip_member_extraction_rejects_duplicate_names_and_truncated_crc(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("scene.ply", b"first")
            archive.writestr("scene.ply", b"second")
    with pytest.raises(ValueError, match="tên thành viên bị lặp"):
        extract_member(duplicate, "scene.ply", tmp_path / "duplicate.ply", max_uncompressed_bytes=64)

    truncated = tmp_path / "truncated.zip"
    with zipfile.ZipFile(truncated, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("scene.ply", b"original member bytes")
    payload = bytearray(truncated.read_bytes())
    payload[payload.index(b"original member bytes")] ^= 0x01
    truncated.write_bytes(payload)
    with pytest.raises(zipfile.BadZipFile):
        extract_member(truncated, "scene.ply", tmp_path / "truncated.ply", max_uncompressed_bytes=64)


def test_sog_runtime_validation_rejects_non_object_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProcess:
        def __init__(self, _settings: object) -> None:
            self.settings = SimpleNamespace(module_path=tmp_path / "splat-transform")

        def run(self, args: tuple[str, ...], _label: tuple[Path, str]) -> None:
            Path(args[3]).write_text("[]", encoding="utf-8")

    monkeypatch.setattr(reconstruction_imports, "VoxelProcess", FakeProcess)
    monkeypatch.setattr(reconstruction_imports, "VoxelRuntimeSettings", lambda: object())
    with pytest.raises(ValueError, match="invalid inspection report"):
        reconstruction_imports.validate_sog_runtime(
            tmp_path / "scene.sog",
            tmp_path / "validation",
            expected_count=4,
            expected_sh_bands=3,
        )


def test_import_default_camera_update(world, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    uploads, service = world
    _fake_runtime(monkeypatch)
    upload = _upload(uploads, "scene.ply", _gaussian(count=4))
    record = service.create(upload, "Scene thử camera", "user-1")
    assert service.process_next(admission=_Admission(), worker_id="test-worker") is True

    from src.services.orchestration.uploads.scene_imports import CameraPoseRecord

    ready = service.get(record.import_id)
    assert ready.initial_camera is not None
    assert ready.default_camera is None

    camera = CameraPoseRecord(position=[1.0, 2.0, 3.0], target=[0.0, 0.0, 0.0], fov=60.0)
    updated = service.update_default_camera(record.import_id, camera)
    assert updated.default_camera == camera
    assert updated.initial_camera == ready.initial_camera
    assert service.get(record.import_id).default_camera == camera

    # Gỡ bookmark (unbookmark) quay lại initial_camera
    cleared = service.update_default_camera(record.import_id, None)
    assert cleared.default_camera is None
    assert cleared.initial_camera == ready.initial_camera
    assert service.get(record.import_id).default_camera is None


def test_generated_camera_starts_inside_the_scene_with_viewer_fov(tmp_path: Path) -> None:
    sog = tmp_path / "scene.sog"
    sog.write_bytes(sog_archive())
    camera = imports_module.compute_robust_camera_from_sog(sog)
    assert camera is not None
    assert camera.position == [0.0, 0.0, 0.0]
    assert camera.target == [2.0, 0.0, 0.0]
    assert camera.fov == 85.0

    # A translated cloud with an outlier must keep the eye in its central region.
    ply = tmp_path / "scene.ply"
    points = [(10.0, -2.0, 4.0)] * 12 + [(10000.0, 10000.0, 10000.0)]
    header = "ply\nformat binary_little_endian 1.0\nelement vertex 13\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
    ply.write_bytes(header.encode("ascii") + b"".join(struct.pack("<fff", *point) for point in points))
    camera = imports_module.compute_robust_camera_from_ply(ply)
    assert camera is not None
    assert camera.position == [-10.0, 2.0, 4.0]
    assert camera.target == [-8.0, 2.0, 4.0]
    assert camera.fov == 85.0


def test_sog_camera_decodes_rgb_webp_instead_of_using_outlier_bounds(tmp_path: Path) -> None:
    from PIL import Image

    image = Image.new("RGB", (13, 1))
    image.putdata([(0, 0, 0)] * 12 + [(255, 255, 255)])
    webp = io.BytesIO()
    image.save(webp, format="WEBP", lossless=True)
    sog = tmp_path / "rgb-means.sog"
    with zipfile.ZipFile(sog, "w") as bundle:
        bundle.writestr(
            "meta.json",
            json.dumps({"count": 13, "means": {"mins": [0, 0, 0], "maxs": [math.log(101)] * 3}}),
        )
        bundle.writestr("means_l.webp", webp.getvalue())
        bundle.writestr("means_u.webp", webp.getvalue())
    camera = imports_module.compute_robust_camera_from_sog(sog)
    assert camera is not None
    # The lone remote splat must not put the eye at the metadata box center (50, 50, 50).
    assert camera.position == [0, 0, 0]
    assert camera.target == [2, 0, 0]
    assert camera.fov == 85


def test_legacy_initial_view_migrates_once_without_overwriting_bookmark(world, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    uploads, service = world
    _fake_runtime(monkeypatch)
    record = service.create(_upload(uploads, "scene.ply", _gaussian(count=4)), "Legacy", None)
    assert service.process_next(admission=_Admission(), worker_id="test-worker") is True
    ready = service.get(record.import_id)
    old_view = imports_module.CameraPoseRecord(position=[10, 5, 10], target=[0, 0, 0], fov=60)
    bookmark = imports_module.CameraPoseRecord(position=[1, 2, 3], target=[4, 2, 3], fov=72)
    legacy = ready.model_copy(update={"initial_camera": old_view, "initial_camera_version": None})
    with service.database.transaction(write=True) as tx:
        tx.execute("UPDATE r2s_imports SET payload=? WHERE import_id=?", (legacy.model_dump_json(), record.import_id))

    compute = imports_module.compute_robust_camera_from_sog
    calls = 0

    def compute_while_bookmark_changes(path: Path) -> imports_module.CameraPoseRecord | None:
        nonlocal calls
        calls += 1
        service.update_default_camera(record.import_id, bookmark)
        return compute(path)

    monkeypatch.setattr(imports_module, "compute_robust_camera_from_sog", compute_while_bookmark_changes)
    migrated = service.get(record.import_id)
    assert migrated.initial_camera_version == 2
    assert migrated.initial_camera is not None and migrated.initial_camera.position == [0, 0, 0]
    assert migrated.initial_camera.fov == 85
    assert migrated.default_camera == bookmark
    assert service.get(record.import_id).default_camera == bookmark
    assert calls == 1
    service.update_default_camera(record.import_id, None)
    assert service.get(record.import_id).initial_camera == migrated.initial_camera
    assert service.get(record.import_id).default_camera is None
