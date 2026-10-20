"""T-070: cấp file bộ LOD theo checksum SOG nguồn — chỉ SOG thuộc allow-list, chỉ đúng tên file của bộ LOD."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_HEX = "f" * 64
_JOB = "job-fixture-001"
_BASE = f"/api/v1/jobs/{_JOB}/lod/{_HEX}"


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from src.api.product import deps as product_deps
    from src.models.contracts.artifacts import ArtifactRef
    from src.services.orchestration.artifacts.store import ArtifactNotFoundError
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    sog = ArtifactRef(
        artifact_type="GaussianSOG",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB}/rec04/scene.sog",
        artifact_checksum="sha256:" + _HEX,
        data_class="derived",
        producer_stage="ST-VISUAL-RECON",
        job_id=_JOB,
    )

    def authorized(job_id, checksum):
        if job_id == _JOB and checksum == sog.artifact_checksum:
            return sog
        raise ArtifactNotFoundError("not allowed")

    monkeypatch.setattr(registry, "authorized_sog_by_checksum", authorized)
    return registry


def _bundle(registry) -> None:
    from src.services.orchestration.artifacts import lod

    root = registry.runtime_resolver.artifact_root / lod.lod_relative_dir(_JOB, "sha256:" + _HEX)
    (root / "0_0").mkdir(parents=True)
    (root / "lod-meta.json").write_text('{"lodLevels":3}')
    (root / "0_0" / "meta.json").write_text("{}")
    (root / "0_0" / "means_l.webp").write_bytes(b"RIFFwebp")


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.mark.asyncio
async def test_serves_bundle_files_with_immutable_cache(client, isolated_registry) -> None:
    _bundle(isolated_registry)
    index = await client.get(f"{_BASE}/lod-meta.json")
    assert index.status_code == 200 and index.json() == {"lodLevels": 3}
    assert "immutable" in index.headers["cache-control"]
    chunk = await client.get(f"{_BASE}/0_0/means_l.webp")
    assert chunk.status_code == 200 and chunk.content == b"RIFFwebp"
    again = await client.get(
        f"{_BASE}/0_0/meta.json",
        headers={"If-None-Match": (await client.get(f"{_BASE}/0_0/meta.json")).headers["etag"]},
    )
    assert again.status_code == 304


@pytest.mark.asyncio
async def test_missing_bundle_is_404_and_not_cached(client, isolated_registry) -> None:
    r = await client.get(f"{_BASE}/lod-meta.json")
    assert r.status_code == 404
    assert "no-store" in r.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_sog_outside_allow_list_is_404(client, isolated_registry) -> None:
    _bundle(isolated_registry)
    r = await client.get(f"/api/v1/jobs/{_JOB}/lod/{'0' * 64}/lod-meta.json")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_only_bundle_file_names(client, isolated_registry) -> None:
    _bundle(isolated_registry)
    # `..` được client chuẩn hoá trước khi gửi; phía máy chủ chặn bằng `valid_bundle_path` (test riêng).
    for bad in ("0_0/x.png", "secret.json", "0_0/%2e%2e/meta.json", "0_0/sub/meta.json"):
        r = await client.get(f"{_BASE}/{bad}")
        assert r.status_code == 404, bad
    assert (await client.get(f"/api/v1/jobs/{_JOB}/lod/not-hex/lod-meta.json")).status_code == 404


@pytest.mark.asyncio
async def test_remote_store_redirects_chunks_and_serves_index_through_the_api(
    client, isolated_registry, monkeypatch
) -> None:
    from src.services.orchestration.artifacts import lod

    relative = lod.lod_relative_dir(_JOB, "sha256:" + _HEX)

    class Remote:
        def head(self, key):  # noqa: ANN001, ANN202
            return object() if key.startswith(relative) else None

        def presign(self, key, seconds):  # noqa: ANN001, ANN202
            return f"https://r2.example/{key}?sig=1"

        def fetch(self, key, destination):  # noqa: ANN001, ANN202
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text('{"lodLevels":3}')

    monkeypatch.setattr(isolated_registry.runtime_resolver, "remote", Remote())
    chunk = await client.get(f"{_BASE}/0_0/means_l.webp")
    assert chunk.status_code == 307 and chunk.headers["location"].startswith("https://r2.example/")
    index = await client.get(f"{_BASE}/lod-meta.json")
    assert index.status_code == 200 and index.json() == {"lodLevels": 3}
