"""Đăng nhập ba role khi bật AUTH_REQUIRED: Guest / Editor / Reviewer."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import Settings
from src.models.contracts.manifests import ExecutionError, JobStatus, StageId
from src.services.orchestration.auth import AuthService
from src.services.orchestration.jobs import TransitionRequest
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects.models import JobCreateInput
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


@pytest.fixture
def product_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectRegistry:
    from src.api.product import deps

    registry = ProjectRegistry(runtime_root=tmp_path / "product-artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    assert deps.registry() is registry
    return registry


def _failed_job(registry: ProjectRegistry, *, retryable: bool = True) -> str:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    registry.transition_job(
        job.job_id,
        TransitionRequest(
            target_status=JobStatus.FAILED,
            error=ExecutionError(
                stage_id=StageId.INPUT_VALIDATE,
                error_code="PREVIEW_RUNNER_FAILED",
                human_message="Fixture failure",
                retryable=retryable,
                details={"exception_type": "TimeoutError"},
            ),
        ),
    )
    return job.job_id


def _gpu_run_count(auth_service: AuthService, user_id: str) -> int:
    return auth_service.count_actions(user_id, "gpu.run", datetime.now(UTC) - timedelta(days=1))


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
    assert me == {"auth_required": True, "guest_signup_enabled": False, "user": None, "quota": None}
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
    assert (await client.post("/api/v1/auth/invites", json={"role": "guest"})).status_code == 422
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
async def test_guest_signup_is_disabled_by_default(client: AsyncClient, secured: AuthService) -> None:
    response = await client.post(
        "/api/v1/auth/register/guest",
        json={"email": "guest@example.com", "display_name": "Guest", "password": PASSWORD},
    )

    assert response.status_code == 404
    assert (await client.get("/api/v1/auth/me")).json()["guest_signup_enabled"] is False
    assert secured.list_users() == []


@pytest.mark.asyncio
async def test_guest_signup_uses_server_role_with_shared_reads_and_reviewer_routes_closed(
    client: AsyncClient,
    secured: AuthService,
    product_registry: ProjectRegistry,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.api import auth

    enabled = Settings(
        database_url=secured.database._url,
        artifact_root=tmp_path / "artifacts",
        auth_required=True,
        auth_guest_signup_enabled=True,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: enabled)

    response = await client.post(
        "/api/v1/auth/register/guest",
        json={"email": " Guest@Example.com ", "display_name": " Hà Linh ", "password": PASSWORD},
    )

    assert response.status_code == 201, response.text
    assert response.json()["role"] == "guest"
    assert response.json()["email"] == "guest@example.com"
    assert response.json()["display_name"] == "Hà Linh"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["guest_signup_enabled"] is True and me["user"]["role"] == "guest"
    assert (await client.get("/api/v1/scenes")).status_code == 200
    assert product_registry.list_projects()
    assert (await client.get("/api/v1/projects")).status_code == 200
    created_project = await client.post(
        "/api/v1/projects",
        json={
            "name": "Guest project",
            "source_type": "upload",
            "input_manifest_checksum": "sha256:" + "a" * 64,
            "attestation": ATTESTATION,
        },
    )
    assert created_project.status_code == 201, created_project.text
    assert created_project.json()["created_by"]["user_id"] == response.json()["user_id"]
    assert created_project.json()["created_by"]["role"] == "guest"
    invite = await client.post("/api/v1/auth/invites", json={"role": "editor"})
    assert invite.status_code == 403

    forged_role = await client.post(
        "/api/v1/auth/register/guest",
        json={"email": "forged@example.com", "display_name": "Guest", "password": PASSWORD, "role": "reviewer"},
    )
    supplied_invite = await client.post(
        "/api/v1/auth/register/guest",
        json={
            "email": "invite@example.com",
            "display_name": "Guest",
            "password": PASSWORD,
            "invite_code": "not-valid",
        },
    )
    duplicate = await client.post(
        "/api/v1/auth/register/guest",
        json={"email": "GUEST@example.com", "display_name": "Duplicate", "password": PASSWORD},
    )
    assert forged_role.status_code == supplied_invite.status_code == 422
    assert duplicate.status_code == 409
    assert [user.email for user in secured.list_users()] == ["guest@example.com"]


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
async def test_retry_counts_against_gpu_quota(
    client: AsyncClient, secured: AuthService, product_registry: ProjectRegistry
) -> None:
    reviewer = secured.create_user("lead@example.com", "Lead", PASSWORD, "reviewer")
    editor = secured.create_user("e@example.com", "E", PASSWORD, "editor")
    secured.update_user(reviewer, editor.user_id, daily_job_quota=1)
    secured.audit(editor.user_id, "gpu.run", "job-old", {"kind": "scene.create"})  # đã dùng 1 lượt
    job_id = _failed_job(product_registry)
    attempts_before = product_registry.list_job_attempts(job_id)
    await _login(client, "e@example.com")
    response = await client.post(f"/api/v1/jobs/{job_id}/retry")

    assert response.status_code == 429 and "xử lý GPU" in response.json()["detail"]
    assert product_registry.get_job(job_id).status == JobStatus.FAILED
    assert product_registry.list_job_attempts(job_id) == attempts_before
    assert _gpu_run_count(secured, editor.user_id) == 1


@pytest.mark.asyncio
async def test_product_job_creation_counts_against_gpu_quota(
    client: AsyncClient, secured: AuthService, product_registry: ProjectRegistry
) -> None:
    reviewer = secured.create_user("lead@example.com", "Lead", PASSWORD, "reviewer")
    editor = secured.create_user("e@example.com", "E", PASSWORD, "editor")
    secured.update_user(reviewer, editor.user_id, daily_job_quota=0)
    jobs_before = product_registry.list_jobs("project-fixture-001")
    await _login(client, "e@example.com")

    response = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})

    assert response.status_code == 429
    assert product_registry.list_jobs("project-fixture-001") == jobs_before
    assert _gpu_run_count(secured, editor.user_id) == 0


@pytest.mark.asyncio
async def test_retry_accepts_eligible_job_and_records_gpu_usage_once(
    client: AsyncClient, secured: AuthService, product_registry: ProjectRegistry
) -> None:
    reviewer = secured.create_user("lead@example.com", "Lead", PASSWORD, "reviewer")
    editor = secured.create_user("e@example.com", "E", PASSWORD, "editor")
    secured.update_user(reviewer, editor.user_id, daily_job_quota=2)
    secured.audit(editor.user_id, "gpu.run", "job-old", {"kind": "scene.create"})
    job_id = _failed_job(product_registry)
    await _login(client, "e@example.com")

    response = await client.post(f"/api/v1/jobs/{job_id}/retry")

    assert response.status_code == 200, response.text
    assert response.json()["job_id"] == job_id
    assert response.json()["status"] == JobStatus.QUEUED
    assert product_registry.list_job_attempts(job_id)[-1].status == JobStatus.QUEUED
    attempts = await client.get(f"/api/v1/jobs/{job_id}/attempts")
    assert attempts.json()["attempts"][-1]["requested_by"] == {
        "user_id": editor.user_id,
        "display_name": "E",
        "role": "editor",
    }
    assert _gpu_run_count(secured, editor.user_id) == 2


@pytest.mark.asyncio
async def test_retry_rejects_missing_and_non_retryable_jobs(
    client: AsyncClient, secured: AuthService, product_registry: ProjectRegistry
) -> None:
    editor = secured.create_user("e@example.com", "E", PASSWORD, "editor")
    non_retryable_job_id = _failed_job(product_registry, retryable=False)
    await _login(client, "e@example.com")

    missing = await client.post("/api/v1/jobs/job-missing/retry")
    denied = await client.post(f"/api/v1/jobs/{non_retryable_job_id}/retry")

    assert missing.status_code == 404
    assert denied.status_code == 409
    assert product_registry.get_job(non_retryable_job_id).status == JobStatus.FAILED
    assert _gpu_run_count(secured, editor.user_id) == 0


@pytest.mark.asyncio
async def test_retry_requires_authenticated_user(client: AsyncClient, secured: AuthService) -> None:
    response = await client.post("/api/v1/jobs/job-missing/retry")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_one_person_failing_does_not_lock_out_the_team(client: AsyncClient, secured: AuthService) -> None:
    """Mọi request đi qua cùng proxy: nhập sai nhiều ở một email không chặn email khác."""
    secured.create_user("lead@example.com", "Lead", PASSWORD, "reviewer")
    for _ in range(12):
        await client.post("/api/v1/auth/login", json={"email": "attacker@example.com", "password": "sai"})
    await _login(client, "lead@example.com")
