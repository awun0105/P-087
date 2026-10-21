"""HTTP tests cho Studio upload → scene: fixture proof, không chạy worker/GPU."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models.contracts.manifests import InputManifest, JobStatus
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import RuleResult
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.review.simulation_package import SimulationPackage
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.usd.capabilities import (
    EffectiveExportMode,
    ExportCapabilityBlocker,
    ExportCapabilityReport,
    ExportCapabilityStatus,
    ExportRequirements,
    RuntimeQualificationStatus,
)
from tests.test_reconstruction.support.sog_fixtures import sog_archive

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
        artifact_s3_bucket=None,
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        artifact_root=tmp_path / "artifacts",
        product_worker_root=tmp_path / "worker",
        product_geometry_gpu_index=None,
        product_upload_max_bytes=64,
        product_privacy_mode="self_attested",
        product_processing_config=Path(__file__).resolve().parents[2] / "configs/product/processing_presets_v1.json",
        product_colmap_use_gpu=False,
        product_input_runtime_registry=None,
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


async def _upload(
    client: AsyncClient, name: str = "kho.mp4", body: bytes = b"\x00\x00\x00\x14ftypqt  " + b"fake-mp4"
) -> dict:
    response = await client.post("/api/v1/uploads", params={"filename": name}, content=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_upload_streams_video_and_lists_it(client: AsyncClient, studio: SimpleNamespace) -> None:
    record = await _upload(client, "C:\\clips\\Kho A.MP4")
    assert record["original_name"] == "Kho A.MP4" and record["media_type"] == "video/mp4"
    assert record["artifact_uri"] == f"artifact://jobs/{record['upload_id']}/input/source.mp4"
    stored = studio.root / "artifacts/jobs" / record["upload_id"] / "input/source.mp4"
    assert stored.read_bytes() == b"\x00\x00\x00\x14ftypqt  " + b"fake-mp4"
    listed = (await client.get("/api/v1/uploads")).json()["uploads"]
    assert [item["upload_id"] for item in listed] == [record["upload_id"]]
    assert "artifacts" not in str(listed)


@pytest.mark.asyncio
async def test_dataset_replay_video_is_served_separately_from_image_manifest(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    images = (studio.root / "000.jpg", studio.root / "001.png")
    for image in images:
        image.write_bytes(image.name.encode())
    video = studio.root / "display.mp4"
    video.write_bytes(b"replay-only")
    project = studio.registry.create_project_from_dataset_images(
        name="replay test", dataset_owner="test dataset", images=images, display_video=video
    )
    response = await client.get(f"/api/v1/projects/{project.project_id}/display-video")
    assert response.status_code == 200 and response.content == b"replay-only"
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.asyncio
async def test_abandoned_upload_cleanup_removes_bytes_and_assembly_rows(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    uploaded = await client.post(
        "/api/v1/uploads?filename=input.mp4&temporary=true", content=b"\x00\x00\x00\x18ftypmp42"
    )
    assert uploaded.status_code == 201
    upload_id = uploaded.json()["upload_id"]
    assert (await client.post(f"/api/v1/input-assemblies/uploads/{upload_id}/stage")).status_code == 200
    assembled = await client.post(
        "/api/v1/input-assemblies", json={"upload_ids": [upload_id], "declarations": {}, "bindings": []}
    )
    assert assembled.status_code == 201, assembled.text
    assembly_id = assembled.json()["assembly_id"]
    deleted = await client.post("/api/v1/uploads/temporary/discard", json={"upload_ids": [upload_id]})
    assert deleted.status_code == 200 and deleted.json()["deleted"] == [upload_id]
    assert (await client.get(f"/api/v1/input-assemblies/uploads/{upload_id}")).status_code == 404
    assert (await client.get(f"/api/v1/input-assemblies/{assembly_id}")).status_code == 404
    assert not (studio.root / "artifacts/jobs" / upload_id).exists()


@pytest.mark.asyncio
async def test_upload_cleanup_enforces_owner(client: AsyncClient, studio: SimpleNamespace) -> None:
    uploaded = await client.post(
        "/api/v1/uploads?filename=input.mp4&temporary=true", content=b"\x00\x00\x00\x18ftypmp42"
    )
    upload_id = uploaded.json()["upload_id"]
    with studio.registry.persistence.database.transaction(write=True) as tx:
        tx.execute("UPDATE r2s_temporary_uploads SET owner_id=? WHERE upload_id=?", ("other-user", upload_id))
    refused = await client.post("/api/v1/uploads/temporary/discard", json={"upload_ids": [upload_id]})
    assert refused.status_code == 403
    assert (studio.root / "artifacts/jobs" / upload_id / "input/source.mp4").exists()


@pytest.mark.asyncio
async def test_existing_verified_upload_can_be_staged_for_unified_input_without_copying_bytes(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    from src.services.orchestration.uploads import VideoUploadService

    uploads = VideoUploadService(
        studio.registry.persistence.database, studio.registry.runtime_resolver, studio.settings.product_upload_max_bytes
    )
    pending = uploads.begin("prepared.mp4")
    original_bytes = b"\x00\x00\x00\x14ftypqt  fake-mp4"
    pending.publication.write(original_bytes)
    uploaded = uploads.finish(pending)

    staged = await client.post(f"/api/v1/input-assemblies/uploads/{uploaded.upload_id}/stage")
    repeated = await client.post(f"/api/v1/input-assemblies/uploads/{uploaded.upload_id}/stage")
    fetched = await client.get(f"/api/v1/input-assemblies/uploads/{uploaded.upload_id}")

    assert staged.status_code == repeated.status_code == fetched.status_code == 200
    assert staged.json() == repeated.json() == fetched.json()
    assert staged.json()["source_file"]["checksum"] == uploaded.checksum
    assert staged.json()["staged_files"][0]["observed_format"] == "video_mov"
    assert studio.registry.runtime_resolver.resolve(uploaded.artifact_uri).read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_sog_import_is_durably_queued_and_idempotent(client: AsyncClient, studio: SimpleNamespace) -> None:
    from src.services.orchestration.uploads import VideoUploadService

    uploads = VideoUploadService(
        studio.registry.persistence.database, studio.registry.runtime_resolver, 8 * 1024 * 1024
    )
    pending = uploads.begin("external.sog")
    pending.publication.write(sog_archive(model="2dgs"))
    upload_record = uploads.finish(pending)
    upload = upload_record.model_dump(mode="json")
    assert upload["input_kind"] == "gaussian_sog" and upload["media_type"] == "application/x-sog"

    request = {"upload_id": upload["upload_id"], "name": "External SOG"}
    first = await client.post("/api/v1/imports", json=request, headers={"Idempotency-Key": "sog-import-1"})
    replay = await client.post("/api/v1/imports", json=request, headers={"Idempotency-Key": "sog-import-1"})

    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert first.json()["import_id"] == replay.json()["import_id"]
    assert first.json()["input_kind"] == "gaussian_sog"
    assert first.json()["status"] == "PACKAGING"
    assert first.json()["operation"]["status"] == "QUEUED"
    assert first.json()["operation"]["attempt"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("source_format", ["gaussian_sog", "gaussian_ply"])
async def test_input_assembly_gaussian_import_replays_the_stored_intent(
    source_format: str, client: AsyncClient, studio: SimpleNamespace
) -> None:
    from src.models.contracts.input_assembly import (
        RuntimeCapabilityKey,
        RuntimeCapabilityRecord,
        RuntimeQualificationRegistry,
        RuntimeQualificationStatus,
        seal_runtime_registry,
    )

    studio.settings.product_upload_max_bytes = 8 * 1024 * 1024
    runtime_path = studio.root / "input-runtime-sog.json"
    capability_key = (
        RuntimeCapabilityKey.GAUSSIAN_SOG_VIEW
        if source_format == "gaussian_sog"
        else RuntimeCapabilityKey.GAUSSIAN_PLY_VIEW
    )
    runtime_path.write_text(
        seal_runtime_registry(
            RuntimeQualificationRegistry(
                schema_version="1.0",
                registry_version=f"test-{source_format}-v1",
                capabilities=[
                    RuntimeCapabilityRecord(
                        capability_key=capability_key,
                        status=RuntimeQualificationStatus.QUALIFIED,
                        runtime_id=f"qualified-{source_format}-importer",
                        runtime_version="1.0.0",
                        qualification_evidence_checksum="sha256:" + "5" * 64,
                    )
                ],
                registry_checksum="sha256:" + "0" * 64,
            )
        ).model_dump_json()
    )
    studio.settings.product_input_runtime_registry = runtime_path

    if source_format == "gaussian_sog":
        payload = sog_archive(model="2dgs")
    else:
        from tests.test_reconstruction.test_input_detection import _gaussian

        payload = _gaussian()
    uploaded = await client.post(
        "/api/v1/input-assemblies/uploads",
        params={"filename": f"external.{source_format.removeprefix('gaussian_')}"},
        content=payload,
    )
    assert uploaded.status_code == 201, uploaded.text
    assembly_response = await client.post(
        "/api/v1/input-assemblies",
        json={"upload_ids": [uploaded.json()["upload_id"]], "requested_intent": "gaussian_view_import"},
    )
    assert assembly_response.status_code == 201, assembly_response.text
    assembly = assembly_response.json()
    resolution = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/resolve", json={"revision": assembly["revision"]}
    )
    assert resolution.status_code == 200, resolution.text
    report = resolution.json()["report"]
    candidate = next(item for item in report["candidates"] if item["candidate_kind"] == "gaussian_view_import")
    assert candidate["state"] == "ready"
    body = {
        "revision": assembly["revision"],
        "resolution_checksum": report["report_checksum"],
        "candidate_id": candidate["candidate_id"],
        "name": "Imported SOG",
    }
    first = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/import",
        json=body,
        headers={"Idempotency-Key": f"assembly-{source_format}-import-1"},
    )
    replay = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/import",
        json=body,
        headers={"Idempotency-Key": f"assembly-{source_format}-import-1"},
    )

    assert first.status_code == replay.status_code == 201, (first.text, replay.text)
    assert first.json()["imported_scene"]["import_id"] == replay.json()["imported_scene"]["import_id"]
    assert first.json()["intent_checksum"] == replay.json()["intent_checksum"]
    assert first.json()["imported_scene"]["input_intent"]["intent_checksum"] == replay.json()["intent_checksum"]
    assert first.json()["imported_scene"]["input_kind"] == source_format
    conflicting = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/import",
        json={**body, "name": "Different request"},
        headers={"Idempotency-Key": f"assembly-{source_format}-import-1"},
    )
    assert conflicting.status_code == 409


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
async def test_input_assembly_run_is_durable_idempotent_and_worker_revalidates_runtime(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    from types import SimpleNamespace

    from src.api.studio import deps
    from src.models.contracts.input_assembly import (
        RuntimeCapabilityKey,
        RuntimeCapabilityRecord,
        RuntimeQualificationRegistry,
        RuntimeQualificationStatus,
        seal_runtime_registry,
    )
    from src.services.orchestration.jobs.runner import _validate_project_input_recipe

    runtime_path = studio.root / "input-runtime.json"
    runtime_path.write_text(
        seal_runtime_registry(
            RuntimeQualificationRegistry(
                schema_version="1.0",
                registry_version="test-r1-v1",
                capabilities=[
                    RuntimeCapabilityRecord(
                        capability_key=RuntimeCapabilityKey.R1,
                        status=RuntimeQualificationStatus.QUALIFIED,
                        runtime_id="qualified-r1-worker",
                        runtime_version="1.2.3",
                        qualification_evidence_checksum="sha256:" + "1" * 64,
                    )
                ],
                registry_checksum="sha256:" + "0" * 64,
            )
        ).model_dump_json()
    )
    studio.settings.product_input_runtime_registry = runtime_path

    uploaded = await client.post(
        "/api/v1/input-assemblies/uploads",
        params={"filename": "walk.mp4", "temporary": True},
        content=b"\x00\x00\x00\x14ftypqt  fake-mp4",
    )
    assert uploaded.status_code == 201, uploaded.text
    created = await client.post("/api/v1/input-assemblies", json={"upload_ids": [uploaded.json()["upload_id"]]})
    assert created.status_code == 201, created.text
    assembly = created.json()
    resolved = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/resolve", json={"revision": assembly["revision"]}
    )
    assert resolved.status_code == 200, resolved.text
    report = resolved.json()["report"]
    candidate_id = report["recommended_candidate_id"]

    options = (await client.get("/api/v1/processing/options")).json()
    chosen = options["presets"]["video_indoor_orbital_360"]
    body = {
        "revision": assembly["revision"],
        "resolution_checksum": report["report_checksum"],
        "candidate_id": candidate_id,
        "name": "Input assembly R1",
        "attestation": _ATTESTATION,
        "processing": chosen,
    }
    first = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
        json=body,
        headers={"Idempotency-Key": "assembly-r1-run-1"},
    )
    replay = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
        json=body,
        headers={"Idempotency-Key": "assembly-r1-run-1"},
    )
    assert first.status_code == replay.status_code == 201, (first.text, replay.text)
    assert first.json()["job"]["job_id"] == replay.json()["job"]["job_id"]
    assert first.json()["project"]["project_id"] == replay.json()["project"]["project_id"]
    conflicting = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
        json={**body, "name": "Different request"},
        headers={"Idempotency-Key": "assembly-r1-run-1"},
    )
    assert conflicting.status_code == 409

    job = studio.registry.get_job(first.json()["job"]["job_id"])
    from src.services.orchestration.processing import job_config_reference

    stored_config = json.loads(
        studio.registry.runtime_resolver.require(job_config_reference(job.job_id, job.config_checksum)).read_bytes()
    )
    assert stored_config["params"] == chosen
    assert stored_config["colmap"]["matching_mode"] == "sequential_vocab_tree"
    assert stored_config["geometry"]["external_fill_size_m"] == 1.6
    assert stored_config["scene"]["max_objects"] == 60
    assert stored_config["simulation"]["ground_plane"] == "enabled"
    project = studio.registry.get_project(job.project_id)
    assert project.input_assembly_ref is not None and project.input_recipe_ref is not None
    manifest = InputManifest.model_validate_json(
        studio.registry.runtime_resolver.require(project.input_manifest_ref).read_bytes()
    )
    attempt = SimpleNamespace(
        registry=studio.registry,
        settings=SimpleNamespace(
            database_url=studio.settings.database_url,
            product_input_runtime_registry=runtime_path,
        ),
        job=job,
    )
    _validate_project_input_recipe(attempt, project, manifest)
    with studio.registry.persistence.database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_input_runs").fetchone() == (1,)
    assert deps.input_assemblies().get_upload(uploaded.json()["upload_id"]).project_ids == [project.project_id]
    cleanup = await client.post(
        "/api/v1/uploads/temporary/discard", json={"upload_ids": [uploaded.json()["upload_id"]]}
    )
    assert cleanup.status_code == 200 and cleanup.json()["deleted"] == []
    assert deps.uploads().get(uploaded.json()["upload_id"])

    runtime_path.write_text(
        seal_runtime_registry(
            RuntimeQualificationRegistry(
                schema_version="1.0",
                registry_version="test-r1-revoked",
                capabilities=[
                    RuntimeCapabilityRecord(
                        capability_key=RuntimeCapabilityKey.R1,
                        status=RuntimeQualificationStatus.UNAVAILABLE,
                        reason_codes=["runtime_revoked"],
                    )
                ],
                registry_checksum="sha256:" + "0" * 64,
            )
        ).model_dump_json()
    )
    with pytest.raises(ValueError, match="runtime or input resolver version differs"):
        _validate_project_input_recipe(attempt, project, manifest)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_key", "cloud_state", "cloud_role", "recipe_group"),
    [
        ("R2", "registered_map", "registered_lidar_map", "R2"),
        ("R3", "single_static_cloud", "static_lidar_cloud", "R3"),
    ],
)
async def test_input_assembly_accepts_registration_map_recipes_end_to_end(
    client: AsyncClient,
    studio: SimpleNamespace,
    runtime_key: str,
    cloud_state: str,
    cloud_role: str,
    recipe_group: str,
) -> None:
    from types import SimpleNamespace

    from src.models.contracts.input_assembly import (
        InputRecipe,
        RuntimeCapabilityKey,
        RuntimeCapabilityRecord,
        RuntimeQualificationRegistry,
        RuntimeQualificationStatus,
        seal_runtime_registry,
    )
    from src.services.orchestration.jobs.registration_preparation import RegistrationRequestPreparer
    from src.services.orchestration.jobs.runner import _validate_project_input_recipe

    studio.settings.product_upload_max_bytes = 1024
    runtime_path = studio.root / f"input-runtime-{runtime_key.lower()}.json"
    runtime_path.write_text(
        seal_runtime_registry(
            RuntimeQualificationRegistry(
                schema_version="1.0",
                registry_version=f"test-{runtime_key.lower()}-v1",
                capabilities=[
                    RuntimeCapabilityRecord(
                        capability_key=RuntimeCapabilityKey(runtime_key),
                        status=RuntimeQualificationStatus.QUALIFIED,
                        runtime_id=f"qualified-{runtime_key.lower()}-registration",
                        runtime_version="1.2.3",
                        qualification_evidence_checksum="sha256:" + "2" * 64,
                    )
                ],
                registry_checksum="sha256:" + "0" * 64,
            )
        ).model_dump_json()
    )
    studio.settings.product_input_runtime_registry = runtime_path

    video = await _upload(client, f"{runtime_key.lower()}-walk.mp4")
    staged_video = await client.post(f"/api/v1/input-assemblies/uploads/{video['upload_id']}/stage")
    assert staged_video.status_code == 200, staged_video.text
    cloud = await client.post(
        "/api/v1/input-assemblies/uploads",
        params={"filename": f"{runtime_key.lower()}-map.pcd"},
        content=(
            b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
            b"WIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n"
        ),
    )
    assert cloud.status_code == 201, cloud.text
    cloud_file_id = cloud.json()["staged_files"][0]["file_id"]

    created = await client.post(
        "/api/v1/input-assemblies",
        json={
            "upload_ids": [staged_video.json()["upload_id"], cloud.json()["upload_id"]],
            "requested_intent": "video_reconstruction",
            "declarations": {
                "same_scene": {"value": True, "provenance": "declared"},
                "cloud_state": {"value": cloud_state, "provenance": "declared"},
                "coordinate_unit": {"value": "m", "provenance": "declared"},
                "lidar_frame_id": {"value": "lidar-map", "provenance": "declared"},
            },
            "bindings": [{"binding_id": "selected-map", "role": cloud_role, "file_ids": [cloud_file_id]}],
        },
    )
    assert created.status_code == 201, created.text
    assembly = created.json()
    resolved = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/resolve", json={"revision": assembly["revision"]}
    )
    assert resolved.status_code == 200, resolved.text
    report = resolved.json()["report"]
    assert report["state"] == "ready", report
    candidate_id = report["recommended_candidate_id"]

    accepted = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
        json={
            "revision": assembly["revision"],
            "resolution_checksum": report["report_checksum"],
            "candidate_id": candidate_id,
            "name": f"{recipe_group} registration input",
            "attestation": _ATTESTATION,
        },
        headers={"Idempotency-Key": f"assembly-{recipe_group.lower()}-registration-run"},
    )
    assert accepted.status_code == 201, accepted.text

    job = studio.registry.get_job(accepted.json()["job"]["job_id"])
    project = studio.registry.get_project(job.project_id)
    assert project.input_recipe_ref is not None
    recipe = studio.registry.runtime_resolver.load_model(project.input_recipe_ref, InputRecipe)
    assert recipe.recipe_group.value == recipe_group
    assert any(binding.role.value == cloud_role and binding.file_ids == [cloud_file_id] for binding in recipe.bindings)
    mode, source_role, source_file_ids = RegistrationRequestPreparer._accepted_map_source(recipe)
    assert mode.value == ("registered_map" if recipe_group == "R2" else "static_cloud")
    assert source_role.value == cloud_role
    assert source_file_ids == [cloud_file_id]
    manifest = InputManifest.model_validate_json(
        studio.registry.runtime_resolver.require(project.input_manifest_ref).read_bytes()
    )
    assert len(manifest.files) == 1
    assert manifest.input_configuration.registered_lidar_present is False

    attempt = SimpleNamespace(
        registry=studio.registry,
        settings=SimpleNamespace(
            database_url=studio.settings.database_url,
            product_input_runtime_registry=runtime_path,
        ),
        job=job,
    )
    evidence = _validate_project_input_recipe(attempt, project, manifest)
    assert evidence is not None
    assert evidence.recipe.recipe_group.value == recipe_group


@pytest.mark.asyncio
async def test_input_assembly_dispatches_supplied_trajectory_only_from_exact_lidar_package(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    from types import SimpleNamespace

    from src.models.contracts.input_assembly import (
        RuntimeCapabilityKey,
        RuntimeCapabilityRecord,
        RuntimeQualificationRegistry,
        RuntimeQualificationStatus,
        seal_runtime_registry,
    )
    from src.services.orchestration.jobs.runner import _validate_project_input_recipe
    from tests.test_reconstruction.test_lidar_package import POSES, _companions, _pcd, _scan, _zip

    studio.settings.product_upload_max_bytes = 16 * 1024 * 1024
    runtime_path = studio.root / "input-runtime-r4.json"
    runtime_path.write_text(
        seal_runtime_registry(
            RuntimeQualificationRegistry(
                schema_version="1.0",
                registry_version="test-r4-v1",
                capabilities=[
                    RuntimeCapabilityRecord(
                        capability_key=RuntimeCapabilityKey.R4,
                        status=RuntimeQualificationStatus.QUALIFIED,
                        runtime_id="qualified-r4-worker",
                        runtime_version="4.0.0",
                        qualification_evidence_checksum="sha256:" + "4" * 64,
                    )
                ],
                registry_checksum="sha256:" + "0" * 64,
            )
        ).model_dump_json()
    )
    studio.settings.product_input_runtime_registry = runtime_path

    video = await client.post(
        "/api/v1/input-assemblies/uploads",
        params={"filename": "walk.mp4"},
        content=b"\x00\x00\x00\x14ftypqt  fake-mp4",
    )
    package_path = _zip(
        studio.root / "lidar.zip",
        {
            **_companions(),
            **{f"lidar/{index:06d}.pcd": _pcd(_scan()) for index in range(POSES)},
        },
    )
    lidar = await client.post(
        "/api/v1/input-assemblies/uploads",
        params={"filename": "lidar.zip"},
        content=package_path.read_bytes(),
    )
    assert video.status_code == lidar.status_code == 201, (video.text, lidar.text)
    package_files = lidar.json()["staged_files"]
    member_ids = {item["archive_member"]["member_path"]: item["file_id"] for item in package_files}
    scan_ids = [member_ids[f"lidar/{index:06d}.pcd"] for index in range(POSES)]
    created = await client.post(
        "/api/v1/input-assemblies",
        json={
            "upload_ids": [video.json()["upload_id"], lidar.json()["upload_id"]],
            "requested_intent": "video_reconstruction",
            "declarations": {
                "same_scene": {"value": True, "provenance": "declared"},
                "cloud_state": {"value": "raw_scan_sequence", "provenance": "declared"},
                "coordinate_unit": {"value": "m", "provenance": "declared"},
                "lidar_frame_id": {"value": "lidar_sensor", "provenance": "declared"},
                "trajectory_convention": {"value": "world_from_sensor", "provenance": "declared"},
            },
            "bindings": [
                {"binding_id": "rgb", "role": "rgb_video", "file_ids": [video.json()["staged_files"][0]["file_id"]]},
                {"binding_id": "scans", "role": "lidar_scan", "file_ids": scan_ids},
                {"binding_id": "trajectory", "role": "sensor_trajectory", "file_ids": [member_ids["traj.txt"]]},
                {
                    "binding_id": "calibration",
                    "role": "camera_lidar_calibration",
                    "file_ids": [member_ids["calibrations.txt"]],
                },
                {"binding_id": "frame-times", "role": "rgb_frame_times", "file_ids": [member_ids["frame_times.txt"]]},
            ],
        },
    )
    assert created.status_code == 201, created.text
    assembly = created.json()
    resolved = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/resolve", json={"revision": assembly["revision"]}
    )
    assert resolved.status_code == 200, resolved.text
    report = resolved.json()["report"]
    candidate = next(
        item
        for item in report["candidates"]
        if item["candidate_kind"] == "video_recipe" and item["recipe_group"] == "R4"
    )
    assert candidate["recipe_group"] == "R4" and candidate["state"] == "ready"
    assert report["recommended_candidate_id"] == candidate["candidate_id"], {
        "state": report["state"],
        "recommended_candidate_id": report["recommended_candidate_id"],
        "candidates": [
            (item.get("recipe_group"), item["state"], [fact["code"] for fact in item["required_facts"]])
            for item in report["candidates"]
        ],
        "missing_facts": [fact["code"] for fact in report["missing_facts"]],
    }

    accepted = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
        json={
            "revision": assembly["revision"],
            "resolution_checksum": report["report_checksum"],
            "candidate_id": candidate["candidate_id"],
            "name": "Supplied trajectory assembly",
            "attestation": _ATTESTATION,
        },
        headers={"Idempotency-Key": "assembly-r4-run-1"},
    )
    assert accepted.status_code == 201, accepted.text
    job = studio.registry.get_job(accepted.json()["job"]["job_id"])
    project = studio.registry.get_project(job.project_id)
    manifest = InputManifest.model_validate_json(
        studio.registry.runtime_resolver.require(project.input_manifest_ref).read_bytes()
    )
    attempt = SimpleNamespace(
        registry=studio.registry,
        settings=SimpleNamespace(
            database_url=studio.settings.database_url,
            product_input_runtime_registry=runtime_path,
        ),
        job=job,
    )
    _validate_project_input_recipe(attempt, project, manifest)
    provenance = manifest.preparation_provenance["lidar"]
    assert provenance["trajectory_origin"] == "supplied"
    assert provenance["evidence"]["scan_count"] == POSES


@pytest.mark.asyncio
async def test_input_assembly_runs_supplied_trajectory_from_loose_files_without_a_zip(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    """Scan, quỹ đạo, calibration và thời điểm frame nộp rời: server tự đóng gói chuẩn rồi chạy R4."""
    import zipfile
    from types import SimpleNamespace

    from src.models.contracts.input_assembly import (
        RuntimeCapabilityKey,
        RuntimeCapabilityRecord,
        RuntimeQualificationRegistry,
        RuntimeQualificationStatus,
        seal_runtime_registry,
    )
    from src.services.orchestration.jobs.runner import _validate_project_input_recipe
    from tests.test_reconstruction.test_lidar_package import POSES, _companions, _pcd, _scan

    studio.settings.product_upload_max_bytes = 16 * 1024 * 1024
    runtime_path = studio.root / "input-runtime-r4-loose.json"
    runtime_path.write_text(
        seal_runtime_registry(
            RuntimeQualificationRegistry(
                schema_version="1.0",
                registry_version="test-r4-loose-v1",
                capabilities=[
                    RuntimeCapabilityRecord(
                        capability_key=RuntimeCapabilityKey.R4,
                        status=RuntimeQualificationStatus.QUALIFIED,
                        runtime_id="qualified-r4-worker",
                        runtime_version="4.0.0",
                        qualification_evidence_checksum="sha256:" + "4" * 64,
                    )
                ],
                registry_checksum="sha256:" + "0" * 64,
            )
        ).model_dump_json()
    )
    studio.settings.product_input_runtime_registry = runtime_path

    async def upload(name: str, payload: bytes) -> dict:
        response = await client.post("/api/v1/input-assemblies/uploads", params={"filename": name}, content=payload)
        assert response.status_code == 201, (name, response.text)
        return response.json()

    video = await upload("walk.mp4", b"\x00\x00\x00\x14ftypqt  fake-mp4")
    companions = _companions()
    trajectory = await upload("poses.txt", companions["traj.txt"])
    calibration = await upload("rig.txt", companions["calibrations.txt"])
    frame_times = await upload("times.txt", companions["frame_times.txt"])
    scans = [await upload(f"scan_{index}.pcd", _pcd(_scan())) for index in range(POSES)]
    scan_ids = [item["staged_files"][0]["file_id"] for item in scans]
    assert all(item["staged_files"][0]["archive_member"] is None for item in scans)

    created = await client.post(
        "/api/v1/input-assemblies",
        json={
            "upload_ids": [
                video["upload_id"],
                trajectory["upload_id"],
                calibration["upload_id"],
                frame_times["upload_id"],
                *[item["upload_id"] for item in scans],
            ],
            "requested_intent": "video_reconstruction",
            "declarations": {
                "same_scene": {"value": True, "provenance": "declared"},
                "cloud_state": {"value": "raw_scan_sequence", "provenance": "declared"},
                "coordinate_unit": {"value": "m", "provenance": "declared"},
                "lidar_frame_id": {"value": "lidar_sensor", "provenance": "declared"},
                "trajectory_convention": {"value": "world_from_sensor", "provenance": "declared"},
            },
            "bindings": [
                {"binding_id": "rgb", "role": "rgb_video", "file_ids": [video["staged_files"][0]["file_id"]]},
                {"binding_id": "scans", "role": "lidar_scan", "file_ids": scan_ids},
                {
                    "binding_id": "trajectory",
                    "role": "sensor_trajectory",
                    "file_ids": [trajectory["staged_files"][0]["file_id"]],
                },
                {
                    "binding_id": "calibration",
                    "role": "camera_lidar_calibration",
                    "file_ids": [calibration["staged_files"][0]["file_id"]],
                },
                {
                    "binding_id": "frame-times",
                    "role": "rgb_frame_times",
                    "file_ids": [frame_times["staged_files"][0]["file_id"]],
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    assembly = created.json()
    resolved = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/resolve", json={"revision": assembly["revision"]}
    )
    assert resolved.status_code == 200, resolved.text
    report = resolved.json()["report"]
    candidate = next(
        item
        for item in report["candidates"]
        if item["candidate_kind"] == "video_recipe" and item["recipe_group"] == "R4"
    )
    assert candidate["state"] == "ready", [fact["code"] for fact in candidate["required_facts"]]
    assert report["recommended_candidate_id"] == candidate["candidate_id"]

    accepted = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
        json={
            "revision": assembly["revision"],
            "resolution_checksum": report["report_checksum"],
            "candidate_id": candidate["candidate_id"],
            "name": "Supplied trajectory from loose files",
            "attestation": _ATTESTATION,
        },
        headers={"Idempotency-Key": "assembly-r4-loose-run-1"},
    )
    assert accepted.status_code == 201, accepted.text
    job = studio.registry.get_job(accepted.json()["job"]["job_id"])
    project = studio.registry.get_project(job.project_id)
    manifest = InputManifest.model_validate_json(
        studio.registry.runtime_resolver.require(project.input_manifest_ref).read_bytes()
    )

    # Manifest chỉ có video + một gói ZIP do server đóng; provenance nêu từng file nguồn.
    zips = [item for item in manifest.files if item.media_type == "application/zip"]
    assert len(zips) == 1
    provenance = manifest.preparation_provenance["lidar"]
    assert provenance["trajectory_origin"] == "supplied"
    assert provenance["evidence"]["scan_count"] == POSES
    members = {item["member_path"]: item for item in provenance["package_members"]}
    assert sorted(members) == sorted(
        [f"{index:06d}.pcd" for index in range(POSES)] + ["trajectory.txt", "calibrations.txt", "frame_times.txt"]
    )
    assert [members[f"{index:06d}.pcd"]["file_id"] for index in range(POSES)] == scan_ids
    assert members["trajectory.txt"]["file_id"] == trajectory["staged_files"][0]["file_id"]

    # Gói do server đóng được gắn vào project, nên xoá project xoá luôn gói (không để dữ liệu LiDAR mồ côi).
    from src.api.studio import deps

    packages = [item for item in deps.uploads().list() if item.input_kind == "lidar_scan_sequence"]
    assert len(packages) == 1 and project.project_id in packages[0].project_ids

    # Gói đã đóng đọc lại được bằng ZIP chuẩn và chứa đúng byte nguồn.
    package_path = studio.registry.runtime_resolver.require_uri(zips[0].artifact_uri, zips[0].checksum)
    with zipfile.ZipFile(package_path) as archive:
        assert archive.read("trajectory.txt") == companions["traj.txt"]
        assert archive.read("000003.pcd") == _pcd(_scan())

    attempt = SimpleNamespace(
        registry=studio.registry,
        settings=SimpleNamespace(
            database_url=studio.settings.database_url,
            product_input_runtime_registry=runtime_path,
        ),
        job=job,
    )
    _validate_project_input_recipe(attempt, project, manifest)

    # Mất gói thì runner phải thất bại rõ ràng, không lặng lẽ bỏ qua bước đối chiếu thành viên.
    from src.services.orchestration.artifacts import ArtifactNotFoundError

    package_path.unlink()
    with pytest.raises(ArtifactNotFoundError):
        _validate_project_input_recipe(attempt, project, manifest)


async def _r4_registry(studio: SimpleNamespace, name: str) -> object:
    """Đăng ký runtime R4 đã qualified cho test chạy file rời; trả về đường dẫn file registry."""
    from src.models.contracts.input_assembly import (
        RuntimeCapabilityKey,
        RuntimeCapabilityRecord,
        RuntimeQualificationRegistry,
        RuntimeQualificationStatus,
        seal_runtime_registry,
    )

    studio.settings.product_upload_max_bytes = 16 * 1024 * 1024
    path = studio.root / name
    path.write_text(
        seal_runtime_registry(
            RuntimeQualificationRegistry(
                schema_version="1.0",
                registry_version="test-r4-v1",
                capabilities=[
                    RuntimeCapabilityRecord(
                        capability_key=RuntimeCapabilityKey.R4,
                        status=RuntimeQualificationStatus.QUALIFIED,
                        runtime_id="qualified-r4-worker",
                        runtime_version="4.0.0",
                        qualification_evidence_checksum="sha256:" + "4" * 64,
                    )
                ],
                registry_checksum="sha256:" + "0" * 64,
            )
        ).model_dump_json()
    )
    studio.settings.product_input_runtime_registry = path
    return path


_R4_DECLARATIONS = {
    "same_scene": {"value": True, "provenance": "declared"},
    "cloud_state": {"value": "raw_scan_sequence", "provenance": "declared"},
    "coordinate_unit": {"value": "m", "provenance": "declared"},
    "lidar_frame_id": {"value": "lidar_sensor", "provenance": "declared"},
    "trajectory_convention": {"value": "world_from_sensor", "provenance": "declared"},
}


_R4_WITH_CAMERA_FRAME = {
    **_R4_DECLARATIONS,
    "camera_frame_id": {"value": "camera_left", "provenance": "declared"},
}


async def _r4_upload(client: AsyncClient, name: str, payload: bytes) -> dict:
    response = await client.post("/api/v1/input-assemblies/uploads", params={"filename": name}, content=payload)
    assert response.status_code == 201, (name, response.text)
    return response.json()


async def _r4_resolve(client: AsyncClient, upload_ids: list[str], bindings: list[dict], declarations: dict) -> tuple:
    created = await client.post(
        "/api/v1/input-assemblies",
        json={
            "upload_ids": upload_ids,
            "requested_intent": "video_reconstruction",
            "declarations": declarations,
            "bindings": bindings,
        },
    )
    assert created.status_code == 201, created.text
    assembly = created.json()
    resolved = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/resolve", json={"revision": assembly["revision"]}
    )
    assert resolved.status_code == 200, resolved.text
    report = resolved.json()["report"]
    candidate = next(
        (
            item
            for item in report["candidates"]
            if item["candidate_kind"] == "video_recipe" and item["recipe_group"] == "R4"
        ),
        None,
    )
    return assembly, report, candidate


async def _r4_run(client: AsyncClient, assembly: dict, report: dict, candidate: dict, key: str):
    return await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
        json={
            "revision": assembly["revision"],
            "resolution_checksum": report["report_checksum"],
            "candidate_id": candidate["candidate_id"],
            "name": "R4 loose",
            "attestation": _ATTESTATION,
        },
        headers={"Idempotency-Key": key},
    )


async def _r4_inputs(
    client: AsyncClient, *, scans_in_zip: bool = False, calibration_file: tuple[str, bytes] | None = None
):
    from tests.test_reconstruction.test_lidar_package import POSES, _companions, _pcd, _scan, _zip

    video = await _r4_upload(client, "walk.mp4", b"\x00\x00\x00\x14ftypqt  fake-mp4")
    companions = _companions()
    trajectory = await _r4_upload(client, "poses.txt", companions["traj.txt"])
    calibration_name, calibration_bytes = calibration_file or ("rig.txt", companions["calibrations.txt"])
    calibration = await _r4_upload(client, calibration_name, calibration_bytes)
    frame_times = await _r4_upload(client, "times.txt", companions["frame_times.txt"])
    if scans_in_zip:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw:
            archive = _zip(Path(raw) / "scans.zip", {f"{i:06d}.pcd": _pcd(_scan()) for i in range(POSES)})
            bundle = await _r4_upload(client, "scans.zip", archive.read_bytes())
        scans = [bundle]
        scan_ids = [
            item["file_id"] for item in sorted(bundle["staged_files"], key=lambda f: f["archive_member"]["member_path"])
        ]
    else:
        scans = [await _r4_upload(client, f"scan_{index}.pcd", _pcd(_scan())) for index in range(POSES)]
        scan_ids = [item["staged_files"][0]["file_id"] for item in scans]
    uploads = [video, trajectory, calibration, frame_times, *scans]
    bindings = [
        {"binding_id": "rgb", "role": "rgb_video", "file_ids": [video["staged_files"][0]["file_id"]]},
        {"binding_id": "scans", "role": "lidar_scan", "file_ids": scan_ids},
        {
            "binding_id": "trajectory",
            "role": "sensor_trajectory",
            "file_ids": [trajectory["staged_files"][0]["file_id"]],
        },
        {
            "binding_id": "calibration",
            "role": "camera_lidar_calibration",
            "file_ids": [calibration["staged_files"][0]["file_id"]],
        },
        {
            "binding_id": "frame-times",
            "role": "rgb_frame_times",
            "file_ids": [frame_times["staged_files"][0]["file_id"]],
        },
    ]
    return [item["upload_id"] for item in uploads], bindings


def _r4_packages() -> list:
    from src.api.studio import deps

    return [item for item in deps.uploads().list() if item.input_kind == "lidar_scan_sequence"]


@pytest.mark.asyncio
async def test_loose_r4_with_missing_declarations_leaves_no_orphan_package(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    await _r4_registry(studio, "input-runtime-r4-orphan.json")
    upload_ids, bindings = await _r4_inputs(client)
    declarations = {key: value for key, value in _R4_DECLARATIONS.items() if key != "trajectory_convention"}
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, declarations)
    # Thiếu khai báo thì resolver không cho ready; ép chạy bằng candidate bất kỳ phải bị chặn và không để lại gói.
    assert candidate is not None
    response = await _r4_run(client, assembly, report, candidate, "orphan-1")
    assert response.status_code in {409, 422}, response.text
    assert _r4_packages() == []


@pytest.mark.asyncio
async def test_loose_r4_failure_after_packaging_removes_the_server_built_package(
    client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lỗi xảy ra SAU khi gói đã được đóng và ghi: gói không thuộc project nào phải bị gỡ, không để bản sao mồ côi."""
    await _r4_registry(studio, "input-runtime-r4-afterfail.json")
    upload_ids, bindings = await _r4_inputs(client)
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, _R4_DECLARATIONS)
    assert candidate["state"] == "ready"

    def explode(*_args: object, **_kwargs: object) -> None:
        raise ValueError("lỗi giả lập sau khi đóng gói")

    monkeypatch.setattr(studio.registry, "create_project_from_input_assembly", explode)

    response = await _r4_run(client, assembly, report, candidate, "afterfail-1")

    assert response.status_code == 422, response.text
    assert _r4_packages() == []


