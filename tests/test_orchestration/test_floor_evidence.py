"""Persisted floor-fit evidence stays bound to its input and frozen profile."""

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.floor_model import FloorFitEvidence, FloorModel
from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import sha256_bytes
from src.services.orchestration.scene.floor_evidence import load_floor_fit_evidence, publish_floor_fit_evidence
from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum


def _source_ref(job_id: str, payload: bytes = b"source") -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type="CanonicalGeometry",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec05/collision.glb",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )


def _floor_model() -> FloorModel:
    points = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
    return fit_canonical_floor_model(points, point_cloud_checksum(points))


def test_published_evidence_loads_only_for_exact_source_and_profile(tmp_path: Path) -> None:
    job_id = "job-floor-evidence"
    source_ref = _source_ref(job_id)
    model = _floor_model()
    published: dict[str, bytes] = {}

    def publish(reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        published[reference.artifact_uri] = payload
        return reference

    reference, evidence = publish_floor_fit_evidence(job_id, source_ref, model, publish)
    artifact_path = tmp_path / "floor-fit.json"
    artifact_path.write_bytes(published[reference.artifact_uri])

    loaded = load_floor_fit_evidence(
        reference,
        lambda _reference: artifact_path,
        expected_source_artifact_ref=source_ref,
        expected_profile_checksum=model.profile_checksum,
    )

    assert loaded == evidence
    assert loaded.floor_model.status == "confirmed_prior_fallback"
    assert reference.artifact_type == "FloorFitEvidence"
    assert reference.producer_stage == StageId.OBJECT_EXTRACT
    assert reference.artifact_checksum == sha256_bytes(artifact_path.read_bytes())

    with pytest.raises(ValueError, match="source artifact mismatch"):
        load_floor_fit_evidence(
            reference,
            lambda _reference: artifact_path,
            expected_source_artifact_ref=_source_ref(job_id, b"different source"),
        )
    with pytest.raises(ValueError, match="profile checksum mismatch"):
        load_floor_fit_evidence(
            reference,
            lambda _reference: artifact_path,
            expected_profile_checksum=f"sha256:{'f' * 64}",
        )


def test_evidence_rejects_point_checksum_or_job_mismatch() -> None:
    job_id = "job-floor-evidence"
    evidence = FloorFitEvidence(
        job_id=job_id,
        source_artifact_ref=_source_ref(job_id),
        point_cloud_checksum=_floor_model().source_checksum,
        floor_model=_floor_model(),
    )
    payload = evidence.model_dump(mode="json")
    payload["point_cloud_checksum"] = f"sha256:{'1' * 64}"
    with pytest.raises(ValidationError, match="point cloud checksum"):
        FloorFitEvidence.model_validate(payload)

    payload = evidence.model_dump(mode="json")
    payload["job_id"] = "another-job"
    with pytest.raises(ValidationError, match="same job"):
        FloorFitEvidence.model_validate(payload)


def test_legacy_floor_model_json_remains_readable() -> None:
    axis = np.linspace(-2, 2, 41)
    xx, yy = np.meshgrid(axis, axis)
    points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size)))
    model = fit_canonical_floor_model(points, point_cloud_checksum(points))

    legacy_payload = json.loads(model.model_dump_json())
    legacy_payload["schema_version"] = "1.0"
    parsed = type(model).model_validate(legacy_payload)

    assert parsed.schema_version == "1.0"
    assert parsed.status == "supported"
