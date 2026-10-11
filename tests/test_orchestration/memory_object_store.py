"""Object store in-memory cùng giao diện `ObjectStore` cho unit test (không phải test)."""

import hashlib
from pathlib import Path
from uuid import uuid4

from src.services.orchestration.artifacts import RemoteObject, UploadedPart


class MemoryObjectStore:
    """key → (bytes, checksum metadata); multipart giữ các phần tới khi ghép."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}
        self.multiparts: dict[str, tuple[str, dict[int, bytes]]] = {}
        self.puts = 0

    def head(self, key: str) -> RemoteObject | None:
        if key not in self.objects:
            return None
        payload, checksum = self.objects[key]
        return RemoteObject(key=key, size_bytes=len(payload), checksum=checksum)

    def put_file(self, key: str, path: Path, checksum: str) -> None:
        self.puts += 1
        self.objects[key] = (path.read_bytes(), checksum)

    def get_file(self, key: str, destination: Path) -> None:
        destination.write_bytes(self.objects[key][0])

    def list_objects(self, prefix: str) -> list[RemoteObject]:
        return [
            RemoteObject(key=key, size_bytes=len(payload))
            for key, (payload, _) in sorted(self.objects.items())
            if key.startswith(prefix)
        ]

    def presign_get(self, key: str, expires_seconds: int) -> str:
        return f"https://store.invalid/{key}?expires={expires_seconds}"

    def create_multipart(self, key: str, content_type: str) -> str:
        multipart_id = uuid4().hex
        self.multiparts[multipart_id] = (key, {})
        return multipart_id

    def presign_part(
        self, key: str, multipart_id: str, part_number: int, expires_seconds: int, content_length: int
    ) -> str:
        return f"https://store.invalid/{key}?upload={multipart_id}&part={part_number}&length={content_length}"

    def upload_part(self, multipart_id: str, part_number: int, payload: bytes) -> str:
        """Thay cho PUT của trình duyệt; trả ETag."""
        self.multiparts[multipart_id][1][part_number] = payload
        return f'"{hashlib.md5(payload).hexdigest()}"'  # noqa: S324 - ETag kiểu S3, không phải bảo mật

    def list_parts(self, key: str, multipart_id: str) -> list[UploadedPart]:
        parts = self.multiparts[multipart_id][1]
        return [
            UploadedPart(part_number=number, etag=f'"{hashlib.md5(data).hexdigest()}"', size_bytes=len(data))  # noqa: S324
            for number, data in sorted(parts.items())
        ]

    def complete_multipart(self, key: str, multipart_id: str, parts: list[tuple[int, str]]) -> None:
        stored = self.multiparts.pop(multipart_id)[1]
        self.objects[key] = (b"".join(stored[number] for number, _ in parts), None)

    def abort_multipart(self, key: str, multipart_id: str) -> None:
        self.multiparts.pop(multipart_id, None)

    def digest(self, key: str) -> tuple[str, int]:
        payload = self.objects[key][0]
        return f"sha256:{hashlib.sha256(payload).hexdigest()}", len(payload)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def read_range(self, key: str, start: int, length: int) -> bytes:
        return self.objects[key][0][start : start + length]
