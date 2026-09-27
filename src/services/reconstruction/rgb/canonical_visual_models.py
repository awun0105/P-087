"""Records nội bộ cho metric visual publication, không cấp final scene approval."""

from typing import Literal, Self

from pydantic import model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.reconstruction import VisualArtifact
from src.services.reconstruction.adapters.gaussian_scale import GaussianTransformReceipt
from src.services.reconstruction.rgb.visual import SplatInspection


class CanonicalVisualRequest(ContractModel):
    """Nguồn raw chỉ lấy từ confirmation; không cho caller đưa derivative vào scale lại."""

    execution_scope: Literal["product", "synthetic_fixture"] = "product"
    confirmation_ref: ProductArtifactRef
    canonical_pose_ref: ProductArtifactRef


class CanonicalVisualManifest(ContractModel):
    """Manifest commit cuối: master metric, SOG delivery và receipt của qualified codec."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["CanonicalVisualManifest"] = "CanonicalVisualManifest"
    request: CanonicalVisualRequest
    master_ref: ProductArtifactRef
    visual: VisualArtifact
    transform_receipt: GaussianTransformReceipt
    inspection: SplatInspection
    artifact_checksum: Checksum

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if canonical_content_checksum(self, "artifact_checksum") != self.artifact_checksum:
            raise ValueError("canonical visual manifest content checksum mismatch")
        return self

    def delivery_ref(self) -> ProductArtifactRef:
        """Shared ref trỏ trực tiếp SOG bytes, không trỏ JSON rồi giả thành Gaussian."""
        visual = self.visual
        return ProductArtifactRef(
            artifact_type=visual.artifact_type,
            schema_version=visual.schema_version,
            artifact_uri=visual.artifact_uri,
            artifact_checksum=visual.artifact_checksum,
            producer_stage=visual.producer_stage,
            job_id=visual.job_id,
            data_class="derived",
            source_provenance=visual.provenance,
        )
