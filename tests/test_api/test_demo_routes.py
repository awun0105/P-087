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