@pytest.mark.asyncio
async def test_loose_r4_replay_with_the_same_key_does_not_create_a_second_package(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    await _r4_registry(studio, "input-runtime-r4-replay.json")
    upload_ids, bindings = await _r4_inputs(client)
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, _R4_DECLARATIONS)
    assert candidate["state"] == "ready"

    first = await _r4_run(client, assembly, report, candidate, "replay-key")
    second = await _r4_run(client, assembly, report, candidate, "replay-key")

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["job"]["job_id"] == second.json()["job"]["job_id"]
    assert len(_r4_packages()) == 1


@pytest.mark.asyncio
async def test_loose_r4_whose_total_size_exceeds_the_package_limit_is_a_conflict_not_a_500(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    await _r4_registry(studio, "input-runtime-r4-size.json")
    upload_ids, bindings = await _r4_inputs(client)
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, _R4_DECLARATIONS)
    assert candidate["state"] == "ready"
    studio.settings.product_upload_max_bytes = 64 * 1024  # từng file nhỏ hơn giới hạn nhưng tổng thì không

    response = await _r4_run(client, assembly, report, candidate, "size-1")

    assert response.status_code in {409, 413}, response.text
    assert "vượt giới hạn" in response.text or "quá lớn" in response.text
    assert _r4_packages() == []


