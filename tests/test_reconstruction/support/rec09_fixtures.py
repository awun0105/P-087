"""Fixture-only alignment reviewer; không import trong product hoặc real demo."""

import hashlib
import json
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.reconstruction import AlignmentStatus
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.alignment import AlignmentRequest, RgbLidarAlignmentService


def _review_evidence(writer: FilesystemArtifactStore, request: AlignmentRequest) -> ProductArtifactRef:
    payload = json.dumps(request.model_dump(mode="json", exclude={"evidence_refs"}), sort_keys=True).encode()
    digest = hashlib.sha256(payload).hexdigest()
    evidence = ProductArtifactRef(
        artifact_type="SyntheticAlignmentReview",
        schema_version="1.0",
        data_class="derived",
        artifact_uri=f"artifact://jobs/{request.job_id}/fixture-review/{digest}.json",
        artifact_checksum="sha256:" + digest,
        producer_stage="ST-RGB-LIDAR-ALIGN",
        job_id=request.job_id,
    )
    writer.publish(evidence, payload)
    return evidence


def reviewed_fixture(
    writer: FilesystemArtifactStore, request: AlignmentRequest
) -> tuple[RgbLidarAlignmentService, AlignmentRequest]:
    """Review exact fixture inputs bằng byte evidence; không default approve bất kỳ request."""
    request = request.model_copy(
        update={
            "status": AlignmentStatus.CONFIRMED,
            "same_scene_attestation": True,
            "provenance": {**request.provenance, "evidence_kind": "synthetic_fixture"},
        }
    )
    evidence = _review_evidence(writer, request)
    request = request.model_copy(update={"evidence_refs": [evidence]})

    def verify(candidate: AlignmentRequest) -> bool:
        if candidate.provenance.get("evidence_kind") != "synthetic_fixture" or candidate.evidence_refs != [evidence]:
            return False
        stored = json.loads(writer.resolver.require(evidence).read_text())
        return stored == candidate.model_dump(mode="json", exclude={"evidence_refs"})

    return RgbLidarAlignmentService(writer, writer.resolver.require, verify), request


def _source(writer: FilesystemArtifactStore, kind: str) -> ProductArtifactRef:
    payload = f"synthetic {kind} for alignment authority tests".encode()
    ref = ProductArtifactRef(
        artifact_type=kind,
        schema_version="1.0",
        data_class="derived",
        job_id="alignment-fixture",
        artifact_uri=f"artifact://jobs/alignment-fixture/{kind}.bin",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        producer_stage="ST-RGB-GEOMETRY" if kind == "RgbGeometry" else "ST-LIDAR-INGEST",
    )
    writer.publish(ref, payload)
    return ref


def alignment_fixture(root: Path) -> tuple[RgbLidarAlignmentService, AlignmentRequest]:
    """Opaque synthetic geometry; teste authority/bytes, không teste geometry decoder."""
    writer = FilesystemArtifactStore(ArtifactResolver(root))
    request = AlignmentRequest(
        job_id="alignment-fixture",
        rgb_geometry_ref=_source(writer, "RgbGeometry"),
        lidar_geometry_ref=_source(writer, "LiDARGeometryArtifact"),
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame="lidar_world",
            translation_xyz=(1, 2, 3),
            rotation_quaternion_xyzw=(0, 0, 0, 1),
        ),
        method="synthetic_fixture_known_transform",
    )
    return reviewed_fixture(writer, request)
