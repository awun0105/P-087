"""Đăng nhập hai role khi bật AUTH_REQUIRED: khách / Editor / Reviewer (ADR 0003 §3)."""

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import Settings
from src.services.orchestration.auth import AuthService
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects.registry import ProjectRegistry

PASSWORD = "mat-khau-du-dai"
ATTESTATION = {
    "data_origin": "self_collected_no_pii",
    "declared_owner": "QA",
    "declared_purpose": "Kiểm tra quyền",
    "rights_to_use_confirmed": True,
    "anonymization_confirmed": True,
    "retention_acknowledged": True,
}


@pytest.fixture
def secured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AuthService:
    from src.api import auth
    from src.api.studio import deps

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        artifact_root=tmp_path / "artifacts",
        product_demo_dir=tmp_path / "samples",
        auth_required=True,
    )
    database = RuntimeDatabase(settings.database_url)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(
        deps, "get_project_registry", lambda: ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database)
    )
    monkeypatch.setattr(auth, "login_limiter", auth._LoginLimiter(attempts=10))
    monkeypatch.setattr(auth, "client_limiter", auth._LoginLimiter(attempts=100))
    return AuthService(database)


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client: AsyncClient, email: str) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_guest_sees_samples_but_not_team_data(client: AsyncClient, secured: AuthService) -> None:
    me = (await client.get("/api/v1/auth/me")).json()
    assert me == {"auth_required": True, "user": None}
    assert (await client.get("/api/v1/samples")).status_code == 200
    for method, path in [
        ("GET", "/api/v1/scenes"),
        ("GET", "/api/v1/uploads"),
        ("POST", "/api/v1/uploads/direct"),
        ("GET", "/api/v1/projects"),
        ("GET", "/api/v1/auth/users"),
    ]:
        response = await client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 401, (path, response.text)


@pytest.mark.asyncio
async def test_invite_flow_and_role_boundaries(client: AsyncClient, secured: AuthService) -> None:
    secured.create_user("lead@example.com", "Trưởng nhóm", PASSWORD, "reviewer")
    await _login(client, "lead@example.com")
    cookie = client.cookies.get("r2s_session")
    assert cookie
    invite = await client.post("/api/v1/auth/invites", json={"role": "editor"})
    assert invite.status_code == 201
    code = invite.json()["code"]
    assert (await client.get("/api/v1/auth/users")).status_code == 200

    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/auth/me")).json()["user"] is None

    registered = await client.post(
        "/api/v1/auth/register",
        json={"invite_code": code, "email": "dung@example.com", "display_name": "Dựng scene", "password": PASSWORD},
    )
    assert registered.status_code == 201 and registered.json()["role"] == "editor"
    set_cookie = registered.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie

    assert (await client.get("/api/v1/scenes")).status_code == 200  # Editor xem được scene nhóm
    assert (await client.get("/api/v1/auth/users")).status_code == 403
    assert (await client.post("/api/v1/auth/invites", json={"role": "editor"})).status_code == 403
    review = await client.post("/api/v1/jobs/job-x/review/approve", json={})
    assert review.status_code == 403  # chỉ Reviewer được duyệt


@pytest.mark.asyncio
async def test_daily_quota_blocks_new_scenes(client: AsyncClient, secured: AuthService) -> None:
    reviewer = secured.create_user("lead@example.com", "Lead", PASSWORD, "reviewer")
    editor = secured.create_user("e@example.com", "E", PASSWORD, "editor")
    secured.update_user(reviewer, editor.user_id, daily_job_quota=0)
    await _login(client, "e@example.com")
    response = await client.post(
        "/api/v1/scenes/from-upload", json={"upload_id": "upload-x", "name": "Kho", "attestation": ATTESTATION}
    )
    assert response.status_code == 429 and "hạn mức" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_is_rate_limited(client: AsyncClient, secured: AuthService) -> None:
    codes = [
        (await client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "sai"})).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10 and codes[10] == 429


@pytest.mark.asyncio
async def test_reviewer_has_no_daily_quota(client: AsyncClient, secured: AuthService) -> None:
    reviewer = secured.create_user("lead@example.com", "Lead", PASSWORD, "reviewer")
    secured.update_user(reviewer, reviewer.user_id, daily_job_quota=0)
    await _login(client, "lead@example.com")
    response = await client.post(
        "/api/v1/scenes/from-upload", json={"upload_id": "upload-x", "name": "Kho", "attestation": ATTESTATION}
    )
    # Không bị 429: qua bước hạn mức, dừng ở kiểm tra sau (chưa cấu hình worker/không có upload).
    assert response.status_code != 429, response.text


@pytest.mark.asyncio
async def test_retry_counts_against_gpu_quota(client: AsyncClient, secured: AuthService) -> None:
    reviewer = secured.create_user("lead@example.com", "Lead", PASSWORD, "reviewer")
    editor = secured.create_user("e@example.com", "E", PASSWORD, "editor")
    secured.update_user(reviewer, editor.user_id, daily_job_quota=1)
    secured.audit(editor.user_id, "gpu.run", "job-old", {"kind": "scene.create"})  # đã dùng 1 lượt
    await _login(client, "e@example.com")
    response = await client.post("/api/v1/jobs/job-x/retry")
    assert response.status_code == 429 and "xử lý GPU" in response.json()["detail"]


@pytest.mark.asyncio
async def test_one_person_failing_does_not_lock_out_the_team(client: AsyncClient, secured: AuthService) -> None:
    """Mọi request đi qua cùng proxy: nhập sai nhiều ở một email không chặn email khác."""
    secured.create_user("lead@example.com", "Lead", PASSWORD, "reviewer")
    for _ in range(12):
        await client.post("/api/v1/auth/login", json={"email": "attacker@example.com", "password": "sai"})
    await _login(client, "lead@example.com")
