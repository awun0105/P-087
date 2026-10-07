"""HTTP tests cho Studio upload → scene: fixture proof, không chạy worker/GPU."""

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
    monkeypatch.setitem(app.dependency_overrides, auth.require_editor, lambda: current["user"])

    upload = await _upload(client)
    assert upload["uploaded_by"] == {"user_id": uploader.user_id, "display_name": "An"}
    assert (await client.get("/api/v1/uploads")).json()["uploads"][0]["uploaded_by"]["display_name"] == "An"

    current["user"] = creator  # người khác trong nhóm tạo scene từ file An đã tải
    created = await client.post(
        "/api/v1/scenes/from-upload",
        json={"upload_id": upload["upload_id"], "name": "Kho A", "attestation": _ATTESTATION},
    )
    assert created.status_code == 201, created.text
    assert created.json()["project"]["created_by"] == {"user_id": creator.user_id, "display_name": "Bình"}
    scene = (await client.get("/api/v1/scenes")).json()["scenes"][0]
    assert scene["project"]["created_by"]["display_name"] == "Bình"
    assert scene["requested_by"] == {"user_id": creator.user_id, "display_name": "Bình"}


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
async def test_simulation_read_build_and_download_require_editor_when_auth_is_enabled(
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
