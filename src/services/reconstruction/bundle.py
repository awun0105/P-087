"""Service tạo, thẩm định và xuất bản ReconstructionBundle cho EX-SCENE (REC-10)."""

import hashlib
import json
from typing import Self

from pydantic import Field, model_validator

from src.models.contracts.artifacts import (
    ArtifactDataClass,
    Checksum,
    ContractModel,
    Identifier,
    JsonObject,
    ProductArtifactRef,
)
from src.models.contracts.coordinates import CoordinateSystem, MetricScale, MetricScaleStatus
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import InputConfiguration, StageId
from src.models.contracts.reconstruction import AlignmentRecord, DepthFrameSet, ReconstructionBundle
from src.services.reconstruction.bundle_validation import BundleDependencies, validate_bundle_sources
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter


class BundleBuildRequest(ContractModel):
    """Yêu cầu tạo ReconstructionBundle tổng hợp cho scene."""

    job_id: Identifier
    source_input_checksum: Checksum
    input_configuration: InputConfiguration
    metric_scale: MetricScale = Field(default_factory=lambda: MetricScale(status=MetricScaleStatus.UNCONFIRMED))
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    rgb_frame_refs: list[ProductArtifactRef] = Field(default_factory=list)
    camera_pose_refs: list[ProductArtifactRef] = Field(default_factory=list)
    visual_artifact_ref: ProductArtifactRef | None = None
    rgb_geometry_ref: ProductArtifactRef | None = None
    lidar_geometry_ref: ProductArtifactRef | None = None
    alignment_record: AlignmentRecord | None = None
    depth_frame_set: DepthFrameSet | None = None
    canonical_geometry_ref: ProductArtifactRef | None = None
    verification_ref: ProductArtifactRef | None = None
    provenance: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.input_configuration.rgb_present and self.input_configuration.registered_lidar_present:
            if self.alignment_record is None or self.alignment_record.status != "CONFIRMED":
                raise ValueError("mixed RGB/LiDAR bundle requires confirmed alignment")
        return self


def _dump(obj: ContractModel | None) -> dict | None:
    return obj.model_dump(mode="json") if obj is not None else None


class ReconstructionBundleService:
    """Service chịu trách nhiệm lắp ráp và công bố ReconstructionBundle chính thức."""

    def __init__(self, writer: ArtifactWriter, dependencies: BundleDependencies | None = None) -> None:
        self.writer = writer
        self.dependencies = dependencies

    def build_and_publish(self, request: BundleBuildRequest) -> tuple[ReconstructionBundle, ProductArtifactRef]:
        """Lắp ráp bundle, tính toán checksum bất biến và xuất bản artifact."""
        request = BundleBuildRequest.model_validate(request.model_dump())
        if self.dependencies is None:
            raise ValueError("bundle dependency resolver/verifiers are not configured")
        validate_bundle_sources(request, self.dependencies)
        bundle = self._construct_bundle(request)
        payload = bundle.model_dump_json(indent=2).encode() + b"\n"
        ref = self._publish_bundle(request.job_id, bundle, payload)
        self.dependencies.require(ref, request.job_id)
        return bundle, ref

    def _construct_bundle(self, request: BundleBuildRequest) -> ReconstructionBundle:
        identity = hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        uri = f"artifact://jobs/{request.job_id}/reconstruction/{identity}/bundle.json"
        if request.canonical_geometry_ref is None:
            raise ValueError("canonical_geometry_ref is required for ReconstructionBundle")
        data = request.model_dump(mode="json", exclude={"verification_ref"})
        data.update(
            artifact_type="ReconstructionBundle",
            schema_version="1.0",
            artifact_uri=uri,
            artifact_checksum="sha256:" + "0" * 64,
            producer_stage=StageId.METRIC_CANONICALIZE,
            provenance=request.provenance | {"metric_verification_ref": _dump(request.verification_ref)},
        )
        data["artifact_checksum"] = canonical_content_checksum(data, "artifact_checksum")
        return ReconstructionBundle.model_validate(data)

    def _publish_bundle(self, job_id: str, bundle: ReconstructionBundle, payload: bytes) -> ProductArtifactRef:
        ref = ProductArtifactRef(
            artifact_type="ReconstructionBundle",
            schema_version="1.0",
            artifact_uri=bundle.artifact_uri,
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.METRIC_CANONICALIZE,
            job_id=job_id,
            source_provenance=bundle.provenance,
        )
        if self.writer.publish(ref, payload) != ref:
            raise ValueError("artifact writer altered ReconstructionBundle identity")
        return ref