@pytest.mark.asyncio
async def test_r4_with_scans_in_a_zip_and_other_roles_loose_runs_through_a_server_built_package(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    await _r4_registry(studio, "input-runtime-r4-mixed.json")
    upload_ids, bindings = await _r4_inputs(client, scans_in_zip=True)
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, _R4_DECLARATIONS)
    assert candidate["state"] == "ready", [fact["code"] for fact in candidate["required_facts"]]

    response = await _r4_run(client, assembly, report, candidate, "mixed-1")

    assert response.status_code == 201, response.text
    assert len(_r4_packages()) == 1


@pytest.mark.asyncio
async def test_r4_zip_the_legacy_detector_rejects_is_repackaged_instead_of_refused(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    """ZIP có đủ file nhưng thừa một quỹ đạo nên bộ nhận diện gói cũ từ chối: vẫn chạy được sau khi đóng lại."""
    from tests.test_reconstruction.test_lidar_package import POSES, _companions, _pcd, _scan, _zip

    await _r4_registry(studio, "input-runtime-r4-repackage.json")
    import tempfile
    from pathlib import Path

    video = await _r4_upload(client, "walk.mp4", b"\x00\x00\x00\x14ftypqt  fake-mp4")
    companions = _companions()
    members = {
        **companions,
        "traj_other.txt": companions["traj.txt"],  # hai quỹ đạo: gói cũ đòi đúng một
        **{f"{i:06d}.pcd": _pcd(_scan()) for i in range(POSES)},
    }
    with tempfile.TemporaryDirectory() as raw:
        bundle = await _r4_upload(client, "everything.zip", _zip(Path(raw) / "all.zip", members).read_bytes())
    ids = {item["archive_member"]["member_path"]: item["file_id"] for item in bundle["staged_files"]}
    bindings = [
        {"binding_id": "rgb", "role": "rgb_video", "file_ids": [video["staged_files"][0]["file_id"]]},
        {"binding_id": "scans", "role": "lidar_scan", "file_ids": [ids[f"{i:06d}.pcd"] for i in range(POSES)]},
        {"binding_id": "trajectory", "role": "sensor_trajectory", "file_ids": [ids["traj.txt"]]},
        {"binding_id": "calibration", "role": "camera_lidar_calibration", "file_ids": [ids["calibrations.txt"]]},
        {"binding_id": "frame-times", "role": "rgb_frame_times", "file_ids": [ids["frame_times.txt"]]},
    ]
    assembly, report, candidate = await _r4_resolve(
        client, [video["upload_id"], bundle["upload_id"]], bindings, _R4_DECLARATIONS
    )
    assert candidate is not None and candidate["state"] == "ready", [
        fact["code"] for fact in (candidate or {}).get("required_facts", [])
    ]

    response = await _r4_run(client, assembly, report, candidate, "repackage-1")

    assert response.status_code == 201, response.text
    assert len(_r4_packages()) == 1


_ROS_CALIBRATION = (
    "header:\n  frame_id: lidar_sensor\nchild_frame_id: camera_left\n"
    "transform:\n  translation: {x: 0.1, y: 0.0, z: -0.1}\n  rotation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}\n"
)
# Cùng biến đổi với calibration TorWIC của _companions (px 0.1, pz -0.1, quaternion đơn vị), nhưng ngược chiều.
_INVERSE_JSON_CALIBRATION = '{"camera_from_lidar": {"matrix": [[1,0,0,-0.1],[0,1,0,0.0],[0,0,1,0.1],[0,0,0,1]]}}'


async def _r4_package_calibration(studio: SimpleNamespace, job_id: str) -> tuple[str, dict]:
    """(nội dung calibration trong gói do server đóng, provenance của gói) của một job R4 file rời."""
    import zipfile

    job = studio.registry.get_job(job_id)
    project = studio.registry.get_project(job.project_id)
    manifest = InputManifest.model_validate_json(
        studio.registry.runtime_resolver.require(project.input_manifest_ref).read_bytes()
    )
    archive_file = next(item for item in manifest.files if item.media_type == "application/zip")
    path = studio.registry.runtime_resolver.require_uri(archive_file.artifact_uri, archive_file.checksum)
    provenance = manifest.preparation_provenance["lidar"]
    name = provenance["evidence"]["calibration_member"]
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8"), provenance


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_name", "payload"),
    [("tf.yaml", _ROS_CALIBRATION), ("inverse.json", _INVERSE_JSON_CALIBRATION)],
    ids=["ros_tf_yaml", "json_camera_from_lidar_matrix"],
)
async def test_r4_loose_files_accept_other_calibration_formats_and_normalize_them_for_the_package(
    file_name: str, payload: str, client: AsyncClient, studio: SimpleNamespace
) -> None:
    from src.services.reconstruction.lidar.package import parse_calibration
    from tests.test_reconstruction.test_lidar_package import CALIBRATION

    await _r4_registry(studio, f"input-runtime-r4-{file_name}.json")
    upload_ids, bindings = await _r4_inputs(client, calibration_file=(file_name, payload.encode()))
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, _R4_WITH_CAMERA_FRAME)
    assert candidate["state"] == "ready", [fact["code"] for fact in candidate["required_facts"]]

    response = await _r4_run(client, assembly, report, candidate, f"calibration-{file_name}")

    assert response.status_code == 201, response.text
    text, provenance = await _r4_package_calibration(studio, response.json()["job"]["job_id"])
    calibration_member = next(
        item for item in provenance["package_members"] if item["role"] == "camera_lidar_calibration"
    )
    assert calibration_member["normalized"] is True
    # Gói ghi JSON chuẩn và bộ đọc gói cho ra đúng biến đổi của calibration TorWIC tương đương.
    expected = parse_calibration(CALIBRATION, "torwic_txt")
    actual = parse_calibration(text, "json")
    assert actual.translation_xyz == pytest.approx(expected.translation_xyz, abs=1e-9)
    assert actual.rotation_quaternion_xyzw == pytest.approx(expected.rotation_quaternion_xyzw, abs=1e-9)


