"""Upload thẳng qua API + MinIO thật: xin link → PUT từng phần → ghép → server tự kiểm.

Bỏ qua khi không có `R2S_TEST_S3_ENDPOINT` (xem `test_s3_artifact_store.py`).
"""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import Settings
from src.services.orchestration.artifacts import S3ObjectStore
from src.services.orchestration.uploads.direct import MIN_PART_BYTES

ENDPOINT = os.environ.get("R2S_TEST_S3_ENDPOINT")
pytestmark = pytest.mark.skipif(ENDPOINT is None, reason="cần R2S_TEST_S3_ENDPOINT (MinIO/R2) để chạy")


@pytest.fixture
def cloud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    from src.api.studio import deps

    bucket = f"r2s-test-{uuid4().hex[:12]}"
    admin = S3ObjectStore(
        bucket,
        endpoint_url=ENDPOINT,
        region="us-east-1",
        access_key_id=os.environ["R2S_TEST_S3_KEY"],
        secret_access_key=os.environ["R2S_TEST_S3_SECRET"],
    )
    admin.client.create_bucket(Bucket=bucket)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        artifact_root=tmp_path / "cache",
        artifact_s3_bucket=bucket,
        artifact_s3_endpoint=ENDPOINT,
        artifact_s3_region="us-east-1",
        artifact_s3_access_key_id=os.environ["R2S_TEST_S3_KEY"],
        artifact_s3_secret_access_key=os.environ["R2S_TEST_S3_SECRET"],
        product_upload_max_bytes=64 * 1024 * 1024,
    )
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    yield settings
    for item in admin.client.list_objects_v2(Bucket=bucket).get("Contents", []):
        admin.client.delete_object(Bucket=bucket, Key=item["Key"])
    for upload in admin.client.list_multipart_uploads(Bucket=bucket).get("Uploads", []):
        admin.client.abort_multipart_upload(Bucket=bucket, Key=upload["Key"], UploadId=upload["UploadId"])
    admin.client.delete_bucket(Bucket=bucket)


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_browser_style_direct_upload(client: AsyncClient, cloud: Settings) -> None:
    assert (await client.get("/api/v1/uploads/config")).json()["direct"] is True
    payload = os.urandom(MIN_PART_BYTES + 4096)

    begun = await client.post("/api/v1/uploads/direct", json={"filename": "kho.mp4", "size_bytes": len(payload)})
    assert begun.status_code == 201, begun.text
    state = begun.json()
    upload_id, part_size = state["upload_id"], state["part_size"]
    assert state["part_count"] == 2 and "multipart_id" not in state

    urls = (await client.post(f"/api/v1/uploads/direct/{upload_id}/urls", json={"part_numbers": [1, 2]})).json()
    with httpx.Client(timeout=30) as storage:
        # Chỉ đẩy phần 1 trước để kiểm tra nối lại (resume) thấy đúng phần đã lên.
        first = storage.put(urls["urls"]["1"], content=payload[:part_size])
        assert first.status_code == 200
        # Link đã ký kích thước: PUT to hơn phần khai báo bị kho file từ chối.
        oversized = storage.put(urls["urls"]["2"], content=payload[part_size:] + b"extra")
        assert oversized.status_code == 403
        resumed = (await client.get(f"/api/v1/uploads/direct/{upload_id}")).json()
        assert resumed["uploaded_parts"] == [1]
        assert storage.put(urls["urls"]["2"], content=payload[part_size:]).status_code == 200

    completed = await client.post(f"/api/v1/uploads/direct/{upload_id}/complete")
    assert completed.status_code == 200, completed.text

    final = (await client.get(f"/api/v1/uploads/direct/{upload_id}")).json()
    assert final["status"] == "READY", final
    listed = (await client.get("/api/v1/uploads")).json()["uploads"]
    assert listed[0]["upload_id"] == upload_id
    assert listed[0]["checksum"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert listed[0]["size_bytes"] == len(payload)


@pytest.mark.asyncio
async def test_lying_about_size_is_rejected(client: AsyncClient, cloud: Settings) -> None:
    """Khai 5000 byte nhưng gửi 5 byte: link đã ký kích thước nên kho file từ chối ngay khi PUT."""
    begun = (await client.post("/api/v1/uploads/direct", json={"filename": "kho.mp4", "size_bytes": 5000})).json()
    upload_id = begun["upload_id"]
    url = (await client.post(f"/api/v1/uploads/direct/{upload_id}/urls", json={"part_numbers": [1]})).json()["urls"]
    with httpx.Client(timeout=30) as storage:
        assert storage.put(url["1"], content=b"short").status_code == 403
    completed = await client.post(f"/api/v1/uploads/direct/{upload_id}/complete")
    assert completed.status_code == 422  # thiếu phần → không ghép
    assert (await client.get("/api/v1/uploads")).json()["uploads"] == []
