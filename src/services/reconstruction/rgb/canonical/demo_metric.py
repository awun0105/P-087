"""Adapter ba demo modes từ registered LiDAR measurement đã được kiểm chứng.

Không đọc raw scans/GT, không cung cấp default correspondence verifier. Producer
phải kiểm cặp điểm, scene/frame/unit và evidence kind trên source thật; fixture
verifier chỉ dùng trong tests. Measurement review không thay metric acceptance.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.services.reconstruction.rgb.canonical.demo_metric_models import (
    DemoLidarMeasurement,
    DemoMetricMode,
    DemoMetricPreview,
    DemoMetricRequest,
)
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer
from src.services.reconstruction.rgb.canonical.metric_models import (
    DistanceAnchor,
    MetricAcceptance,
    MetricConfirmation,
    MetricRequest,
)


@dataclass(frozen=True)
class DemoMetricDependencies:
    """Inject source/measurement authority riêng với Editor metric acceptance."""

    metric: MetricCanonicalizer
    verify_measurement: Callable[[DemoLidarMeasurement], bool] | None = None


class DemoMetricAdapter:
    """Dùng chung REC-06 preview/gate; không đổi mode thành ba reconstruction engines."""

    def __init__(self, dependencies: DemoMetricDependencies) -> None:
        self.deps = dependencies

    def publish_measurement(self, measurement: DemoLidarMeasurement, job_id: str) -> ProductArtifactRef:
        """Publish exact prepared evidence; không tự phát hành metric CONFIRMED."""
        measurement = DemoLidarMeasurement.model_validate(measurement.model_dump())
        self._verify_sources(measurement)
        payload = measurement.model_dump_json(indent=2).encode() + b"\n"
        checksum = hashlib.sha256(payload).hexdigest()
        reference = ProductArtifactRef(
            artifact_type="DemoLidarMeasurement",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/rec06/demo-measurements/{checksum}.json",
            artifact_checksum="sha256:" + checksum,
            data_class="derived",
            producer_stage=StageId.METRIC_CANONICALIZE,
            job_id=job_id,
            source_provenance=_provenance(measurement),
        )
        if self.deps.metric.deps.writer.publish(reference, payload) != reference:
            raise ValueError("artifact writer changed demo measurement identity")
        return reference

    def _verify_sources(self, measurement: DemoLidarMeasurement) -> None:
        resolver = self.deps.metric.deps.visuals
        if resolver.load(measurement.source_visual).master != measurement.source_master:
            raise ValueError("demo measurement belongs to a different visual master")
        for ref in (measurement.source_lidar, measurement.correspondence_ref, measurement.frame.evidence_ref):
            resolver.require(ref)
        if self.deps.verify_measurement is None:
            raise ValueError("demo correspondence verifier is not configured")
        if self.deps.verify_measurement(measurement) is not True:
            raise ValueError("demo scene/correspondence evidence was not verified")

    def _load(self, reference: ProductArtifactRef) -> DemoLidarMeasurement:
        if reference.artifact_type != "DemoLidarMeasurement" or reference.producer_stage != StageId.METRIC_CANONICALIZE:
            raise ValueError("not a prepared demo LiDAR measurement")
        payload = self.deps.metric.deps.visuals.require(reference).read_bytes()
        measurement = DemoLidarMeasurement.model_validate_json(payload)
        if reference.source_provenance != _provenance(measurement):
            raise ValueError("demo reference provenance differs from measurement")
        self._verify_sources(measurement)
        return measurement

    def preview(self, request: DemoMetricRequest) -> DemoMetricPreview:
        """Gợi ý distance cho đúng selection; không auto-confirm hoặc đoán correspondence."""
        request = DemoMetricRequest.model_validate(request.model_dump())
        measurement = self._load(request.measurement_ref)
        if request.identity != measurement.identity or request.source_visual != measurement.source_visual:
            raise ValueError("demo measurement belongs to a different scene/traversal/visual")
        if request.selected_rgb_points not in (None, measurement.rgb_points, measurement.rgb_points[::-1]):
            raise ValueError("selected points have no verified LiDAR correspondence; measure again")
        metric = self.deps.metric.preview(_metric_request(request, measurement))
        return DemoMetricPreview(
            request=request,
            metric_preview=metric,
            suggested_distance_m=measurement.distance_m(),
            preprocessing_provenance=measurement.preprocessing_provenance,
            lidar_geometry_for_composition=(
                measurement.source_lidar if request.mode == DemoMetricMode.RGB_LIDAR_FUSION else None
            ),
        )

    def confirm(self, preview: DemoMetricPreview, acceptance: MetricAcceptance | None) -> MetricConfirmation:
        """Recheck LiDAR/selection lineage trước existing explicit Editor acceptance gate."""
        preview = DemoMetricPreview.model_validate(preview.model_dump())
        if self.preview(preview.request) != preview:
            raise ValueError("demo preview changed; review current measurement")
        return self.deps.metric.confirm(preview.metric_preview, acceptance)


def _provenance(measurement: DemoLidarMeasurement) -> dict:
    """Lineage sống trong measurement ref nên metric record không mất nhãn hỗ trợ."""
    return {
        "assistance": "lidar_assisted_demo",
        "independent_rgb_only": False,
        "identity": measurement.identity.model_dump(mode="json"),
        "source_lidar": measurement.source_lidar.model_dump(mode="json"),
        "preprocessing_provenance": measurement.preprocessing_provenance.model_dump(mode="json"),
        "ground_truth_assisted": measurement.preprocessing_provenance.ground_truth_assisted,
        "evidence_kind": measurement.evidence_kind,
    }


def _metric_request(request: DemoMetricRequest, measurement: DemoLidarMeasurement) -> MetricRequest:
    points = request.selected_rgb_points or measurement.rgb_points
    return MetricRequest(
        source_visual=request.source_visual,
        evidence_kind=measurement.evidence_kind,
        anchor=DistanceAnchor(
            anchor_id="lidar-distance-" + request.measurement_ref.artifact_checksum.removeprefix("sha256:"),
            source_master=measurement.source_master,
            point_a=points[0],
            point_b=points[1],
            distance_m=measurement.distance_m(),
            measurement_ref=request.measurement_ref,
        ),
        frame=measurement.frame,
    )
