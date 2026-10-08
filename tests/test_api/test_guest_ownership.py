from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from src.api import auth as auth_api
from src.api.product import jobs as jobs_api
from src.api.product import scene as scene_api
from src.api.studio import imports as imports_api
from src.api.studio import scenes as studio_scenes_api
from src.api.studio import uploads as uploads_api
from src.main import app
from src.services.orchestration.auth import Actor, AuthService, UserRecord
from src.services.orchestration.auth.quota import guest_quota_window
from src.services.orchestration.auth.quota_ledger import guest_quota_summary
from src.services.orchestration.jobs import InvalidTransitionError
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects import ProjectRegistry
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.uploads.scene_imports import ImportedScene


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
async def test_guest_membership_correction_rejects_foreign_job_before_scene_read(
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
            "/api/v1/jobs/job-foreign/scene/corrections/merge",
            json={
                "expected_scene_revision": "rev-001",
                "membership_checksum": "sha256:" + "a" * 64,
                "primary_object_id": "candidate-001",
                "secondary_object_ids": ["candidate-002"],
            },
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 403
    assert owner_lookups == ["job-foreign"]


@pytest.mark.asyncio
async def test_guest_can_edit_own_scene_when_daily_run_quota_is_exhausted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'quota-at-cap.db'}")
    user = AuthService(database).create_user("guest-cap@example.com", "Guest Cap", "test-password-long", "guest")
    window = guest_quota_window(datetime.now(UTC))
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_guest_quota_windows "
            "(actor_user_id, policy_id, window_start_utc, resets_at_utc, policy_limit, used_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                user.user_id,
                window.policy_id,
                window.window_start_utc.isoformat(),
                window.resets_at_utc.isoformat(),
                window.limit,
                window.limit,
            ),
        )
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database)
    registry.seed_from_fixtures()
    monkeypatch.setattr(registry, "get_job_owner_user_id", lambda job_id: user.user_id)
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    monkeypatch.setattr(scene_api.deps, "registry", lambda: registry)
    try:
        response = await client.post(
            "/api/v1/jobs/job-fixture-001/scene/objects/object-pallet-001/hide",
            json={"expected_scene_revision": "rev-001", "active": False},
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 201, response.text
    assert response.json()["scene_revision"] == "rev-002"
    quota = guest_quota_summary(database, user.user_id)
    assert quota.used == 3 and quota.remaining == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "owner_user_id", "expected_status"),
    [
        ("guest", "user-guest", 201),
        ("guest", "user-editor", 403),
        ("editor", "user-guest", 201),
        ("reviewer", "user-guest", 201),
    ],
)
async def test_collider_edit_route_enforces_guest_ownership_and_operator_roles(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    role: str,
    owner_user_id: str,
    expected_status: int,
) -> None:
    user = _user(role)
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(registry, "get_job_owner_user_id", lambda _job_id: owner_user_id)
    monkeypatch.setattr(scene_api.deps, "registry", lambda: registry)
    audit_service = AuthService(RuntimeDatabase(f"sqlite:///{tmp_path / 'scene-collider-audit.db'}"))
    monkeypatch.setattr(auth_api, "auth_service", lambda: audit_service)
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    try:
        response = await client.post(
            "/api/v1/jobs/job-fixture-001/scene/collider",
            json={
                "expected_scene_revision": "rev-001",
                "object_id": "object-pallet-001",
                "dimensions_xyz_m": [1.25, 0.9, 0.7],
            },
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == expected_status, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "owner_user_id", "expected_mutate"),
    [
        ("guest", "user-guest", True),
        ("guest", "user-editor", False),
        ("guest", None, False),
        ("editor", "user-guest", True),
        ("reviewer", "user-guest", True),
    ],
)
async def test_progress_returns_actor_specific_job_capabilities(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    role: str,
    owner_user_id: str | None,
    expected_mutate: bool,
) -> None:
    user = _user(role)
    registry = ProjectRegistry(
        runtime_root=tmp_path / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}"),
    )
    registry.seed_from_fixtures()
    monkeypatch.setattr(registry, "get_job_owner_user_id", lambda job_id: owner_user_id)
    monkeypatch.setattr(studio_scenes_api.deps, "registry", lambda: registry)
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    try:
        response = await client.get("/api/v1/jobs/job-fixture-001/progress")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 200, response.text
    capabilities = response.json()["capabilities"]
    assert capabilities["can_mutate"] is expected_mutate
    assert capabilities["can_cancel"] is False
    assert capabilities["can_retry"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "expected_delete"),
    [
        ("guest", [True, False, True]),
        ("editor", [True, True, True]),
        ("reviewer", [True, True, True]),
    ],
)
async def test_import_list_returns_capability_for_guest_owner_and_higher_roles(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    expected_delete: list[bool],
) -> None:
    user = _user(role)
    records = [
        ImportedScene(
            import_id="import-guest",
            upload_id="upload-guest",
            name="Guest import",
            input_kind="gaussian_ply",
            status="FAILED",
            operation={
                "operation_id": "operation-guest-failed",
                "status": "FAILED",
                "attempt": 1,
                "attempt_history": [],
                "error": "temporary failure",
                "failure_code": "runtime_failure",
                "retryable": True,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
            created_at=datetime.now(UTC),
            created_by="user-guest",
        ),
        ImportedScene(
            import_id="import-editor",
            upload_id="upload-editor",
            name="Editor import",
            input_kind="gaussian_ply",
            status="FAILED",
            operation={
                "operation_id": "operation-editor-failed",
                "status": "FAILED",
                "attempt": 1,
                "attempt_history": [],
                "error": "temporary failure",
                "failure_code": "publication_failure",
                "retryable": True,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
            created_at=datetime.now(UTC),
            created_by="user-editor",
        ),
        ImportedScene(
            import_id="import-guest-queued",
            upload_id="upload-queued",
            name="Guest queued import",
            input_kind="gaussian_ply",
            status="PACKAGING",
            operation={
                "operation_id": "operation-guest-queued",
                "status": "QUEUED",
                "attempt": 0,
                "attempt_history": [],
                "error": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
            created_at=datetime.now(UTC),
            created_by="user-guest",
        ),
    ]

    class ImportList:
        def list(self) -> list[ImportedScene]:
            return records

    monkeypatch.setattr(imports_api, "_service", lambda: ImportList())
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    try:
        response = await client.get("/api/v1/imports")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 200, response.text
    imports = response.json()["imports"]
    assert [item["capabilities"]["can_delete"] for item in imports] == expected_delete
    assert [item["capabilities"]["can_retry"] for item in imports] == (
        [True, False, False] if role == "guest" else [True, True, False]
    )
    assert [item["capabilities"]["can_cancel"] for item in imports] == (
        [False, False, True] if role == "guest" else [False, False, True]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "owner_user_id", "expected_status"),
    [
        ("guest", "user-guest", 200),
        ("guest", "user-editor", 403),
        ("editor", "user-guest", 200),
        ("reviewer", "user-guest", 200),
    ],
)
@pytest.mark.parametrize("action", ["retry", "cancel"])
async def test_import_retry_and_cancel_routes_enforce_owner_and_operator_roles(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    owner_user_id: str,
    expected_status: int,
    action: str,
) -> None:
    user = _user(role)
    now = datetime.now(UTC)
    queued = action == "cancel"
    record = ImportedScene(
        import_id="import-target",
        upload_id="upload-target",
        name="Target import",
        input_kind="gaussian_ply",
        status="PACKAGING" if queued else "FAILED",
        operation={
            "operation_id": "operation-target",
            "status": "QUEUED" if queued else "FAILED",
            "attempt": 0 if queued else 1,
            "attempt_history": [],
            "error": None if queued else "temporary failure",
            "failure_code": None if queued else "runtime_failure",
            "retryable": None if queued else True,
            "created_at": now,
            "updated_at": now,
        },
        created_at=now,
        created_by=owner_user_id,
    )
    calls: list[str] = []

    class ImportCommands:
        def get(self, import_id: str) -> ImportedScene:
            assert import_id == record.import_id
            return record

        def retry(self, import_id: str) -> ImportedScene:
            calls.append("retry")
            return record

        def cancel(self, import_id: str) -> ImportedScene:
            calls.append("cancel")
            return record

    monkeypatch.setattr(imports_api, "_service", lambda: ImportCommands())
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[auth_api.require_contributor] = lambda: user
    try:
        response = await client.post(f"/api/v1/imports/{record.import_id}/{action}")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == expected_status, response.text
    assert calls == ([action] if expected_status == 200 else [])


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
