"""ADR 0005: danh sách lớp xem được của từng bước do backend dựng từ JobManifest."""

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry


@pytest.fixture(autouse=True)
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectRegistry:
    from src.api.studio import deps

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    return registry


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_job_without_results_has_no_views(client: AsyncClient, registry: ProjectRegistry) -> None:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    response = await client.get(f"/api/v1/jobs/{job.job_id}/stage-views")
    assert response.status_code == 200
    assert response.json() == {"job_id": job.job_id, "views": []}


@pytest.mark.asyncio
async def test_unknown_job_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/jobs/no-such-job/stage-views")).status_code == 404


@pytest.mark.asyncio
async def test_lidar_overlay_is_404_for_a_scene_without_aligned_lidar(
    client: AsyncClient, registry: ProjectRegistry
) -> None:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    response = await client.get(f"/api/v1/jobs/{job.job_id}/lidar-overlay")
    assert response.status_code == 404 and "LiDAR" in response.json()["detail"]
    assert (await client.get("/api/v1/jobs/no-such-job/lidar-overlay")).status_code == 404
