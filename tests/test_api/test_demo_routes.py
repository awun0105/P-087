"""Bản demo: đánh dấu mốc gốc, chỉnh scene rồi khôi phục — revision mới mang nội dung gốc, không chạy lại xử lý."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_JOB = "/api/v1/jobs/job-fixture-001"
_PALLET = "object-pallet-001"


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from src.api.product import deps as product_deps
    from src.api.studio import deps as studio_deps
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(studio_deps, "get_project_registry", lambda: registry)
    return registry


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_scene_is_not_a_demo_until_marked(client) -> None:
    state = (await client.get(f"{_JOB}/demo")).json()
    assert state["baseline"] is None and state["at_baseline"] is False
    reset = await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-001"})
    assert reset.status_code == 422 and "bản demo" in reset.json()["detail"]


@pytest.mark.asyncio
async def test_edit_then_reset_restores_the_marked_content_as_a_new_revision(client, isolated_registry) -> None:
    marked = (await client.post(f"{_JOB}/demo/baseline")).json()
    assert marked["baseline"]["scene_revision"] == "rev-001" and marked["at_baseline"] is True
    project = (await client.get("/api/v1/projects/project-fixture-001")).json()
    assert project["demo_baseline"]["job_id"] == "job-fixture-001"

    deleted = await client.post(f"{_JOB}/scene/objects/{_PALLET}/delete", json={"expected_scene_revision": "rev-001"})
    assert deleted.status_code == 201
    edited = (await client.get(f"{_JOB}/demo")).json()
    assert edited["current_revision"] == "rev-002" and edited["at_baseline"] is False

    reset = await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-002"})
    assert reset.status_code == 200
    body = reset.json()
    assert body["current_revision"] == "rev-003" and body["at_baseline"] is True
    scene = isolated_registry.scene.current("job-fixture-001").scene
    assert any(item.id == _PALLET for item in scene.objects)

    # Đang đúng mốc gốc thì khôi phục lần nữa không tạo revision thừa.
    again = (await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-003"})).json()
    assert again["current_revision"] == "rev-003"


@pytest.mark.asyncio
async def test_reset_with_a_stale_revision_conflicts(client) -> None:
    await client.post(f"{_JOB}/demo/baseline")
    await client.post(f"{_JOB}/scene/objects/{_PALLET}/delete", json={"expected_scene_revision": "rev-001"})
    stale = await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-001"})
    assert stale.status_code == 409 and "tải lại" in stale.json()["detail"]


@pytest.mark.asyncio
async def test_clearing_the_mark_keeps_the_scene(client) -> None:
    await client.post(f"{_JOB}/demo/baseline")
    await client.post(f"{_JOB}/scene/objects/{_PALLET}/delete", json={"expected_scene_revision": "rev-001"})
    cleared = (await client.delete(f"{_JOB}/demo/baseline")).json()
    assert cleared["baseline"] is None
    project = (await client.get("/api/v1/projects/project-fixture-001")).json()
    assert project["demo_baseline"] is None


def test_baseline_survives_a_database_backed_registry(tmp_path) -> None:
    from src.services.orchestration.jobs.database import RuntimeDatabase
    from src.services.orchestration.projects.registry import ProjectRegistry
    from src.services.orchestration.scene.demo import clear_demo, demo_state, mark_demo

    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database)
    registry.seed_from_fixtures()
    before = registry.get_project("project-fixture-001")
    # Mốc trống không được đổi bytes của bản ghi cũ (cập nhật project so khớp bytes).
    assert "demo_baseline" not in before.model_dump_json()

    mark_demo(registry, "job-fixture-001", None)
    reopened = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database)
    assert demo_state(reopened, "job-fixture-001").baseline.scene_revision == "rev-001"
    clear_demo(reopened, "job-fixture-001")
    assert reopened.get_project("project-fixture-001").demo_baseline is None


# --- Đặt làm bản demo = xuất vào thư viện mẫu -------------------------------------------------------------------


@pytest.fixture
def library(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.api.studio import deps as studio_deps

    root = tmp_path / "library"
    monkeypatch.setattr(studio_deps, "settings", lambda: SimpleNamespace(product_demo_dir=root))
    return root


def _attest(registry, monkeypatch, **flags) -> None:
    project = registry.get_project(registry.get_job("job-fixture-001").project_id)
    patched = project.model_copy(update={"source_rights_attestation": {"attested": True, **flags}})
    monkeypatch.setattr(registry, "get_project", lambda project_id: patched)


_CONFIRMED = {"rights_to_use_confirmed": True, "anonymization_confirmed": True}


@pytest.mark.asyncio
async def test_publish_needs_the_reviewer_to_confirm_public_release(client, library) -> None:
    refused = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": False})
    assert refused.status_code == 422 and "công khai" in refused.json()["detail"]
    assert not library.exists()


@pytest.mark.asyncio
async def test_publish_refuses_scenes_without_rights_and_anonymization(
    client, library, isolated_registry, monkeypatch
) -> None:
    refused = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert refused.status_code == 409 and "ẩn danh" in refused.json()["detail"]
    _attest(isolated_registry, monkeypatch, rights_to_use_confirmed=True, anonymization_confirmed=False)
    still = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert still.status_code == 409
    assert not library.exists()


@pytest.mark.asyncio
async def test_publish_exports_through_the_shared_service_and_reports_it(
    client, library, isolated_registry, monkeypatch
) -> None:
    from datetime import UTC, datetime

    from src.api.studio import demo as demo_api
    from src.services.orchestration.samples import DemoFile, DemoManifest, DemoSource

    _attest(isolated_registry, monkeypatch, **_CONFIRMED)
    calls = []

    def fake_publish(registry, job_id, root, *, title, description, source, frames=12):
        calls.append((job_id, root, title, description, source))
        (root / "kho-1").mkdir(parents=True)
        manifest = DemoManifest(
            demo_id="kho-1",
            title=title,
            description=description,
            origin="pipeline_job",
            source=source,
            produced_at=datetime(2026, 10, 10, tzinfo=UTC),
            provenance={"job_id": job_id},
            stages=[],
            splat=DemoFile(
                name="scene.sog", media_type="application/octet-stream", size_bytes=1, checksum="sha256:" + "0" * 64
            ),
        )
        (root / "kho-1" / "manifest.json").write_text(manifest.model_dump_json())
        return manifest

    monkeypatch.setattr(demo_api, "publish_job_bundle", fake_publish)
    done = await client.post(
        f"{_JOB}/demo/publish", json={"confirm_public": True, "title": "Kho 1", "description": "Mô tả"}
    )
    assert done.status_code == 201 and done.json() == {"sample_id": "kho-1", "title": "Kho 1"}
    (job_id, root, title, description, source) = calls[0]
    assert (job_id, root, title, description) == ("job-fixture-001", library, "Kho 1", "Mô tả")
    assert isinstance(source, DemoSource) and source.dataset == "Real2Sim Studio"
    # Trạng thái demo của job báo mẫu đã có trong thư viện.
    assert (await client.get(f"{_JOB}/demo")).json()["published_sample_id"] == "kho-1"


@pytest.mark.asyncio
async def test_publish_maps_export_failures_to_clear_conflicts(client, library, isolated_registry, monkeypatch) -> None:
    _attest(isolated_registry, monkeypatch, **_CONFIRMED)
    # Fixture không có preview đã xác minh: dịch vụ xuất từ chối thay vì tạo mẫu rỗng, và không để lại thư mục.
    refused = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert refused.status_code == 409 and "bản xem 3DGS" in refused.json()["detail"]
    assert not any(library.iterdir()) if library.exists() else True
    missing = await client.post("/api/v1/jobs/job-nope/demo/publish", json={"confirm_public": True})
    assert missing.status_code == 404