@pytest.mark.asyncio
async def test_r4_ros_calibration_naming_a_different_lidar_frame_is_refused_without_a_package(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    await _r4_registry(studio, "input-runtime-r4-ros-frame.json")
    upload_ids, bindings = await _r4_inputs(client, calibration_file=("tf.yaml", _ROS_CALIBRATION.encode()))
    declarations = {**_R4_WITH_CAMERA_FRAME, "lidar_frame_id": {"value": "velodyne", "provenance": "declared"}}
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, declarations)
    assert candidate["state"] == "ready"  # resolver chưa đọc nội dung YAML; kiểm tên frame xảy ra lúc đóng gói

    response = await _r4_run(client, assembly, report, candidate, "ros-wrong-frame")

    assert response.status_code == 409, response.text
    assert "không khớp" in response.text
    assert _r4_packages() == []


@pytest.mark.asyncio
async def test_r4_ros_calibration_needs_the_camera_frame_and_checks_both_ends_of_the_file(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    await _r4_registry(studio, "input-runtime-r4-ros-camera.json")
    upload_ids, bindings = await _r4_inputs(client, calibration_file=("tf.yaml", _ROS_CALIBRATION.encode()))

    # Chưa khai frame camera: hỏi, không đoán đầu còn lại của file là camera.
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, _R4_DECLARATIONS)
    assert candidate["state"] == "needs_input"
    assert "CAMERA_FRAME_REQUIRED" in {fact["code"] for fact in candidate["required_facts"]}

    # Khai sai tên camera (đầu kia của file là LiDAR ↔ base_link chẳng hạn): từ chối lúc đóng gói, không để lại gói.
    wrong = {**_R4_DECLARATIONS, "camera_frame_id": {"value": "base_link", "provenance": "declared"}}
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, wrong)
    assert candidate["state"] == "ready"
    response = await _r4_run(client, assembly, report, candidate, "ros-wrong-camera")
    assert response.status_code == 409, response.text
    assert "không phải camera đã khai" in response.text
    assert _r4_packages() == []


