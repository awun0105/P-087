"""Publish a QA-gated LiDAR collision candidate without selecting it in SceneIR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self, TypeVar

import numpy as np
from pydantic import model_validator

from src.models.contracts.artifacts import ArtifactDataClass, Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.collision_quality import (
    CollisionInputMode,
    LidarAlignedPointCloudEvidence,
    LidarSelfMaskEvidence,
)
from src.models.contracts.floor_model import FloorFitEvidence
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.lidar_calibration_qa import LidarCalibrationQAReport
from src.models.contracts.lidar_projection_qa import LidarCalibrationProjectionEvidence
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import ReconstructionBundle
from src.services.orchestration.artifacts.checksum import sha256_bytes
from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.adapters.lidar_collision import (
    LidarCollisionProfile,
    build_lidar_collision_candidate,
    lidar_self_mask_binding_checksum,
)
from src.services.reconstruction.lidar.collision_eligibility import (
    LidarCollisionEligibilityAssessment,
    LidarCollisionEligibilityInputs,
    alignment_reference,
    bundle_ref,
    evaluate_lidar_collision_eligibility,
)
from src.services.reconstruction.lidar.package import LidarPackageRecord
from src.services.scene.floor_model import point_cloud_checksum

TContract = TypeVar("TContract", bound=ContractModel)


class LidarCollisionCandidateManifest(ContractModel):
    """Commit record linking an immutable candidate to its exact QA and build evidence."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["LidarCollisionCandidateManifest"] = "LidarCollisionCandidateManifest"
    job_id: Identifier
    input_mode: CollisionInputMode
    source_geometry_ref: ProductArtifactRef
    alignment_ref: ProductArtifactRef
    aligned_point_cloud_ref: ProductArtifactRef
    floor_evidence_ref: ProductArtifactRef
    self_mask_evidence_ref: ProductArtifactRef
    eligibility_evidence_refs: list[ProductArtifactRef]
    profile: LidarCollisionProfile
    profile_checksum: Checksum
    source_point_checksum: Checksum
    self_mask_binding_checksum: Checksum
    output_collision_checksum: Checksum
    candidate_ref: ProductArtifactRef
    build_report_ref: ProductArtifactRef
    eligibility: LidarCollisionEligibilityAssessment

    @model_validator(mode="after")
    def _validate_bindings(self) -> Self:
        references = (
            self.source_geometry_ref,
            self.alignment_ref,
            self.aligned_point_cloud_ref,
            self.floor_evidence_ref,
            self.self_mask_evidence_ref,
            self.candidate_ref,
            self.build_report_ref,
            *self.eligibility_evidence_refs,
        )
        if any(
            reference.job_id != self.job_id or not reference.artifact_uri.startswith(f"artifact://jobs/{self.job_id}/")
            for reference in references
        ):
            raise ValueError("collision candidate manifest refs must belong to the same job")
        if (
            self.source_geometry_ref.artifact_type != "LiDARGeometryArtifact"
            or self.source_geometry_ref.producer_stage != StageId.LIDAR_INGEST
            or self.alignment_ref.artifact_type != "AlignmentRecord"
            or self.alignment_ref.producer_stage != StageId.RGB_LIDAR_ALIGN
            or self.aligned_point_cloud_ref.artifact_type != "LidarAlignedPointCloudEvidence"
            or self.aligned_point_cloud_ref.producer_stage != StageId.COLLIDER
            or self.floor_evidence_ref.artifact_type != "FloorFitEvidence"
            or self.floor_evidence_ref.producer_stage != StageId.OBJECT_EXTRACT
            or self.self_mask_evidence_ref.artifact_type != "LidarSelfMaskEvidence"
            or self.self_mask_evidence_ref.producer_stage != StageId.COLLIDER
        ):
            raise ValueError("collision candidate manifest input refs have the wrong artifact contract")
        if (
            self.candidate_ref.artifact_type != "LidarCollisionCandidate"
            or self.candidate_ref.producer_stage != StageId.COLLIDER
            or self.candidate_ref.artifact_checksum != self.output_collision_checksum
            or self.build_report_ref.artifact_type != "LidarCollisionBuildReport"
            or self.build_report_ref.producer_stage != StageId.COLLIDER
        ):
            raise ValueError("collision candidate manifest output refs do not match the published build")
        if self.input_mode != CollisionInputMode.LIDAR_SENSOR_PACKAGE:
            raise ValueError("only the qualified sensor-package collision route publishes in this sprint")
        if self.eligibility.state != "eligible":
            raise ValueError("collision candidate manifest requires an eligible assessment")
        if (
            self.eligibility.input_mode != self.input_mode
            or self.eligibility.source_geometry_ref != self.source_geometry_ref
            or self.eligibility.profile_checksum != self.profile_checksum
            or self.profile.checksum() != self.profile_checksum
        ):
            raise ValueError("collision candidate manifest differs from its eligibility assessment")
        required_evidence_refs = (
            self.source_geometry_ref,
            self.alignment_ref,
            self.aligned_point_cloud_ref,
            self.floor_evidence_ref,
            self.self_mask_evidence_ref,
        )
        if any(reference not in self.eligibility_evidence_refs for reference in required_evidence_refs):
            raise ValueError("collision candidate manifest omits a source or QA evidence reference")
        if self.eligibility.evidence_refs != self.eligibility_evidence_refs:
            raise ValueError("collision candidate manifest evidence differs from the eligibility assessment")
        return self


