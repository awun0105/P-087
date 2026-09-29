"""Kho file S3-compatible đứng sau `ArtifactResolver` (ADR 0003, Contract §7.4 amendment).

Filesystem vẫn là cache cục bộ trên mỗi máy (API, GPU worker); lớp này chỉ đồng bộ
cache với object store theo đúng key logical `jobs/<namespace>/<path>`. Bucket,
endpoint và presigned URL không bao giờ đi vào contract.

Bất biến giữ nguyên như filesystem store:

- object đã publish không bị ghi đè: key đã có với checksum khác → `ArtifactAlreadyExistsError`;
- tải về ghi vào file tạm cùng thư mục rồi `os.link`, lỗi không để lại file dở;
- checksum SHA-256 lưu trong metadata object và được kiểm khi tải về.
"""

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from src.services.orchestration.artifacts.checksum import sha256_file
from src.services.orchestration.artifacts.errors import (
    ArtifactAlreadyExistsError,
    ArtifactChecksumError,
    ArtifactNotFoundError,
)

logger = logging.getLogger(__name__)

#: Metadata S3 (`x-amz-meta-sha256`) giữ checksum có prefix `sha256:`.
CHECKSUM_METADATA_KEY = "sha256"


class RemoteObject(BaseModel):
    """Thông tin tối thiểu của một object để quyết định đồng bộ."""

    model_config = ConfigDict(frozen=True)

    key: str
    size_bytes: int
    checksum: str | None = None


class UploadedPart(BaseModel):
    """Một phần của multipart upload đã lên kho file."""

    model_config = ConfigDict(frozen=True)

    part_number: int
    etag: str
    size_bytes: int


class ObjectStore(Protocol):
    """Phần API object store hệ thống cần; test dùng bản in-memory cùng giao diện."""

    def head(self, key: str) -> RemoteObject | None:
        """Metadata của object, `None` nếu không tồn tại."""
        ...

    def put_file(self, key: str, path: Path, checksum: str) -> None:
        """Upload file cục bộ kèm checksum trong metadata."""
        ...

    def get_file(self, key: str, destination: Path) -> None:
        """Tải object về đúng đường dẫn `destination` (đã là file tạm do caller tạo)."""
        ...

    def list_objects(self, prefix: str) -> list[RemoteObject]:
        """Liệt kê object theo prefix (không cần metadata checksum)."""
        ...

    def presign_get(self, key: str, expires_seconds: int) -> str:
        """Link tải có hạn cho trình duyệt; không lưu vào contract."""
        ...

    def create_multipart(self, key: str, content_type: str) -> str:
        """Mở multipart upload cho trình duyệt; trả upload id của kho file."""
        ...

    def presign_part(self, key: str, multipart_id: str, part_number: int, expires_seconds: int) -> str:
        """Link PUT có hạn cho một phần."""
        ...

    def list_parts(self, key: str, multipart_id: str) -> list[UploadedPart]:
        """Các phần đã lên (để nối lại upload khi rớt mạng)."""
        ...

    def complete_multipart(self, key: str, multipart_id: str, parts: list[tuple[int, str]]) -> None:
        """Ghép các phần theo (part_number, etag) thành object."""
        ...

    def abort_multipart(self, key: str, multipart_id: str) -> None:
        """Hủy multipart, xóa các phần đã lên."""
        ...

    def digest(self, key: str) -> tuple[str, int]:
        """SHA-256 (`sha256:`) và kích thước tính theo stream, không giữ cả file trong RAM."""
        ...

    def delete(self, key: str) -> None:
        """Xóa object (chỉ dùng cho upload bị từ chối khi kiểm tra)."""
        ...


