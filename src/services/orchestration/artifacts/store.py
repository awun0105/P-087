"""Filesystem-backed implementation of the logical artifact store.

Khi có `ArtifactRemote` (kho file S3-compatible, ADR 0003), filesystem là cache cục bộ:
đọc artifact chưa có thì tải về và kiểm checksum, publish xong thì đẩy lên kho file.
"""

import hashlib
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.models.contracts.artifacts import ArtifactRef
from src.services.orchestration.artifacts.checksum import sha256_bytes, verify_file_checksum
from src.services.orchestration.artifacts.errors import (
    ArtifactAlreadyExistsError,
    ArtifactNotFoundError,
    ArtifactSchemaError,
    ArtifactTooLargeError,
    InvalidArtifactUriError,
)
from src.services.orchestration.artifacts.remote import ArtifactRemote

ContractT = TypeVar("ContractT", bound=BaseModel)
_URI_PREFIX = "artifact://jobs/"


class ArtifactResolver:
    """Map logical artifact URIs into one configured filesystem root."""

    def __init__(self, artifact_root: Path, remote: ArtifactRemote | None = None) -> None:
        self.artifact_root = artifact_root.expanduser().resolve()
        self.remote = remote

    def resolve(self, artifact_uri: str) -> Path:
        """Resolve one safe logical URI without allowing path traversal."""
        relative = self._parse_relative_path(artifact_uri)
        resolved = (self.artifact_root / relative).resolve()
        if not resolved.is_relative_to(self.artifact_root):
            raise InvalidArtifactUriError("artifact URI escapes ARTIFACT_ROOT")
        return resolved

    def require(self, reference: ArtifactRef) -> Path:
        """Resolve, assert existence and verify checksum for a reference."""
        return self.require_uri(reference.artifact_uri, reference.artifact_checksum)

    def require_uri(self, artifact_uri: str, checksum: str) -> Path:
        """Như `require` nhưng nhận URI + checksum (vd `InputFile` của InputManifest)."""
        path = self.resolve(artifact_uri)
        if not path.is_file() and self.remote is not None:
            self.remote.fetch(self.relative_key(artifact_uri), path, checksum)
        if not path.is_file():
            raise ArtifactNotFoundError(f"artifact does not exist: {artifact_uri}")
        verify_file_checksum(path, checksum)
        return path

    def relative_key(self, artifact_uri: str) -> str:
        """Key logical `jobs/<namespace>/<path>` dùng chung giữa filesystem và kho file."""
        return self._parse_relative_path(artifact_uri).as_posix()

    def published(self, artifact_uri: str) -> None:
        """Hook sau khi publish cục bộ: đẩy artifact lên kho file nếu có."""
        if self.remote is not None:
            self.remote.push(self.relative_key(artifact_uri), self.resolve(artifact_uri))

    def sync_down(self, namespace: str) -> int:
        """Tải các artifact còn thiếu của một namespace `jobs/<namespace>` từ kho file."""
        if self.remote is None:
            return 0
        relative = self._namespace_dir(namespace)
        return self.remote.pull_tree(relative, self.artifact_root / relative)

    def sync_up(self, namespace: str) -> int:
        """Đẩy mọi artifact đã publish cục bộ của một namespace lên kho file."""
        if self.remote is None:
            return 0
        relative = self._namespace_dir(namespace)
        return self.remote.push_tree(relative, self.artifact_root / relative)

    @staticmethod
    def _namespace_dir(namespace: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", namespace) is None:
            raise InvalidArtifactUriError("artifact namespace không hợp lệ")
        return f"jobs/{namespace}"

    def load_model(self, reference: ArtifactRef, model_type: type[ContractT]) -> ContractT:
        """Load JSON and enforce the target Pydantic contract/schema version."""
        path = self.require(reference)
        try:
            return model_type.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, ValueError) as error:
            raise ArtifactSchemaError(f"invalid {model_type.__name__}: {error}") from error

    @staticmethod
    def _parse_relative_path(artifact_uri: str) -> PurePosixPath:
        if not artifact_uri.startswith(_URI_PREFIX) or "\\" in artifact_uri:
            raise InvalidArtifactUriError("artifact URI must use artifact://jobs/<job>/<path>")
        raw_path = artifact_uri.removeprefix(_URI_PREFIX)
        path = PurePosixPath(raw_path)
        raw_parts = raw_path.split("/")
        if len(path.parts) < 2 or any(part in {"", ".", ".."} for part in raw_parts):
            raise InvalidArtifactUriError("artifact URI contains an unsafe path")
        if raw_path.startswith("/") or "//" in raw_path:
            raise InvalidArtifactUriError("artifact URI contains an unsafe path")
        if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part) is None for part in raw_parts):
            raise InvalidArtifactUriError("artifact URI contains an unsupported path segment")
        return PurePosixPath("jobs") / path


