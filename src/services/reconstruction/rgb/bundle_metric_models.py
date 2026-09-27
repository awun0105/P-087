"""Review/verification nội bộ REC-06 cho exact RGB bundle candidate, không đổi shared schema."""

import hashlib
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, canonical_json_bytes
from src.services.reconstruction.bundle import BundleBuildRequest
from src.services.reconstruction.rgb.metric_models import DistanceAnchor, EvidenceKind


class BundleMetricRequest(ContractModel):
    """Tolerance/sample phải khóa trong review, không tự chọn lại để làm error pass."""

    execution_scope: Literal["product", "synthetic_fixture"] = "product"
    bundle: BundleBuildRequest
    confirmation_ref: ProductArtifactRef
    canonical_visual_ref: ProductArtifactRef
    independent_sample: DistanceAnchor
    tolerance_m: FiniteFloat = Field(gt=0)

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if self.bundle.verification_ref is not None:
            raise ValueError("verification candidate cannot contain its own proof reference")
        if not self.bundle.input_configuration.rgb_present or self.bundle.depth_frame_set is not None:
            raise ValueError("this verifier supports RGB without sensor depth; other paths need their verifier")
        if self.bundle.canonical_geometry_ref != self.bundle.rgb_geometry_ref or self.bundle.rgb_geometry_ref is None:
            raise ValueError("RGB verifier requires canonical geometry to be the checked RGB geometry")
        if len(self.bundle.camera_pose_refs) != 1:
            raise ValueError("RGB verifier requires one canonical camera pose manifest")
        return self

    def checksum(self) -> str:
        """Mọi input/config/provenance tham gia identity của review."""
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self)).hexdigest()


class BundleMetricAcceptance(ContractModel):
    """Authenticated authority phải xác minh decision và measurement protocol cho candidate này."""

    request_checksum: Checksum
    evidence_kind: EvidenceKind
    decision_ref: ProductArtifactRef


class BundleMetricRecord(ContractModel):
    """Metric proof không là physics/Isaac acceptance hoặc verification của mixed alignment."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["ReconstructionMetricVerification"] = "ReconstructionMetricVerification"
    scope: Literal["canonical_rgb_bundle_metric"] = "canonical_rgb_bundle_metric"
    status: Literal["VERIFIED"] = "VERIFIED"
    request: BundleMetricRequest
    acceptance: BundleMetricAcceptance
    independent_distance_error_m: FiniteFloat = Field(ge=0)
    record_checksum: Checksum

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if self.acceptance.request_checksum != self.request.checksum():
            raise ValueError("metric decision belongs to a different bundle candidate")
        if canonical_content_checksum(self, "record_checksum") != self.record_checksum:
            raise ValueError("bundle metric record checksum mismatch")
        return self
