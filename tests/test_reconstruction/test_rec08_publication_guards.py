"""REC-08 coordinate declarations, byte identity và retry publication guards."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.reconstruction import PreprocessingProvenance
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError
from src.services.reconstruction.lidar import (
    LiDARIngestRequest,
    LiDARIngestService,
    inspect_rec07_preparation,
)
from tests.test_reconstruction.test_rec08_lidar_ingest import _create_test_ply


def _request(path: Path) -> LiDARIngestRequest:
    return LiDARIngestRequest(
        job_id="rec08-audit",
        lidar_file=path,
        source_input_checksum=_create_test_ply(path),
        coordinate_system=CoordinateSystem(),
        source_frame="registered_lidar",
        preprocessing_provenance=PreprocessingProvenance(ground_truth_assisted=False, dependencies=[]),
    )


def test_coordinate_declarations_required(tmp_path: Path) -> None:
    values = _request(tmp_path / "cloud.ply").model_dump()
    for field in ("coordinate_system", "source_frame"):
        missing = {k: v for k, v in values.items() if k != field}
        with pytest.raises(ValidationError, match=field):
            LiDARIngestRequest.model_validate(missing)


def test_declared_format_must_match_bytes(tmp_path: Path) -> None:
    request = _request(tmp_path / "cloud.ply").model_copy(update={"geometry_format": "pcd"})
    with pytest.raises(ValueError, match="format does not match"):
        request.validate_payload()


def test_metadata_and_retry_identity(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "store")
    service = LiDARIngestService(FilesystemArtifactStore(resolver))
    request = _request(tmp_path / "cloud.ply")
    first = service.ingest_with_metadata(request)
    # Shared store contract là create-only, không được đổi thành implicit overwrite.
    with pytest.raises(ArtifactAlreadyExistsError):
        service.ingest_with_metadata(request)
    changed = request.model_copy(update={"source_frame": "other_declared_frame"})
    second = service.ingest_with_metadata(changed)
    assert first.geometry_ref.artifact_uri != second.geometry_ref.artifact_uri
    assert first.geometry_ref.artifact_checksum == second.geometry_ref.artifact_checksum
    assert json.loads(resolver.require(first.metadata_ref).read_text())["source_frame"] == request.source_frame
    assert resolver.require(first.geometry_ref).read_bytes() == request.lidar_file.read_bytes()


def test_source_mutation_between_validation_and_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(tmp_path / "cloud.ply")
    original = LiDARIngestRequest.validate_payload

    def mutate(instance: LiDARIngestRequest) -> object:
        stats = original(instance)
        instance.lidar_file.write_bytes(b"changed after inspection")
        return stats

    monkeypatch.setattr(LiDARIngestRequest, "validate_payload", mutate)
    resolver = ArtifactResolver(tmp_path / "store")
    with pytest.raises(ValueError, match="changed during ingest"):
        LiDARIngestService(FilesystemArtifactStore(resolver)).ingest(request)
    assert not list((tmp_path / "store").rglob("*.ply"))


def test_prefusion_manifest_tamper_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"manifest_checksum": "sha256:" + "0" * 64}))
    with pytest.raises(ValueError, match="manifest checksum mismatch"):
        inspect_rec07_preparation(manifest, tmp_path / "absent.ply")


def test_error_does_not_expose_local_path(tmp_path: Path) -> None:
    request = _request(tmp_path / "private_cloud.ply")
    request.lidar_file.unlink()
    with pytest.raises(ValueError) as error:
        request.validate_payload()
    assert str(tmp_path) not in str(error.value)
