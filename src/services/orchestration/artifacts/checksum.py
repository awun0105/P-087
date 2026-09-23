"""SHA-256 calculation and verification for immutable artifacts."""

import hashlib
from pathlib import Path

from src.services.orchestration.artifacts.errors import ArtifactChecksumError

_READ_CHUNK_BYTES = 1024 * 1024


def sha256_bytes(payload: bytes) -> str:
    """Tính checksum có prefix algorithm cho một byte payload."""
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def sha256_file(path: Path) -> str:
    """Tính SHA-256 theo stream để không giữ artifact lớn trong RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def verify_file_checksum(path: Path, expected: str) -> None:
    """Fail closed khi bytes không khớp checksum trong contract."""
    observed = sha256_file(path)
    if observed != expected:
        raise ArtifactChecksumError(f"checksum mismatch: expected {expected}, observed {observed}")
