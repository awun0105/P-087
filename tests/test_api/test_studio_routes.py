"""HTTP tests cho Studio upload → scene: fixture proof, không chạy worker/GPU."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models.contracts.manifests import InputManifest, JobStatus
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.projects.registry import ProjectRegistry

_ATTESTATION = {
    "data_origin": "self_collected_no_pii",
    "declared_owner": "Studio test",
    "declared_purpose": "MVP upload test",
    "rights_to_use_confirmed": True,
    "anonymization_confirmed": True,
    "retention_acknowledged": True,
}


@pytest.fixture
def studio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from src.api.studio import deps

    settings = SimpleNamespace(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        artifact_root=tmp_path / "artifacts",
        product_upload_max_bytes=64,
        product_privacy_mode="self_attested",
        product_processing_config=Path(__file__).resolve().parents[2] / "configs/product/processing_presets_v1.json",
    )
    probe = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry = ProjectRegistry(
        runtime_root=tmp_path / "artifacts",
        database=RuntimeDatabase(settings.database_url),
        execution_profile=ExecutionProfile(
            config_checksum=probe._fixture_config_checksum(),
            runtime_manifest_checksum=probe._fixture_runtime_checksum(),
            seed=7,
        ),
    )
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    return SimpleNamespace(settings=settings, registry=registry, root=tmp_path)


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _upload(client: AsyncClient, name: str = "kho.mp4", body: bytes = b"fake-mp4-bytes") -> dict:
    response = await client.post("/api/v1/uploads", params={"filename": name}, content=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_upload_streams_video_and_lists_it(client: AsyncClient, studio: SimpleNamespace) -> None:
    record = await _upload(client, "C:\\clips\\Kho A.MP4")
    assert record["original_name"] == "Kho A.MP4" and record["media_type"] == "video/mp4"
    assert record["artifact_uri"] == f"artifact://jobs/{record['upload_id']}/input/source.mp4"
    stored = studio.root / "artifacts/jobs" / record["upload_id"] / "input/source.mp4"
    assert stored.read_bytes() == b"fake-mp4-bytes"
    listed = (await client.get("/api/v1/uploads")).json()["uploads"]
    assert [item["upload_id"] for item in listed] == [record["upload_id"]]
    assert "artifacts" not in str(listed)


@pytest.mark.asyncio
async def test_upload_rejects_wrong_type_and_oversize(client: AsyncClient, studio: SimpleNamespace) -> None:
    wrong = await client.post("/api/v1/uploads", params={"filename": "scan.ply"}, content=b"x")
    assert wrong.status_code == 422
    big = await client.post("/api/v1/uploads", params={"filename": "big.mov"}, content=b"x" * 65)
    assert big.status_code == 413
    empty = await client.post("/api/v1/uploads", params={"filename": "empty.mov"}, content=b"")
    assert empty.status_code == 422
    assert (await client.get("/api/v1/uploads")).json()["uploads"] == []
    leftovers = [p for p in (studio.root / "artifacts").rglob("*") if p.is_file()]
    assert leftovers == []


@pytest.mark.asyncio
async def test_scene_from_upload_publishes_manifest_and_queues_job(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    upload = await _upload(client)
    response = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    project, job = body["project"], body["job"]
    assert project["privacy"]["privacy_mode"] == "self_attested"
    assert project["privacy"]["dispatch_allowed"] is True
    assert project["privacy"]["result"] == "PRELIMINARY_SCREENED"
    assert project["input_video"]["original_name"] == "kho.mp4"
    assert job["status"] == JobStatus.QUEUED and job["project_id"] == project["project_id"]
    record = studio.registry.get_project(project["project_id"])
    manifest = InputManifest.model_validate_json(
        studio.registry.runtime_resolver.require(record.input_manifest_ref).read_bytes()
    )
    assert manifest.input_manifest_checksum == project["input_manifest_checksum"]
    assert manifest.files[0].checksum == upload["checksum"]
    assert manifest.source_rights_attestation["attested"] is True
    listed = (await client.get("/api/v1/uploads")).json()["uploads"]
    assert listed[0]["project_ids"] == [project["project_id"]]


@pytest.mark.asyncio
async def test_scene_from_upload_requires_mvp_privacy_mode_and_known_upload(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    missing = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": "upload-missing", "name": "x", "attestation": _ATTESTATION},
    )
    assert missing.status_code == 404
    upload = await _upload(client)
    studio.settings.product_privacy_mode = "qa_verified"
    blocked = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "x", "attestation": _ATTESTATION},
    )
    assert blocked.status_code == 409
    no_anonymization = {**_ATTESTATION, "anonymization_confirmed": False}
    studio.settings.product_privacy_mode = "self_attested"
    invalid = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "x", "attestation": no_anonymization},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_progress_endpoint_reports_queued_pipeline(client: AsyncClient, studio: SimpleNamespace) -> None:
    upload = await _upload(client)
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    job_id = created.json()["job"]["job_id"]
    response = await client.get(f"/api/v1/jobs/{job_id}/progress")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "QUEUED" and body["preview_ready"] is False and body["attempt"] == 1
    assert [stage["stage_id"] for stage in body["stages"]] == [
        "ST-INPUT-VALIDATE",
        "ST-PRIVACY-GATE",
        "ST-FRAME-EXTRACT",
        "ST-CAMERA-POSE",
        "ST-VISUAL-RECON",
    ]
    assert {stage["state"] for stage in body["stages"]} == {"pending"}
    assert (await client.get("/api/v1/jobs/job-missing/progress")).status_code == 404


@pytest.mark.asyncio
async def test_scenes_lists_uploaded_scenes_only(client: AsyncClient, studio: SimpleNamespace) -> None:
    studio.registry.seed_from_fixtures()
    upload = await _upload(client)
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    body = (await client.get("/api/v1/scenes")).json()["scenes"]
    assert [scene["project"]["name"] for scene in body] == ["Kho A"]
    assert body[0]["latest_job"]["job_id"] == created.json()["job"]["job_id"]
    assert body[0]["preview_ready"] is False


def _record_machine(studio: SimpleNamespace, vram: float) -> None:
    from datetime import UTC, datetime

    from src.services.orchestration.processing.capability import record
    from src.services.orchestration.processing.models import MachineCapability

    record(
        RuntimeDatabase(studio.settings.database_url),
        MachineCapability(
            worker_id="gpu",
            measured_at=datetime.now(UTC),
            gpu_name="GPU test",
            vram_total_gb=vram,
            cpu_count=8,
            ram_total_gb=32,
            disk_free_gb=200,
        ),
    )


@pytest.mark.asyncio
async def test_processing_options_include_machine_presets(client: AsyncClient, studio: SimpleNamespace) -> None:
    unknown = (await client.get("/api/v1/processing/options")).json()
    assert unknown["capability"] is None
    assert unknown["presets"]["machine_maximum"] == unknown["presets"]["minimum_quality"]
    _record_machine(studio, vram=4)
    body = (await client.get("/api/v1/processing/options")).json()
    assert body["capability"]["gpu_name"] == "GPU test"
    assert {p["key"] for p in body["parameters"]} == set(body["presets"]["minimum_quality"])
    machine = body["presets"]["machine_maximum"]
    assert machine["brush.max_splats"] < body["presets"]["maximum"]["brush.max_splats"]
    checked = (await client.post("/api/v1/processing/evaluate", json={"params": machine})).json()
    assert not checked["blocking"]
    red = (await client.post("/api/v1/processing/evaluate", json={"params": body["presets"]["maximum"]})).json()
    assert red["blocking"]
    assert {p["key"]: p["status"] for p in red["parameters"]}["brush.max_splats"] == "danger"
    bad = await client.post("/api/v1/processing/evaluate", json={"params": {"brush.max_splats": 1}})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_scene_uses_chosen_processing_and_server_blocks_red(client: AsyncClient, studio: SimpleNamespace) -> None:
    import json

    from src.services.orchestration.processing import job_config_reference

    _record_machine(studio, vram=4)
    options = (await client.get("/api/v1/processing/options")).json()
    upload = await _upload(client)
    blocked = await client.post(
        "/api/v1/scenes/from-upload",
        json={
            "upload_id": upload["upload_id"],
            "name": "Quá tải",
            "attestation": _ATTESTATION,
            "processing": options["presets"]["maximum"],
        },
    )
    assert blocked.status_code == 409 and "đỏ" in blocked.json()["detail"]
    chosen = {**options["presets"]["minimum_quality"], "brush.total_train_iters": 12000}
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Tùy chỉnh", "attestation": _ATTESTATION, "processing": chosen},
    )
    assert created.status_code == 201, created.text
    job = created.json()["job"]
    path = studio.registry.runtime_resolver.require(job_config_reference(job["job_id"], job["config_checksum"]))
    stored = json.loads(path.read_text())
    assert stored["brush"]["total_train_iters"] == 12000 and stored["colmap"]["num_threads"] == 8
