from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from src.api import auth as auth_api
from src.api.product import jobs as jobs_api
from src.api.product import scene as scene_api
from src.api.studio import imports as imports_api
from src.api.studio import uploads as uploads_api
from src.main import app
from src.services.orchestration.auth import Actor, UserRecord
from src.services.orchestration.jobs import InvalidTransitionError
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects import ProjectRegistry
from src.services.orchestration.projects.models import JobCreateInput


def _user(role: str) -> UserRecord:
    return UserRecord(
        user_id=f"user-{role}",
        email=f"{role}@example.com",
        display_name=role.title(),
        role=role,  # type: ignore[arg-type]
        password_hash="test-only-hash",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_user_id", ["user-editor", None])
async def test_guest_direct_cancel_rejects_foreign_or_unknown_job_without_transition(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, owner_user_id: str | None
) -> None:
    user = _user("guest")
    transitions: list[tuple] = []

    class Registry:
        persistence = None

        def get_job_owner_user_id(self, job_id: str) -> str | None:
            assert job_id == "job-target"
            return owner_user_id

        def transition_job(self, *args: object, **kwargs: object) -> None:
            transitions.append((args, kwargs))

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    monkeypatch.setattr(jobs_api.deps, "registry", Registry)
    try:
        response = await client.post(
            "/api/v1/jobs/job-target/transitions",
            json={"target_status": "CANCELLED"},
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 403
    assert transitions == []


@pytest.mark.asyncio
async def test_guest_can_cancel_own_database_job_without_changing_owner(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    user = _user("guest")
    actor = Actor(user_id=user.user_id, display_name=user.display_name, role=user.role)
    registry = ProjectRegistry(
        runtime_root=tmp_path / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}"),
    )
    registry.seed_from_fixtures()
    job = registry.create_job(
        JobCreateInput(project_id="project-fixture-001"),
        requested_by=actor,
        owner_user_id=user.user_id,
    )
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    monkeypatch.setattr(jobs_api.deps, "registry", lambda: registry)
    try:
        response = await client.post(f"/api/v1/jobs/{job.job_id}/transitions", json={"target_status": "CANCELLED"})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"
    assert registry.get_job_owner_user_id(job.job_id) == user.user_id


@pytest.mark.asyncio
async def test_guest_direct_scene_edit_rejects_foreign_job_before_revision_write(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user("guest")
    owner_lookups: list[str] = []

    class Registry:
        def get_job_owner_user_id(self, job_id: str) -> str:
            owner_lookups.append(job_id)
            return "user-someone-else"

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    monkeypatch.setattr(scene_api.deps, "registry", Registry)
    try:
        response = await client.post(
            "/api/v1/jobs/job-foreign/scene/edits",
            json={
                "expected_scene_revision": "rev-001",
                "edits": [{"object_id": "object-1", "translation_xyz": [1, 0, 0]}],
            },
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 403
    assert owner_lookups == ["job-foreign"]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["editor", "reviewer"])
async def test_editor_and_reviewer_can_intervene_on_guest_job_and_are_audited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    user = _user(role)
    transitions: list[tuple] = []
    audit_entries: list[tuple] = []

    class Registry:
        persistence = None

        def get_job_owner_user_id(self, job_id: str) -> str:
            assert job_id == "job-guest"
            return "guest-owner"

        def transition_job(self, *args: object, **kwargs: object) -> None:
            transitions.append((args, kwargs))
            raise InvalidTransitionError("test reached the lifecycle gate")

    class AuditService:
        def audit(self, *args: object) -> None:
            audit_entries.append(args)

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    monkeypatch.setattr(jobs_api.deps, "registry", Registry)
    monkeypatch.setattr(auth_api, "auth_service", AuditService)
    try:
        response = await client.post(
            "/api/v1/jobs/job-guest/transitions",
            json={"target_status": "CANCELLED"},
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 422
    assert len(transitions) == 1
    assert audit_entries == [
        (
            user.user_id,
            "operator.intervention",
            "job-guest",
            {"operation": "hủy job", "resource_type": "job", "owner_user_id": "guest-owner"},
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("owner_user_id", "expected_status"), [("user-guest", 200), ("user-editor", 403)])
async def test_guest_direct_upload_urls_require_session_owner_before_presigning(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    owner_user_id: str,
    expected_status: int,
) -> None:
    user = _user("guest")
    calls: list[tuple] = []

    class DirectUploads:
        def get(self, upload_id: str) -> SimpleNamespace:
            assert upload_id == "upload-target"
            return SimpleNamespace(
                upload_id=upload_id,
                uploaded_by=Actor(user_id=owner_user_id, display_name="Owner", role="editor"),
            )

        def part_urls(self, upload_id: str, part_numbers: list[int], expires_seconds: int) -> dict[int, str]:
            calls.append((upload_id, part_numbers, expires_seconds))
            return {1: "https://signed.example/part"}

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    monkeypatch.setattr(uploads_api.deps, "direct_uploads", DirectUploads)
    monkeypatch.setattr(uploads_api.deps, "settings", lambda: SimpleNamespace(artifact_presign_seconds=300))
    try:
        response = await client.post(
            "/api/v1/uploads/direct/upload-target/urls",
            json={"part_numbers": [1]},
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == expected_status
    assert calls == ([("upload-target", [1], 300)] if expected_status == 200 else [])


@pytest.mark.asyncio
async def test_guest_cannot_import_another_users_upload(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user("guest")
    upload = SimpleNamespace(
        upload_id="upload-foreign",
        uploaded_by=Actor(user_id="user-editor", display_name="Editor", role="editor"),
    )

    class Uploads:
        def get(self, upload_id: str) -> SimpleNamespace:
            assert upload_id == upload.upload_id
            return upload

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    monkeypatch.setattr(imports_api.deps, "uploads", Uploads)
    monkeypatch.setattr(imports_api, "_service", lambda: pytest.fail("foreign upload must be denied before import"))
    try:
        response = await client.post(
            "/api/v1/imports",
            json={"upload_id": upload.upload_id, "name": "Foreign scene"},
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 403
