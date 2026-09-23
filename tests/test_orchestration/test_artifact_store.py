"""Filesystem artifact resolver/publication contract tests."""

from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef
from src.models.contracts.manifests import RuntimeManifest
from src.services.orchestration.artifacts import (
    ArtifactResolver,
    FilesystemArtifactStore,
    sha256_bytes,
)
from src.services.orchestration.artifacts.errors import (
    ArtifactAlreadyExistsError,
    ArtifactChecksumError,
    ArtifactSchemaError,
    InvalidArtifactUriError,
)


def _reference(payload: bytes, name: str = "payload.bin") -> ArtifactRef:
    return ArtifactRef(
        artifact_type="TestPayload",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/job-test-001/results/{name}",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="ST-INPUT-VALIDATE",
        job_id="job-test-001",
    )


def test_atomic_publish_resolve_and_verify(tmp_path: Path) -> None:
    """Publication is atomic and returned bytes are checksum-verifiable."""
    payload = b"immutable artifact\n"
    resolver = ArtifactResolver(tmp_path)
    store = FilesystemArtifactStore(resolver)
    reference = _reference(payload)

    store.publish(reference, payload)

    assert resolver.require(reference).read_bytes() == payload


def test_publication_is_immutable(tmp_path: Path) -> None:
    """A logical URI cannot be overwritten after publication."""
    payload = b"immutable artifact\n"
    store = FilesystemArtifactStore(ArtifactResolver(tmp_path))
    reference = _reference(payload)
    store.publish(reference, payload)

    with pytest.raises(ArtifactAlreadyExistsError):
        store.publish(reference, payload)


def test_checksum_mismatch_and_path_traversal_fail_closed(tmp_path: Path) -> None:
    """Corrupt bytes and unsafe URIs do not cross the storage boundary."""
    resolver = ArtifactResolver(tmp_path)
    reference = _reference(b"expected")
    path = resolver.resolve(reference.artifact_uri)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"corrupt")

    with pytest.raises(ArtifactChecksumError):
        resolver.require(reference)
    with pytest.raises(InvalidArtifactUriError):
        resolver.resolve("artifact://jobs/job-test-001/../../outside.bin")


def test_load_model_enforces_schema_version(tmp_path: Path) -> None:
    """Resolved JSON must validate the requested schema, including version."""
    payload = b'{"schema_version":"2.0","components":{},"runtime_manifest_checksum":"sha256:8888888888888888888888888888888888888888888888888888888888888888"}\n'
    resolver = ArtifactResolver(tmp_path)
    reference = _reference(payload, "runtime_manifest.json")
    FilesystemArtifactStore(resolver).publish(reference, payload)

    with pytest.raises(ArtifactSchemaError, match="invalid RuntimeManifest"):
        resolver.load_model(reference, RuntimeManifest)
