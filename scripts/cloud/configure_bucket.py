"""Cấu hình bucket kho file (Cloudflare R2/S3) cho upload thẳng từ trình duyệt.

    python -m scripts.cloud.configure_bucket --origin https://studio.example.vercel.app

- CORS: cho phép trình duyệt từ các origin của Web UI PUT từng phần và GET file.
- Lifecycle: tự hủy multipart upload bỏ dở sau 1 ngày (không tính tiền phần rác).

Đọc bucket/endpoint/key từ `ARTIFACT_S3_*` giống API; không in secret.
"""

import argparse

from botocore.exceptions import ClientError

from src.config import get_settings
from src.services.orchestration.artifacts import S3ObjectStore


def main(argv: list[str] | None = None) -> int:
    """Entry point; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origin", action="append", required=True, help="Origin của Web UI (lặp lại được)")
    parser.add_argument("--abort-multipart-days", type=int, default=1)
    args = parser.parse_args(argv)

    settings = get_settings()
    if (
        not settings.artifact_s3_bucket
        or not settings.artifact_s3_access_key_id
        or not settings.artifact_s3_secret_access_key
    ):
        parser.error("Cần ARTIFACT_S3_BUCKET, ARTIFACT_S3_ACCESS_KEY_ID, ARTIFACT_S3_SECRET_ACCESS_KEY")
    store = S3ObjectStore(
        settings.artifact_s3_bucket,
        endpoint_url=settings.artifact_s3_endpoint,
        region=settings.artifact_s3_region,
        access_key_id=settings.artifact_s3_access_key_id,
        secret_access_key=settings.artifact_s3_secret_access_key.get_secret_value(),
    )
    client, bucket = store.client, store.bucket
    status = 0
    try:
        client.put_bucket_cors(
            Bucket=bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": args.origin,
                        "AllowedMethods": ["GET", "HEAD", "PUT"],
                        "AllowedHeaders": ["*"],
                        "ExposeHeaders": ["ETag"],
                        "MaxAgeSeconds": 3600,
                    }
                ]
            },
        )
        print(f"CORS: cho phép {', '.join(args.origin)}")
    except ClientError as error:
        print(f"CORS: kho file không nhận cấu hình ({error.response['Error'].get('Code')}); cấu hình trong dashboard")
        status = 1
    try:
        client.put_bucket_lifecycle_configuration(
            Bucket=bucket,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": "abort-incomplete-multipart",
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": args.abort_multipart_days},
                    }
                ]
            },
        )
        print(f"Lifecycle: hủy multipart bỏ dở sau {args.abort_multipart_days} ngày")
    except ClientError as error:
        print(
            f"Lifecycle: kho file không nhận cấu hình ({error.response['Error'].get('Code')}); cấu hình trong dashboard"
        )
        status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
