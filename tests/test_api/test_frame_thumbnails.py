"""T-066: ảnh frame thu nhỏ — JPEG nhỏ, kiểm allow-list như route content, đệm đĩa, 304, chỉ ba cỡ rộng."""

import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

_JOB = "/api/v1/jobs/job-fixture-001"
_URI = "artifact://jobs/job-fixture-001/frames/frame_0001.png"
_CHECKSUM = "sha256:" + "b" * 64


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from src.api.product import deps as product_deps
    from src.services.orchestration.artifacts import thumbnails
    from src.services.orchestration.projects.registry import ProjectRegistry

    thumbnails.clear_memory()
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    return registry


@pytest.fixture
def frame(tmp_path, isolated_registry, monkeypatch):
    """Một PNG 3000×2000 coi như nằm trong allow-list của job."""
    path = tmp_path / "frame.png"
    Image.new("RGB", (3000, 2000), (200, 120, 40)).save(path)
    real_authorized = isolated_registry.authorized_artifact

    def authorized(job_id, reference):
        if reference.artifact_uri == _URI and reference.artifact_checksum == _CHECKSUM:
            return reference
        return real_authorized(job_id, reference)

    resolved: list[int] = []

    def resolve(job_id, reference):
        authorized(job_id, reference)
        resolved.append(1)
        return path

    monkeypatch.setattr(isolated_registry, "authorized_artifact", authorized)
    monkeypatch.setattr(isolated_registry, "resolve_artifact", resolve)
    return resolved


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _params(width: int = 320) -> dict[str, str | int]:
    return {"artifact_uri": _URI, "artifact_checksum": _CHECKSUM, "width": width}


@pytest.mark.asyncio
async def test_thumbnail_is_small_jpeg(client, frame) -> None:
    r = await client.get(f"{_JOB}/frames/thumbnail", params=_params())
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert "immutable" in r.headers["cache-control"] and "private" in r.headers["cache-control"]
    image = Image.open(io.BytesIO(r.content))
    assert image.format == "JPEG"
    assert image.size == (320, 213)
    assert len(r.content) < 50_000


@pytest.mark.asyncio
async def test_thumbnail_requires_allow_list(client, frame) -> None:
    r = await client.get(
        f"{_JOB}/frames/thumbnail",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/evaluation_only/groundtruth_map.mock",
            "artifact_checksum": "sha256:" + "0" * 64,
            "width": 320,
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_cached_on_disk(client, frame, monkeypatch) -> None:
    first = await client.get(f"{_JOB}/frames/thumbnail", params=_params())
    assert first.status_code == 200

    from src.services.orchestration.artifacts import thumbnails

    def never(*args, **kwargs):
        raise AssertionError("cached thumbnail must not be rebuilt")

    monkeypatch.setattr(thumbnails, "_render_jpeg", never)
    thumbnails.clear_memory()
    second = await client.get(f"{_JOB}/frames/thumbnail", params=_params())
    assert second.status_code == 200
    assert second.content == first.content


@pytest.mark.asyncio
async def test_thumbnail_304(client, frame) -> None:
    first = await client.get(f"{_JOB}/frames/thumbnail", params=_params())
    resolved = len(frame)
    again = await client.get(
        f"{_JOB}/frames/thumbnail", params=_params(), headers={"If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304
    assert len(frame) == resolved


@pytest.mark.asyncio
async def test_invalid_width_rejected(client, frame) -> None:
    r = await client.get(f"{_JOB}/frames/thumbnail", params=_params(width=999))
    assert r.status_code == 422