class ArtifactRemote:
    """Đồng bộ cache filesystem ↔ object store theo key logical `jobs/...`."""

    def __init__(self, store: ObjectStore, prefix: str = "") -> None:
        cleaned = prefix.strip("/")
        self.store = store
        self.prefix = f"{cleaned}/" if cleaned else ""

    def key(self, relative: str) -> str:
        """Key object của một đường dẫn tương đối `jobs/<ns>/<path>`."""
        return self.prefix + relative

    def fetch(self, relative: str, destination: Path, expected_checksum: str | None = None) -> None:
        """Tải object về cache cục bộ một cách atomic; thiếu object → ArtifactNotFoundError.

        Kiểm checksum theo reference nếu caller truyền, không thì theo metadata object.
        """
        remote = self.store.head(self.key(relative))
        if remote is None:
            raise ArtifactNotFoundError(f"artifact does not exist: {relative}")
        expected = expected_checksum or remote.checksum
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent, prefix=".fetch-")
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            self.store.get_file(self.key(relative), temporary)
            if expected is not None:
                observed = sha256_file(temporary)
                if observed != expected:
                    raise ArtifactChecksumError(f"checksum mismatch: expected {expected}, observed {observed}")
            try:
                os.link(temporary, destination)
            except FileExistsError:
                # Tiến trình khác vừa tải cùng artifact; bytes bất biến nên dùng bản đã có.
                logger.debug("Artifact đã có trong cache: %s", relative)
        finally:
            temporary.unlink(missing_ok=True)

    def push(self, relative: str, path: Path) -> None:
        """Đẩy một artifact đã publish cục bộ; idempotent nếu object đã có cùng checksum."""
        checksum = sha256_file(path)
        existing = self.store.head(self.key(relative))
        if existing is not None:
            if existing.checksum == checksum:
                return
            raise ArtifactAlreadyExistsError(f"artifact already exists with other bytes: {relative}")
        self.store.put_file(self.key(relative), path, checksum)

    def push_tree(self, relative_dir: str, local_dir: Path) -> int:
        """Đẩy mọi file đã publish trong một namespace; bỏ file tạm (tên bắt đầu bằng `.`).

        So theo danh sách object một lần; object đã có cùng kích thước được coi là đã
        đồng bộ vì artifact bất biến. Trả số file vừa upload.
        """
        if not local_dir.is_dir():
            return 0
        remote_sizes = {item.key: item.size_bytes for item in self.store.list_objects(self.key(relative_dir))}
        pushed = 0
        for path in sorted(local_dir.rglob("*")):
            relative_path = path.relative_to(local_dir)
            if not path.is_file() or any(part.startswith(".") for part in relative_path.parts):
                continue
            relative = f"{relative_dir.rstrip('/')}/{relative_path.as_posix()}"
            size = remote_sizes.get(self.key(relative))
            if size is not None:
                if size != path.stat().st_size:
                    raise ArtifactAlreadyExistsError(f"artifact already exists with other bytes: {relative}")
                continue
            self.store.put_file(self.key(relative), path, sha256_file(path))
            pushed += 1
        return pushed

    def pull_tree(self, relative_dir: str, local_dir: Path) -> int:
        """Tải mọi object của một namespace còn thiếu trong cache. Trả số file vừa tải."""
        prefix = self.key(relative_dir.rstrip("/") + "/")
        pulled = 0
        for item in self.store.list_objects(prefix):
            relative_path = item.key.removeprefix(prefix)
            if not relative_path or any(part in {"", ".", ".."} for part in relative_path.split("/")):
                continue
            destination = local_dir / relative_path
            if destination.is_file():
                continue
            self.fetch(item.key.removeprefix(self.prefix), destination)
            pulled += 1
        return pulled

    def presign(self, relative: str, expires_seconds: int) -> str:
        """Link tải có hạn cho trình duyệt."""
        return self.store.presign_get(self.key(relative), expires_seconds)

    # --- upload thẳng từ trình duyệt (multipart) ---------------------------

    def begin_upload(self, relative: str, content_type: str) -> str:
        """Mở multipart cho một artifact chưa tồn tại; key đã có thì từ chối (bất biến)."""
        if self.store.head(self.key(relative)) is not None:
            raise ArtifactAlreadyExistsError(f"artifact already exists: {relative}")
        return self.store.create_multipart(self.key(relative), content_type)

    def part_url(self, relative: str, multipart_id: str, part_number: int, expires_seconds: int) -> str:
        """Link PUT có hạn cho một phần."""
        return self.store.presign_part(self.key(relative), multipart_id, part_number, expires_seconds)

    def uploaded_parts(self, relative: str, multipart_id: str) -> list[UploadedPart]:
        """Các phần đã lên kho file."""
        return self.store.list_parts(self.key(relative), multipart_id)

    def complete_upload(self, relative: str, multipart_id: str, parts: list[tuple[int, str]]) -> None:
        """Ghép multipart thành object."""
        self.store.complete_multipart(self.key(relative), multipart_id, parts)

    def abort_upload(self, relative: str, multipart_id: str) -> None:
        """Hủy multipart dở."""
        self.store.abort_multipart(self.key(relative), multipart_id)

    def digest(self, relative: str) -> tuple[str, int]:
        """Checksum + kích thước object do server tự tính (không tin client)."""
        return self.store.digest(self.key(relative))

    def delete(self, relative: str) -> None:
        """Xóa object bị từ chối sau kiểm tra."""
        self.store.delete(self.key(relative))