@dataclass(frozen=True)
class LidarCollisionCandidatePublication:
    """Blocked assessment or fully published candidate/report/manifest triple."""

    assessment: LidarCollisionEligibilityAssessment
    candidate_ref: ProductArtifactRef | None = None
    build_report_ref: ProductArtifactRef | None = None
    manifest_ref: ProductArtifactRef | None = None


class LidarCollisionCandidatePublisher:
    """Build and publish only after the source-specific eligibility gate passes.

    The caller supplies the checksum-resolved world-meter point array and its exact
    self-mask. This service verifies both against the aligned-cloud and self-mask
    receipts before invoking the bounded adapter. It does not mutate SceneIR or
    make a source-selection decision; source-aware ownership must land first.
    """

    def __init__(self, writer: FilesystemArtifactStore) -> None:
        self.writer = writer

    def publish(
        self,
        inputs: LidarCollisionEligibilityInputs,
        points_world_m: np.ndarray,
        self_mask: np.ndarray,
    ) -> LidarCollisionCandidatePublication:
        """Publish content-addressed artifacts, with the manifest committed last."""
        assessment = evaluate_lidar_collision_eligibility(inputs)
        if assessment.state != "eligible":
            return LidarCollisionCandidatePublication(assessment=assessment)

        bundle = inputs.bundle
        aligned = inputs.aligned_point_cloud
        floor_evidence = inputs.floor_evidence
        self_mask_evidence = inputs.self_mask_evidence
        if (
            bundle is None
            or bundle.alignment_record is None
            or bundle.lidar_geometry_ref is None
            or aligned is None
            or inputs.aligned_point_cloud_ref is None
            or floor_evidence is None
            or inputs.floor_evidence_ref is None
            or self_mask_evidence is None
            or inputs.self_mask_evidence_ref is None
            or inputs.profile is None
        ):
            raise ValueError("eligible assessment is missing one or more exact publication inputs")
        if (
            assessment.source_geometry_ref != bundle.lidar_geometry_ref
            or assessment.profile_checksum != inputs.profile.checksum()
        ):
            raise ValueError("eligible assessment changed source geometry or collision profile identity")

        for reference in assessment.evidence_refs:
            self.writer.resolver.require(reference)

        points = np.asarray(points_world_m)
        if (
            points.ndim != 2
            or points.shape[1] != 3
            or not np.issubdtype(points.dtype, np.number)
            or not np.isfinite(points).all()
        ):
            raise ValueError("aligned LiDAR points must be a finite numeric (N, 3) world-meter array")
        observed_point_checksum = point_cloud_checksum(points)
        if len(points) != aligned.point_count or observed_point_checksum != aligned.point_cloud_checksum:
            raise ValueError("world points do not match the exact aligned-cloud receipt")
        if (
            floor_evidence.source_artifact_ref != inputs.aligned_point_cloud_ref
            or floor_evidence.point_cloud_checksum != observed_point_checksum
        ):
            raise ValueError("floor evidence does not match the exact aligned point cloud")

        mask = np.asarray(self_mask)
        mask_checksum = lidar_self_mask_binding_checksum(observed_point_checksum, mask)
        if (
            mask.shape != (aligned.point_count,)
            or mask_checksum != self_mask_evidence.mask_binding_checksum
            or int(mask.sum()) != self_mask_evidence.masked_point_count
        ):
            raise ValueError("self-mask bytes do not match the exact point-order-bound receipt")

        alignment_ref = alignment_reference(bundle.alignment_record)
        if alignment_ref is None:
            raise ValueError("eligible assessment has no exact alignment reference")
        build = build_lidar_collision_candidate(
            points,
            floor_evidence.floor_model,
            inputs.profile,
            self_mask=mask,
            self_mask_ref=inputs.self_mask_evidence_ref,
        )
        if build.report.self_mask_binding_checksum != mask_checksum:
            raise ValueError("mesh builder changed the self-mask binding identity")

        provenance = {
            "input_mode": inputs.input_mode.value,
            "source_geometry_ref": bundle.lidar_geometry_ref.model_dump(mode="json"),
            "alignment_ref": alignment_ref.model_dump(mode="json"),
            "aligned_point_cloud_ref": inputs.aligned_point_cloud_ref.model_dump(mode="json"),
            "floor_evidence_ref": inputs.floor_evidence_ref.model_dump(mode="json"),
            "self_mask_evidence_ref": inputs.self_mask_evidence_ref.model_dump(mode="json"),
            "profile_checksum": inputs.profile.checksum(),
            "eligibility_evidence_refs": [ref.model_dump(mode="json") for ref in assessment.evidence_refs],
        }
        identity_payload = canonical_json_bytes(
            {
                "provenance": provenance,
                "assessment": assessment.model_dump(mode="json"),
                "source_point_checksum": observed_point_checksum,
                "self_mask_binding_checksum": mask_checksum,
                "output_collision_checksum": build.report.output_collision_checksum,
            }
        )
        identity = sha256_bytes(identity_payload).removeprefix("sha256:")
        prefix = f"artifact://jobs/{bundle.job_id}/collider/lidar-candidate/{identity}"

        candidate_ref = _product_ref(
            "LidarCollisionCandidate",
            f"{prefix}/collision.glb",
            build.report.output_collision_checksum,
            bundle.job_id,
            provenance,
        )
        report_payload = build.report.model_dump_json(indent=2).encode("utf-8") + b"\n"
        build_report_ref = _product_ref(
            "LidarCollisionBuildReport",
            f"{prefix}/build-report.json",
            sha256_bytes(report_payload),
            bundle.job_id,
            provenance,
        )
        manifest = LidarCollisionCandidateManifest(
            job_id=bundle.job_id,
            input_mode=inputs.input_mode,
            source_geometry_ref=bundle.lidar_geometry_ref,
            alignment_ref=alignment_ref,
            aligned_point_cloud_ref=inputs.aligned_point_cloud_ref,
            floor_evidence_ref=inputs.floor_evidence_ref,
            self_mask_evidence_ref=inputs.self_mask_evidence_ref,
            eligibility_evidence_refs=assessment.evidence_refs,
            profile=inputs.profile,
            profile_checksum=inputs.profile.checksum(),
            source_point_checksum=observed_point_checksum,
            self_mask_binding_checksum=mask_checksum,
            output_collision_checksum=build.report.output_collision_checksum,
            candidate_ref=candidate_ref,
            build_report_ref=build_report_ref,
            eligibility=assessment,
        )
        manifest_payload = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
        manifest_ref = _product_ref(
            manifest.artifact_type,
            f"{prefix}/candidate-manifest.json",
            sha256_bytes(manifest_payload),
            bundle.job_id,
            provenance,
        )

        # The manifest is the commit marker. A failed report/manifest write leaves
        # only unreferenced immutable artifacts, which a retry reuses by checksum.
        self._publish_or_verify(candidate_ref, build.glb_bytes)
        self._publish_or_verify(build_report_ref, report_payload)
        self._publish_or_verify(manifest_ref, manifest_payload)
        return LidarCollisionCandidatePublication(
            assessment=assessment,
            candidate_ref=candidate_ref,
            build_report_ref=build_report_ref,
            manifest_ref=manifest_ref,
        )

    def _publish_or_verify(self, reference: ProductArtifactRef, payload: bytes) -> None:
        if sha256_bytes(payload) != reference.artifact_checksum:
            raise ValueError("publication payload differs from its immutable artifact reference")
        resolver = self.writer.resolver
        existing = resolver.locate(reference.artifact_uri, fresh=True)
        if existing is not None:
            resolver.require(reference)
            resolver.published(reference.artifact_uri)
            return
        try:
            observed = self.writer.publish(reference, payload)
        except ArtifactAlreadyExistsError:
            resolver.require(reference)
            resolver.published(reference.artifact_uri)
            return
        if observed != reference:
            raise ValueError("artifact writer changed collision candidate identity")


