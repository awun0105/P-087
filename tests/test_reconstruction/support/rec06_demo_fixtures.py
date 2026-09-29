"""Prepared correspondences giả lập; không đọc hoặc xác nhận metric dataset thật."""

import hashlib
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.reconstruction import PreprocessingProvenance
from src.services.reconstruction.rgb.canonical.demo_metric import DemoMetricAdapter, DemoMetricDependencies
from src.services.reconstruction.rgb.canonical.demo_metric_models import (
    DemoLidarMeasurement,
    DemoMetricMode,
    DemoMetricRequest,
)
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer
from tests.test_reconstruction.support.rec06_fixtures import metric_fixture, publish_evidence


def _lidar(service: MetricCanonicalizer, assisted: bool) -> tuple[ProductArtifactRef, PreprocessingProvenance]:
    """Tiny ASCII PLY có đơn vị fixture mét; giữ GT lineage qua tất cả modes."""
    lineage = PreprocessingProvenance.model_validate(
        dict(
            dependencies=[
                dict(
                    role="pose",
                    origin="ground_truth" if assisted else "estimated",
                    source_checksum="sha256:" + "a" * 64,
                )
            ],
            ground_truth_assisted=assisted,
            details={"evidence_kind": "synthetic_fixture"},
        )
    )
    payload = b"ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\nproperty float z\nend_header\n10 20 36\n10 21 36\n"
    ref = ProductArtifactRef(
        artifact_type="LiDARGeometryArtifact",
        schema_version="1.0",
        artifact_uri="artifact://jobs/rec06-fixture/lidar/registered.ply",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class="derived",
        producer_stage="ST-LIDAR-INGEST",
        source_provenance=lineage.model_dump(mode="json"),
    )
    service.deps.writer.publish(ref, payload)
    return ref, lineage


def demo_fixture(root: Path, assisted: bool = False) -> tuple[DemoMetricAdapter, DemoLidarMeasurement]:
    """Verifier chỉ nhận exact fixture đã chuẩn bị, không là real correspondence solver."""
    service, request = metric_fixture(root)
    lidar, lineage = _lidar(service, assisted)
    correspondence = publish_evidence(service.deps.writer, "correspondence", {"kind": "synthetic_pairs"})
    measurement = DemoLidarMeasurement(
        identity=dict(scene_id="fixture-scene", traversal_id="fixture-traversal"),
        source_visual=request.source_visual,
        source_master=request.anchor.source_master,
        source_lidar=lidar,
        preprocessing_provenance=lineage,
        correspondence_ref=correspondence,
        frame=request.frame,
        rgb_points=(request.anchor.point_a, request.anchor.point_b),
        lidar_points_m=((10, 20, 36), (10, 21, 36)),
        evidence_kind="synthetic_fixture",
    )
    expected = measurement.model_dump(mode="json")

    def verify(candidate: DemoLidarMeasurement) -> bool:
        return candidate.evidence_kind == "synthetic_fixture" and candidate.model_dump(mode="json") == expected

    return DemoMetricAdapter(DemoMetricDependencies(service, verify)), measurement


def request_for(context: tuple[DemoMetricAdapter, DemoLidarMeasurement], mode: DemoMetricMode) -> DemoMetricRequest:
    """Publish measurement một lần, rồi tạo input cho mode được chọn."""
    adapter, measurement = context
    reference = adapter.publish_measurement(measurement, "rec06-demo")
    return DemoMetricRequest(
        execution_scope="prepared_dataset_demo",
        mode=mode,
        identity=measurement.identity,
        source_visual=measurement.source_visual,
        measurement_ref=reference,
        selected_rgb_points=measurement.rgb_points if mode == DemoMetricMode.RGB_TWO_POINT else None,
    )
