"""SHA-256 calculation and verification for immutable artifacts."""

import hashlib
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.artifacts.errors import ArtifactChecksumError

_READ_CHUNK_BYTES = 1024 * 1024
ContractT = TypeVar("ContractT", bound=BaseModel)


def with_canonical_checksum(model: ContractT, checksum_field: str) -> ContractT:
    """Điền self-checksum canonical cho một model vừa dựng.

    Dựng model với giá trị chỗ giữ chỗ rồi gọi hàm này. `canonical_content_checksum`
    bỏ qua chính field checksum nên giá trị chỗ giữ chỗ không ảnh hưởng digest.
    """
    return model.model_copy(update={checksum_field: canonical_content_checksum(model, checksum_field)})


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
