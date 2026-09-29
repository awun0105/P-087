"""Fixture pipeline có một job xuyên REC-02A→03→04→06→05→10, không giả GPU acceptance."""

import hashlib
import json
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import MetricScale
from src.models.contracts.manifests import InputConfiguration
from src.services.reconstruction.adapters.gaussian_scale import SplatTransformSimilarityAdapter
from src.services.reconstruction.adapters.splat import SplatRuntimeSettings
from src.services.reconstruction.adapters.voxel import SplatTransformVoxelAdapter
from src.services.reconstruction.adapters.voxel_runtime import VoxelRuntimeSettings
from src.services.reconstruction.bundle import BundleBuildRequest
from src.services.reconstruction.rgb.bundle_metric import BundleMetricDependencies, BundleMetricVerifier
from src.services.reconstruction.rgb.bundle_metric_models import BundleMetricAcceptance, BundleMetricRequest
from src.services.reconstruction.rgb.canonical_poses import CanonicalPoseService
from src.services.reconstruction.rgb.canonical_visual import CanonicalVisualDependencies, CanonicalVisualService
from src.services.reconstruction.rgb.canonical_visual_models import CanonicalVisualRequest
from src.services.reconstruction.rgb.geometry_publication import (
    GeometryDependencies,
    GeometryExecutionRequest,
    GeometryPublisher,
    RgbGeometryService,
)
from src.services.reconstruction.rgb.metric import MetricCanonicalizer, MetricDependencies
from src.services.reconstruction.rgb.metric_models import DistanceAnchor, MetricAcceptance, MetricPreview
from src.services.reconstruction.rgb.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.visual_publication import VisualResolver
from tests.test_reconstruction.support.rec06_fixtures import _request
from tests.test_reconstruction.test_rec05_adapter import FixtureProcess, config
from tests.test_reconstruction.test_rec06_canonical_visual import FixturePackaging
from tests.test_reconstruction.test_rec11_preview import preview


def evidence(service: MetricCanonicalizer, name: str, payload: dict) -> ProductArtifactRef:
    """Opaque fixture decisions luôn ghi nhãn synthetic, không định nghĩa auth format PRODUCT."""
    encoded = json.dumps(payload, sort_keys=True).encode()
    ref = ProductArtifactRef(
        artifact_type="SyntheticMetricEvidence",
        schema_version="1.0",
        job_id="input",
        data_class="derived",
        artifact_uri=f"artifact://jobs/input/evidence/{name}.json",
        artifact_checksum="sha256:" + hashlib.sha256(encoded).hexdigest(),
        producer_stage="ST-METRIC-CANONICALIZE",
        source_provenance={"evidence_kind": "synthetic_fixture"},
    )
    service.deps.writer.publish(ref, encoded)
    return ref


def prepared(root: Path) -> tuple:
    worker, request, resolver = preview(root)
    result, _ = worker.run(request, root / "preview")
    assert result.preview_complete
    sources = VisualResolver(resolver.require, CameraPoseResolver(resolver.require, worker.deps.frames))

    def verify(candidate: MetricPreview, acceptance: MetricAcceptance) -> bool:
        data = json.loads(sources.require(acceptance.decision_ref).read_bytes())
        return candidate.request.evidence_kind == "synthetic_fixture" and data == {"preview": candidate.checksum()}

    canonicalizer = MetricCanonicalizer(MetricDependencies(sources, worker.deps.writer, verify))
    measured = evidence(canonicalizer, "anchor", {"fixture_distance_m": 1})
    raw = sources.load(result.raw_visual_ref)
    candidate = canonicalizer.preview(_request(result.raw_visual_ref, raw.master, measured))
    acceptance = MetricAcceptance(
        preview_checksum=candidate.checksum(),
        evidence_kind="synthetic_fixture",
        decision_ref=evidence(canonicalizer, "anchor-review", {"preview": candidate.checksum()}),
    )
    confirmation = canonicalizer.publish(canonicalizer.confirm(candidate, acceptance), request.job_id)
    return worker, resolver, canonicalizer, confirmation


