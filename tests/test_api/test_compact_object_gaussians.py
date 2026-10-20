"""T-067: Gaussian của vật phục vụ dạng PLY nén (tạo lười, đệm theo checksum); lỗi hoặc thiếu runtime thì về PLY gốc."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_JOB = "/api/v1/jobs/job-fixture-001"
_URI = "artifact://jobs/job-fixture-001/scene/objects/abc.ply"
_CHECKSUM = "sha256:" + "c" * 64


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from src.api.product import deps as product_deps
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    return registry


@pytest.fixture
def object_ply(tmp_path, isolated_registry, monkeypatch):
    """Một PLY Gaussian của vật trong allow-list; `kind` đổi được để thử loại artifact khác."""
    from src.services.orchestration.artifacts import compact_gaussians

    source = tmp_path / "object.ply"
    source.write_bytes(b"ply\nformat binary_little_endian 1.0\nend_header\n" + b"\0" * 1000)
    state = {"kind": "ObjectGaussians", "converted": 0}
    real_authorized = isolated_registry.authorized_artifact

    def authorized(job_id, reference):
        if reference.artifact_uri == _URI and reference.artifact_checksum == _CHECKSUM:
            return reference.model_copy(update={"artifact_type": state["kind"]})
        return real_authorized(job_id, reference)

    def resolve(job_id, reference):
        authorized(job_id, reference)
        return source

    def convert(cli, source_path, output):
        state["converted"] += 1
        output.write_bytes(b"compressed:" + source_path.read_bytes()[:10])

    monkeypatch.setattr(isolated_registry, "authorized_artifact", authorized)
    monkeypatch.setattr(isolated_registry, "resolve_artifact", resolve)
    monkeypatch.setattr(compact_gaussians, "_convert", convert)
    monkeypatch.setattr(compact_gaussians, "compact_cli", lambda: tmp_path / "cli.mjs")
    return state


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


_PARAMS = {"artifact_uri": _URI, "artifact_checksum": _CHECKSUM}


@pytest.mark.asyncio
async def test_compact_ply_is_served_and_cached(client, object_ply) -> None:
    first = await client.get(f"{_JOB}/objects/compact", params=_PARAMS)
    assert first.status_code == 200
    assert first.content.startswith(b"compressed:")
    assert "immutable" in first.headers["cache-control"]
    second = await client.get(f"{_JOB}/objects/compact", params=_PARAMS)
    assert second.content == first.content
    assert object_ply["converted"] == 1


@pytest.mark.asyncio
async def test_compact_304_skips_conversion(client, object_ply) -> None:
    first = await client.get(f"{_JOB}/objects/compact", params=_PARAMS)
    again = await client.get(
        f"{_JOB}/objects/compact", params=_PARAMS, headers={"If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304


@pytest.mark.asyncio
async def test_compact_requires_allow_list(client, object_ply) -> None:
    r = await client.get(
        f"{_JOB}/objects/compact",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/evaluation_only/groundtruth_map.mock",
            "artifact_checksum": "sha256:" + "0" * 64,
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_compact_only_for_object_gaussians(client, object_ply) -> None:
    object_ply["kind"] = "GaussianSOG"
    r = await client.get(f"{_JOB}/objects/compact", params=_PARAMS)
    assert r.status_code == 404
    assert object_ply["converted"] == 0


@pytest.mark.asyncio
async def test_failure_redirects_to_original(client, object_ply, monkeypatch) -> None:
    from src.services.orchestration.artifacts import compact_gaussians

    def broken(cli, source_path, output):
        raise compact_gaussians.CompactConversionError("boom")

    monkeypatch.setattr(compact_gaussians, "_convert", broken)
    r = await client.get(f"{_JOB}/objects/compact", params=_PARAMS)
    assert r.status_code == 307
    assert "/artifacts/content" in r.headers["location"]
    assert "no-store" in r.headers["cache-control"]


@pytest.mark.asyncio
async def test_missing_runtime_redirects_to_original(client, object_ply, monkeypatch) -> None:
    from src.services.orchestration.artifacts import compact_gaussians

    monkeypatch.setattr(compact_gaussians, "compact_cli", lambda: None)
    r = await client.get(f"{_JOB}/objects/compact", params=_PARAMS)
    assert r.status_code == 307
    assert object_ply["converted"] == 0


_LOCAL_CLI = "data/reconstruction_runtime/node_modules/@playcanvas/splat-transform/bin/cli.mjs"


def test_real_conversion_shrinks_an_object(tmp_path) -> None:
    """Chạy splat-transform thật trên một PLY vật có sẵn ở máy dev; bỏ qua khi không có runtime hoặc dữ liệu."""
    from pathlib import Path

    from src.services.orchestration.artifacts import compact_gaussians

    cli = compact_gaussians.compact_cli() or (Path(_LOCAL_CLI) if Path(_LOCAL_CLI).is_file() else None)
    sources = sorted(Path("data/studio_local/artifacts/jobs").glob("*/scene/objects/*.ply"))
    if cli is None or not sources:
        pytest.skip("splat-transform runtime or local object PLY not available")
    source = min(sources, key=lambda path: path.stat().st_size)
    path = compact_gaussians.get_compact(tmp_path, "sha256:" + "d" * 64, lambda: source, cli)
    assert path.stat().st_size < source.stat().st_size
    assert path.read_bytes().startswith(b"ply")
