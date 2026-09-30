"""Ảnh xem trước của scene: JPEG nhỏ từ frame đầu, cache theo checksum frame."""

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.services.orchestration import thumbnails

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="cần ffmpeg")


def _frame(tmp_path: Path) -> tuple[ProductArtifactRef, Path]:
    source = tmp_path / "000000.png"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720", "-frames:v", "1", str(source)],
        check=True,
    )
    reference = ProductArtifactRef(
        artifact_type="RGBFrame",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-a/rec02a/frames/000000.png",
        artifact_checksum="sha256:" + "ab" * 32,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.FRAME_EXTRACT,
        job_id="job-a",
    )
    return reference, source


def test_thumbnail_is_small_jpeg_and_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reference, source = _frame(tmp_path)
    reads: list[str] = []

    def require(ref: ProductArtifactRef) -> Path:
        reads.append(ref.artifact_uri)
        return source

    registry = SimpleNamespace(get_job=lambda job_id: object(), runtime_resolver=SimpleNamespace(require=require))
    monkeypatch.setattr(thumbnails, "job_frame_images", lambda registry, job: [reference])
    path = thumbnails.scene_thumbnail(registry, "job-a", tmp_path / "cache")  # type: ignore[arg-type]
    assert path is not None and path.read_bytes()[:2] == b"\xff\xd8"  # JPEG
    assert path.stat().st_size < source.stat().st_size
    again = thumbnails.scene_thumbnail(registry, "job-a", tmp_path / "cache")  # type: ignore[arg-type]
    assert again == path and len(reads) == 1  # lần hai đọc cache, không đọc lại frame


def test_no_frames_means_no_thumbnail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = SimpleNamespace(get_job=lambda job_id: object(), runtime_resolver=None)
    monkeypatch.setattr(thumbnails, "job_frame_images", lambda registry, job: [])
    assert thumbnails.scene_thumbnail(registry, "job-a", tmp_path / "cache") is None  # type: ignore[arg-type]