def load_lidar_collision_eligibility_inputs(
    manifest: LidarCollisionCandidateManifest,
    resolver: ArtifactResolver,
) -> LidarCollisionEligibilityInputs:
    """Reload the exact immutable receipts needed to re-run candidate eligibility.

    Selection/export consumers must not trust the serialized ``eligible`` flag by
    itself. This reconstructs the assessment inputs from the manifest's bound refs
    and lets the same source-of-truth gate make the decision again.
    """
    for reference in manifest.eligibility_evidence_refs:
        resolver.require(reference)

    def required_ref(artifact_type: str) -> ProductArtifactRef:
        matches = [ref for ref in manifest.eligibility_evidence_refs if ref.artifact_type == artifact_type]
        if len(matches) != 1:
            raise ValueError(f"candidate manifest requires exactly one {artifact_type} evidence reference")
        return matches[0]

    def load(model_type: type[TContract], artifact_type: str) -> tuple[ProductArtifactRef, TContract]:
        reference = required_ref(artifact_type)
        return reference, model_type.model_validate_json(resolver.require(reference).read_bytes())

    bundle_reference, bundle = load(ReconstructionBundle, "ReconstructionBundle")
    package_ref, package = load(LidarPackageRecord, "LidarPackageRecord")
    calibration_qa_ref, calibration_qa = load(LidarCalibrationQAReport, "LidarCalibrationQAReport")
    projection_evidence_ref, projection_evidence = load(
        LidarCalibrationProjectionEvidence, "LidarCalibrationProjectionEvidence"
    )
    aligned_point_cloud_ref, aligned_point_cloud = load(
        LidarAlignedPointCloudEvidence, "LidarAlignedPointCloudEvidence"
    )
    floor_evidence_ref, floor_evidence = load(FloorFitEvidence, "FloorFitEvidence")
    self_mask_evidence_ref, self_mask_evidence = load(LidarSelfMaskEvidence, "LidarSelfMaskEvidence")
    if bundle_ref(bundle) != bundle_reference:
        raise ValueError("candidate manifest bundle evidence identity differs from its serialized bundle")
    return LidarCollisionEligibilityInputs(
        input_mode=manifest.input_mode,
        bundle=bundle,
        package_ref=package_ref,
        package=package,
        calibration_qa_ref=calibration_qa_ref,
        calibration_qa=calibration_qa,
        projection_evidence_ref=projection_evidence_ref,
        projection_evidence=projection_evidence,
        aligned_point_cloud_ref=aligned_point_cloud_ref,
        aligned_point_cloud=aligned_point_cloud,
        floor_evidence_ref=floor_evidence_ref,
        floor_evidence=floor_evidence,
        self_mask_evidence_ref=self_mask_evidence_ref,
        self_mask_evidence=self_mask_evidence,
        profile=manifest.profile,
    )


def _product_ref(
    artifact_type: str,
    artifact_uri: str,
    artifact_checksum: Checksum,
    job_id: str,
    source_provenance: dict[str, object],
) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=artifact_uri,
        artifact_checksum=artifact_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.COLLIDER,
        job_id=job_id,
        source_provenance=source_provenance,
    )
