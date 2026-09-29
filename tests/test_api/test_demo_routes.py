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
from src.services.orchestration.demo import DemoFile, DemoManifest, DemoSource, DemoStage
from src.services.orchestration.jobs.models import JobAttemptRecord

ROOT = Path(__file__).resolve().parents[2]


def _file(root: Path, name: str, data: bytes, media: str) -> DemoFile:
    (root / "files" / name).write_bytes(data)
    return DemoFile(
        name=name, media_type=media, size_bytes=len(data), checksum="sha256:" + hashlib.sha256(data).hexdigest()
    )


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from src.api import routes_studio

    (tmp_path / "files").mkdir()
    manifest = DemoManifest(
        demo_id="demo",
        title="Demo",
        origin="smoke_run",
        source=DemoSource(dataset="TorWIC-SLAM", sequence="Aisle_CW"),
        produced_at=datetime(2026, 9, 29, tzinfo=UTC),
        stages=[DemoStage(stage_id=StageId.CAMERA_POSE, duration_seconds=12.5)],
        frames=[_file(tmp_path, "frame-000001.png", b"png", "image/png")],
        splat=_file(tmp_path, "scene.sog", b"sog-bytes", "application/octet-stream"),
    )
    (tmp_path / "manifest.json").write_text(manifest.model_dump_json())
    (tmp_path / "files" / "secret.txt").write_text("not listed")
    monkeypatch.setattr(routes_studio, "get_settings", lambda: SimpleNamespace(product_demo_dir=tmp_path))
    return tmp_path


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_demo_manifest_and_allow_listed_file(client: AsyncClient, bundle: Path) -> None:
    manifest = (await client.get("/api/v1/demo")).json()
    assert manifest["origin"] == "smoke_run" and manifest["splat"]["name"] == "scene.sog"
    response = await client.get("/api/v1/demo/files/scene.sog")
    assert response.status_code == 200 and response.content == b"sog-bytes"
    for name in ("secret.txt", "..%2Fmanifest.json", "missing.png"):
        assert (await client.get(f"/api/v1/demo/files/{name}")).status_code == 404


@pytest.mark.asyncio
async def test_tampered_or_missing_bundle_is_404(client: AsyncClient, bundle: Path) -> None:
    (bundle / "files" / "scene.sog").write_bytes(b"tampered!")
    assert (await client.get("/api/v1/demo/files/scene.sog")).status_code == 404
    (bundle / "manifest.json").unlink()
    assert (await client.get("/api/v1/demo")).status_code == 404


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