@pytest.mark.asyncio
async def test_r4_user_zip_with_a_matrix_calibration_is_repackaged_not_left_to_fail_in_the_worker(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    """Bộ nhận diện gói cũ khớp chuỗi `lidar_from_camera` rồi bộ đọc mới đòi translation+quaternion → hỏng muộn."""
    import tempfile
    from pathlib import Path

    from src.services.reconstruction.lidar.package import parse_calibration
    from tests.test_reconstruction.test_lidar_package import CALIBRATION, POSES, _companions, _pcd, _scan, _zip

    await _r4_registry(studio, "input-runtime-r4-matrix-zip.json")
    video = await _r4_upload(client, "walk.mp4", b"\x00\x00\x00\x14ftypqt  fake-mp4")
    companions = _companions()
    matrix = '{"lidar_from_camera": {"matrix": [[1,0,0,0.1],[0,1,0,0.0],[0,0,1,-0.1],[0,0,0,1]]}}'
    members = {
        "traj.txt": companions["traj.txt"],
        "frame_times.txt": companions["frame_times.txt"],
        "calibration.json": matrix.encode(),
        **{f"{i:06d}.pcd": _pcd(_scan()) for i in range(POSES)},
    }
    with tempfile.TemporaryDirectory() as raw:
        bundle = await _r4_upload(client, "package.zip", _zip(Path(raw) / "p.zip", members).read_bytes())
    ids = {item["archive_member"]["member_path"]: item["file_id"] for item in bundle["staged_files"]}
    bindings = [
        {"binding_id": "rgb", "role": "rgb_video", "file_ids": [video["staged_files"][0]["file_id"]]},
        {"binding_id": "scans", "role": "lidar_scan", "file_ids": [ids[f"{i:06d}.pcd"] for i in range(POSES)]},
        {"binding_id": "trajectory", "role": "sensor_trajectory", "file_ids": [ids["traj.txt"]]},
        {"binding_id": "calibration", "role": "camera_lidar_calibration", "file_ids": [ids["calibration.json"]]},
        {"binding_id": "frame-times", "role": "rgb_frame_times", "file_ids": [ids["frame_times.txt"]]},
    ]
    assembly, report, candidate = await _r4_resolve(
        client, [video["upload_id"], bundle["upload_id"]], bindings, _R4_DECLARATIONS
    )
    assert candidate is not None and candidate["state"] == "ready"

    response = await _r4_run(client, assembly, report, candidate, "matrix-zip-1")

    assert response.status_code == 201, response.text
    text, provenance = await _r4_package_calibration(studio, response.json()["job"]["job_id"])
    assert any(item["normalized"] for item in provenance["package_members"])
    expected = parse_calibration(CALIBRATION, "torwic_txt")
    assert parse_calibration(text, "json").translation_xyz == pytest.approx(expected.translation_xyz, abs=1e-9)


@pytest.mark.asyncio
async def test_r4_calibration_json_with_a_utf8_bom_is_packaged(client: AsyncClient, studio: SimpleNamespace) -> None:
    """Trình soạn thảo trên Windows hay thêm BOM: probe nhận file rồi thì đóng gói cũng phải đọc được."""
    from src.services.reconstruction.lidar.package import parse_calibration
    from tests.test_reconstruction.test_lidar_package import CALIBRATION

    await _r4_registry(studio, "input-runtime-r4-bom.json")
    payload = ("\ufeff" + _INVERSE_JSON_CALIBRATION).encode("utf-8")
    upload_ids, bindings = await _r4_inputs(client, calibration_file=("inverse.json", payload))
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, _R4_WITH_CAMERA_FRAME)
    assert candidate["state"] == "ready", [fact["code"] for fact in candidate["required_facts"]]

    response = await _r4_run(client, assembly, report, candidate, "bom-1")

    assert response.status_code == 201, response.text
    text, _ = await _r4_package_calibration(studio, response.json()["job"]["job_id"])
    expected = parse_calibration(CALIBRATION, "torwic_txt")
    assert parse_calibration(text, "json").translation_xyz == pytest.approx(expected.translation_xyz, abs=1e-9)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_name", "payload"),
    [
        (
            "bad_quaternion.yaml",
            "header:\n  frame_id: lidar_sensor\nchild_frame_id: camera_left\n"
            "transform:\n  translation: {x: 0, y: 0, z: 0}\n  rotation: {x: 0, y: 0, z: 0, w: 3}\n",
        ),
        (
            "two_transforms.yaml",
            "transforms:\n"
            "  - {header: {frame_id: a}, child_frame_id: b, transform: {translation: {x: 0, y: 0, z: 0},"
            " rotation: {x: 0, y: 0, z: 0, w: 1}}}\n"
            "  - {header: {frame_id: a}, child_frame_id: c, transform: {translation: {x: 0, y: 0, z: 0},"
            " rotation: {x: 0, y: 0, z: 0, w: 1}}}\n",
        ),
        ("not_a_rotation.json", '{"camera_from_lidar": {"matrix": [[2,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}}'),
    ],
)
async def test_r4_broken_calibration_is_reported_when_analysing_not_when_packaging(
    file_name: str, payload: str, client: AsyncClient, studio: SimpleNamespace
) -> None:
    await _r4_registry(studio, f"input-runtime-r4-bad-{file_name}.json")
    upload_ids, bindings = await _r4_inputs(client, calibration_file=(file_name, payload.encode()))
    created = await client.post(
        "/api/v1/input-assemblies",
        json={
            "upload_ids": upload_ids,
            "requested_intent": "video_reconstruction",
            "declarations": _R4_WITH_CAMERA_FRAME,
            "bindings": [],
        },
    )
    assert created.status_code == 201, created.text
    resolved = await client.post(
        f"/api/v1/input-assemblies/{created.json()['assembly_id']}/resolve",
        json={"revision": created.json()["revision"]},
    )
    report = resolved.json()["report"]

    # File hỏng làm cả bộ file không hợp lệ ngay lúc phân tích, kèm mã chẩn đoán người dùng đọc được.
    assert report["state"] == "invalid"
    assert {item["code"] for item in report["diagnostics"]} & {"invalid_calibration_yaml", "invalid_calibration_json"}


