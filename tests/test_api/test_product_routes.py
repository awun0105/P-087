"""HTTP-level tests for product API routes.

Uses httpx AsyncClient + ASGITransport against the real FastAPI app.
Tests confirm:
- Fixture project/job/artifact are served correctly
- Privacy gate blocks job creation for new projects (PRELIMINARY_SCREENED)
- QUARANTINED project also blocked
- evaluation_only artifacts never appear in artifact list
- response body never contains filesystem paths or artifact_root
- 404 on missing project/job
- 422 on invalid attestation (anonymization_confirmed=False)
- Schema: JobManifest is returned for /jobs/{id}

All async tests require @pytest.mark.asyncio per pytest-asyncio strict mode.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models.contracts.manifests import PrivacyResult
from src.services.orchestration.projects.models import DataOrigin

_VALID_ATTESTATION = {
    "data_origin": DataOrigin.ANONYMIZED,
    "declared_owner": "Cường test",
    "declared_purpose": "HTTP route testing",
    "rights_to_use_confirmed": True,
    "anonymization_confirmed": True,
    "retention_acknowledged": True,
}

_CREATE_PROJECT_BODY = {
    "name": "Kho test",
    "source_type": "upload",
    "input_manifest_checksum": "sha256:" + "c" * 64,
    "attestation": _VALID_ATTESTATION,
}


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Give every test its own registry writing to tmp_path, not the repo's data/.

    Without this, POSTing a job would publish JobManifest revisions into the real
    `data/artifacts` tree and leak state between tests.
    """
    from src.api.product import deps as product_deps
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    return registry


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for product API testing."""
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── fixture project/job ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_projects_contains_fixture(client) -> None:
    r = await client.get("/api/v1/projects")
    assert r.status_code == 200
    ids = [p["project_id"] for p in r.json()["projects"]]
    assert "project-fixture-001" in ids


@pytest.mark.asyncio
async def test_get_fixture_project(client) -> None:
    r = await client.get("/api/v1/projects/project-fixture-001")
    assert r.status_code == 200
    body = r.json()
    assert body["privacy"]["result"] == PrivacyResult.VERIFIED_ANONYMIZED
    assert body["privacy"]["dispatch_allowed"] is True


@pytest.mark.asyncio
async def test_get_fixture_job(client) -> None:
    r = await client.get("/api/v1/jobs/job-fixture-001")
    assert r.status_code == 200
    assert r.json()["status"] == "SUCCEEDED"
    assert r.json()["job_id"] == "job-fixture-001"


@pytest.mark.asyncio
async def test_fixture_job_artifacts_returned(client) -> None:
    r = await client.get("/api/v1/jobs/job-fixture-001/artifacts")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-fixture-001"
    assert isinstance(body["artifacts"], list)


# ── security: no filesystem paths in response ────────────────────────────────


@pytest.mark.asyncio
async def test_response_does_not_expose_filesystem_paths(client) -> None:
    """Response body must never contain artifact_root or on-disk file paths."""
    r = await client.get("/api/v1/jobs/job-fixture-001/artifacts")
    text = r.text
    assert "artifact_root" not in text
    # Windows path indicators must not appear
    assert ":\\" not in text
    assert "fixtures\\artifact_store" not in text


@pytest.mark.asyncio
async def test_artifact_uris_are_logical(client) -> None:
    r = await client.get("/api/v1/jobs/job-fixture-001/artifacts")
    for artifact in r.json()["artifacts"]:
        assert artifact["artifact_uri"].startswith("artifact://jobs/")


# ── security: evaluation_only never in artifact list ────────────────────────


@pytest.mark.asyncio
async def test_evaluation_only_not_in_artifact_list(client) -> None:
    r = await client.get("/api/v1/jobs/job-fixture-001/artifacts")
    assert r.status_code == 200
    for artifact in r.json()["artifacts"]:
        assert "evaluation_only" not in artifact["artifact_uri"]
        assert "ground_truth" not in artifact["artifact_uri"]


# ── project creation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_project_returns_201(client) -> None:
    r = await client.post("/api/v1/projects", json=_CREATE_PROJECT_BODY)
    assert r.status_code == 201
    body = r.json()
    assert "project_id" in body
    assert body["privacy"]["result"] == PrivacyResult.PRELIMINARY_SCREENED
    assert body["privacy"]["dispatch_allowed"] is False


@pytest.mark.asyncio
async def test_project_and_job_routes_snapshot_authenticated_actor(client, tmp_path, monkeypatch) -> None:
    from src.api import auth
    from src.api.product import projects as project_routes
    from src.main import app
    from src.services.orchestration.auth import AuthService
    from src.services.orchestration.jobs.database import RuntimeDatabase

    service = AuthService(RuntimeDatabase(f"sqlite:///{tmp_path / 'actor.db'}"))
    user = service.create_user("reviewer@example.com", "Minh An", "mat-khau-du-dai", "reviewer")
    monkeypatch.setattr(auth, "auth_service", lambda: service)
    monkeypatch.setitem(app.dependency_overrides, auth.require_contributor, lambda: user)
    monkeypatch.setattr(project_routes, "record_gpu_run", lambda *_: None)

    forged = await client.post("/api/v1/projects", json={**_CREATE_PROJECT_BODY, "created_by": {"user_id": "attacker"}})
    assert forged.status_code == 422

    project = await client.post("/api/v1/projects", json=_CREATE_PROJECT_BODY)
    assert project.status_code == 201
    assert project.json()["created_by"] == {
        "user_id": user.user_id,
        "display_name": "Minh An",
        "role": "reviewer",
    }

    job = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    assert job.status_code == 201, job.text
    attempts = await client.get(f"/api/v1/jobs/{job.json()['job_id']}/attempts")
    assert attempts.json()["attempts"][0]["requested_by"] == {
        "user_id": user.user_id,
        "display_name": "Minh An",
        "role": "reviewer",
    }


@pytest.mark.asyncio
async def test_create_project_invalid_attestation_422(client) -> None:
    """Attestation with anonymization_confirmed=False must be rejected at 422."""
    bad = {**_CREATE_PROJECT_BODY, "attestation": {**_VALID_ATTESTATION, "anonymization_confirmed": False}}
    r = await client.post("/api/v1/projects", json=bad)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_project_missing_field_422(client) -> None:
    r = await client.post("/api/v1/projects", json={"name": "x"})
    assert r.status_code == 422


# ── job creation and privacy gate ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_job_on_fixture_project_201(client) -> None:
    r = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    assert r.status_code == 201
    assert r.json()["status"] == "QUEUED"


@pytest.mark.asyncio
async def test_create_job_on_new_project_blocked_409(client) -> None:
    """New project is PRELIMINARY_SCREENED — job creation must be rejected with 409."""
    cr = await client.post("/api/v1/projects", json=_CREATE_PROJECT_BODY)
    pid = cr.json()["project_id"]
    r = await client.post(f"/api/v1/projects/{pid}/jobs", json={})
    assert r.status_code == 409
    assert "không thể tạo job" in r.json()["detail"]


# ── not-found ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_missing_project_404(client) -> None:
    r = await client.get("/api/v1/projects/no-such-project")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_missing_job_404(client) -> None:
    r = await client.get("/api/v1/jobs/no-such-job")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_artifacts_for_missing_job_404(client) -> None:
    r = await client.get("/api/v1/jobs/no-such-job/artifacts")
    assert r.status_code == 404


# ── PRODUCT-02: job lifecycle over HTTP ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_job_then_run_then_fail(client) -> None:
    created = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    job_id = created.json()["job_id"]

    running = await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "RUNNING"})
    assert running.status_code == 200
    assert running.json()["status"] == "RUNNING"

    failed = await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "FAILED"})
    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"
    assert failed.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_illegal_transition_rejected_422(client) -> None:
    created = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    job_id = created.json()["job_id"]

    r = await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "SUCCEEDED"})
    assert r.status_code == 422
    assert "chỉ cho phép" in r.json()["detail"]


@pytest.mark.asyncio
async def test_succeeded_cannot_be_faked_over_http(client) -> None:
    """Job mới không có artifact publish nào, nên không thể ghi SUCCEEDED."""
    created = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    job_id = created.json()["job_id"]
    await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "RUNNING"})

    r = await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "SUCCEEDED"})
    assert r.status_code == 409
    assert "artifact" in r.json()["detail"]


@pytest.mark.asyncio
async def test_retry_appends_attempt_over_http(client) -> None:
    created = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    job_id = created.json()["job_id"]
    await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "RUNNING"})
    failed = await client.post(
        f"/api/v1/jobs/{job_id}/transitions",
        json={
            "target_status": "FAILED",
            "error": {
                "stage_id": "ST-CAMERA-POSE",
                "error_code": "COLMAP_TIMEOUT",
                "human_message": "COLMAP exceeded configured timeout",
                "retryable": True,
            },
        },
    )
    assert failed.status_code == 200

    before = await client.get(f"/api/v1/jobs/{job_id}/attempts")
    retried = await client.post(f"/api/v1/jobs/{job_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "QUEUED"
    duplicate = await client.post(f"/api/v1/jobs/{job_id}/retry")
    assert duplicate.status_code == 422

    after = await client.get(f"/api/v1/jobs/{job_id}/attempts")
    assert len(after.json()["attempts"]) == len(before.json()["attempts"]) + 1
    assert after.json()["attempts"][: len(before.json()["attempts"])] == before.json()["attempts"]
    assert after.json()["attempts"][-1]["attempt"] == 2


@pytest.mark.asyncio
async def test_retry_on_non_failed_job_rejected(client) -> None:
    created = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    r = await client.post(f"/api/v1/jobs/{created.json()['job_id']}/retry")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_retry_rejects_nonretryable_input_error_even_if_legacy_flag_is_true(client) -> None:
    created = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    job_id = created.json()["job_id"]
    await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "RUNNING"})
    await client.post(
        f"/api/v1/jobs/{job_id}/transitions",
        json={
            "target_status": "FAILED",
            "error": {
                "stage_id": "ST-FRAME-EXTRACT",
                "error_code": "FRAME_QUALITY_MISMATCH",
                "human_message": "Quality mask belongs to another input",
                "retryable": True,
            },
        },
    )

    retried = await client.post(f"/api/v1/jobs/{job_id}/retry")
    assert retried.status_code == 409
    attempts = await client.get(f"/api/v1/jobs/{job_id}/attempts")
    assert [event["attempt"] for event in attempts.json()["attempts"]] == [1, 1, 1]


@pytest.mark.asyncio
async def test_retry_rejects_failed_job_without_structured_error(client) -> None:
    created = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    job_id = created.json()["job_id"]
    await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "RUNNING"})
    await client.post(f"/api/v1/jobs/{job_id}/transitions", json={"target_status": "FAILED"})

    retried = await client.post(f"/api/v1/jobs/{job_id}/retry")
    assert retried.status_code == 409


@pytest.mark.asyncio
async def test_transition_on_missing_job_404(client) -> None:
    r = await client.post("/api/v1/jobs/no-such-job/transitions", json={"target_status": "RUNNING"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_fixture_job_attempts_endpoint(client) -> None:
    r = await client.get("/api/v1/jobs/job-fixture-001/attempts")
    assert r.status_code == 200
    assert r.json()["attempts"][0]["status"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_attempt_response_has_no_filesystem_paths(client) -> None:
    r = await client.get("/api/v1/jobs/job-fixture-001/attempts")
    assert ":\\" not in r.text
    assert "artifact_root" not in r.text


@pytest.mark.asyncio
async def test_unknown_target_status_422(client) -> None:
    created = await client.post("/api/v1/projects/project-fixture-001/jobs", json={})
    r = await client.post(
        f"/api/v1/jobs/{created.json()['job_id']}/transitions",
        json={"target_status": "NOT_A_STATUS"},
    )
    assert r.status_code == 422
