"""Fixture-only authority và published REC-03/04 inputs cho REC-06 tests."""

import hashlib
import json
import math
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.reconstruction.rgb.metric import MetricCanonicalizer, MetricDependencies
from src.services.reconstruction.rgb.metric_models import MetricAcceptance, MetricPreview, MetricRequest
from src.services.reconstruction.rgb.publication import ArtifactWriter
from tests.test_reconstruction.test_rec04_brush import adapter


def publish_evidence(writer: ArtifactWriter, name: str, payload: dict) -> ProductArtifactRef:
    """Opaque test measurement/decision; không định nghĩa product approval schema."""
    data = json.dumps(payload, sort_keys=True).encode()
    reference = ProductArtifactRef(
        artifact_type="SyntheticMetricEvidence",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/rec06-fixture/evidence/{name}.json",
        artifact_checksum="sha256:" + hashlib.sha256(data).hexdigest(),
        data_class="derived",
        producer_stage="ST-METRIC-CANONICALIZE",
        job_id="rec06-fixture",
        source_provenance={"evidence_kind": "synthetic_fixture"},
    )
    writer.publish(reference, data)
    return reference


def metric_fixture(root: Path) -> tuple[MetricCanonicalizer, MetricRequest]:
    """Published fixture tools, real artifact resolver/store; không chạy Brush/COLMAP thật."""
    brush, request = adapter(root)
    visual = brush.execute(request)
    resolver, writer = brush.deps.resolver, brush.deps.publisher.writer
    evidence = publish_evidence(writer, "measurement", {"kind": "synthetic_known_dimensions"})

    def verify(preview: MetricPreview, acceptance: MetricAcceptance) -> bool:
        decision = json.loads(resolver.require(acceptance.decision_ref).read_text())
        return preview.request.evidence_kind == "synthetic_fixture" and decision == {
            "preview_checksum": preview.checksum(),
            "decision": "accept_fixture",
        }

    service = MetricCanonicalizer(MetricDependencies(resolver, writer, verify))
    return service, _request(visual.reference, visual.artifact.master, evidence)


def _request(visual: ProductArtifactRef, master: ProductArtifactRef, evidence: ProductArtifactRef) -> MetricRequest:
    values = dict(
        source_visual=visual,
        evidence_kind="synthetic_fixture",
        anchor=dict(
            anchor_id="fixture-ab",
            source_master=master,
            point_a=(0, 0, 3),
            point_b=(0.5, 0, 3),
            distance_m=1,
            measurement_ref=evidence,
        ),
        frame=dict(
            rotation_xyzw=(0, 0, math.sqrt(0.5), math.sqrt(0.5)), translation_m=(10, 20, 30), evidence_ref=evidence
        ),
    )
    return MetricRequest.model_validate(values)


def acceptance_for(service: MetricCanonicalizer, preview: MetricPreview) -> MetricAcceptance:
    """Stub decision được publish riêng sau khi đã có exact preview checksum."""
    evidence = publish_evidence(
        service.deps.writer,
        preview.checksum().removeprefix("sha256:"),
        {"preview_checksum": preview.checksum(), "decision": "accept_fixture"},
    )
    return MetricAcceptance(
        preview_checksum=preview.checksum(), decision_ref=evidence, evidence_kind="synthetic_fixture"
    )
