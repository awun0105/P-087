"""T-068: bản xem nhanh của SOG (≤500k splat, màu bậc 0) tạo nền trên API, đệm theo checksum; scene nhỏ không cần bản nhẹ."""

import json
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_JOB = "/api/v1/jobs/job-fixture-001"
_URI = "artifact://jobs/job-fixture-001/rec04/scene.sog"
_CHECKSUM = "sha256:" + "e" * 64
_PARAMS = {"artifact_uri": _URI, "artifact_checksum": _CHECKSUM}


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from src.api.product import deps as product_deps
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    return registry


def _sog(path, count: int):
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("meta.json", json.dumps({"version": 2, "count": count}))
    return path


@pytest.fixture
def scene_sog(tmp_path, isolated_registry, monkeypatch):
    from src.services.orchestration.artifacts import compact_gaussians, quick_sog

    state = {"count": 1_860_000, "converted": 0, "fail": False}
    source = tmp_path / "scene.sog"
    real_authorized = isolated_registry.authorized_artifact

    def authorized(job_id, reference):
        if reference.artifact_uri == _URI and reference.artifact_checksum == _CHECKSUM:
            return reference
        return real_authorized(job_id, reference)

    def resolve(job_id, reference):
        authorized(job_id, reference)
        return _sog(source, state["count"])

    def convert(cli, source_path, output, scratch):
        state["converted"] += 1
        if state["fail"]:
            raise quick_sog.QuickSogError("boom")
        output.write_bytes(b"quick-sog")

    monkeypatch.setattr(isolated_registry, "authorized_artifact", authorized)
    monkeypatch.setattr(isolated_registry, "resolve_artifact", resolve)
    monkeypatch.setattr(quick_sog, "_convert", convert)
    monkeypatch.setattr(compact_gaussians, "compact_cli", lambda: tmp_path / "cli.mjs")
    # Chạy việc nền ngay trong luồng gọi để test xác định.
    monkeypatch.setattr(quick_sog, "_spawn", lambda work: work())
    return state


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.mark.asyncio
async def test_large_scene_builds_quick_view_then_serves_it(client, scene_sog) -> None:
    missing = await client.get(f"{_JOB}/artifacts/quick", params=_PARAMS)
    assert missing.status_code == 404
    status = await client.get(f"{_JOB}/artifacts/quick/status", params=_PARAMS)
    assert status.json() == {"state": "ready"}
    assert "no-store" in status.headers["cache-control"]
    served = await client.get(f"{_JOB}/artifacts/quick", params=_PARAMS)
    assert served.status_code == 200
    assert served.content == b"quick-sog"
    assert "immutable" in served.headers["cache-control"]
    await client.get(f"{_JOB}/artifacts/quick/status", params=_PARAMS)
    assert scene_sog["converted"] == 1


@pytest.mark.asyncio
async def test_small_scene_needs_no_quick_view(client, scene_sog) -> None:
    scene_sog["count"] = 290_000
    status = await client.get(f"{_JOB}/artifacts/quick/status", params=_PARAMS)
    assert status.json() == {"state": "unavailable"}
    assert scene_sog["converted"] == 0


@pytest.mark.asyncio
async def test_failed_build_is_unavailable(client, scene_sog) -> None:
    scene_sog["fail"] = True
    status = await client.get(f"{_JOB}/artifacts/quick/status", params=_PARAMS)
    assert status.json() == {"state": "unavailable"}
    again = await client.get(f"{_JOB}/artifacts/quick/status", params=_PARAMS)
    assert again.json() == {"state": "unavailable"}
    assert scene_sog["converted"] == 1


@pytest.mark.asyncio
async def test_quick_view_requires_allow_list(client, scene_sog) -> None:
    params = {
        "artifact_uri": "artifact://jobs/job-fixture-001/evaluation_only/groundtruth_map.mock",
        "artifact_checksum": "sha256:" + "0" * 64,
    }
    assert (await client.get(f"{_JOB}/artifacts/quick/status", params=params)).status_code == 404
    assert (await client.get(f"{_JOB}/artifacts/quick", params=params)).status_code == 404


@pytest.mark.asyncio
async def test_missing_runtime_is_unavailable(client, scene_sog, monkeypatch) -> None:
    from src.services.orchestration.artifacts import compact_gaussians

    monkeypatch.setattr(compact_gaussians, "compact_cli", lambda: None)
    status = await client.get(f"{_JOB}/artifacts/quick/status", params=_PARAMS)
    assert status.json() == {"state": "unavailable"}
