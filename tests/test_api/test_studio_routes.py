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
    from src.api import routes_studio

    settings = SimpleNamespace(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        artifact_root=tmp_path / "artifacts",
        product_upload_max_bytes=64,
        product_privacy_mode="self_attested",
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
    monkeypatch.setattr(routes_studio, "get_settings", lambda: settings)
    monkeypatch.setattr(routes_studio, "get_project_registry", lambda: registry)
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
