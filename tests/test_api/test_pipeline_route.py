"""T-059: GET /jobs/{id}/pipeline — one light request with the steps, the wait and the next action."""

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models.contracts.manifests import JobStatus, StageId
from src.services.orchestration.jobs.models import TransitionRequest
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
async def test_pipeline_view_matches_progress_payload(client: AsyncClient, registry: ProjectRegistry) -> None:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    progress = (await client.get(f"/api/v1/jobs/{job.job_id}/progress")).json()
    view = (await client.get(f"/api/v1/jobs/{job.job_id}/pipeline")).json()
    assert view["progress"] == progress
    assert view["next_action"]["kind"] == "wait_system" and view["next_action"]["owner"] == "system"
    assert [step["step_id"] for step in view["steps"]][0] == StageId.INPUT_VALIDATE.value
    assert view["usable"] is False


@pytest.mark.asyncio
async def test_pipeline_304_when_unchanged(client: AsyncClient, registry: ProjectRegistry) -> None:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    first = await client.get(f"/api/v1/jobs/{job.job_id}/pipeline")
    again = await client.get(f"/api/v1/jobs/{job.job_id}/pipeline", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


@pytest.mark.asyncio
async def test_pipeline_version_changes_on_stage_progress(client: AsyncClient, registry: ProjectRegistry) -> None:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    first = await client.get(f"/api/v1/jobs/{job.job_id}/pipeline")
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    again = await client.get(f"/api/v1/jobs/{job.job_id}/pipeline", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 200 and again.json()["version"] != first.json()["version"]


@pytest.mark.asyncio
async def test_pipeline_unknown_job_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/jobs/no-such-job/pipeline")).status_code == 404


@pytest.mark.asyncio
async def test_failed_retryable_job_asks_for_retry(client: AsyncClient, registry: ProjectRegistry) -> None:
    from src.models.contracts.manifests import ExecutionError

    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    error = ExecutionError(error_code="COLMAP_TIMEOUT", stage_id=StageId.CAMERA_POSE, human_message="x", retryable=True)
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.FAILED, error=error))
    view = (await client.get(f"/api/v1/jobs/{job.job_id}/pipeline")).json()
    assert view["next_action"]["kind"] == "retry_job"
