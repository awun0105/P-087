"""CPU/ASGI isolation evidence; these fixtures do not exercise GPU or Isaac."""

import asyncio
import shutil
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import Settings
from src.services.orchestration.artifacts import sha256_file
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.samples import DemoFile, DemoManifest, DemoSource
from src.services.orchestration.samples.sessions import get_session, hold_session, purge_sessions, session_path

JOB = "job-fixture-001"


@pytest.fixture
def source(tmp_path, monkeypatch):
    from src.api import auth
    from src.api.product import deps as product
    from src.api.studio import deps as studio

    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        product_demo_dir=tmp_path / "library",
        auth_required=False,
    )
    registry = ProjectRegistry(runtime_root=settings.artifact_root, database=RuntimeDatabase(settings.database_url))
    shutil.copytree(registry.artifact_root, settings.artifact_root, dirs_exist_ok=True)
    registry.seed_from_fixtures()
    registry.scene.current(JOB)
    project = registry.get_project("project-fixture-001")
    registry.persistence.save_project(
        project.model_copy(
            update={
                "source_rights_attestation": {
                    "rights_to_use_confirmed": True,
                    "anonymization_confirmed": True,
                }
            }
        ),
        expected=project,
    )
    sample = settings.product_demo_dir / "sample"
    (sample / "files").mkdir(parents=True)
    splat = sample / "files/scene.sog"
    splat.write_bytes(b"fixture-not-real-gaussians")
    manifest = DemoManifest(
        demo_id="sample",
        title="Fixture demo",
        origin="pipeline_job",
        source=DemoSource(dataset="Fixture", sequence="Test"),
        produced_at=datetime.now(UTC),
        provenance={"job_id": JOB},
        stages=[],
        splat=DemoFile(
            name="scene.sog",
            media_type="application/octet-stream",
            size_bytes=splat.stat().st_size,
            checksum=sha256_file(splat),
        ),
    )
    (sample / "manifest.json").write_text(manifest.model_dump_json())
    from src.services.orchestration.samples.bundle import DemoBundle
    from src.services.orchestration.samples.workspace import freeze_workspace

    freeze_workspace(registry, DemoBundle(sample))
    monkeypatch.setattr(product, "get_project_registry", lambda: registry)
    monkeypatch.setattr(studio, "get_project_registry", lambda: registry)
    monkeypatch.setattr(product, "get_settings", lambda: settings)
    monkeypatch.setattr(studio, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    return settings, registry


@pytest.mark.asyncio
async def test_two_sessions_edit_independently_and_never_mutate_the_source(source):
    from src.main import app

    settings, registry = source
    original = registry.scene.current(JOB)
    original_bytes = registry.runtime_resolver.require(original.scene_reference).read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        opened = await client.post("/api/v1/samples/sample/sessions")
        assert opened.status_code == 201, opened.text
        first = opened.json()["session_id"]
        second_response = await client.post("/api/v1/samples/sample/sessions")
        assert second_response.status_code == 201, second_response.text
        second = second_response.json()["session_id"]
        a = f"/api/v1/demo-sessions/{first}/api/v1/jobs/{JOB}"
        b = f"/api/v1/demo-sessions/{second}/api/v1/jobs/{JOB}"
        edit = {
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3, 2, 0]}],
        }
        changed, untouched = await asyncio.gather(client.post(a + "/scene/edits", json=edit), client.get(b + "/scene"))
        assert changed.status_code == 201, changed.text
        assert changed.json()["scene_revision"] == "rev-002"
        assert untouched.status_code == 200, untouched.text
        assert untouched.json()["scene_revision"] == "rev-001"
        assert (await client.post(a + "/scene/edits", json=edit)).status_code == 409
        assert (await client.get(f"/api/v1/demo-sessions/{first}/api/v1/jobs/other-job/scene")).status_code == 404
        assert (await client.get(f"/api/v1/demo-sessions/{first}/api/v1/auth/users")).status_code == 404
        assert (await client.get(f"/api/v1/demo-sessions/{first}/api/v1/auth/me")).json()["user"][
            "display_name"
        ] == "Khách thử mẫu"
        assert (await client.get(f"/api/v1/jobs/{JOB}/scene")).json()["scene_revision"] == "rev-001"
        await client.delete(f"/api/v1/demo-sessions/{first}")
        assert (await client.get(a + "/scene")).status_code == 410
        assert not session_path(settings, first).exists()
        assert (await client.get(b + "/scene")).status_code == 200
        await client.delete(f"/api/v1/demo-sessions/{second}")
    assert registry.scene.current(JOB) == original
    assert registry.runtime_resolver.require(original.scene_reference).read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_close_waits_for_active_reader_then_purges_and_reopening_starts_fresh(source):
    from src.main import app

    settings, _ = source
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/samples/sample/sessions")
        assert response.status_code == 201, response.text
        session_id = response.json()["session_id"]
        root = session_path(settings, session_id)
        with hold_session(settings, session_id):
            assert (await client.delete(f"/api/v1/demo-sessions/{session_id}")).status_code == 202
            assert root.exists()
        assert purge_sessions(settings) == 1
        response = await client.post("/api/v1/samples/sample/sessions")
        assert response.status_code == 201, response.text
        assert response.json()["session_id"] != session_id
        new_id = response.json()["session_id"]
        get_session(settings, new_id)
        await client.delete(f"/api/v1/demo-sessions/{new_id}")