@pytest.mark.asyncio
async def test_r4_kalibr_file_is_recognized_but_never_used_as_a_camera_lidar_calibration(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    kalibr = (
        "cam0:\n  camera_model: pinhole\n  intrinsics: [461.6, 460.1, 362.7, 246.0]\n"
        "  distortion_model: radtan\n  distortion_coeffs: [0.0, 0.0, 0.0, 0.0]\n  resolution: [752, 480]\n"
        "  T_cam_imu:\n  - [1, 0, 0, 0]\n  - [0, 1, 0, 0]\n  - [0, 0, 1, 0]\n  - [0, 0, 0, 1]\n"
    )
    await _r4_registry(studio, "input-runtime-r4-kalibr.json")
    upload_ids, bindings = await _r4_inputs(client, calibration_file=("camchain.yaml", kalibr.encode()))
    # Không bind vai trò calibration: file Kalibr không có vai trò nào, nên R4 phải thiếu calibration.
    bindings = [item for item in bindings if item["role"] != "camera_lidar_calibration"]
    assembly, report, candidate = await _r4_resolve(client, upload_ids, bindings, _R4_DECLARATIONS)

    assert candidate["state"] == "needs_input"
    assert "CAMERA_LIDAR_CALIBRATION_REQUIRED" in {fact["code"] for fact in candidate["required_facts"]}
    assert any(item["code"] == "kalibr_camera_imu_only" for item in report["diagnostics"]), report["diagnostics"]


async def _scan_times_assembly(
    client: AsyncClient, studio: SimpleNamespace, declarations: dict, times_payload: bytes
) -> dict:
    """Tạo assembly với 3 scan rời + một file thời điểm không bind vai trò; trả snapshot assembly."""
    studio.settings.product_upload_max_bytes = 16 * 1024 * 1024
    from tests.test_reconstruction.test_lidar_package import _pcd, _scan

    video = await _r4_upload(client, "walk.mp4", b"\x00\x00\x00\x14ftypqt  fake-mp4")
    scans = [await _r4_upload(client, f"scan_{index}.pcd", _pcd(_scan())) for index in range(3)]
    times = await _r4_upload(client, "scan_times.txt", times_payload)
    created = await client.post(
        "/api/v1/input-assemblies",
        json={
            "upload_ids": [video["upload_id"], *[item["upload_id"] for item in scans], times["upload_id"]],
            "requested_intent": "video_reconstruction",
            "declarations": declarations,
            "bindings": [],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


@pytest.mark.asyncio
async def test_assembly_estimates_a_missing_scan_time_unit_from_the_sampling_rate(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    snapshot = await _scan_times_assembly(
        client, studio, {"cloud_state": _R4_DECLARATIONS["cloud_state"]}, b"0.0\n0.1\n0.2\n"
    )

    unit = snapshot["declarations"]["lidar_timestamp_unit"]
    assert unit["value"] == "seconds"
    assert unit["provenance"] == "estimated"
    assert unit["method"] == "timestamp_rate_window_v1"
    # Không có file thời điểm frame RGB nên không có gì để suy ở phía RGB.
    assert snapshot["declarations"].get("rgb_timestamp_unit") is None


@pytest.mark.asyncio
async def test_assembly_does_not_override_a_unit_the_user_declared(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    declarations = {
        "cloud_state": _R4_DECLARATIONS["cloud_state"],
        "lidar_timestamp_unit": {"value": "milliseconds", "provenance": "declared"},
    }
    snapshot = await _scan_times_assembly(client, studio, declarations, b"0.0\n0.1\n0.2\n")

    unit = snapshot["declarations"]["lidar_timestamp_unit"]
    assert unit["value"] == "milliseconds" and unit["provenance"] == "declared"


@pytest.mark.asyncio
async def test_assembly_leaves_an_unguessable_unit_empty_for_the_user_to_declare(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    # Khoảng cách 5 đơn vị: 0,2 Hz theo giây hoặc 200 Hz theo mili giây, cả hai khả dĩ nên không được đoán.
    payload = b"0\n5\n10\n"
    snapshot = await _scan_times_assembly(client, studio, {"cloud_state": _R4_DECLARATIONS["cloud_state"]}, payload)

    assert snapshot["declarations"].get("lidar_timestamp_unit") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ["zip", "loose"])
@pytest.mark.parametrize("recipe_group", ["R5", "R6"])
async def test_estimated_odometry_run_requires_qualified_runtime_and_verified_rgb_bindings(
    recipe_group: str, layout: str, client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from src.models.contracts.input_assembly import (
        RuntimeCapabilityKey,
        RuntimeCapabilityRecord,
        RuntimeQualificationRegistry,
        RuntimeQualificationStatus,
        seal_runtime_registry,
    )
    from src.services.orchestration.jobs.runner import _validate_project_input_recipe
    from tests.test_reconstruction.test_lidar_package import _companions, _pcd, _scan, _zip

    studio.settings.product_upload_max_bytes = 16 * 1024 * 1024
    runtime_path = studio.root / f"input-runtime-{recipe_group.lower()}.json"
    capabilities = [
        RuntimeCapabilityRecord(
            capability_key=RuntimeCapabilityKey.R5,
            status=RuntimeQualificationStatus.QUALIFIED,
            runtime_id="kiss-icp-python",
            runtime_version="1.3.0",
            qualification_evidence_checksum="sha256:" + "5" * 64,
        )
    ]
    if recipe_group == "R6":
        capabilities.append(
            RuntimeCapabilityRecord(
                capability_key=RuntimeCapabilityKey.R6,
                status=RuntimeQualificationStatus.QUALIFIED,
                runtime_id="qualified-r6-sensor-guided",
                runtime_version="6.0.0",
                qualification_evidence_checksum="sha256:" + "6" * 64,
            )
        )
    runtime_path.write_text(
        seal_runtime_registry(
            RuntimeQualificationRegistry(
                schema_version="1.0",
                registry_version=f"test-{recipe_group.lower()}-v1",
                capabilities=capabilities,
                registry_checksum="sha256:" + "0" * 64,
            )
        ).model_dump_json()
    )
    studio.settings.product_input_runtime_registry = runtime_path

    video = await client.post(
        "/api/v1/input-assemblies/uploads",
        params={"filename": "walk.mp4"},
        content=b"\x00\x00\x00\x14ftypqt  fake-mp4",
    )
    scans = {f"lidar/{index:06d}.pcd": _pcd(_scan()) for index in range(4)}
    scans["lidar/times.txt"] = b"0.0\n0.1\n0.2\n0.3\n"
    if recipe_group == "R6":
        companions = _companions()
        scans["lidar/calibrations.txt"] = companions["calibrations.txt"]
        scans["lidar/frame_times.txt"] = companions["frame_times.txt"]
    assert video.status_code == 201, video.text
    if layout == "zip":
        scan_upload = await client.post(
            "/api/v1/input-assemblies/uploads",
            params={"filename": "raw-scans.zip"},
            content=_zip(studio.root / f"{recipe_group.lower()}-scans.zip", scans).read_bytes(),
        )
        assert scan_upload.status_code == 201, scan_upload.text
        scan_upload_ids = [scan_upload.json()["upload_id"]]
        member_ids = {
            item["archive_member"]["member_path"]: item["file_id"]
            for item in scan_upload.json()["staged_files"]
            if item["archive_member"] is not None
        }
    else:
        # Mỗi file nộp riêng, không có ZIP nào: scan, thời điểm scan, calibration, thời điểm frame.
        scan_upload_ids = []
        member_ids = {}
        for name, payload in scans.items():
            response = await client.post(
                "/api/v1/input-assemblies/uploads",
                params={"filename": name.rsplit("/", 1)[-1]},
                content=payload,
            )
            assert response.status_code == 201, (name, response.text)
            staged = response.json()["staged_files"]
            assert len(staged) == 1 and staged[0]["archive_member"] is None
            scan_upload_ids.append(response.json()["upload_id"])
            member_ids[name] = staged[0]["file_id"]
    declarations = {
        "same_scene": {"value": True, "provenance": "declared"},
        "cloud_state": {"value": "raw_scan_sequence", "provenance": "declared"},
        "coordinate_unit": {"value": "m", "provenance": "declared"},
        "lidar_frame_id": {"value": "lidar_sensor", "provenance": "declared"},
        "lidar_timestamp_unit": {"value": "seconds", "provenance": "declared"},
    }
    bindings = [
        {"binding_id": "scans", "role": "lidar_scan", "file_ids": [member_ids[f"lidar/{i:06d}.pcd"] for i in range(4)]},
        {"binding_id": "scan-times", "role": "lidar_scan_times", "file_ids": [member_ids["lidar/times.txt"]]},
    ]
    if recipe_group == "R6":
        declarations.update(
            {
                "clock_relation": {"value": "same_clock", "provenance": "declared"},
                "rgb_timestamp_unit": {"value": "seconds", "provenance": "declared"},
            }
        )
        bindings.extend(
            [
                {
                    "binding_id": "calibration",
                    "role": "camera_lidar_calibration",
                    "file_ids": [member_ids["lidar/calibrations.txt"]],
                },
                {
                    "binding_id": "rgb-frame-times",
                    "role": "rgb_frame_times",
                    "file_ids": [member_ids["lidar/frame_times.txt"]],
                },
            ]
        )
    created = await client.post(
        "/api/v1/input-assemblies",
        json={
            "upload_ids": [video.json()["upload_id"], *scan_upload_ids],
            "requested_intent": "video_reconstruction",
            "declarations": declarations,
            "bindings": [
                {
                    "binding_id": "rgb",
                    "role": "rgb_video",
                    "file_ids": [video.json()["staged_files"][0]["file_id"]],
                },
                *bindings,
            ],
        },
    )
    assert created.status_code == 201, created.text
    assembly = created.json()
    resolved = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/resolve", json={"revision": assembly["revision"]}
    )
    assert resolved.status_code == 200, resolved.text
    report = resolved.json()["report"]
    candidate = next(item for item in report["candidates"] if item.get("recipe_group") == recipe_group)
    if recipe_group == "R6":
        assert report["state"] == "needs_input"
        assert "VERIFIED_RGB_FRAME_MAP_REQUIRED" in {fact["code"] for fact in report["missing_facts"]}
        blocked = await client.post(
            f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
            json={
                "revision": assembly["revision"],
                "resolution_checksum": report["report_checksum"],
                "candidate_id": candidate["candidate_id"],
                "name": "R6 missing verified frame map",
                "attestation": _ATTESTATION,
            },
            headers={"Idempotency-Key": "assembly-r6-unverified-frame-map"},
        )
        assert blocked.status_code == 409
        return
    assert report["state"] == "ready", {
        "report": report["state"],
        "recommended": report["recommended_candidate_id"],
        "selected": candidate["candidate_id"],
        "candidates": [
            (item.get("recipe_group"), item["state"], [fact["code"] for fact in item["required_facts"]])
            for item in report["candidates"]
        ],
        "missing": [fact["code"] for fact in report["missing_facts"]],
    }
    assert candidate["state"] == "ready"
    assert report["recommended_candidate_id"] == candidate["candidate_id"]

    accepted = await client.post(
        f"/api/v1/input-assemblies/{assembly['assembly_id']}/run",
        json={
            "revision": assembly["revision"],
            "resolution_checksum": report["report_checksum"],
            "candidate_id": candidate["candidate_id"],
            "name": f"Estimated trajectory {recipe_group}",
            "attestation": _ATTESTATION,
        },
        headers={"Idempotency-Key": f"assembly-{recipe_group.lower()}-run-1"},
    )
    assert accepted.status_code == 201, accepted.text
    job = studio.registry.get_job(accepted.json()["job"]["job_id"])
    project = studio.registry.get_project(job.project_id)
    from src.services.orchestration.inputs.assembly import InputAssemblyService
    from src.services.orchestration.uploads import VideoUploadService

    input_uploads = InputAssemblyService(
        RuntimeDatabase(studio.settings.database_url), str(runtime_path), studio.registry.runtime_resolver
    )
    product_uploads = VideoUploadService(
        RuntimeDatabase(studio.settings.database_url),
        studio.registry.runtime_resolver,
        studio.settings.product_upload_max_bytes,
    )
    assert project.project_id in product_uploads.get(video.json()["upload_id"]).project_ids
    for scan_upload_id in scan_upload_ids:
        assert project.project_id in input_uploads.get_upload(scan_upload_id).project_ids
    manifest = InputManifest.model_validate_json(
        studio.registry.runtime_resolver.require(project.input_manifest_ref).read_bytes()
    )
    attempt = SimpleNamespace(
        registry=studio.registry,
        settings=SimpleNamespace(
            database_url=studio.settings.database_url,
            product_input_runtime_registry=runtime_path,
        ),
        job=job,
    )
    accepted_evidence = _validate_project_input_recipe(attempt, project, manifest)
    assert accepted_evidence is not None
    assert accepted_evidence.recipe.recipe_group.value == recipe_group
    assert any(item.component_id == "odometry-profile" for item in accepted_evidence.recipe.component_versions)
    assert job.status == JobStatus.QUEUED
    if recipe_group != "R5":
        return

    import json

    import numpy as np

    from src.models.contracts.manifests import StageId
    from src.models.contracts.reconstruction import EstimatedTrajectoryProductEvidence
    from src.services.orchestration.artifacts import ArtifactChecksumError
    from src.services.orchestration.jobs.models import TransitionRequest
    from src.services.orchestration.jobs.runner import _Attempt, _execute_lidar_odometry
    from src.services.reconstruction.lidar.cloud_payload import inspect_point_cloud
    from src.services.reconstruction.lidar.odometry import KissIcpProcess

    monkeypatch.setenv("R2S_LIDAR_ODOMETRY_WORK_ROOT", str(studio.root / "odometry-work"))
    started = studio.registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    started = studio.registry.record_stage_progress(started, StageId.LIDAR_ODOMETRY)
    workspace = studio.root / "worker" / job.job_id / "attempt-r5"
    workspace.mkdir(parents=True)
    attempt = _Attempt(registry=studio.registry, settings=studio.settings, job=started, workspace=workspace)

    def fake_provider_run(
        self: object,
        manifest_path: Path,
        output_path: Path,
        log_path: Path,
        profile: object,
        *,
        cancel_event: object,
        lease_is_current: object,
    ) -> dict[str, object]:
        del self, log_path, profile, cancel_event
        assert callable(lease_is_current) and lease_is_current()
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        scan_specs = manifest_payload["scans"]
        poses = []
        for index in range(len(scan_specs)):
            matrix = np.eye(4)
            matrix[0, 3] = index * 0.1
            poses.append(matrix.tolist())
        result = {
            "schema_version": "1.0",
            "provider_id": "kiss-icp-python",
            "provider_version": "1.3.0",
            "poses": poses,
            "point_counts": [int(np.load(item["path"], allow_pickle=False).shape[0]) for item in scan_specs],
            "provider_elapsed_seconds": 0.2,
            "provider_cpu_seconds": 0.1,
            "provider_peak_rss_bytes": 32_000_000,
            "process_elapsed_seconds": 0.3,
        }
        output_path.write_text(json.dumps(result), encoding="utf-8")
        return result

    monkeypatch.setattr(KissIcpProcess, "run", fake_provider_run)
    completed = _execute_lidar_odometry(attempt)

    assert completed.status == JobStatus.RUNNING
    assert completed.current_stage == StageId.CAMERA_POSE
    stage = next(item for item in completed.stage_artifacts if item.stage_id == StageId.LIDAR_ODOMETRY)
    product_evidence = studio.registry.runtime_resolver.load_model(
        studio.registry._to_product_ref(completed.job_id, stage),
        EstimatedTrajectoryProductEvidence,
    )
    evidence = product_evidence.consumer_evidence
    assert evidence.world_frame_status == "pending_world_from_map_confirmation"
    assert evidence.floor_status == "pending_floor_and_up_axis_evidence"
    assert evidence.alignment_status == "not_registered"
    assert evidence.assembly_ref.job_id == completed.job_id
    assert evidence.assembly_ref.artifact_checksum == project.input_assembly_ref.artifact_checksum
    assert len(evidence.ingest_binding.source_scan_file_ids) == 4
    map_evidence = product_evidence.map_evidence
    assert map_evidence.map_status == "ready"
    assert map_evidence.map_cloud_ref is not None
    assert map_evidence.point_count == map_evidence.fusion_stats.point_count
    assert (
        map_evidence.map_cloud_ref.source_provenance["source_scan_file_ids"]
        == evidence.ingest_binding.source_scan_file_ids
    )
    map_path = studio.registry.runtime_resolver.require(map_evidence.map_cloud_ref)
    map_stats = inspect_point_cloud(map_path, max_points=20_000_000)
    assert map_stats.geometry_format == "ply"
    assert map_stats.point_count == map_evidence.point_count

    map_path.write_bytes(b"tampered map payload")
    with pytest.raises(ArtifactChecksumError, match="checksum mismatch"):
        studio.registry.record_lidar_odometry(started, stage)


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
        "ST-METRIC-CANONICALIZE",
        "ST-RGB-GEOMETRY",
        "ST-OBJECT-EXTRACT",
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


@pytest.mark.asyncio
async def test_scene_list_flags_a_job_waiting_for_the_anonymization_review(
    client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Danh sách phải nói job đang chờ người xem bản đã che, thay vì để nó trông như đang chạy."""
    from src.api.studio import scenes

    studio.registry.seed_from_fixtures()
    upload = await _upload(client)
    await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    assert (await client.get("/api/v1/scenes")).json()["scenes"][0]["awaiting_anonymization_review"] is False
    monkeypatch.setattr(scenes, "awaiting_anonymization_review", lambda job: True)
    assert (await client.get("/api/v1/scenes")).json()["scenes"][0]["awaiting_anonymization_review"] is True


def _finished_job(studio: SimpleNamespace, *, object_stage: bool = True, status: str = "SUCCEEDED"):  # noqa: ANN202
    from datetime import UTC, datetime

    from src.models.contracts.manifests import JobStatus, StageArtifact, StageId, StageStatus

    when = datetime(2026, 10, 10, tzinfo=UTC)
    stage = StageArtifact(
        stage_id=StageId.OBJECT_EXTRACT,
        status=StageStatus.SUCCEEDED,
        artifact_type="SceneIR",
        artifact_uri="artifact://jobs/j/scene",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        started_at=when,
        completed_at=when,
    )
    job = studio.registry.get_job("job-fixture-001")
    return job.model_copy(update={"status": JobStatus(status), "stage_artifacts": [stage] if object_stage else []})


def _registry_with_scene(provenance: dict, revision: str = "rev-001", *, error: Exception | None = None):  # noqa: ANN202
    reads: list[str] = []

    def current(job_id: str):  # noqa: ANN202
        reads.append(job_id)
        if error is not None:
            raise error
        return SimpleNamespace(scene=SimpleNamespace(provenance=provenance))

    head = SimpleNamespace(scene_revision=revision)
    holder = SimpleNamespace(head=head)
    scene = SimpleNamespace(current=current, head_repository=SimpleNamespace(get=lambda job_id: holder.head))
    return SimpleNamespace(scene=scene), reads, holder


def test_scene_list_flags_a_finished_job_whose_object_extraction_awaits_the_user(
    studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Job xong nhưng tách theo vật lỗi hết số lần thử: danh sách không được ghi 'Đã dựng scene' như thể xong hẳn."""
    from src.api.studio import scenes

    monkeypatch.setattr(scenes, "_objectify_request_pending", lambda *_: False)

    scenes._OBJECT_CHOICE_CACHE.clear()
    studio.registry.seed_from_fixtures()
    waiting = {"object_extraction": "objectify_failed_awaiting_choice"}
    registry, reads, _ = _registry_with_scene(waiting)
    assert scenes._awaiting_object_choice(registry, _finished_job(studio)) is True

    scenes._OBJECT_CHOICE_CACHE.clear()
    healthy, _, _ = _registry_with_scene(
        {"object_extraction": "objectify_v1(sampro3d_sam2+render_lift+coacd+seed_inpaint)"}
    )
    assert scenes._awaiting_object_choice(healthy, _finished_job(studio)) is False

    # Chưa xong hoặc chưa có bước tách vật thể thành công thì không đọc scene.
    scenes._OBJECT_CHOICE_CACHE.clear()
    registry, reads, _ = _registry_with_scene(waiting)
    assert scenes._awaiting_object_choice(registry, _finished_job(studio, status="RUNNING")) is False
    assert scenes._awaiting_object_choice(registry, _finished_job(studio, object_stage=False)) is False
    assert reads == []


def test_object_choice_is_not_reported_while_a_rerun_is_pending(
    studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.studio import scenes

    scenes._OBJECT_CHOICE_CACHE.clear()
    studio.registry.seed_from_fixtures()
    registry, _, _ = _registry_with_scene({"object_extraction": "objectify_failed_awaiting_choice"})
    job = _finished_job(studio)
    monkeypatch.setattr(scenes, "_objectify_request_pending", lambda *_: True)
    assert scenes._awaiting_object_choice(registry, job) is False
    monkeypatch.setattr(scenes, "_objectify_request_pending", lambda *_: False)
    assert scenes._awaiting_object_choice(registry, job) is True


def test_a_vanished_scene_file_never_breaks_the_list(studio: SimpleNamespace) -> None:
    from src.api.studio import scenes

    scenes._OBJECT_CHOICE_CACHE.clear()
    studio.registry.seed_from_fixtures()
    broken, _, _ = _registry_with_scene({}, error=FileNotFoundError("scene.json"))
    assert scenes._awaiting_object_choice(broken, _finished_job(studio)) is False


@pytest.mark.asyncio
async def test_scene_list_response_carries_the_object_choice_flag(
    client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.studio import scenes

    studio.registry.seed_from_fixtures()
    upload = await _upload(client)
    await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    assert (await client.get("/api/v1/scenes")).json()["scenes"][0]["awaiting_object_choice"] is False
    monkeypatch.setattr(scenes, "_awaiting_object_choice", lambda registry, job: True)
    assert (await client.get("/api/v1/scenes")).json()["scenes"][0]["awaiting_object_choice"] is True


@pytest.mark.asyncio
async def test_scene_list_reads_preview_and_object_choice_once_per_scene(
    client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-069: T-059 từng gọi `preview_ready` và `_awaiting_object_choice` hai lần cho mỗi scene."""
    from src.api.studio import deps as studio_deps
    from src.api.studio import scenes

    studio.registry.seed_from_fixtures()
    upload = await _upload(client)
    await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    calls = {"preview": 0, "choice": 0}
    real_preview, real_choice = studio_deps.preview_ready, scenes._awaiting_object_choice

    def preview(*args):
        calls["preview"] += 1
        return real_preview(*args)

    def choice(*args):
        calls["choice"] += 1
        return real_choice(*args)

    monkeypatch.setattr(studio_deps, "preview_ready", preview)
    monkeypatch.setattr(scenes, "_awaiting_object_choice", choice)
    body = (await client.get("/api/v1/scenes")).json()
    with_job = [scene for scene in body["scenes"] if scene["latest_job"] is not None]
    assert with_job
    assert calls == {"preview": len(with_job), "choice": len(with_job)}


def test_object_choice_is_cached_per_scene_revision_and_never_guessed(
    studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.studio import scenes

    monkeypatch.setattr(scenes, "_objectify_request_pending", lambda *_: False)
    from src.services.orchestration.scene.errors import SceneNotAvailableError

    scenes._OBJECT_CHOICE_CACHE.clear()
    studio.registry.seed_from_fixtures()
    job = _finished_job(studio)
    registry, reads, holder = _registry_with_scene({"object_extraction": "objectify_failed_awaiting_choice"})
    assert scenes._awaiting_object_choice(registry, job) is True
    assert scenes._awaiting_object_choice(registry, job) is True
    assert reads == [job.job_id]  # lần hai lấy từ bộ nhớ đệm theo revision
    holder.head = SimpleNamespace(scene_revision="rev-002")  # scene đổi revision (vd. người dùng đã chọn hộp ứng viên)
    scenes._awaiting_object_choice(registry, job)
    assert len(reads) == 2

    scenes._OBJECT_CHOICE_CACHE.clear()
    broken, _, _ = _registry_with_scene({}, error=SceneNotAvailableError("chưa có"))
    assert scenes._awaiting_object_choice(broken, job) is False  # scene chưa đọc được: không đoán


def _record_machine(studio: SimpleNamespace, vram: float, vocab: bool | None = True) -> None:
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
            colmap_vocab_tree_available=vocab,
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
    assert stored["colmap"]["use_gpu"] is False


@pytest.mark.asyncio
async def test_scene_creation_honors_colmap_use_gpu_setting(client: AsyncClient, studio: SimpleNamespace) -> None:
    import json

    from src.services.orchestration.processing import job_config_reference

    studio.settings.product_colmap_use_gpu = True
    upload = await _upload(client)
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "GPU Scene", "attestation": _ATTESTATION},
    )
    assert created.status_code == 201, created.text
    job = created.json()["job"]
    path = studio.registry.runtime_resolver.require(job_config_reference(job["job_id"], job["config_checksum"]))
    stored = json.loads(path.read_text())
    assert stored["colmap"]["use_gpu"] is True


@pytest.mark.asyncio
async def test_scene_from_gaussian_upload_is_refused_until_import_flow_exists(
    client: AsyncClient, studio: SimpleNamespace
) -> None:
    """ADR 0004: file PLY 3DGS được nhận và nhận diện, nhưng chưa tạo job video từ nó."""
    from tests.test_reconstruction.test_input_detection import _gaussian

    studio.settings.product_upload_max_bytes = 4096

    upload = await _upload(client, name="scene.ply", body=_gaussian(count=1, sh_rest=0))
    assert upload["input_kind"] == "gaussian_ply"
    response = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Scene PLY", "attestation": _ATTESTATION},
    )
    assert response.status_code == 409 and "PLY/ZIP" in response.json()["detail"]


def _lidar_package() -> bytes:
    """Gói LiDAR tối thiểu hợp lệ: một đám mây đã đăng ký + quỹ đạo + calibration + thời điểm frame."""
    import io
    import struct
    import zipfile

    cloud = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 2\nproperty float x\nproperty float y\n"
        b"property float z\nend_header\n" + struct.pack("<6f", 0, 0, 0, 1, 1, 1)
    )
    calibration = "".join(
        f"T_cam1_os.{key}: {value}\n" for key, value in zip("px py pz qx qy qz qw".split(), "0 0 0 0 0 0 1".split())
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("map.ply", cloud)
        archive.writestr("traj.txt", "0.0 0 0 0 0 0 0 1\n0.1 1 0 0 0 0 0 1\n")
        archive.writestr("calibrations.txt", calibration)
        archive.writestr("frame_times.txt", "0.0\n0.1\n")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_scene_from_upload_carries_a_lidar_package(client: AsyncClient, studio: SimpleNamespace) -> None:
    """ADR 0009: video + gói LiDAR → manifest ghi cả hai, khai cùng scene, giữ bằng chứng nhận diện của gói."""
    studio.settings.product_upload_max_bytes = 1024 * 1024
    video = await _upload(client)
    package = await _upload(client, "lidar.zip", _lidar_package())
    assert package["input_kind"] == "registered_lidar"
    lidar = {"upload_id": package["upload_id"], "trajectory_origin": "ground_truth", "same_scene_confirmed": True}
    response = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": video["upload_id"], "name": "Kho LiDAR", "attestation": _ATTESTATION, "lidar": lidar},
    )
    assert response.status_code == 201, response.text
    record = studio.registry.get_project(response.json()["project"]["project_id"])
    manifest = InputManifest.model_validate_json(
        studio.registry.runtime_resolver.require(record.input_manifest_ref).read_bytes()
    )
    assert [item.checksum for item in manifest.files] == [video["checksum"], package["checksum"]]
    assert manifest.input_configuration.registered_lidar_present and manifest.input_configuration.declared_same_scene
    assert manifest.lidar_metadata is not None and manifest.lidar_metadata.registration_status == "registered"
    provenance = manifest.preparation_provenance["lidar"]  # type: ignore[index]
    assert provenance["trajectory_origin"] == "ground_truth" and provenance["evidence"]["pose_count"] == 2
    listed = {
        item["upload_id"]: item["project_ids"] for item in (await client.get("/api/v1/uploads")).json()["uploads"]
    }
    assert listed[package["upload_id"]] == [record.project_id]

    # Thiếu lời khai cùng scene, hoặc đính kèm file không phải gói LiDAR: từ chối, không tạo scene.
    unconfirmed = await client.post(
        "/api/v1/scenes/from-upload",
        json={
            "upload_id": video["upload_id"],
            "name": "x",
            "attestation": _ATTESTATION,
            "lidar": {**lidar, "same_scene_confirmed": False},
        },
    )
    assert unconfirmed.status_code == 422
    wrong = await client.post(
        "/api/v1/scenes/from-upload",
        json={
            "upload_id": video["upload_id"],
            "name": "x",
            "attestation": _ATTESTATION,
            "lidar": {**lidar, "upload_id": video["upload_id"]},
        },
    )
    assert wrong.status_code == 409 and "gói LiDAR" in wrong.json()["detail"]


@pytest.mark.asyncio
async def test_uploads_and_scenes_show_who_did_what(
    client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nhóm dùng chung (ADR 0003): file, scene và job phải ghi rõ người tải lên, người tạo, người chạy."""
    from src.api import auth
    from src.main import app
    from src.services.orchestration.auth import AuthService

    identity = SimpleNamespace(
        database_url=studio.settings.database_url, auth_required=True, auth_session_days=7, auth_invite_days=7
    )
    monkeypatch.setattr(auth, "get_settings", lambda: identity)
    service = AuthService(RuntimeDatabase(studio.settings.database_url))
    uploader = service.create_user("an@example.com", "An", "mat-khau-du-dai-1", "editor")
    creator = service.create_user("binh@example.com", "Bình", "mat-khau-du-dai-2", "reviewer")
    current = {"user": uploader}
    monkeypatch.setitem(app.dependency_overrides, auth.require_contributor, lambda: current["user"])

    upload = await _upload(client)
    assert upload["uploaded_by"] == {"user_id": uploader.user_id, "display_name": "An", "role": "editor"}
    listed_upload = (await client.get("/api/v1/uploads")).json()["uploads"][0]
    assert listed_upload["uploaded_by"]["display_name"] == "An"
    assert listed_upload["uploaded_by"]["role"] == "editor"

    current["user"] = creator  # người khác trong nhóm tạo scene từ file An đã tải
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    assert created.status_code == 201, created.text
    assert created.json()["project"]["created_by"] == {
        "user_id": creator.user_id,
        "display_name": "Bình",
        "role": "reviewer",
    }
    scene = (await client.get("/api/v1/scenes")).json()["scenes"][0]
    assert scene["project"]["created_by"]["display_name"] == "Bình"
    assert scene["requested_by"] == {"user_id": creator.user_id, "display_name": "Bình", "role": "reviewer"}

    renamed = creator.model_copy(update={"display_name": "Bình mới", "role": "editor"})
    with RuntimeDatabase(studio.settings.database_url).transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_users SET payload=? WHERE user_id=?",
            (renamed.model_dump_json(), creator.user_id),
        )
    historical_scene = (await client.get("/api/v1/scenes")).json()["scenes"][0]
    assert historical_scene["requested_by"] == {
        "user_id": creator.user_id,
        "display_name": "Bình",
        "role": "reviewer",
    }
    project_creator = historical_scene["project"]["created_by"]
    assert project_creator == {"user_id": creator.user_id, "display_name": "Bình", "role": "reviewer"}

    # Bản ghi cũ chưa có snapshot role: phản hồi điền role hiện tại của đúng tài khoản; dữ liệu đã lưu không đổi.
    with RuntimeDatabase(studio.settings.database_url).transaction(write=True) as tx:
        row = tx.execute("SELECT project_id, payload FROM r2s_projects").fetchone()
        stored = json.loads(row[1])
        stored["created_by"].pop("role", None)
        tx.execute("UPDATE r2s_projects SET payload=? WHERE project_id=?", (json.dumps(stored), row[0]))
    legacy_scene = (await client.get("/api/v1/scenes")).json()["scenes"][0]
    assert legacy_scene["project"]["created_by"] == {
        "user_id": creator.user_id,
        "display_name": "Bình",
        "role": "editor",
    }
    with RuntimeDatabase(studio.settings.database_url).transaction() as tx:
        unchanged = json.loads(tx.execute("SELECT payload FROM r2s_projects").fetchone()[0])
    assert "role" not in unchanged["created_by"]


@pytest.mark.asyncio
async def test_actions_without_login_have_no_actor(client: AsyncClient, studio: SimpleNamespace) -> None:
    """Deployment không bật đăng nhập: không biết ai thao tác thì để trống, không điền tên giả."""
    upload = await _upload(client)
    assert upload["uploaded_by"] is None
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    assert created.json()["project"]["created_by"] is None
    scene = (await client.get("/api/v1/scenes")).json()["scenes"][0]
    assert scene["requested_by"] is None


@pytest.mark.asyncio
async def test_simulation_api_projects_export_block_separately_from_preflight(
    client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A static Preflight PASS must not hide an unsupported USD export capability."""
    from datetime import UTC, datetime

    from src.api.studio import simulation as simulation_api

    scene = SceneIR.model_validate_json(Path("fixtures/scene_ir/scene.json").read_text(encoding="utf-8"))
    preflight = run_preflight(scene)
    blocked = SimulationPackage(
        job_id="job-capability-blocked",
        source_scene_revision=scene.scene_revision,
        scene_revision=scene.scene_revision,
        scene_ir_checksum=scene.scene_ir_checksum,
        created_at=datetime.now(UTC),
        preflight=preflight,
        confirmed_objects=0,
        environment_triangles=0,
        carved_triangles=0,
        export_capability=ExportCapabilityReport(
            scene_revision=scene.scene_revision,
            scene_ir_checksum=scene.scene_ir_checksum,
            status=ExportCapabilityStatus.BLOCKED,
            effective_mode=EffectiveExportMode.HYBRID,
            builder_version="usd-export-capabilities-v2",
            runtime_qualification=RuntimeQualificationStatus.FAILED,
            requirements=ExportRequirements(hybrid_visuals=True),
            blockers=[
                ExportCapabilityBlocker(
                    code="USD_RUNTIME_UNQUALIFIED",
                    message="The configured USD runtime did not pass its capability probe.",
                )
            ],
        ),
    )
    monkeypatch.setattr(simulation_api, "_guard", lambda _job_id: None)
    monkeypatch.setattr(simulation_api.deps, "registry", lambda: studio.registry)
    monkeypatch.setattr(simulation_api, "build_simulation_package", lambda _registry, _job_id: blocked)

    response = await client.post("/api/v1/jobs/job-capability-blocked/simulation-package")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preflight"]["blocking_result"] == RuleResult.PASS
    assert body["export_capability"]["status"] == ExportCapabilityStatus.BLOCKED
    assert body["export_capability"]["blockers"][0]["code"] == "USD_RUNTIME_UNQUALIFIED"
    assert body["candidate"] is None and body["package_ref"] is None


@pytest.mark.asyncio
async def test_simulation_read_build_and_download_require_login_when_auth_is_enabled(
    client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Studio router auth phải phủ đủ cả read, build và artifact download của gói mô phỏng."""
    from src.api import auth

    identity = SimpleNamespace(
        database_url=studio.settings.database_url,
        auth_required=True,
        auth_session_days=7,
        auth_invite_days=7,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: identity)

    responses = [
        await client.get("/api/v1/jobs/job-private/simulation-package"),
        await client.post("/api/v1/jobs/job-private/simulation-package"),
        await client.get("/api/v1/jobs/job-private/simulation-package/download"),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]


@pytest.mark.asyncio
async def test_anonymize_option_is_offered_and_recorded_only_with_a_configured_anonymizer(
    client: AsyncClient, studio: SimpleNamespace, tmp_path: Path
) -> None:
    import json

    from src.services.orchestration.processing import job_config_reference

    async def create(name: str, **extra: object):  # noqa: ANN202
        upload = await _upload(client)
        return await client.post(
            "/api/v1/scenes/from-upload",
            json={"upload_id": upload["upload_id"], "name": name, "attestation": _ATTESTATION, **extra},
        )

    def stored(response) -> dict:  # noqa: ANN001
        job = response.json()["job"]
        reference = job_config_reference(job["job_id"], job["config_checksum"])
        return json.loads(studio.registry.runtime_resolver.require(reference).read_text())

    # Chưa cấu hình anonymizer: UI không được mời chọn, và yêu cầu che bị từ chối thay vì âm thầm bỏ qua.
    options = (await client.get("/api/v1/processing/options")).json()
    assert options["anonymize_available"] is False and options["anonymize_enforced"] is False
    refused = await create("Che khi chưa có", anonymize=True)
    assert refused.status_code == 409 and "che khuôn mặt" in refused.json()["detail"]
    plain = await create("Không che")
    assert plain.status_code == 201 and "anonymize" not in stored(plain)

    studio.settings.product_scene_runtime_python = tmp_path / "python"
    studio.settings.product_egoblur_weights = tmp_path / "weights"
    options = (await client.get("/api/v1/processing/options")).json()
    assert options["anonymize_available"] is True and options["anonymize_enforced"] is False
    chosen = await create("Có che", anonymize=True)
    assert chosen.status_code == 201 and stored(chosen)["anonymize"] is True
    assert "anonymize" not in stored(await create("Vẫn không che"))

    # API tách khỏi worker (production): không có đường dẫn runtime trên API, chỉ có cờ khai worker có bộ che.
    studio.settings.product_scene_runtime_python = studio.settings.product_egoblur_weights = None
    assert (await client.get("/api/v1/processing/options")).json()["anonymize_available"] is False
    studio.settings.product_anonymize_remote_worker = True
    assert (await client.get("/api/v1/processing/options")).json()["anonymize_available"] is True
    assert stored(await create("Che qua worker từ xa", anonymize=True))["anonymize"] is True

    # `qa_verified`: mọi video bị che dù người dùng không chọn, và form hiện ô chọn ở trạng thái bắt buộc.
    studio.settings.product_privacy_mode = "qa_verified"
    assert (await client.get("/api/v1/processing/options")).json()["anonymize_enforced"] is True
    forced = await create("Bắt buộc che theo chế độ")
    assert forced.status_code == 201 and stored(forced)["anonymize"] is True
    assert studio.registry.get_project(forced.json()["project"]["project_id"]).privacy_mode == "qa_verified"
    # Thiếu bộ che thì chế độ này không tạo được scene, kèm lý do nói rõ cho người dùng.
    studio.settings.product_anonymize_remote_worker = False
    blocked = await create("Không có bộ che")
    assert blocked.status_code == 409 and "bộ che" in blocked.json()["detail"]
    studio.settings.product_privacy_mode, studio.settings.product_anonymize_remote_worker = "self_attested", True

    # Deployment bắt buộc: job không chọn vẫn được ghi là có che.
    studio.settings.product_anonymize_input = True
    assert (await client.get("/api/v1/processing/options")).json()["anonymize_enforced"] is True
    assert stored(await create("Bắt buộc che"))["anonymize"] is True


@pytest.mark.asyncio
async def test_import_camera_bookmark_and_clear_routes(client: AsyncClient, studio: SimpleNamespace) -> None:
    from src.services.orchestration.uploads import VideoUploadService

    uploads = VideoUploadService(
        studio.registry.persistence.database,
        studio.registry.runtime_resolver,
        8 * 1024 * 1024,
    )
    pending = uploads.begin("room.sog")
    pending.publication.write(sog_archive(model="2dgs"))
    uploaded = uploads.finish(pending)

    request = {"upload_id": uploaded.upload_id, "name": "Room SOG"}
    create_resp = await client.post("/api/v1/imports", json=request)
    assert create_resp.status_code == 201
    import_id = create_resp.json()["import_id"]

    # Bookmark camera qua PATCH
    pose = {"position": [1.5, 2.5, 3.5], "target": [0.0, 0.0, 0.0], "fov": 65.0}
    patch_resp = await client.patch(f"/api/v1/imports/{import_id}/camera", json=pose)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["default_camera"]["position"] == [1.5, 2.5, 3.5]
    assert patch_resp.json()["default_camera"]["fov"] == 65.0

    # Gỡ bookmark qua DELETE
    del_resp = await client.delete(f"/api/v1/imports/{import_id}/camera")
    assert del_resp.status_code == 200
    assert del_resp.json().get("default_camera") is None

    # Bookmark lại rồi gỡ qua PATCH với null
    await client.patch(f"/api/v1/imports/{import_id}/camera", json=pose)
    clear_patch_resp = await client.patch(f"/api/v1/imports/{import_id}/camera", json={})
    assert clear_patch_resp.status_code == 200
    assert clear_patch_resp.json().get("default_camera") is None


def test_scene_list_reports_the_geometry_review_step_of_a_draft_scene(
    studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scene Draft không được ghi "Hoàn tất" trên danh sách: báo bước Duyệt vật & Tạo mesh, cache theo revision."""
    from src.api.studio import scenes

    calls: list[tuple[str, str, str]] = []

    def queue_state(job_id: str, geometry: str, revision: str) -> str:
        calls.append((job_id, geometry, revision))
        return "waiting"

    monkeypatch.setattr(scenes, "_geometry_queue_state", queue_state)
    scenes._GEOMETRY_CACHE.clear()
    studio.registry.seed_from_fixtures()
    job = _finished_job(studio)
    registry, reads, holder = _registry_with_scene({"object_geometry": "awaiting_review"})
    assert scenes._geometry_review(registry, job) == "waiting"
    assert scenes._geometry_review(registry, job) == "waiting"
    assert reads == [job.job_id]  # lần hai lấy trạng thái scene từ bộ nhớ đệm, hàng đợi vẫn đọc lại
    assert calls == [(job.job_id, "awaiting_review", "rev-001")] * 2
    holder.head = SimpleNamespace(scene_revision="rev-002")
    scenes._geometry_review(registry, job)
    assert len(reads) == 2 and calls[-1][2] == "rev-002"

    # Scene cũ không có khoá: không đọc hàng đợi. Job chưa xong: không đọc scene.
    scenes._GEOMETRY_CACHE.clear()
    calls.clear()
    legacy, _, _ = _registry_with_scene({})
    assert scenes._geometry_review(legacy, job) is None
    assert calls == []
    registry, reads, _ = _registry_with_scene({"object_geometry": "awaiting_review"})
    assert scenes._geometry_review(registry, _finished_job(studio, status="RUNNING")) is None
    assert scenes._geometry_review(registry, _finished_job(studio, object_stage=False)) is None
    assert reads == []

    # Scene chưa đọc được: không đoán.
    scenes._GEOMETRY_CACHE.clear()
    broken, _, _ = _registry_with_scene({}, error=FileNotFoundError("scene.json"))
    assert scenes._geometry_review(broken, job) is None


@pytest.mark.asyncio
async def test_scene_list_response_carries_the_geometry_review_step(
    client: AsyncClient, studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.studio import scenes

    studio.registry.seed_from_fixtures()
    upload = await _upload(client)
    await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    assert (await client.get("/api/v1/scenes")).json()["scenes"][0]["geometry_review"] is None
    monkeypatch.setattr(scenes, "_geometry_review", lambda registry, job: "failed")
    assert (await client.get("/api/v1/scenes")).json()["scenes"][0]["geometry_review"] == "failed"
