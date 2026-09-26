"""Records nội bộ EX-REC cho anchor confirmation, chưa là shared bundle contract."""

import hashlib
import math
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.identity import canonical_content_checksum, canonical_json_bytes
from src.services.reconstruction.rgb.camera_pose import Quaternion, Vector3
from src.services.reconstruction.rgb.metric_math import SimilarityTransform, scale_from_distance, unit_quaternion

EvidenceKind = Literal["synthetic_fixture", "real_measurement"]


class DistanceAnchor(ContractModel):
    """Hai điểm trong raw PLY/SfM frame và measurement evidence được user khóa."""

    anchor_id: Identifier
    source_master: ProductArtifactRef
    point_a: Vector3
    point_b: Vector3
    distance_m: FiniteFloat = Field(gt=0)
    measurement_ref: ProductArtifactRef

    def scale(self) -> float:
        """Chỉ tính preview, không tự xác nhận measurement provenance."""
        return scale_from_distance((self.point_a, self.point_b), self.distance_m)

    @model_validator(mode="after")
    def _nondegenerate(self) -> Self:
        self.scale()
        return self


class CanonicalFrameDeclaration(ContractModel):
    """Rotation/origin explicit; không derive orientation từ một distance anchor."""

    rotation_xyzw: Quaternion
    translation_m: Vector3
    evidence_ref: ProductArtifactRef

    @model_validator(mode="after")
    def _unit_rotation(self) -> Self:
        unit_quaternion(self.rotation_xyzw)
        return self


class MetricRequest(ContractModel):
    """Mọi declaration được bind vào exact source visual và review preview."""

    source_visual: ProductArtifactRef
    anchor: DistanceAnchor
    frame: CanonicalFrameDeclaration
    evidence_kind: EvidenceKind


class MetricPreview(ContractModel):
    """Computed transform chưa confirmed; thay bất kỳ input nào phải review lại."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["UNCONFIRMED"] = "UNCONFIRMED"
    request: MetricRequest
    source_camera_poses: ProductArtifactRef
    transform: SimilarityTransform

    @model_validator(mode="after")
    def _matches_request(self) -> Self:
        frame = self.request.frame
        expected = SimilarityTransform(
            scale_m_per_sfm_unit=self.request.anchor.scale(),
            rotation_xyzw=frame.rotation_xyzw,
            translation_m=frame.translation_m,
        )
        if self.transform != expected:
            raise ValueError("preview transform differs from anchor/frame declaration")
        return self

    def checksum(self) -> str:
        """Logical preview identity gồm defaults, refs và evidence kind."""
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self)).hexdigest()


class MetricAcceptance(ContractModel):
    """Proof chỉ hợp lệ nếu injected authority verifier xác minh decision artifact."""

    preview_checksum: Checksum
    decision_ref: ProductArtifactRef
    evidence_kind: EvidenceKind


class MetricConfirmation(ContractModel):
    """Anchor/frame confirmation không có nghĩa final REC-06/physics đã đạt."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["RGBMetricConfirmation"] = "RGBMetricConfirmation"
    status: Literal["CONFIRMED"] = "CONFIRMED"
    scope: Literal["anchor_and_frame_only"] = "anchor_and_frame_only"
    preview: MetricPreview
    acceptance: MetricAcceptance
    record_checksum: Checksum

    @model_validator(mode="after")
    def _bind_review(self) -> Self:
        if self.acceptance.preview_checksum != self.preview.checksum():
            raise ValueError("acceptance belongs to a different metric preview")
        if self.acceptance.evidence_kind != self.preview.request.evidence_kind:
            raise ValueError("metric evidence kind differs from accepted preview")
        if canonical_content_checksum(self, "record_checksum") != self.record_checksum:
            raise ValueError("metric confirmation content checksum mismatch")
        return self


def confirmation_record(preview: MetricPreview, acceptance: MetricAcceptance) -> MetricConfirmation:
    """Serialize sau authority gate; hàm này tự nó không xác minh user authorization."""
    payload = dict(
        schema_version="1.0",
        artifact_type="RGBMetricConfirmation",
        status="CONFIRMED",
        scope="anchor_and_frame_only",
        preview=preview.model_dump(mode="json"),
        acceptance=acceptance.model_dump(mode="json"),
        record_checksum="sha256:" + "0" * 64,
    )
    payload["record_checksum"] = canonical_content_checksum(payload, "record_checksum")
    return MetricConfirmation.model_validate(payload)


class MetricConversionPlan(ContractModel):
    """Deterministic plan/provenance, không phải bằng chứng payload đã convert."""

    confirmation_ref: ProductArtifactRef
    confirmation_checksum: Checksum
    input_ref: ProductArtifactRef
    transform: SimilarityTransform
    evidence_kind: EvidenceKind
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    output_meters_per_unit: Literal[1.0] = 1.0
    payload_converted: Literal[False] = False


def independent_distance_error(confirmation: MetricConfirmation, sample: DistanceAnchor) -> float:
    """Fixture/local verification; không đọc eval-only data hoặc khóa tolerance ngầm."""
    confirmation = MetricConfirmation.model_validate(confirmation.model_dump())
    sample = DistanceAnchor.model_validate(sample.model_dump())
    anchor = confirmation.preview.request.anchor
    if sample.source_master != anchor.source_master:
        raise ValueError("independent distance must belong to the same source master")
    if sample.anchor_id == anchor.anchor_id or {sample.point_a, sample.point_b} == {anchor.point_a, anchor.point_b}:
        raise ValueError("calibration anchor cannot be reused as independent test distance")
    transform = confirmation.preview.transform
    measured = math.dist(transform.apply_point(sample.point_a), transform.apply_point(sample.point_b))
    error = abs(measured - sample.distance_m)
    if not math.isfinite(error):
        raise ValueError("independent distance error is not finite")
    return error