@pytest.mark.asyncio
async def test_unpublished_sample_revokes_its_session(source):
    from src.main import app

    settings, _ = source
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        opened = await client.post("/api/v1/samples/sample/sessions")
        assert opened.status_code == 201, opened.text
        token = opened.json()["session_id"]
        (settings.product_demo_dir / "sample/.unpublished").touch()
        result = await client.get(f"/api/v1/demo-sessions/{token}/api/v1/jobs/{JOB}/scene")
        assert result.status_code == 410
        await client.delete(f"/api/v1/demo-sessions/{token}")


@pytest.mark.asyncio
@pytest.mark.parametrize("admitted", [False, True])
async def test_private_worker_requires_shared_machine_reservation(source, monkeypatch, admitted):
    from types import SimpleNamespace

    from src.main import app
    from src.services.orchestration.jobs.admission import OperationResourceProfile
    from src.services.orchestration.samples import session_worker

    settings, registry = source
    events = []
    profile = OperationResourceProfile(required_gb={"vram": 1, "ram": 1, "disk": 1}, measured=True, danger_ratio=0.9)
    monkeypatch.setattr(session_worker, "_pending", lambda _: "scene")
    monkeypatch.setattr(session_worker, "_profile", lambda *args: profile)
    monkeypatch.setattr(session_worker, "_run", lambda *args: events.append("child"))

    def reserve(request):
        events.append("admit")
        assert request.operation_kind == "demo_session"
        assert request.resources.measured is False
        return SimpleNamespace(
            status="admitted" if admitted else "waiting_resources",
            model_dump=lambda **kwargs: {"status": "admitted" if admitted else "waiting_resources"},
        )

    gate = SimpleNamespace(admit_operation=reserve, release_operation=lambda _: events.append("release"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        opened = await client.post("/api/v1/samples/sample/sessions")
        assert opened.status_code == 201, opened.text
        assert session_worker.process_demo_session(settings, registry, gate) is admitted
        assert events == (["admit", "child", "release"] if admitted else ["admit"])
        await client.delete(f"/api/v1/demo-sessions/{opened.json()['session_id']}")


@pytest.mark.asyncio
async def test_parallel_edits_in_one_session_keep_the_native_revision_fence(source):
    from src.main import app

    _, registry = source
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        opened = await client.post("/api/v1/samples/sample/sessions")
        assert opened.status_code == 201, opened.text
        token = opened.json()["session_id"]
        path = f"/api/v1/demo-sessions/{token}/api/v1/jobs/{JOB}/scene/edits"
        commands = [
            {
                "expected_scene_revision": "rev-001",
                "edits": [{"object_id": "object-pallet-001", "translation_xyz": [x, 2, 0]}],
            }
            for x in (3, 4)
        ]
        results = await asyncio.gather(*(client.post(path, json=command) for command in commands))
        assert sorted(result.status_code for result in results) == [201, 409]
        assert registry.scene.current(JOB).scene.scene_revision == "rev-001"
        await client.delete(f"/api/v1/demo-sessions/{token}")


@pytest.mark.asyncio
async def test_frozen_sample_ignores_later_source_edits_and_source_removal(source, monkeypatch):
    from src.main import app
    from src.services.orchestration.scene.models import SceneEditCommand, TransformEdit

    _, registry = source
    registry.scene.apply(
        JOB,
        SceneEditCommand(
            expected_scene_revision="rev-001",
            edits=[TransformEdit(object_id="object-pallet-001", translation_xyz=(9, 9, 0))],
        ),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Session creation must use the published bundle even when the live source is unavailable.
        def missing_source(job_id):
            raise AssertionError("read from live source instead of frozen demo")

        monkeypatch.setattr(registry, "get_job", missing_source)
        opened = await client.post("/api/v1/samples/sample/sessions")
        assert opened.status_code == 201, opened.text
        session = opened.json()
        assert session["source_revision"] == "rev-001"
        response = await client.get(f"/api/v1/demo-sessions/{session['session_id']}/api/v1/jobs/{JOB}/scene")
        assert response.status_code == 200, response.text
        assert response.json()["scene_revision"] == "rev-001"
        await client.delete(f"/api/v1/demo-sessions/{session['session_id']}")


def test_artifact_envelope_checksum_is_not_a_second_dependency(tmp_path):
    import json

    from src.services.orchestration.artifacts import ArtifactResolver
    from src.services.orchestration.samples.snapshot import copy_artifact_graph

    source = ArtifactResolver(tmp_path / "source")
    target = ArtifactResolver(tmp_path / "target")
    uri = "artifact://jobs/job-a/bundle.json"
    path = source.resolve(uri)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"artifact_uri": uri, "artifact_checksum": "sha256:" + "a" * 64, "data": {"value": 1}}))
    copied = copy_artifact_graph(source, target, [{"artifact_uri": uri, "artifact_checksum": sha256_file(path)}])
    assert copied == [uri]
    assert target.resolve(uri).read_bytes() == path.read_bytes()
