"""HTTP tests cho xác nhận tỉ lệ mét: guard trạng thái/quyền (luồng đầy đủ ở test port REC-06)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.services.orchestration.projects.registry import ProjectRegistry

_INPUT = {
    "floor_points": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    "point_a": [0, 0, 0],
    "point_b": [1, 0, 0],
    "distance_m": 2.0,
}


@pytest.fixture(autouse=True)
def studio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from src.api import auth
    from src.api.studio import deps

    settings = SimpleNamespace(auth_required=False, database_url=f"sqlite:///{tmp_path / 'runtime.db'}")
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    return SimpleNamespace(settings=settings, registry=registry)


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_unknown_job_is_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/jobs/no-such-job/metric/preview", json=_INPUT)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_job_not_waiting_is_409(client: AsyncClient) -> None:
    preview = await client.post("/api/v1/jobs/job-fixture-001/metric/preview", json=_INPUT)
    assert preview.status_code == 409
    confirm = await client.post(
        "/api/v1/jobs/job-fixture-001/metric/confirm", json={"input": _INPUT, "preview_checksum": "sha256:x"}
    )
    assert confirm.status_code == 409


@pytest.mark.asyncio
async def test_invalid_distance_is_422(client: AsyncClient) -> None:
    body = {**_INPUT, "distance_m": 0}
    response = await client.post("/api/v1/jobs/job-fixture-001/metric/preview", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_required_when_auth_enabled(client: AsyncClient, studio: SimpleNamespace) -> None:
    studio.settings.auth_required = True
    studio.settings.auth_session_days = 7
    studio.settings.auth_invite_days = 7
    response = await client.post(
        "/api/v1/jobs/job-fixture-001/metric/confirm", json={"input": _INPUT, "preview_checksum": "sha256:x"}
    )
    assert response.status_code == 401