class S3ObjectStore:
    """Object store qua boto3 cho Cloudflare R2, MinIO hoặc S3."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            # R2/MinIO dùng path-style ổn định hơn virtual-host với endpoint tùy biến.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 5}),
        )

    def head(self, key: str) -> RemoteObject | None:
        """HEAD object; 404 → None, lỗi khác giữ nguyên để caller thấy."""
        from botocore.exceptions import ClientError

        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        metadata = response.get("Metadata", {})
        return RemoteObject(key=key, size_bytes=response["ContentLength"], checksum=metadata.get(CHECKSUM_METADATA_KEY))

    def put_file(self, key: str, path: Path, checksum: str) -> None:
        """Managed upload (tự multipart với file lớn), checksum trong metadata."""
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs={"Metadata": {CHECKSUM_METADATA_KEY: checksum}})

    def get_file(self, key: str, destination: Path) -> None:
        """Managed download vào file tạm do caller cấp."""
        self.client.download_file(self.bucket, key, str(destination))

    def list_objects(self, prefix: str) -> list[RemoteObject]:
        """Liệt kê theo trang; không lấy metadata để tránh một HEAD mỗi object."""
        paginator = self.client.get_paginator("list_objects_v2")
        items: list[RemoteObject] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for entry in page.get("Contents", []):
                items.append(RemoteObject(key=entry["Key"], size_bytes=entry["Size"]))
        return items

    def presign_get(self, key: str, expires_seconds: int) -> str:
        """Presigned GET cho trình duyệt tải thẳng từ kho file."""
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_seconds
        )

    def create_multipart(self, key: str, content_type: str) -> str:
        """CreateMultipartUpload."""
        response = self.client.create_multipart_upload(Bucket=self.bucket, Key=key, ContentType=content_type)
        return response["UploadId"]

    def presign_part(self, key: str, multipart_id: str, part_number: int, expires_seconds: int) -> str:
        """Presigned UploadPart (PUT)."""
        return self.client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": self.bucket, "Key": key, "UploadId": multipart_id, "PartNumber": part_number},
            ExpiresIn=expires_seconds,
        )

    def list_parts(self, key: str, multipart_id: str) -> list[UploadedPart]:
        """ListParts theo trang."""
        paginator = self.client.get_paginator("list_parts")
        parts: list[UploadedPart] = []
        for page in paginator.paginate(Bucket=self.bucket, Key=key, UploadId=multipart_id):
            for entry in page.get("Parts", []):
                parts.append(
                    UploadedPart(part_number=entry["PartNumber"], etag=entry["ETag"], size_bytes=entry["Size"])
                )
        return parts

    def complete_multipart(self, key: str, multipart_id: str, parts: list[tuple[int, str]]) -> None:
        """CompleteMultipartUpload."""
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=multipart_id,
            MultipartUpload={"Parts": [{"PartNumber": number, "ETag": etag} for number, etag in parts]},
        )

    def abort_multipart(self, key: str, multipart_id: str) -> None:
        """AbortMultipartUpload."""
        self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=multipart_id)

    def digest(self, key: str) -> tuple[str, int]:
        """Đọc object theo chunk để tính SHA-256."""
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        hasher = hashlib.sha256()
        size = 0
        for chunk in body.iter_chunks(chunk_size=8 * 1024 * 1024):
            hasher.update(chunk)
            size += len(chunk)
        return f"sha256:{hasher.hexdigest()}", size

    def delete(self, key: str) -> None:
        """DeleteObject."""
        self.client.delete_object(Bucket=self.bucket, Key=key)
