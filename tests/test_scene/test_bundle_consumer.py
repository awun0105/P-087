"""Fixture proof cho handoff REC → SCENE, gồm các lỗi cần chặn sớm."""

import json
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactRef
from src.services.orchestration.artifacts import ArtifactResolver, sha256_bytes
from src.services.orchestration.artifacts.errors import (
    ArtifactChecksumError,
    ArtifactNotFoundError,
    ArtifactSchemaError,
)
from src.services.scene.bundle_consumer import load_reconstruction_bundle

FIXTURES = Path(__file__).parents[2] / "fixtures"
STORE = FIXTURES / "artifact_store"


def _stage_fixture(tmp_path: Path, name: str) -> tuple[ArtifactRef, ArtifactResolver]:
    """Giữ byte identity LF của fixture trong ZIP có line endings CRLF."""
    payload = (FIXTURES / "reconstruction_bundle" / name).read_bytes().replace(b"\r\n", b"\n")
    document = json.loads(payload)
    resolver = ArtifactResolver(tmp_path)
    reference = ArtifactRef(
        artifact_type="ReconstructionBundle",
        schema_version="1.0",
        artifact_uri=document["artifact_uri"],
        artifact_checksum=sha256_bytes(payload),
        data_class="derived",
        producer_stage=document["producer_stage"],
        job_id=document["job_id"],
    )
    target = resolver.resolve(reference.artifact_uri)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    for source in STORE.rglob("*"):
        if source.is_file():
            destination = tmp_path / source.relative_to(STORE)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
    return reference, resolver


@pytest.mark.parametrize("name", ["manifest.json", "mixed_manifest.json", "rgb_depth_manifest.json"])
def test_load_fixture_profiles(tmp_path: Path, name: str) -> None:
    """RGB, mixed và sensor-depth refs được consume trực tiếp theo contract."""
    reference, resolver = _stage_fixture(tmp_path, name)
    view = load_reconstruction_bundle(reference, resolver)
    assert view.canonical_geometry.is_file()
    assert len(view.rgb_frames) == 1
    assert len(view.camera_poses) == 1
    assert (view.lidar_geometry is not None) == (name == "mixed_manifest.json")
    assert bool(view.depth_frames) == (name == "rgb_depth_manifest.json")


def test_bad_schema_fails_before_processing(tmp_path: Path) -> None:
    """Ref byte-valid không bỏ qua schema version không được hỗ trợ."""
    reference, resolver = _stage_fixture(tmp_path, "manifest.json")
    path = resolver.resolve(reference.artifact_uri)
    payload = json.loads(path.read_text())
    payload["schema_version"] = "2.0"
    changed = json.dumps(payload).encode()
    path.write_bytes(changed)
    reference = reference.model_copy(update={"artifact_checksum": sha256_bytes(changed)})
    with pytest.raises(ArtifactSchemaError, match="ReconstructionBundle"):
        load_reconstruction_bundle(reference, resolver)


def test_bad_logical_checksum_fails_before_processing(tmp_path: Path) -> None:
    """Byte checksum của envelope không thay thế logical bundle identity."""
    reference, resolver = _stage_fixture(tmp_path, "manifest.json")
    path = resolver.resolve(reference.artifact_uri)
    payload = json.loads(path.read_text())
    payload["artifact_checksum"] = "sha256:" + "0" * 64
    changed = json.dumps(payload).encode()
    path.write_bytes(changed)
    reference = reference.model_copy(update={"artifact_checksum": sha256_bytes(changed)})
    with pytest.raises(ValueError, match="canonical content"):
        load_reconstruction_bundle(reference, resolver)


def test_missing_and_corrupt_nested_refs_fail(tmp_path: Path) -> None:
    """Cần resolve và verify mọi nested ref, không chỉ manifest."""
    reference, resolver = _stage_fixture(tmp_path, "manifest.json")
    payload = json.loads(resolver.resolve(reference.artifact_uri).read_text())
    frame = resolver.resolve(payload["rgb_frame_refs"][0]["artifact_uri"])
    frame.unlink()
    with pytest.raises(ArtifactNotFoundError):
        load_reconstruction_bundle(reference, resolver)
    frame.write_bytes(b"corrupted")
    with pytest.raises(ArtifactChecksumError):
        load_reconstruction_bundle(reference, resolver)
