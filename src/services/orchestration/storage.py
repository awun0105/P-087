"""Dựng artifact resolver runtime theo Settings: filesystem local, thêm kho file S3 nếu cấu hình."""

from functools import lru_cache

from src.config import Settings
from src.services.orchestration.artifacts import ArtifactRemote, ArtifactResolver, S3ObjectStore


@lru_cache(maxsize=4)
def _remote(
    bucket: str, endpoint: str | None, region: str, access_key_id: str, secret_access_key: str, prefix: str
) -> ArtifactRemote:
    # Một boto3 client cho mỗi cấu hình; client của boto3 dùng chung giữa thread được.
    store = S3ObjectStore(
        bucket,
        endpoint_url=endpoint,
        region=region,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )
    return ArtifactRemote(store, prefix)


def artifact_remote(settings: Settings) -> ArtifactRemote | None:
    """Kho file S3-compatible của deployment; `None` khi chạy chỉ filesystem (local/test)."""
    if not settings.artifact_s3_bucket:
        return None
    if settings.artifact_s3_access_key_id is None or settings.artifact_s3_secret_access_key is None:
        raise ValueError("ARTIFACT_S3_BUCKET cần access key và secret key")
    return _remote(
        settings.artifact_s3_bucket,
        settings.artifact_s3_endpoint,
        settings.artifact_s3_region,
        settings.artifact_s3_access_key_id,
        settings.artifact_s3_secret_access_key.get_secret_value(),
        settings.artifact_s3_prefix,
    )


def runtime_resolver(settings: Settings) -> ArtifactResolver:
    """Resolver cho artifact runtime (`ARTIFACT_ROOT` + kho file nếu có)."""
    return ArtifactResolver(settings.artifact_root, artifact_remote(settings))
