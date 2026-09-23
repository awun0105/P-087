"""Filesystem-backed implementation of the logical artifact store."""

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
    InvalidArtifactUriError,
)

ContractT = TypeVar("ContractT", bound=BaseModel)
_URI_PREFIX = "artifact://jobs/"


class ArtifactResolver:
    """Map logical artifact URIs into one configured filesystem root."""

    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root.expanduser().resolve()

    def resolve(self, artifact_uri: str) -> Path:
        """Resolve one safe logical URI without allowing path traversal."""
        relative = self._parse_relative_path(artifact_uri)
        resolved = (self.artifact_root / relative).resolve()
        if not resolved.is_relative_to(self.artifact_root):
            raise InvalidArtifactUriError("artifact URI escapes ARTIFACT_ROOT")
        return resolved

    def require(self, reference: ArtifactRef) -> Path:
        """Resolve, assert existence and verify checksum for a reference."""
        path = self.resolve(reference.artifact_uri)
        if not path.is_file():
            raise ArtifactNotFoundError(f"artifact does not exist: {reference.artifact_uri}")
        verify_file_checksum(path, reference.artifact_checksum)
        return path

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
