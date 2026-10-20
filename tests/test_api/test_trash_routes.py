"""HTTP tests cho thùng rác scene: gỡ, liệt kê, khôi phục, xoá hẳn và phân quyền."""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import Settings
from src.services.orchestration.auth.models import Actor
from src.services.orchestration.auth.service import AuthService
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.uploads import VideoUploadService
from tests.test_orchestration.test_scene_deletion import _input_run, _scene, _upload

PASSWORD = "mat-khau-du-dai-123"


def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, auth_required: bool) -> SimpleNamespace:
    from src.api import auth
    from src.api.product import deps as product_deps
    from src.api.studio import deps

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        artifact_root=tmp_path / "artifacts",
        product_worker_root=tmp_path / "workers",
        product_rerun_recording_dir=tmp_path / "rerun",
        product_demo_dir=tmp_path / "samples",
        artifact_s3_bucket=None,
        auth_required=auth_required,
    )
    config = tmp_path / "processing.json"
    config.write_text(json.dumps({"colmap": {}, "brush": {}}))
    profile = ExecutionProfile(
        config_checksum="sha256:" + hashlib.sha256(config.read_bytes()).hexdigest(),
        runtime_manifest_checksum="sha256:" + "d" * 64,
    )
    database = RuntimeDatabase(settings.database_url)
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database, execution_profile=profile)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(product_deps, "get_settings", lambda: settings)
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(auth, "login_limiter", auth._LoginLimiter(attempts=10))
    monkeypatch.setattr(auth, "client_limiter", auth._LoginLimiter(attempts=100))
    return SimpleNamespace(
        root=tmp_path,
        database=database,
        registry=registry,
        uploads=VideoUploadService(database, registry.runtime_resolver, 8 * 1024 * 1024),
    )


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _scene_names(client: AsyncClient) -> list[str]:
    scenes = (await client.get("/api/v1/scenes")).json()["scenes"]
    return sorted(scene["project"]["name"] for scene in scenes)


@pytest.mark.asyncio
async def test_scene_created_from_assembly_can_be_trashed_and_restored(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path, monkeypatch, auth_required=False)
    project_id, job_id = _scene(world, _upload(world), "Assembly scene")
    _input_run(world, project_id, job_id, "accepted-run")
    with world.database.transaction() as tx:
        original = tx.execute("SELECT * FROM r2s_input_runs").fetchall()

    response = await client.delete(f"/api/v1/scenes/{project_id}")
    assert response.status_code == 200, response.text
    entry_id = response.json()["entry_id"]
    assert await _scene_names(client) == []
    restored = await client.post("/api/v1/trash/restore", json={"entry_ids": [entry_id]})
    assert restored.json() == {"done": [entry_id], "failed": []}
    assert await _scene_names(client) == ["Assembly scene"]
    with world.database.transaction() as tx:
        assert tx.execute("SELECT * FROM r2s_input_runs").fetchall() == original


@pytest.mark.asyncio
async def test_scene_goes_to_trash_then_restores_or_is_purged(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path, monkeypatch, auth_required=False)
    first, first_job = _scene(world, _upload(world), "Kho A")
    second, _ = _scene(world, _upload(world, "b.mp4"), "Kho B")
    assert await _scene_names(client) == ["Kho A", "Kho B"]

    removed = await client.delete(f"/api/v1/scenes/{first}")
    assert removed.status_code == 200, removed.text
    entry = removed.json()
    assert entry["title"] == "Kho A" and entry["size_bytes"] > 0
    assert [(item["kind"], item["name"]) for item in entry["items"]] == [("scene", "Kho A"), ("upload", "walk.mp4")]
    assert await _scene_names(client) == ["Kho B"]
    assert (await client.get(f"/api/v1/jobs/{first_job}")).status_code == 404
    listed = (await client.get("/api/v1/trash")).json()["entries"]
    assert [item["entry_id"] for item in listed] == [entry["entry_id"]]
    kept_for = datetime.fromisoformat(listed[0]["expires_at"]) - datetime.fromisoformat(listed[0]["deleted_at"])
    assert kept_for == timedelta(days=7)

    restored = await client.post("/api/v1/trash/restore", json={"entry_ids": [entry["entry_id"], "khong-co"]})
    body = restored.json()
    assert body["done"] == [entry["entry_id"]] and [item["entry_id"] for item in body["failed"]] == ["khong-co"]
    assert await _scene_names(client) == ["Kho A", "Kho B"]
    assert (await client.get(f"/api/v1/jobs/{first_job}")).status_code == 200
    assert (await client.get("/api/v1/trash")).json()["entries"] == []

    ids = [(await client.delete(f"/api/v1/scenes/{project}")).json()["entry_id"] for project in (first, second)]
    purged = await client.post("/api/v1/trash/purge", json={"entry_ids": ids})
    assert purged.json() == {"done": ids, "failed": []}
    assert await _scene_names(client) == [] and (await client.get("/api/v1/trash")).json()["entries"] == []
    again = await client.post("/api/v1/trash/restore", json={"entry_ids": ids})
    assert again.json()["done"] == [] and len(again.json()["failed"]) == 2
    assert not any((tmp_path / "trash").iterdir())


