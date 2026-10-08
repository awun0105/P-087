"""Persist and verify source-bound floor-fit evidence for SceneIR handoff."""

from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, Checksum, JsonObject, ProductArtifactRef
from src.models.contracts.floor_model import FloorFitEvidence, FloorModel
from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import sha256_bytes

Publish = Callable[[ProductArtifactRef, bytes], ProductArtifactRef]
Resolve = Callable[[ProductArtifactRef], Path]


def publish_floor_fit_evidence(
    job_id: str,
    source_artifact_ref: ProductArtifactRef,
    floor_model: FloorModel,
    publish: Publish,
) -> tuple[ProductArtifactRef, FloorFitEvidence]:
    """Publish deterministic evidence for the exact artifact and point cloud used by a fit."""
    evidence = FloorFitEvidence(
        job_id=job_id,
        source_artifact_ref=source_artifact_ref,
        point_cloud_checksum=floor_model.source_checksum,
        floor_model=floor_model,
    )
    payload = evidence.model_dump_json(indent=2).encode("utf-8") + b"\n"
    reference = _reference(evidence, payload)
    published = publish(reference, payload)
    if published != reference:
        raise ValueError("floor-fit evidence publication changed its content identity")
    return reference, evidence


def load_floor_fit_evidence(
    reference: ProductArtifactRef,
    resolve: Resolve,
    *,
    expected_source_artifact_ref: ProductArtifactRef | None = None,
    expected_profile_checksum: Checksum | None = None,
) -> FloorFitEvidence:
    """Load immutable evidence and reject stale source/profile bindings when supplied."""
    if reference.artifact_type != "FloorFitEvidence" or reference.producer_stage != StageId.OBJECT_EXTRACT:
        raise ValueError("not a floor-fit evidence artifact")
    payload = resolve(reference).read_bytes()
    if sha256_bytes(payload) != reference.artifact_checksum:
        raise ValueError("floor-fit evidence artifact checksum mismatch")
    evidence = FloorFitEvidence.model_validate_json(payload)
    if reference != _reference(evidence, payload):
        raise ValueError("floor-fit evidence reference does not match its content")
    if expected_source_artifact_ref is not None and evidence.source_artifact_ref != expected_source_artifact_ref:
        raise ValueError("floor-fit evidence source artifact mismatch")
    if expected_profile_checksum is not None and evidence.floor_model.profile_checksum != expected_profile_checksum:
        raise ValueError("floor-fit evidence profile checksum mismatch")
    return evidence


def scene_floor_fit_summary(reference: ProductArtifactRef, evidence: FloorFitEvidence) -> JsonObject:
    """Compact diagnostic stored in SceneIR.provenance; detailed evidence remains content-addressed."""
    model = evidence.floor_model
    return {
        "artifact_ref": reference.model_dump(mode="json"),
        "status": model.status,
        "fallback_reason": model.fallback_reason,
        "floor_band_m": model.floor_band_m,
        "profile_checksum": model.profile_checksum,
        "point_cloud_checksum": model.source_checksum,
    }


def _reference(evidence: FloorFitEvidence, payload: bytes) -> ProductArtifactRef:
    digest = sha256_bytes(payload).removeprefix("sha256:")
    return ProductArtifactRef(
        artifact_type=evidence.artifact_type,
        schema_version=evidence.schema_version,
        artifact_uri=f"artifact://jobs/{evidence.job_id}/scene/floor-fit/{digest}.json",
        artifact_checksum=f"sha256:{digest}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.OBJECT_EXTRACT,
        job_id=evidence.job_id,
    )
