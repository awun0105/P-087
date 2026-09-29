"""Demo bundle API: chỉ phục vụ file trong allow-list, đúng checksum; thiếu bundle → 404."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scripts.demo.export_demo_bundle import stage_durations
from src.models.contracts.manifests import JobManifest, JobStatus, StageArtifact, StageId
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.samples import DemoFile, DemoManifest, DemoSource, DemoStage

ROOT = Path(__file__).resolve().parents[2]


def _file(root: Path, name: str, data: bytes, media: str) -> DemoFile:
    (root / "files" / name).write_bytes(data)
    return DemoFile(
        name=name, media_type=media, size_bytes=len(data), checksum="sha256:" + hashlib.sha256(data).hexdigest()
    )


def _write_bundle(root: Path, demo_id: str, durations: list[float | None]) -> None:
    (root / "files").mkdir(parents=True)
    manifest = DemoManifest(
        demo_id=demo_id,
        title=f"Demo {demo_id}",
        origin="pipeline_job",
        source=DemoSource(dataset="TorWIC-SLAM", sequence="Aisle_CW"),
        produced_at=datetime(2026, 9, 29, tzinfo=UTC),
        stages=[
            DemoStage(stage_id=stage, duration_seconds=seconds)
            for stage, seconds in zip((StageId.CAMERA_POSE, StageId.VISUAL_RECON), durations, strict=True)
        ],
        frames=[_file(root, "frame-000001.png", b"png", "image/png")],
        splat=_file(root, "scene.sog", b"sog-bytes", "application/octet-stream"),
        processing={"brush.total_train_iters": 7000},
    )
    (root / "manifest.json").write_text(manifest.model_dump_json())
    (root / "files" / "secret.txt").write_text("not listed")


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from src.api.studio import deps

    _write_bundle(tmp_path / "aisle", "a", [12.5, 60.0])
    _write_bundle(tmp_path / "loop", "b", [10.0, None])
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "manifest.json").write_text("{}")
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(product_demo_dir=tmp_path))
    return tmp_path


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_sample_library_lists_valid_bundles(client: AsyncClient, library: Path) -> None:
    samples = (await client.get("/api/v1/samples")).json()["samples"]
    assert [item["sample_id"] for item in samples] == ["aisle", "loop"]
    assert samples[0]["total_seconds"] == 72.5 and samples[0]["has_processing"] is True
    assert samples[1]["total_seconds"] is None  # thiếu thời lượng một stage → không đoán
    assert samples[0]["cover"] == "frame-000001.png"
    assert (await client.get("/api/v1/samples/aisle")).json()["processing"] == {"brush.total_train_iters": 7000}


@pytest.mark.asyncio
async def test_sample_files_are_allow_listed_and_checksummed(client: AsyncClient, library: Path) -> None:
    response = await client.get("/api/v1/samples/aisle/files/scene.sog")
    assert response.status_code == 200 and response.content == b"sog-bytes"
    for path in (
        "/api/v1/samples/aisle/files/secret.txt",
        "/api/v1/samples/aisle/files/..%2Fmanifest.json",
        "/api/v1/samples/missing/files/scene.sog",
        "/api/v1/samples/broken",
    ):
        assert (await client.get(path)).status_code == 404
    (library / "aisle" / "files" / "scene.sog").write_bytes(b"tampered!")
    assert (await client.get("/api/v1/samples/aisle/files/scene.sog")).status_code == 404


@pytest.mark.asyncio
async def test_single_bundle_root_still_works(client: AsyncClient, tmp_path: Path, monkeypatch) -> None:
    from src.api.studio import deps

    _write_bundle(tmp_path / "single", "torwic-aisle-cw", [1.0, 2.0])
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(product_demo_dir=tmp_path / "single"))
    samples = (await client.get("/api/v1/samples")).json()["samples"]
    assert [item["sample_id"] for item in samples] == ["torwic-aisle-cw"]
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(product_demo_dir=tmp_path / "none"))
    assert (await client.get("/api/v1/samples")).json()["samples"] == []


def test_stage_durations_follow_completed_chain() -> None:
    t0 = datetime(2026, 9, 29, 8, tzinfo=UTC)
    job = JobManifest.model_validate_json((ROOT / "fixtures/mock_job/job_manifest.json").read_text())

    def done(stage: StageId, seconds: int) -> StageArtifact:
        return StageArtifact(
            stage_id=stage,
            status="SUCCEEDED",
            artifact_type="X",
            artifact_uri=f"artifact://jobs/j/{stage.value.lower()}",
            artifact_checksum="sha256:" + "a" * 64,
            data_class="derived",
            completed_at=t0 + timedelta(seconds=seconds),
        )

    job = job.model_copy(
        update={
            "stage_artifacts": [
                done(StageId.INPUT_VALIDATE, 10),
                done(StageId.PRIVACY_GATE, 11),
                done(StageId.FRAME_EXTRACT, 40),
                done(StageId.CAMERA_POSE, 340),
            ]
        }
    )
    attempts = [
        JobAttemptRecord(attempt=1, status=JobStatus.QUEUED, current_stage=StageId.INPUT_VALIDATE, recorded_at=t0),
        JobAttemptRecord(attempt=1, status=JobStatus.RUNNING, current_stage=StageId.INPUT_VALIDATE, recorded_at=t0),
    ]
    durations = [stage.duration_seconds for stage in stage_durations(job, attempts)]
    assert durations == [10.0, 1.0, 29.0, 300.0, None]
