"""Demo bundle API: chỉ phục vụ file trong allow-list, đúng checksum; thiếu bundle → 404."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scripts.demo.export_demo_bundle import stage_durations
from src.models.contracts.manifests import JobManifest, JobStatus, StageArtifact, StageId
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.samples import (
    DemoFact,
    DemoFile,
    DemoManifest,
    DemoSource,
    DemoStage,
    DemoStageAsset,
)

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
    # Ghi shape bundle cũ thật sự: chỉ 2 stage đã chạy, chưa có field state.
    payload = manifest.model_dump(mode="json")
    payload["stages"] = [
        stage.model_dump(mode="json", exclude={"state"}) for stage in manifest.stages if stage.state == "succeeded"
    ]
    (root / "manifest.json").write_text(json.dumps(payload))
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
    stages = (await client.get("/api/v1/samples/aisle")).json()["stages"]
    assert len(stages) == 8
    assert sum(stage["state"] == "succeeded" for stage in stages) == 2
    assert stages[-1]["stage_id"] == StageId.OBJECT_EXTRACT and stages[-1]["state"] == "pending"


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
    assert durations == [40.0, None, None, 300.0, None, None, None, None]
    assert [stage.state for stage in stage_durations(job, attempts)] == ["succeeded"] * 4 + ["pending"] * 4


def test_export_includes_later_stages_with_real_state_and_timing() -> None:
    t0 = datetime(2026, 10, 2, tzinfo=UTC)
    job = JobManifest.model_validate_json((ROOT / "fixtures/mock_job/job_manifest.json").read_text())
    geometry = StageArtifact(
        stage_id=StageId.RGB_GEOMETRY,
        status="SUCCEEDED",
        artifact_type="Geometry",
        artifact_uri="artifact://jobs/j/geometry",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        started_at=t0,
        completed_at=t0 + timedelta(seconds=12),
    )
    result = stage_durations(job.model_copy(update={"stage_artifacts": [geometry]}), [])
    assert len(result) == 8 and result[-2].state == "succeeded" and result[-2].duration_seconds == 12
    assert result[-1].state == "pending" and result[-1].duration_seconds is None


def test_sample_manifest_carries_cameras_trajectory() -> None:
    from src.services.reconstruction.views import CameraMarker

    camera = CameraMarker(frame_id=1, center=(1.0, 2.0, 3.0), rotation_xyzw=(0.0, 0.0, 0.0, 1.0))
    manifest = DemoManifest(
        demo_id="cam_demo",
        title="Demo With Cameras",
        origin="pipeline_job",
        source=DemoSource(dataset="TorWIC-SLAM", sequence="Aisle_CW"),
        produced_at=datetime(2026, 9, 29, tzinfo=UTC),
        stages=[],
        splat=DemoFile(
            name="scene.sog",
            media_type="application/octet-stream",
            size_bytes=100,
            checksum="sha256:" + "0" * 64,
        ),
        cameras=[camera],
    )
    payload = manifest.model_dump_json()
    reloaded = DemoManifest.model_validate_json(payload)
    assert len(reloaded.cameras) == 1
    assert reloaded.cameras[0].frame_id == 1
    assert reloaded.cameras[0].center == (1.0, 2.0, 3.0)


def _manifest(stages: list[DemoStage]) -> DemoManifest:
    return DemoManifest(
        demo_id="asset_demo",
        title="Demo có asset",
        origin="pipeline_job",
        source=DemoSource(dataset="TorWIC-SLAM", sequence="Aisle_CW"),
        produced_at=datetime(2026, 10, 10, tzinfo=UTC),
        stages=stages,
        splat=DemoFile(
            name="scene.sog", media_type="application/octet-stream", size_bytes=100, checksum="sha256:" + "0" * 64
        ),
    )


@pytest.mark.parametrize("rotation", [(0, 0, 0, 0), (0, 0, 0, 2), (0, 1), (0, 0, 0, float("nan"))])
def test_sample_rejects_invalid_display_rotation(rotation: tuple[float, ...]) -> None:
    data = _manifest([]).model_dump()
    data["display_rotation_xyzw"] = rotation
    with pytest.raises(ValueError):
        DemoManifest.model_validate(data)


def test_lidar_stages_are_kept_after_frame_extract_in_pipeline_order() -> None:
    manifest = _manifest(
        [
            DemoStage(stage_id=StageId.LIDAR_CALIBRATION_QA),
            DemoStage(stage_id=StageId.LIDAR_INGEST),
            DemoStage(stage_id=StageId.FRAME_EXTRACT),
        ]
    )
    order = [stage.stage_id for stage in manifest.stages]
    assert order[:5] == [
        StageId.INPUT_VALIDATE,
        StageId.PRIVACY_GATE,
        StageId.FRAME_EXTRACT,
        StageId.LIDAR_INGEST,
        StageId.LIDAR_CALIBRATION_QA,
    ]
    assert StageId.LIDAR_ODOMETRY not in order
    # Bundle không LiDAR giữ nguyên pipeline Studio.
    assert all("LIDAR" not in stage.stage_id.value for stage in _manifest([]).stages)
    assert len(_manifest([]).stages) == 8


def test_stage_assets_are_served_through_the_allow_list_and_validated() -> None:
    image = DemoFile(name="metric.png", media_type="image/png", size_bytes=10, checksum="sha256:" + "1" * 64)
    manifest = _manifest(
        [
            DemoStage(
                stage_id=StageId.METRIC_CANONICALIZE,
                assets=[
                    DemoStageAsset(kind="image", title="Điểm đo", file=image),
                    DemoStageAsset(kind="facts", facts=[DemoFact(label="Khoảng cách A–B", value="1.20 m")]),
                ],
            )
        ]
    )
    assert image in manifest.files()
    reloaded = DemoManifest.model_validate_json(manifest.model_dump_json())
    metric = next(s for s in reloaded.stages if s.stage_id == StageId.METRIC_CANONICALIZE)
    assert [asset.kind for asset in metric.assets] == ["image", "facts"]
    with pytest.raises(ValueError):
        DemoStageAsset(kind="image")  # thiếu file
    with pytest.raises(ValueError):
        DemoStageAsset(kind="facts", facts=[])  # thiếu số đo
    with pytest.raises(ValueError):
        DemoStageAsset(kind="facts", facts=[DemoFact(label="a", value="b")], file=image)
    with pytest.raises(ValueError):
        _manifest(
            [
                DemoStage(stage_id=StageId.METRIC_CANONICALIZE, assets=[DemoStageAsset(kind="image", file=image)]),
                DemoStage(stage_id=StageId.RGB_GEOMETRY, assets=[DemoStageAsset(kind="image", file=image)]),
            ]
        )  # trùng tên file


@pytest.fixture
def sample_reviewer(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    from src.api import auth
    from src.main import app

    user = SimpleNamespace(user_id="reviewer-1")
    monkeypatch.setitem(app.dependency_overrides, auth.require_reviewer, lambda: user)
    monkeypatch.setattr(auth, "auth_service", lambda: SimpleNamespace(audit=lambda *args: None))
    return user


@pytest.mark.asyncio
async def test_remove_sample_persists_and_stops_serving_files_without_deleting_them(
    client: AsyncClient, library: Path, sample_reviewer: SimpleNamespace
) -> None:
    original = (library / "aisle" / "manifest.json").read_bytes()
    response = await client.delete("/api/v1/samples/aisle")
    assert response.status_code == 200
    assert [item["sample_id"] for item in (await client.get("/api/v1/samples")).json()["samples"]] == ["loop"]
    assert (await client.get("/api/v1/samples/aisle")).status_code == 404
    assert (await client.get("/api/v1/samples/aisle/files/scene.sog")).status_code == 404
    assert (library / "aisle" / "manifest.json").read_bytes() == original
    assert (library / "aisle" / "files" / "scene.sog").read_bytes() == b"sog-bytes"


@pytest.mark.asyncio
async def test_remove_sample_requires_a_real_reviewer_even_without_auth(
    client: AsyncClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api import auth
    from src.main import app

    monkeypatch.setitem(app.dependency_overrides, auth.require_reviewer, lambda: None)
    assert (await client.delete("/api/v1/samples/aisle")).status_code == 401
    assert (await client.get("/api/v1/samples/aisle")).status_code == 200


@pytest.mark.asyncio
async def test_remove_legacy_single_bundle(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_reviewer: SimpleNamespace
) -> None:
    from src.api.studio import deps

    _write_bundle(tmp_path / "single", "legacy", [1.0, 2.0])
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(product_demo_dir=tmp_path / "single"))
    assert (await client.delete("/api/v1/samples/legacy")).status_code == 200
    assert (await client.get("/api/v1/samples")).json()["samples"] == []
    assert (tmp_path / "single" / "manifest.json").is_file()


@pytest.mark.asyncio
async def test_remove_sample_reports_missing_or_unwritable_library(
    client: AsyncClient, library: Path, sample_reviewer: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services.orchestration.samples import DemoLibrary

    assert (await client.delete("/api/v1/samples/missing")).status_code == 404

    def unavailable(self: DemoLibrary, sample_id: str) -> None:
        raise PermissionError("internal path must stay private")

    monkeypatch.setattr(DemoLibrary, "unpublish", unavailable)
    response = await client.delete("/api/v1/samples/aisle")
    assert response.status_code == 503
    assert "internal path" not in response.text
    assert (await client.get("/api/v1/samples/aisle")).status_code == 200


def test_remove_sample_does_not_write_through_a_symlink_outside_the_library(tmp_path: Path) -> None:
    from src.services.orchestration.samples import DemoLibrary, DemoUnavailableError

    outside = tmp_path / "outside"
    _write_bundle(outside, "external", [1.0, 2.0])
    root = tmp_path / "library"
    root.mkdir()
    (root / "external").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DemoUnavailableError):
        DemoLibrary(root).unpublish("external")
    assert sorted(item.name for item in outside.iterdir()) == ["files", "manifest.json"]
