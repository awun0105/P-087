"""Service tạo, thẩm định và xuất bản ReconstructionBundle cho EX-SCENE (REC-10)."""

import hashlib
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
from src.services.reconstruction.rgb.publication import ArtifactWriter


class BundleBuildRequest(ContractModel):
    """Yêu cầu tạo ReconstructionBundle tổng hợp cho scene."""

    job_id: Identifier
    source_input_checksum: Checksum
    input_configuration: InputConfiguration
    metric_scale: MetricScale = Field(
        default_factory=lambda: MetricScale(status=MetricScaleStatus.CONFIRMED, meters_per_unit=1.0)
    )
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    rgb_frame_refs: list[ProductArtifactRef] = Field(default_factory=list)
    camera_pose_refs: list[ProductArtifactRef] = Field(default_factory=list)
    visual_artifact_ref: ProductArtifactRef | None = None
    rgb_geometry_ref: ProductArtifactRef | None = None
    lidar_geometry_ref: ProductArtifactRef | None = None
    alignment_record: AlignmentRecord | None = None
    depth_frame_set: DepthFrameSet | None = None
    canonical_geometry_ref: ProductArtifactRef | None = None
    provenance: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.canonical_geometry_ref is None and self.rgb_geometry_ref is not None:
            self.canonical_geometry_ref = self.rgb_geometry_ref
        if self.input_configuration.rgb_present and self.input_configuration.registered_lidar_present:
            if self.alignment_record is None or self.alignment_record.status != "CONFIRMED":
                raise ValueError("mixed RGB/LiDAR bundle requires confirmed alignment")
        return self


def _dump(obj: object | None) -> dict | None:
    return obj.model_dump(mode="json") if obj is not None else None


class ReconstructionBundleService:
    """Service chịu trách nhiệm lắp ráp và công bố ReconstructionBundle chính thức."""

    def __init__(self, writer: ArtifactWriter) -> None:
        self.writer = writer

    def build_and_publish(self, request: BundleBuildRequest) -> tuple[ReconstructionBundle, ProductArtifactRef]:
        """Lắp ráp bundle, tính toán checksum bất biến và xuất bản artifact."""
        request = BundleBuildRequest.model_validate(request.model_dump())
        bundle = self._construct_bundle(request)
        payload = bundle.model_dump_json(indent=2).encode() + b"\n"
        ref = self._publish_bundle(request.job_id, bundle, payload)
        return bundle, ref

    def _construct_bundle(self, request: BundleBuildRequest) -> ReconstructionBundle:
        uri = f"artifact://jobs/{request.job_id}/reconstruction/bundle.json"
        if request.canonical_geometry_ref is None:
            raise ValueError("canonical_geometry_ref is required for ReconstructionBundle")
        data = dict(
            artifact_type="ReconstructionBundle",
            schema_version="1.0",
            artifact_uri=uri,
            artifact_checksum="sha256:" + "0" * 64,
            producer_stage=StageId.METRIC_CANONICALIZE,
            job_id=request.job_id,
            source_input_checksum=request.source_input_checksum,
            input_configuration=request.input_configuration.model_dump(mode="json"),
            coordinate_system=request.coordinate_system.model_dump(mode="json"),
            metric_scale=request.metric_scale.model_dump(mode="json"),
            rgb_frame_refs=[r.model_dump(mode="json") for r in request.rgb_frame_refs],
            depth_frame_set=_dump(request.depth_frame_set),
            camera_pose_refs=[r.model_dump(mode="json") for r in request.camera_pose_refs],
            visual_artifact_ref=_dump(request.visual_artifact_ref),
            rgb_geometry_ref=_dump(request.rgb_geometry_ref),
            lidar_geometry_ref=_dump(request.lidar_geometry_ref),
            alignment_record=_dump(request.alignment_record),
            canonical_geometry_ref=request.canonical_geometry_ref.model_dump(mode="json"),
            provenance=request.provenance,
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