@pytest.mark.asyncio
async def test_opening_the_trash_drops_expired_entries(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path, monkeypatch, auth_required=False)
    project_id, _ = _scene(world, _upload(world), "Quá hạn")
    entry_id = (await client.delete(f"/api/v1/scenes/{project_id}")).json()["entry_id"]
    with world.database.transaction(write=True) as tx:
        payload = json.loads(tx.execute("SELECT payload FROM r2s_trash").fetchone()[0])
        payload["created_at"] = "2026-01-01T00:00:00Z"
        tx.execute("UPDATE r2s_trash SET payload=?", (json.dumps(payload),))

    assert (await client.get("/api/v1/trash")).json()["entries"] == []
    restored = await client.post("/api/v1/trash/restore", json={"entry_ids": [entry_id]})
    assert restored.json()["done"] == [] and not (tmp_path / "trash" / entry_id).exists()


@pytest.mark.asyncio
async def test_refusals_map_to_http_errors(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path, monkeypatch, auth_required=False)
    busy, _ = _scene(world, _upload(world), "Đang chờ worker", stopped=False)

    assert (await client.delete("/api/v1/scenes/project-khong-co")).status_code == 404
    assert (await client.delete("/api/v1/imports/import-khong-co")).status_code == 404
    refused = await client.delete(f"/api/v1/scenes/{busy}")
    assert refused.status_code == 409 and "QUEUED" in refused.json()["detail"]
    assert await _scene_names(client) == ["Đang chờ worker"]
    assert (await client.post("/api/v1/trash/purge", json={"entry_ids": []})).status_code == 422


@pytest.mark.asyncio
async def test_only_reviewer_may_purge_and_actions_are_attributed(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path, monkeypatch, auth_required=True)
    service = AuthService(world.database)
    editor = service.create_user("editor@example.com", "Biên tập", PASSWORD, "editor")
    reviewer = service.create_user("lead@example.com", "Trưởng nhóm", PASSWORD, "reviewer")
    project_id, _ = _scene(world, _upload(world), "Kho A")

    assert (await client.delete(f"/api/v1/scenes/{project_id}")).status_code == 401
    assert (await client.get("/api/v1/trash")).status_code == 401

    login = await client.post("/api/v1/auth/login", json={"email": editor.email, "password": PASSWORD})
    assert login.status_code == 200
    entry_id = (await client.delete(f"/api/v1/scenes/{project_id}")).json()["entry_id"]
    assert (await client.get("/api/v1/trash")).json()["entries"][0]["deleted_by"] == editor.user_id
    assert (await client.post("/api/v1/trash/purge", json={"entry_ids": [entry_id]})).status_code == 403
    assert [item["entry_id"] for item in (await client.get("/api/v1/trash")).json()["entries"]] == [entry_id]

    await client.post("/api/v1/auth/logout")
    login = await client.post("/api/v1/auth/login", json={"email": reviewer.email, "password": PASSWORD})
    assert login.status_code == 200
    purged = await client.post("/api/v1/trash/purge", json={"entry_ids": [entry_id]})
    assert purged.status_code == 200 and purged.json()["done"] == [entry_id]
    audit = {(row.action, row.user_id) for row in service.recent_audit()}
    assert {("scene.delete", editor.user_id), ("scene.purge", reviewer.user_id)} <= audit


