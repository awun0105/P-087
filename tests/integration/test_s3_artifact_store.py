"""S3ObjectStore trên object store thật (MinIO/R2), bỏ qua khi không cấu hình.

Chạy local:
    docker run -d --rm --name r2s-minio-test -p 19000:9000 \\
        -e MINIO_ROOT_USER=r2stest -e MINIO_ROOT_PASSWORD=r2stest-secret minio/minio server /data
    R2S_TEST_S3_ENDPOINT=http://127.0.0.1:19000 R2S_TEST_S3_KEY=r2stest \\
        R2S_TEST_S3_SECRET=r2stest-secret pytest tests/integration/test_s3_artifact_store.py
"""

import os
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef
from src.services.orchestration.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactRemote,
    ArtifactResolver,
    FilesystemArtifactStore,
    S3ObjectStore,
    sha256_bytes,
)

ENDPOINT = os.environ.get("R2S_TEST_S3_ENDPOINT")
pytestmark = pytest.mark.skipif(ENDPOINT is None, reason="cần R2S_TEST_S3_ENDPOINT (MinIO/R2) để chạy")


@pytest.fixture
def store() -> S3ObjectStore:
    bucket = f"r2s-test-{uuid4().hex[:12]}"
    client_store = S3ObjectStore(
        bucket,
        endpoint_url=ENDPOINT,
        region="us-east-1",
        access_key_id=os.environ["R2S_TEST_S3_KEY"],
        secret_access_key=os.environ["R2S_TEST_S3_SECRET"],
    )
    client_store.client.create_bucket(Bucket=bucket)
    yield client_store
    objects = client_store.client.list_objects_v2(Bucket=bucket).get("Contents", [])
    for item in objects:
        client_store.client.delete_object(Bucket=bucket, Key=item["Key"])
    client_store.client.delete_bucket(Bucket=bucket)


def test_roundtrip_between_two_machines(tmp_path: Path, store: S3ObjectStore) -> None:
    payload = os.urandom(9 * 1024 * 1024)  # > ngưỡng multipart mặc định 8 MiB của boto3
    reference = ArtifactRef(
        artifact_type="video",
        schema_version="1.0",
        artifact_uri="artifact://jobs/upload-1/input/source.mp4",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.PRODUCT_INPUT,
        producer_stage="upload",
    )
    api = ArtifactResolver(tmp_path / "api", ArtifactRemote(store, "studio"))
    FilesystemArtifactStore(api).publish(reference, payload)

    head = store.head("studio/jobs/upload-1/input/source.mp4")
    assert head is not None and head.size_bytes == len(payload)
    assert head.checksum == reference.artifact_checksum

    gpu = ArtifactResolver(tmp_path / "gpu", ArtifactRemote(store, "studio"))
    assert gpu.require(reference).read_bytes() == payload

    link = api.remote.presign("jobs/upload-1/input/source.mp4", 60)
    with urllib.request.urlopen(link, timeout=10) as response:  # noqa: S310 - endpoint test cục bộ
        assert response.read() == payload


def test_sync_and_immutability(tmp_path: Path, store: S3ObjectStore) -> None:
    gpu = ArtifactResolver(tmp_path / "gpu", ArtifactRemote(store))
    job = tmp_path / "gpu/jobs/job-1"
    (job / "frames").mkdir(parents=True)
    (job / "frames/000001.jpg").write_bytes(b"frame")
    (job / "frames/.upload-partial").write_bytes(b"x")
    assert gpu.sync_up("job-1") == 1

    api = ArtifactResolver(tmp_path / "api", ArtifactRemote(store))
    assert api.sync_down("job-1") == 1
    assert (tmp_path / "api/jobs/job-1/frames/000001.jpg").read_bytes() == b"frame"

    other = tmp_path / "other.jpg"
    other.write_bytes(b"different")
    with pytest.raises(ArtifactAlreadyExistsError):
        gpu.remote.push("jobs/job-1/frames/000001.jpg", other)
