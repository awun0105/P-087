"""Bộ mẫu vào danh sách upload qua đúng đường nhận file của sản phẩm, và chạy lại không tạo bản trùng."""

from pathlib import Path

from scripts.demo.make_torwic_lidar_samples import build
from scripts.studio.seed_samples import SAMPLE_ACTOR, seed
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.uploads.service import VideoUploadService
from tests.test_demo.test_torwic_lidar_samples import _dataset


def test_samples_become_selectable_uploads_once(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    build(_dataset(tmp_path / "data"), "Aisle_CW", 0, 8, 2, samples)
    (samples / "manifest.json").write_text("{}")  # file không phải đầu vào thì bị bỏ qua
    service = VideoUploadService(
        RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}"), ArtifactResolver(tmp_path / "artifacts"), 10**8
    )
    added = seed(samples, service)
    assert sorted(record.input_kind for record in added) == ["lidar_scan_sequence", "registered_lidar", "rgb_video"]
    assert all(record.uploaded_by == SAMPLE_ACTOR for record in added)
    assert seed(samples, service) == [] and len(service.list()) == 3