@pytest.mark.asyncio
async def test_guest_scene_and_trash_capabilities_follow_resource_owner(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path, monkeypatch, auth_required=True)
    service = AuthService(world.database)
    guest = service.create_user("guest@example.com", "Khách", PASSWORD, "guest")
    editor = service.create_user("editor@example.com", "Biên tập", PASSWORD, "editor")
    reviewer = service.create_user("reviewer@example.com", "Duyệt", PASSWORD, "reviewer")
    guest_actor = Actor(user_id=guest.user_id, display_name=guest.display_name, role=guest.role)
    editor_actor = Actor(user_id=editor.user_id, display_name=editor.display_name, role=editor.role)

    owned_project, _ = _scene(
        world,
        _upload(world, "guest.mp4", uploaded_by=guest_actor),
        "Scene của Guest",
        created_by=guest_actor,
        owner_user_id=guest.user_id,
    )
    foreign_project, _ = _scene(
        world,
        _upload(world, "editor.mp4", uploaded_by=editor_actor),
        "Scene của Editor",
        created_by=editor_actor,
        owner_user_id=editor.user_id,
    )

    assert (
        await client.post("/api/v1/auth/login", json={"email": guest.email, "password": PASSWORD})
    ).status_code == 200
    guest_scenes = (await client.get("/api/v1/scenes")).json()["scenes"]
    guest_caps = {item["project"]["name"]: item["capabilities"]["can_delete_project"] for item in guest_scenes}
    assert guest_caps == {"Scene của Guest": True, "Scene của Editor": False}

    await client.post("/api/v1/auth/logout")
    assert (
        await client.post("/api/v1/auth/login", json={"email": editor.email, "password": PASSWORD})
    ).status_code == 200
    editor_scenes = (await client.get("/api/v1/scenes")).json()["scenes"]
    assert all(item["capabilities"]["can_delete_project"] for item in editor_scenes)
    owned_entry = (await client.delete(f"/api/v1/scenes/{owned_project}")).json()
    foreign_entry = (await client.delete(f"/api/v1/scenes/{foreign_project}")).json()

    editor_trash = (await client.get("/api/v1/trash")).json()["entries"]
    assert all(item["capabilities"] == {"can_restore": True, "can_purge": False} for item in editor_trash)
    await client.post("/api/v1/auth/logout")

    assert (
        await client.post("/api/v1/auth/login", json={"email": guest.email, "password": PASSWORD})
    ).status_code == 200
    guest_trash = (await client.get("/api/v1/trash")).json()["entries"]
    guest_trash_caps = {item["entry_id"]: item["capabilities"] for item in guest_trash}
    assert guest_trash_caps[owned_entry["entry_id"]] == {"can_restore": True, "can_purge": False}
    assert guest_trash_caps[foreign_entry["entry_id"]] == {"can_restore": False, "can_purge": False}
    restore = await client.post(
        "/api/v1/trash/restore", json={"entry_ids": [owned_entry["entry_id"], foreign_entry["entry_id"]]}
    )
    assert restore.json()["done"] == [owned_entry["entry_id"]]
    assert [item["entry_id"] for item in restore.json()["failed"]] == [foreign_entry["entry_id"]]
    assert (
        await client.post("/api/v1/trash/purge", json={"entry_ids": [foreign_entry["entry_id"]]})
    ).status_code == 403

    await client.post("/api/v1/auth/logout")
    assert (
        await client.post("/api/v1/auth/login", json={"email": reviewer.email, "password": PASSWORD})
    ).status_code == 200
    reviewer_trash = (await client.get("/api/v1/trash")).json()["entries"]
    assert len(reviewer_trash) == 1
    assert reviewer_trash[0]["entry_id"] == foreign_entry["entry_id"]
    assert reviewer_trash[0]["capabilities"] == {"can_restore": True, "can_purge": True}