def derivatives(root: Path) -> tuple:
    worker, resolver, canonicalizer, confirmation = prepared(root)
    poses = CanonicalPoseService(canonicalizer).publish(confirmation)
    process = FixtureProcess(VoxelRuntimeSettings(cli=Path("unused"), module_path=Path("unused")))
    service = CanonicalVisualService(
        CanonicalVisualDependencies(
            canonicalizer,
            SplatTransformSimilarityAdapter(process),
            FixturePackaging(SplatRuntimeSettings(module_path=Path("unused")), worker.deps.brush),
        )
    )
    manifest = service.execute(
        CanonicalVisualRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=confirmation,
            canonical_pose_ref=poses,
        ),
        root / "canonical",
    )
    geometry = geometry_derivative(service, confirmation, root)
    return service, resolver, confirmation, manifest, geometry


def geometry_derivative(
    service: CanonicalVisualService, confirmation: ProductArtifactRef, root: Path
) -> ProductArtifactRef:
    canonicalizer = service.canonicalizer
    raw = canonicalizer.load(confirmation).preview.request.source_visual
    process = FixtureProcess(VoxelRuntimeSettings(cli=Path("unused"), module_path=Path("unused")))
    geometry = RgbGeometryService(
        GeometryDependencies(
            canonicalizer,
            canonicalizer.deps.visuals,
            SplatTransformVoxelAdapter(process),
            GeometryPublisher(canonicalizer.deps.writer, "input"),
        )
    ).execute(
        GeometryExecutionRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=confirmation,
            source_visual=raw,
            config=config(),
            job_id="input",
        ),
        root / "geometry",
    )
    return geometry.geometry_ref


def fixture(root: Path) -> tuple:
    """Không remap artifact thủ công: tất cả refs do producer pipeline phát hành."""
    service, resolver, confirmation, manifest_ref, geometry = derivatives(root)
    manifest = service.load(manifest_ref)
    raw = service.canonicalizer.load(confirmation).preview.request
    frames = service.visuals.poses.frames.load(service.visuals.load(raw.source_visual).source_frame_set)
    bundle = BundleBuildRequest(
        job_id="input",
        source_input_checksum=frames.input_manifest_checksum,
        input_configuration=InputConfiguration(rgb_present=True, registered_lidar_present=False),
        metric_scale=MetricScale(status="CONFIRMED", meters_per_unit=1),
        rgb_frame_refs=[frame.image for frame in frames.frames],
        camera_pose_refs=[manifest.request.canonical_pose_ref],
        visual_artifact_ref=manifest.delivery_ref(),
        rgb_geometry_ref=geometry,
        canonical_geometry_ref=geometry,
        provenance={"evidence_kind": "synthetic_fixture"},
    )
    request = BundleMetricRequest(
        execution_scope="synthetic_fixture",
        bundle=bundle,
        confirmation_ref=confirmation,
        canonical_visual_ref=manifest_ref,
        independent_sample=independent_sample(service, raw.anchor.source_master),
        tolerance_m=0.02,
    )
    return reviewed(service, request), request, resolver


def independent_sample(service: CanonicalVisualService, master: ProductArtifactRef) -> DistanceAnchor:
    """Known dimensions fixture độc lập với pair calibration, cùng raw master."""
    return DistanceAnchor(
        anchor_id="independent",
        source_master=master,
        point_a=(0, 0, 3),
        point_b=(0, 0.25, 3),
        distance_m=0.5,
        measurement_ref=evidence(service.canonicalizer, "independent", {"fixture_distance_m": 0.5}),
    )


def reviewed(service: CanonicalVisualService, request: BundleMetricRequest) -> tuple:
    """Review port kiểm exact fixture decision, không dùng lambda True."""
    decision = evidence(service.canonicalizer, "bundle-review", {"request_checksum": request.checksum()})
    acceptance = BundleMetricAcceptance(
        request_checksum=request.checksum(),
        evidence_kind="synthetic_fixture",
        decision_ref=decision,
    )

    def verify(candidate: BundleMetricRequest, review: BundleMetricAcceptance) -> bool:
        stored = json.loads(service.visuals.require(review.decision_ref).read_bytes())
        return review.evidence_kind == "synthetic_fixture" and stored == {"request_checksum": candidate.checksum()}

    verifier = BundleMetricVerifier(BundleMetricDependencies(service, verify, "synthetic_fixture"))
    return verifier, acceptance