class FilesystemArtifactStore:
    """Atomically publish immutable artifacts and return verifiable refs."""

    def __init__(self, resolver: ArtifactResolver) -> None:
        self.resolver = resolver

    def publish(self, reference: ArtifactRef, payload: bytes) -> ArtifactRef:
        """Publish exact bytes once; existing paths are immutable."""
        expected = sha256_bytes(payload)
        if reference.artifact_checksum != expected:
            raise ValueError("reference checksum does not match publication payload")
        destination = self.resolver.resolve(reference.artifact_uri)
        self._atomic_create(destination, payload)
        self.resolver.published(reference.artifact_uri)
        return reference

    def publish_model(self, reference: ArtifactRef, model: BaseModel) -> ArtifactRef:
        """Publish deterministic UTF-8 JSON produced from a validated model."""
        payload = model.model_dump_json(indent=2).encode("utf-8") + b"\n"
        return self.publish(reference, payload)

    @staticmethod
    def _atomic_create(destination: Path, payload: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ArtifactAlreadyExistsError(f"artifact already exists: {destination.name}")
        descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary_path, destination)
        except FileExistsError as error:
            raise ArtifactAlreadyExistsError(f"artifact already exists: {destination.name}") from error
        finally:
            temporary_path.unlink(missing_ok=True)


class StreamingPublication:
    """Publish một artifact lớn (video upload) theo chunk, vẫn atomic và immutable.

    Bytes được ghi vào file tạm cùng thư mục đích, băm SHA-256 trong lúc ghi rồi
    `os.link` sang đích ở `commit()`; lỗi hoặc `abort()` không để lại artifact dở.
    Caller async phải gọi `write` qua threadpool vì đây là file I/O đồng bộ.
    """

    def __init__(self, resolver: ArtifactResolver, artifact_uri: str, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes phải dương")
        self.artifact_uri = artifact_uri
        self.resolver = resolver
        self.destination = resolver.resolve(artifact_uri)
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        if self.destination.exists():
            raise ArtifactAlreadyExistsError(f"artifact already exists: {self.destination.name}")
        self.max_bytes = max_bytes
        self.size_bytes = 0
        self._digest = hashlib.sha256()
        descriptor, temporary_name = tempfile.mkstemp(dir=self.destination.parent, prefix=".upload-")
        self._temporary = Path(temporary_name)
        self._stream = os.fdopen(descriptor, "wb")
        self._closed = False

    def write(self, chunk: bytes) -> None:
        """Ghi một chunk; vượt giới hạn thì hủy ngay, không chờ hết body."""
        if self._closed:
            raise ValueError("publication đã đóng")
        self.size_bytes += len(chunk)
        if self.size_bytes > self.max_bytes:
            self.abort()
            raise ArtifactTooLargeError(f"payload vượt giới hạn {self.max_bytes} bytes")
        self._digest.update(chunk)
        self._stream.write(chunk)

    def staged_path(self) -> Path:
        """Flush và trả file tạm để kiểm nội dung trước `commit` (chỉ đọc, hết hiệu lực sau commit/abort)."""
        if self._closed:
            raise ValueError("publication đã đóng")
        self._stream.flush()
        return self._temporary

    def commit(self) -> str:
        """Fsync, link sang đích và trả checksum `sha256:`; payload rỗng bị từ chối."""
        if self._closed:
            raise ValueError("publication đã đóng")
        if self.size_bytes == 0:
            self.abort()
            raise ValueError("payload rỗng")
        try:
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._stream.close()
            os.link(self._temporary, self.destination)
        except FileExistsError as error:
            raise ArtifactAlreadyExistsError(f"artifact already exists: {self.destination.name}") from error
        finally:
            self._closed = True
            self._temporary.unlink(missing_ok=True)
        self.resolver.published(self.artifact_uri)
        return "sha256:" + self._digest.hexdigest()

    def abort(self) -> None:
        """Bỏ file tạm; gọi nhiều lần vẫn an toàn."""
        if self._closed:
            return
        self._closed = True
        self._stream.close()
        self._temporary.unlink(missing_ok=True)
