"""HTTP tests for the PRODUCT-06 scene endpoints.

Router note: the scene routes sit in the same product router as the project/job
routes, so the isolation fixture is duplicated here on purpose — each test module
must own its registry rather than share mutable state across files.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_JOB = "/api/v1/jobs/job-fixture-001"


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Per-test registry writing revisions into tmp_path, seeded from fixtures."""
    from src.api import routes_product
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(routes_product, "get_project_registry", lambda: registry)
    return registry


@pytest_asyncio.fixture
async def client():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _scene(client) -> dict:
    response = await client.get(f"{_JOB}/scene")
    assert response.status_code == 200
    return response.json()


# ── reading the scene ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_scene_returns_revision(client) -> None:
    body = await _scene(client)
    assert body["job_id"] == "job-fixture-001"
    assert body["scene_revision"] == "rev-001"
    assert body["scene"]["scene_id"] == "scene-fixture-001"


@pytest.mark.asyncio
async def test_scene_response_carries_bindable_ref(client) -> None:
    body = await _scene(client)
    assert body["scene_uri"].startswith("artifact://jobs/job-fixture-001/scene/")
    assert body["scene_checksum"].startswith("sha256:")


@pytest.mark.asyncio
async def test_scene_response_has_no_filesystem_paths(client) -> None:
    r = await client.get(f"{_JOB}/scene")
    assert ":\\" not in r.text
    assert "artifact_root" not in r.text
    assert "fixtures/" not in r.text


@pytest.mark.asyncio
async def test_scene_reports_visual_is_not_brush_proof(client) -> None:
    """Fixture visual phải tự khai nó không phải bằng chứng Brush."""
    body = await _scene(client)
    assert body["visual"]["available"] is True
    assert body["visual"]["brush_compatibility_proof"] is False


@pytest.mark.asyncio
async def test_scene_for_missing_job_404(client) -> None:
    r = await client.get("/api/v1/jobs/no-such-job/scene")
    assert r.status_code == 404


# ── editing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_bumps_revision_over_http(client) -> None:
    r = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["previous_scene_revision"] == "rev-001"
    assert body["scene_revision"] == "rev-002"


@pytest.mark.asyncio
async def test_edit_persists_so_next_read_sees_it(client) -> None:
    await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    body = await _scene(client)
    assert body["scene_revision"] == "rev-002"
    moved = next(item for item in body["scene"]["objects"] if item["id"] == "object-pallet-001")
    assert moved["transform"]["translation_xyz"] == [3.0, 2.0, 0.0]


@pytest.mark.asyncio
async def test_stale_edit_rejected_409(client) -> None:
    payload = {
        "expected_scene_revision": "rev-001",
        "edits": [{"object_id": "object-pallet-001", "translation_xyz": [1.0, 0.0, 0.0]}],
    }
    assert (await client.post(f"{_JOB}/scene/edits", json=payload)).status_code == 201
    assert (await client.post(f"{_JOB}/scene/edits", json=payload)).status_code == 409


@pytest.mark.asyncio
async def test_unknown_object_edit_rejected_422(client) -> None:
    r = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-khong-co", "translation_xyz": [1.0, 0.0, 0.0]}],
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unnormalized_quaternion_rejected(client) -> None:
    r = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "rotation_quaternion_xyzw": [0.0, 0.0, 0.5, 0.5]}],
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_edit_on_missing_job_404(client) -> None:
    r = await client.post(
        "/api/v1/jobs/no-such-job/scene/edits",
        json={"expected_scene_revision": "rev-001", "edits": [{"object_id": "x", "translation_xyz": [1, 0, 0]}]},
    )
    assert r.status_code == 404


# ── restart: revision state must outlive the process ─────────────────────────


def _restart_registry(tmp_path, monkeypatch):
    """Registry mới trên cùng runtime root — mô phỏng backend khởi động lại."""
    from src.api import routes_product
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(routes_product, "get_project_registry", lambda: registry)
    return registry


@pytest.mark.asyncio
async def test_edit_after_restart_does_not_500(client, tmp_path, monkeypatch) -> None:
    """Regression: edit đầu tiên sau restart từng trả 500 thay vì revision mới."""
    first = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    assert first.status_code == 201
    assert first.json()["scene_revision"] == "rev-002"

    _restart_registry(tmp_path, monkeypatch)

    second = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-002",
            "edits": [{"object_id": "object-rack-001", "translation_xyz": [7.0, 7.0, 0.0]}],
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["scene_revision"] == "rev-003"


@pytest.mark.asyncio
async def test_scene_read_after_restart_reports_persisted_revision(client, tmp_path, monkeypatch) -> None:
    """Sau restart, `GET /scene` phải trả revision đã persist, không phải `rev-001`."""
    await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    _restart_registry(tmp_path, monkeypatch)
    assert (await _scene(client))["scene_revision"] == "rev-002"


# ── artifact content: allow-list, not free-form paths ────────────────────────


@pytest.mark.asyncio
async def test_geometry_bytes_are_served(client) -> None:
    body = await _scene(client)
    reference = body["scene"]["environment"]["geometry_ref"]
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={"artifact_uri": reference["artifact_uri"], "artifact_checksum": reference["artifact_checksum"]},
    )
    assert r.status_code == 200
    assert r.content.startswith(b"ply")


@pytest.mark.asyncio
async def test_evaluation_only_artifact_cannot_be_fetched(client) -> None:
    """`groundtruth_map.mock` nằm cùng thư mục job nhưng không được phép tải."""
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/evaluation_only/groundtruth_map.mock",
            "artifact_checksum": "sha256:" + "0" * 64,
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_artifact_from_another_job_cannot_be_fetched(client) -> None:
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={
            "artifact_uri": "artifact://jobs/job-khac-001/scene/object_pallet_geometry.ply",
            "artifact_checksum": "sha256:" + "0" * 64,
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_path_traversal_uri_is_rejected(client) -> None:
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/scene/../../mock_job/job_manifest.json",
            "artifact_checksum": "sha256:" + "0" * 64,
        },
    )
    assert r.status_code in {404, 422}


@pytest.mark.asyncio
async def test_wrong_checksum_is_rejected(client) -> None:
    """Allow-list rồi vẫn phải verify bytes: checksum sai thì fail closed."""
    body = await _scene(client)
    reference = body["scene"]["environment"]["geometry_ref"]
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={"artifact_uri": reference["artifact_uri"], "artifact_checksum": "sha256:" + "f" * 64},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_content_for_missing_job_404(client) -> None:
    r = await client.get(
        "/api/v1/jobs/no-such-job/artifacts/content",
        params={"artifact_uri": "artifact://jobs/x/y.ply", "artifact_checksum": "sha256:" + "0" * 64},
    )
    assert r.status_code == 404
