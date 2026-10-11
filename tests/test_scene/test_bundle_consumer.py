"""Fixture proof cho handoff REC → SCENE, gồm các lỗi cần chặn sớm."""

import json
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import AlignmentRecord, ReconstructionBundle
from src.services.orchestration.artifacts import ArtifactResolver, sha256_bytes
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.artifacts.errors import (
    ArtifactChecksumError,
    ArtifactNotFoundError,
    ArtifactSchemaError,
)
from src.services.reconstruction.alignment.models import AlignmentRequest
from src.services.scene.bundle_consumer import load_reconstruction_bundle

FIXTURES = Path(__file__).parents[2] / "fixtures"
STORE = FIXTURES / "artifact_store"


def _stage_fixture(tmp_path: Path, name: str) -> tuple[ArtifactRef, ArtifactResolver]:
    """Stage fixture với identity LF và REC-09 evidence hiện hành cho mixed bundle."""
    payload = (FIXTURES / "reconstruction_bundle" / name).read_bytes().replace(b"\r\n", b"\n")
    document = json.loads(payload)
    resolver = ArtifactResolver(tmp_path)
    for source in STORE.rglob("*"):
        if source.is_file():
            destination = tmp_path / source.relative_to(STORE)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))

    if name == "mixed_manifest.json":
        legacy = document["alignment_record"]
        request = AlignmentRequest(
            job_id=document["job_id"],
            rgb_geometry_ref=document["rgb_geometry_ref"],
            lidar_geometry_ref=document["lidar_geometry_ref"],
            transform_target_from_source=legacy["transform_target_from_source"],
            method="fixture_confirmed_alignment",
            status=legacy["status"],
            evidence_refs=legacy["evidence_refs"],
            same_scene_attestation=True,
            provenance={"fixture": True, "adapted_to_rec09": True},
        )
        alignment_payload = (
            json.dumps(
                {"schema_version": "1.0", "request": request.model_dump(mode="json")}, sort_keys=True, indent=2
            ).encode()
            + b"\n"
        )
        alignment_checksum = sha256_bytes(alignment_payload)
        alignment_uri = (
            f"artifact://jobs/{document['job_id']}/rec09/{alignment_checksum.removeprefix('sha256:')}"
            "/alignment_evidence.json"
        )
        record = AlignmentRecord(
            artifact_type="AlignmentRecord",
            schema_version="1.0",
            artifact_uri=alignment_uri,
            artifact_checksum=alignment_checksum,
            producer_stage=StageId.RGB_LIDAR_ALIGN,
            job_id=request.job_id,
            source_lidar_checksum=request.lidar_geometry_ref.artifact_checksum,
            target_rgb_geometry_checksum=request.rgb_geometry_ref.artifact_checksum,
            transform_target_from_source=request.transform_target_from_source,
            status=request.status,
            method=request.method,
            evidence_refs=request.evidence_refs,
            provenance=request.provenance,
        )
        document["alignment_record"] = record.model_dump(mode="json")
        bundle = with_canonical_checksum(ReconstructionBundle.model_validate(document), "artifact_checksum")
        payload = json.dumps(bundle.model_dump(mode="json"), sort_keys=True, indent=2).encode() + b"\n"
        alignment_path = resolver.resolve(alignment_uri)
        alignment_path.parent.mkdir(parents=True, exist_ok=True)
        alignment_path.write_bytes(alignment_payload)

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


def test_missing_and_corrupt_alignment_publication_fail(tmp_path: Path) -> None:
    """Mixed bundles require the exact immutable alignment publication bytes."""
    reference, resolver = _stage_fixture(tmp_path, "mixed_manifest.json")
    payload = json.loads(resolver.resolve(reference.artifact_uri).read_text())
    alignment_path = resolver.resolve(payload["alignment_record"]["artifact_uri"])
    alignment_path.unlink()
    with pytest.raises(ArtifactNotFoundError):
        load_reconstruction_bundle(reference, resolver)

    alignment_path.write_bytes(b"corrupted")
    with pytest.raises(ArtifactChecksumError):
        load_reconstruction_bundle(reference, resolver)


def test_embedded_alignment_must_match_published_alignment_evidence(tmp_path: Path) -> None:
    reference, resolver = _stage_fixture(tmp_path, "mixed_manifest.json")
    path = resolver.resolve(reference.artifact_uri)
    payload = json.loads(path.read_text())
    payload["alignment_record"]["transform_target_from_source"]["translation_xyz"][0] += 0.25
    bundle = with_canonical_checksum(ReconstructionBundle.model_validate(payload), "artifact_checksum")
    encoded = json.dumps(bundle.model_dump(mode="json")).encode()
    path.write_bytes(encoded)
    reference = reference.model_copy(update={"artifact_checksum": sha256_bytes(encoded)})

    with pytest.raises(ValueError, match="published alignment evidence"):
        load_reconstruction_bundle(reference, resolver)


def test_published_alignment_requires_confirmation_and_same_scene_evidence(tmp_path: Path) -> None:
    reference, resolver = _stage_fixture(tmp_path, "mixed_manifest.json")
    bundle_path = resolver.resolve(reference.artifact_uri)
    bundle_payload = json.loads(bundle_path.read_text())
    record = bundle_payload["alignment_record"]
    old_alignment_path = resolver.resolve(record["artifact_uri"])
    evidence = json.loads(old_alignment_path.read_text())
    evidence["request"]["same_scene_attestation"] = False
    encoded_evidence = json.dumps(evidence, sort_keys=True, indent=2).encode() + b"\n"
    alignment_checksum = sha256_bytes(encoded_evidence)
    alignment_uri = (
        f"artifact://jobs/{record['job_id']}/rec09/{alignment_checksum.removeprefix('sha256:')}/alignment_evidence.json"
    )
    alignment_path = resolver.resolve(alignment_uri)
    alignment_path.parent.mkdir(parents=True, exist_ok=True)
    alignment_path.write_bytes(encoded_evidence)
    record["artifact_uri"] = alignment_uri
    record["artifact_checksum"] = alignment_checksum
    bundle = with_canonical_checksum(ReconstructionBundle.model_validate(bundle_payload), "artifact_checksum")
    encoded_bundle = json.dumps(bundle.model_dump(mode="json")).encode()
    bundle_path.write_bytes(encoded_bundle)
    reference = reference.model_copy(update={"artifact_checksum": sha256_bytes(encoded_bundle)})

    with pytest.raises(ValueError, match="confirmation or same-scene proof"):
        load_reconstruction_bundle(reference, resolver)
