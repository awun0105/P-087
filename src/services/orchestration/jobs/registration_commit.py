"""Commit a qualified RGB–LiDAR registration through REC-09 and REC-10."""

from __future__ import annotations

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ProductArtifactRef
from src.models.contracts.manifests import JobManifest, JobStatus, StageId, StageStatus
from src.models.contracts.reconstruction import AlignmentRecord, LiDARGeometryArtifact, ReconstructionBundle
from src.models.contracts.rgb_lidar_registration import (
    RegistrationConfirmationRecord,
    RegistrationOperationState,
    RegistrationOverlayPreview,
    RegistrationProposal,
    RegistrationProposalState,
    RegistrationQAReport,
    RegistrationQAStatus,
    RegistrationSourceCloudManifest,
    seal_registration_confirmation,
    validate_registration_overlay_binding,
    validate_registration_proposal_binding,
    validate_registration_qa_binding,
)
from src.services.orchestration.artifacts import (
    ArtifactNotFoundError,
    FilesystemArtifactStore,
    sha256_bytes,
)
from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError
from src.services.orchestration.artifacts.store import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.registration_operations import (
    RegistrationOperationRecord,
    RegistrationOperationStore,
)
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects import ProjectRegistry
from src.services.orchestration.scene.errors import SceneNotAvailableError
from src.services.reconstruction.alignment.models import AlignmentRequest
from src.services.reconstruction.alignment.service import RgbLidarAlignmentService
from src.services.reconstruction.bundle import BundleBuildRequest, ReconstructionBundleService
from src.services.reconstruction.bundle_validation import BundleDependencies
from src.services.reconstruction.lidar.models import LiDARIngestRequest
from src.services.reconstruction.rgb.canonical.bundle_metric import _reference as metric_verification_reference
from src.services.reconstruction.rgb.canonical.bundle_metric_models import BundleMetricRecord


class _IdempotentArtifactWriter:
    """Accept an exact concurrent replay while keeping published bytes immutable."""

    def __init__(self, resolver: ArtifactResolver) -> None:
        self.resolver = resolver
        self.store = FilesystemArtifactStore(resolver)

    def publish(self, reference: ArtifactRef, payload: bytes) -> ArtifactRef:
        try:
            existing = self.resolver.require(reference)
        except ArtifactNotFoundError:
            try:
                return self.store.publish(reference, payload)
            except ArtifactAlreadyExistsError:
                existing = self.resolver.require(reference)
        if existing.read_bytes() != payload:
            raise RuntimeStateConflictError("Immutable registration artifact differs from an existing publication")
        return reference


class RegistrationBundleCommitter:
    """Revalidate one user decision and publish its immutable mixed-modality bundle."""

    def __init__(self, registry: ProjectRegistry, operations: RegistrationOperationStore) -> None:
        if registry.persistence is None:
            raise RuntimeStateConflictError("Registration bundle publication requires durable project persistence")
        self.registry = registry
        self.operations = operations
        self.resolver = registry.runtime_resolver
        self.writer = _IdempotentArtifactWriter(self.resolver)

    def commit(self, operation: RegistrationOperationRecord) -> RegistrationOperationRecord:
        """Publish/recover an exact confirmation; conflicts never replace the manifest head."""
        operation = self.operations.get(operation.operation_id)
        if operation.state == RegistrationOperationState.COMMITTED:
            self._verify_committed(operation)
            return operation
        if operation.state != RegistrationOperationState.CONFIRMED:
            raise RuntimeStateConflictError("Only a confirmed registration can be committed")

        job = self.registry.get_job(operation.target_job_id)
        existing = self._existing_publication(job, operation)
        if existing is not None:
            bundle_ref, alignment_ref = existing
            return self.operations.commit(
                operation.operation_id,
                expected_operation_checksum=operation.operation_checksum,
                expected_scene_revision=operation.request.expected_scene_revision,
                bundle_ref=bundle_ref,
                alignment_ref=alignment_ref,
                manifest_checksum=job.job_manifest_checksum,
            )

        try:
            current_scene_revision = self.registry.scene.current(operation.target_job_id).scene.scene_revision
        except SceneNotAvailableError as error:
            raise RuntimeStateConflictError("Registration target scene is unavailable") from error
        if current_scene_revision != operation.request.expected_scene_revision:
            raise RuntimeStateConflictError("Scene revision changed before registration bundle publication")
        if job.status != JobStatus.SUCCEEDED:
            raise RuntimeStateConflictError("Registration bundle publication requires a completed reconstruction")

        (
            proposal,
            report,
            _overlay,
            overlay_ref,
            source_manifest,
            lidar_geometry_ref,
            lidar_metadata_ref,
        ) = self._verified_inputs(operation)
        confirmation, confirmation_ref = self._publish_confirmation(operation)
        alignment_service = self._alignment_service(operation, confirmation, confirmation_ref)
        candidate = next(item for item in proposal.candidates if item.candidate_id == operation.confirmed_candidate_id)
        evidence_refs = self._alignment_evidence(
            operation,
            report,
            overlay_ref,
            source_manifest,
            lidar_geometry_ref,
            lidar_metadata_ref,
            confirmation_ref,
        )
        alignment_request = AlignmentRequest(
            job_id=operation.target_job_id,
            rgb_geometry_ref=operation.request.target_rgb_geometry_ref,
            lidar_geometry_ref=lidar_geometry_ref,
            transform_target_from_source=candidate.transform_target_from_source,
            method="floor_constrained_bev_icp_qualified_registration",
            status="CONFIRMED",
            evidence_refs=evidence_refs,
            same_scene_attestation=True,
            provenance={
                "registration_operation_id": operation.operation_id,
                "registration_operation_checksum": confirmation.operation_checksum,
                "registration_request_checksum": operation.request_checksum,
                "registration_candidate_id": candidate.candidate_id,
                "registration_confirmation_ref": confirmation_ref.model_dump(mode="json"),
                "registration_proposal_ref": operation.proposal_ref.model_dump(mode="json"),
                "registration_qa_ref": operation.qa_report_ref.model_dump(mode="json"),
                "registration_overlay_ref": overlay_ref.model_dump(mode="json"),
                "registration_scene_revision": operation.request.expected_scene_revision,
            },
        )
        alignment_record, alignment_ref = alignment_service.align(alignment_request)

        base = job_bundle(self.registry, job)
        if base is None:
            raise RuntimeStateConflictError("Completed job has no verified ReconstructionBundle")
        request, proof = self._mixed_bundle_request(
            operation,
            base,
            alignment_record,
            lidar_geometry_ref,
            alignment_ref,
        )
        bundle_service = ReconstructionBundleService(
            self.writer,
            BundleDependencies(
                resolve=self.resolver.require,
                verify_metric=lambda candidate_request: self._preserves_metric_proof(candidate_request, proof),
                load_alignment=alignment_service.load,
            ),
        )
        bundle, bundle_ref = bundle_service.build_and_publish(request)
        try:
            updated_job = self.registry.record_registration_bundle(
                job,
                alignment_ref=alignment_ref,
                bundle_ref=bundle_ref,
                expected_scene_revision=operation.request.expected_scene_revision,
            )
        except RuntimeStateConflictError:
            latest = self.registry.get_job(operation.target_job_id)
            replay = self._existing_publication(latest, operation)
            if replay is None or replay != (bundle_ref, alignment_ref):
                raise
            updated_job = latest
        return self.operations.commit(
            operation.operation_id,
            expected_operation_checksum=operation.operation_checksum,
            expected_scene_revision=operation.request.expected_scene_revision,
            bundle_ref=bundle_ref,
            alignment_ref=alignment_ref,
            manifest_checksum=updated_job.job_manifest_checksum,
        )

    def _verified_inputs(
        self, operation: RegistrationOperationRecord
    ) -> tuple[
        RegistrationProposal,
        RegistrationQAReport,
        RegistrationOverlayPreview,
        ProductArtifactRef,
        RegistrationSourceCloudManifest,
        ProductArtifactRef,
        ProductArtifactRef,
    ]:
        request = operation.request
        if (
            operation.proposal_ref is None
            or operation.qa_report_ref is None
            or operation.confirmed_candidate_id is None
            or operation.confirmed_by_user_id is None
            or operation.confirmed_at is None
            or operation.confirmed_from_checksum is None
            or operation.request_checksum != request.request_checksum
            or request.expected_scene_revision == ""
        ):
            raise RuntimeStateConflictError("Confirmed registration is missing its exact decision evidence")
        proposal = self.resolver.load_model(operation.proposal_ref, RegistrationProposal)
        report = self.resolver.load_model(operation.qa_report_ref, RegistrationQAReport)
        validate_registration_proposal_binding(request, proposal)
        validate_registration_qa_binding(request, proposal, report)
        if (
            proposal.state != RegistrationProposalState.PROPOSED
            or proposal.selected_candidate_id != operation.confirmed_candidate_id
            or report.result != RegistrationQAStatus.PASS
            or report.candidate_id != operation.confirmed_candidate_id
            or report.same_scene_attestation is not True
            or request.source.same_scene_attestation is not True
        ):
            raise RuntimeStateConflictError("Registration QA no longer authorizes the confirmed candidate")
        candidate = next(
            (item for item in proposal.candidates if item.candidate_id == operation.confirmed_candidate_id), None
        )
        if candidate is None or (candidate.rgb_scale_factor is not None and candidate.rgb_scale_factor != 1.0):
            raise RuntimeStateConflictError("Confirmed registration has no rigid metric candidate")

        overlay_refs = [
            reference for reference in report.evidence_refs if reference.artifact_type == "RegistrationOverlayPreview"
        ]
        matching_overlays: list[tuple[RegistrationOverlayPreview, ProductArtifactRef]] = []
        for reference in overlay_refs:
            preview = self.resolver.load_model(reference, RegistrationOverlayPreview)
            validate_registration_overlay_binding(request, proposal, preview, operation.operation_id)
            if preview.candidate_id == operation.confirmed_candidate_id:
                matching_overlays.append((preview, reference))
        if len(matching_overlays) != 1:
            raise RuntimeStateConflictError("Confirmed candidate has no unique byte-verified overlay")

        source_manifest_ref = self._one_evidence_ref(report, "RegistrationSourceCloudManifest")
        source_manifest = self.resolver.load_model(source_manifest_ref, RegistrationSourceCloudManifest)
        source = request.source
        if (
            source_manifest.job_id != operation.target_job_id
            or source_manifest.source_geometry_ref != proposal.source_geometry_ref
            or source_manifest.source_input_checksum != source.source_input_checksum
            or source_manifest.source_point_count != source.source_point_count
            or source_manifest.source_distance_unit != source.source_distance_unit
            or source.source_format is None
            or source_manifest.source_format != source.source_format.value.removeprefix("point_cloud_")
            or source_manifest.source_frame != source.source_frame
            or source_manifest.input_mode != source.mode
            or source_manifest.input_assembly_id != source.input_assembly_id
            or source_manifest.input_assembly_revision != source.input_assembly_revision
            or source_manifest.input_assembly_checksum != source.input_assembly_checksum
            or source_manifest.same_scene_lineage_verified is not True
            or report.source_input_checksum != source_manifest.source_input_checksum
            or proposal.source_input_checksum != source_manifest.source_input_checksum
            or source_manifest.source_header_checksum != source.source_header_checksum
        ):
            raise RuntimeStateConflictError("Registration source manifest differs from the accepted request")
        if source_manifest.source_geometry_ref.artifact_checksum != source.source_input_checksum:
            raise RuntimeStateConflictError("Registration source-cloud bytes differ from accepted input checksum")
        self.resolver.require(source_manifest.source_geometry_ref)

        geometry_ref = self._one_evidence_ref(report, "LiDARGeometryArtifact")
        metadata_ref = self._one_evidence_ref(report, "LiDARGeometryMetadata")
        geometry = self.resolver.load_model(metadata_ref, LiDARGeometryArtifact)
        if (
            geometry_ref.job_id != operation.target_job_id
            or geometry_ref.producer_stage != StageId.LIDAR_INGEST
            or geometry_ref.artifact_type != "LiDARGeometryArtifact"
            or geometry.artifact_type != geometry_ref.artifact_type
            or geometry.artifact_uri != geometry_ref.artifact_uri
            or geometry.artifact_checksum != geometry_ref.artifact_checksum
            or geometry.source_modality != "registered_lidar"
            or geometry.source_input_checksum != geometry_ref.artifact_checksum
            or geometry.coordinate_system.unit != "meter"
            or geometry.source_frame != proposal.source_frame
            or geometry.declared_transform_to_canonical is not None
        ):
            raise RuntimeStateConflictError("Metric LiDAR geometry metadata does not bind the registered source")
        details = geometry.preprocessing_provenance.details
        if (
            details.get("registration_operation_id") != operation.operation_id
            or details.get("registration_request_checksum") != operation.request_checksum
            or details.get("source_distance_unit") != source_manifest.source_distance_unit
            or details.get("normalized_distance_unit") != "m"
            or details.get("coordinate_semantics") != "local_map_unaligned"
        ):
            raise RuntimeStateConflictError("Metric LiDAR normalization provenance is incomplete or stale")
        metric_payload_path = self.resolver.require(geometry_ref)
        ingest = LiDARIngestRequest(
            job_id=operation.target_job_id,
            lidar_file=metric_payload_path,
            source_input_checksum=geometry_ref.artifact_checksum,
            geometry_format="ply",
            coordinate_system=geometry.coordinate_system,
            source_frame=geometry.source_frame,
            preprocessing_provenance=geometry.preprocessing_provenance,
            max_points=operation.request.profile.max_source_points,
        )
        stats = ingest.validate_payload()
        if stats.point_count != source_manifest.source_point_count:
            raise RuntimeStateConflictError("Metric LiDAR point count differs from the verified source cloud")

        expected_metric_ref = ProductArtifactRef.model_validate(
            {
                "artifact_type": "LiDARGeometryArtifact",
                "schema_version": "1.0",
                "artifact_uri": geometry_ref.artifact_uri,
                "artifact_checksum": geometry_ref.artifact_checksum,
                "data_class": ArtifactDataClass.DERIVED,
                "producer_stage": StageId.LIDAR_INGEST,
                "job_id": operation.target_job_id,
                "source_provenance": geometry.preprocessing_provenance.model_dump(mode="json"),
            }
        )
        if geometry_ref != expected_metric_ref:
            raise RuntimeStateConflictError("Metric LiDAR reference provenance differs from its metadata")
        if metadata_ref.source_provenance != geometry.preprocessing_provenance.model_dump(mode="json"):
            raise RuntimeStateConflictError("Metric LiDAR metadata reference lost its preprocessing provenance")
        overlay, overlay_ref = matching_overlays[0]
        return proposal, report, overlay, overlay_ref, source_manifest, geometry_ref, metadata_ref

    def _publish_confirmation(
        self,
        operation: RegistrationOperationRecord,
    ) -> tuple[RegistrationConfirmationRecord, ProductArtifactRef]:
        if (
            operation.confirmed_candidate_id is None
            or operation.confirmed_by_user_id is None
            or operation.confirmed_at is None
            or operation.confirmed_from_checksum is None
        ):
            raise RuntimeStateConflictError("Confirmed registration has incomplete user decision fields")
        confirmation = seal_registration_confirmation(
            {
                "job_id": operation.target_job_id,
                "operation_id": operation.operation_id,
                "operation_checksum": operation.operation_checksum,
                "request_checksum": operation.request_checksum,
                "expected_scene_revision": operation.request.expected_scene_revision,
                "candidate_id": operation.confirmed_candidate_id,
                "confirmed_by_user_id": operation.confirmed_by_user_id,
                "confirmed_at": operation.confirmed_at,
                "confirmed_from_checksum": operation.confirmed_from_checksum,
                "confirmation_checksum": "sha256:" + "0" * 64,
            }
        )
        payload = confirmation.model_dump_json(indent=2).encode("utf-8") + b"\n"
        checksum = sha256_bytes(payload)
        reference = ProductArtifactRef(
            artifact_type=confirmation.artifact_type,
            schema_version=confirmation.schema_version,
            artifact_uri=(
                f"artifact://jobs/{operation.target_job_id}/rec09/registration-confirmations/"
                f"{operation.operation_id}/{confirmation.confirmation_checksum.removeprefix('sha256:')}.json"
            ),
            artifact_checksum=checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.RGB_LIDAR_ALIGN,
            job_id=operation.target_job_id,
            source_provenance={
                "operation_id": operation.operation_id,
                "registration_request_checksum": operation.request_checksum,
                "candidate_id": operation.confirmed_candidate_id,
            },
        )
        self._publish_immutable(reference, payload)
        return confirmation, reference

    def _alignment_service(
        self,
        expected: RegistrationOperationRecord,
        confirmation: RegistrationConfirmationRecord,
        confirmation_ref: ProductArtifactRef,
    ) -> RgbLidarAlignmentService:
        def verify_decision(request: AlignmentRequest) -> bool:
            provenance = request.provenance
            try:
                reference = ProductArtifactRef.model_validate(provenance.get("registration_confirmation_ref"))
                actual = self.resolver.load_model(reference, RegistrationConfirmationRecord)
                operation = self.operations.get(expected.operation_id)
            except (ValueError, TypeError, KeyError):
                return False
            if reference != confirmation_ref or actual != confirmation:
                return False
            if operation.state not in {RegistrationOperationState.CONFIRMED, RegistrationOperationState.COMMITTED}:
                return False
            proposal, report, overlay, overlay_ref, manifest, geometry_ref, metadata_ref = self._verified_inputs(
                operation
            )
            candidate = next(
                (item for item in proposal.candidates if item.candidate_id == operation.confirmed_candidate_id), None
            )
            expected_evidence = self._alignment_evidence(
                operation, report, overlay_ref, manifest, geometry_ref, metadata_ref, confirmation_ref
            )
            expected_evidence_ids = {
                (item.artifact_type, item.artifact_uri, item.artifact_checksum) for item in expected_evidence
            }
            observed_evidence_ids = {
                (item.artifact_type, item.artifact_uri, item.artifact_checksum) for item in request.evidence_refs
            }
            return (
                request.job_id == operation.target_job_id
                and request.rgb_geometry_ref == operation.request.target_rgb_geometry_ref
                and request.lidar_geometry_ref == geometry_ref
                and candidate is not None
                and request.transform_target_from_source == candidate.transform_target_from_source
                and request.same_scene_attestation is True
                and expected_evidence_ids.issubset(observed_evidence_ids)
                and provenance.get("registration_proposal_ref") == operation.proposal_ref.model_dump(mode="json")
                and provenance.get("registration_qa_ref") == operation.qa_report_ref.model_dump(mode="json")
                and provenance.get("registration_overlay_ref") == overlay_ref.model_dump(mode="json")
                and provenance.get("registration_operation_id") == operation.operation_id
                and provenance.get("registration_operation_checksum") == confirmation.operation_checksum
                and provenance.get("registration_request_checksum") == operation.request_checksum
                and provenance.get("registration_candidate_id") == operation.confirmed_candidate_id
                and provenance.get("registration_scene_revision") == operation.request.expected_scene_revision
                and confirmation.job_id == operation.target_job_id
                and confirmation.operation_id == operation.operation_id
                and confirmation.request_checksum == operation.request_checksum
                and confirmation.expected_scene_revision == operation.request.expected_scene_revision
                and confirmation.candidate_id == operation.confirmed_candidate_id
                and confirmation.confirmed_by_user_id == operation.confirmed_by_user_id
                and confirmation.confirmed_at == operation.confirmed_at
                and confirmation.confirmed_from_checksum == operation.confirmed_from_checksum
                and (
                    operation.state != RegistrationOperationState.CONFIRMED
                    or operation.operation_checksum == confirmation.operation_checksum
                )
            )

        return RgbLidarAlignmentService(self.writer, self.resolver.require, verify_decision)

    @staticmethod
    def _alignment_evidence(
        operation: RegistrationOperationRecord,
        report: RegistrationQAReport,
        overlay_ref: ProductArtifactRef,
        source_manifest: RegistrationSourceCloudManifest,
        lidar_geometry_ref: ProductArtifactRef,
        lidar_metadata_ref: ProductArtifactRef,
        confirmation_ref: ProductArtifactRef,
    ) -> list[ProductArtifactRef]:
        refs = [
            *report.evidence_refs,
            operation.proposal_ref,
            operation.qa_report_ref,
            report.proposal_ref,
            source_manifest.source_geometry_ref,
            lidar_geometry_ref,
            lidar_metadata_ref,
            overlay_ref,
            confirmation_ref,
            operation.request.metric_confirmation_ref,
            *operation.request.floor_evidence_refs,
            source_manifest.estimated_trajectory_product_ref,
            source_manifest.estimated_map_cloud_ref,
        ]
        unique: dict[tuple[str, str, str], ProductArtifactRef] = {}
        for reference in refs:
            if reference is not None:
                unique[(reference.artifact_type, reference.artifact_uri, reference.artifact_checksum)] = reference
        return list(unique.values())

    def _mixed_bundle_request(
        self,
        operation: RegistrationOperationRecord,
        base: ReconstructionBundle,
        alignment: AlignmentRecord,
        lidar_geometry_ref: ProductArtifactRef,
        alignment_ref: ProductArtifactRef,
    ) -> tuple[BundleBuildRequest, BundleMetricRecord]:
        if (
            base.job_id != operation.target_job_id
            or base.canonical_geometry_ref != base.rgb_geometry_ref
            or base.rgb_geometry_ref != operation.request.target_rgb_geometry_ref
            or base.lidar_geometry_ref is not None
            or base.alignment_record is not None
            or base.input_configuration.registered_lidar_present
        ):
            raise RuntimeStateConflictError("Current bundle is not the exact unregistered RGB metric bundle")
        raw_proof_ref = base.provenance.get("metric_verification_ref")
        if not isinstance(raw_proof_ref, dict):
            raise RuntimeStateConflictError("Current RGB bundle has no immutable metric proof")
        proof_ref = ProductArtifactRef.model_validate(raw_proof_ref)
        proof_payload = self.resolver.require(proof_ref).read_bytes()
        proof = BundleMetricRecord.model_validate_json(proof_payload)
        if proof_ref != metric_verification_reference(proof, proof_payload):
            raise RuntimeStateConflictError("Current RGB metric proof identity is invalid")
        original_request = _base_bundle_request(base)
        if original_request != proof.request.bundle:
            raise RuntimeStateConflictError("Current RGB bundle differs from its exact metric proof")

        provenance = dict(original_request.provenance)
        provenance.update(
            {
                "registration_operation_id": operation.operation_id,
                "registration_operation_checksum": operation.operation_checksum,
                "registration_request_checksum": operation.request_checksum,
                "registration_candidate_id": operation.confirmed_candidate_id,
                "registration_alignment_ref": alignment_ref.model_dump(mode="json"),
            }
        )
        request = original_request.model_copy(
            update={
                "input_configuration": original_request.input_configuration.model_copy(
                    update={"registered_lidar_present": True}
                ),
                "lidar_geometry_ref": lidar_geometry_ref,
                "alignment_record": alignment,
                "verification_ref": proof_ref,
                "provenance": provenance,
            }
        )
        return BundleBuildRequest.model_validate(request.model_dump()), proof

    @staticmethod
    def _preserves_metric_proof(candidate: BundleBuildRequest, proof: BundleMetricRecord) -> bool:
        if candidate.verification_ref is None:
            return False
        projected = candidate.model_copy(
            update={
                "input_configuration": candidate.input_configuration.model_copy(
                    update={"registered_lidar_present": False}
                ),
                "lidar_geometry_ref": None,
                "alignment_record": None,
                "verification_ref": None,
                "provenance": proof.request.bundle.provenance,
            }
        )
        return BundleBuildRequest.model_validate(projected.model_dump()) == proof.request.bundle

    def _existing_publication(
        self,
        job: JobManifest,
        operation: RegistrationOperationRecord,
    ) -> tuple[ProductArtifactRef, ProductArtifactRef] | None:
        bundle = job_bundle(self.registry, job)
        if bundle is None or bundle.provenance.get("registration_operation_id") != operation.operation_id:
            return None
        bundle_stage = next(
            (
                stage
                for stage in reversed(job.stage_artifacts)
                if stage.stage_id == StageId.METRIC_CANONICALIZE
                and stage.status == StageStatus.SUCCEEDED
                and stage.artifact_type == "ReconstructionBundle"
            ),
            None,
        )
        if bundle_stage is None or bundle_stage.artifact_uri is None or bundle_stage.artifact_checksum is None:
            raise RuntimeStateConflictError("Registered bundle stage is incomplete")
        if bundle.alignment_record is None:
            raise RuntimeStateConflictError("Registered bundle has no alignment record")
        alignment = bundle.alignment_record
        alignment_ref = ProductArtifactRef(
            artifact_type=alignment.artifact_type,
            schema_version=alignment.schema_version,
            artifact_uri=alignment.artifact_uri,
            artifact_checksum=alignment.artifact_checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=alignment.producer_stage,
            job_id=alignment.job_id,
            source_provenance=alignment.provenance,
        )
        bundle_ref = ProductArtifactRef(
            artifact_type="ReconstructionBundle",
            schema_version="1.0",
            artifact_uri=bundle_stage.artifact_uri,
            artifact_checksum=bundle_stage.artifact_checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.METRIC_CANONICALIZE,
            job_id=job.job_id,
            source_provenance=bundle.provenance,
        )
        if (
            bundle.provenance.get("registration_request_checksum") != operation.request_checksum
            or bundle.provenance.get("registration_candidate_id") != operation.confirmed_candidate_id
            or bundle.provenance.get("registration_alignment_ref") != alignment_ref.model_dump(mode="json")
            or bundle.artifact_uri != bundle_ref.artifact_uri
        ):
            raise RuntimeStateConflictError("Published registration bundle does not match the confirmed decision")
        confirmation, confirmation_ref = self._publish_confirmation(operation)
        self._alignment_service(operation, confirmation, confirmation_ref).load(alignment_ref)
        return bundle_ref, alignment_ref

    def _verify_committed(self, operation: RegistrationOperationRecord) -> None:
        if (
            operation.committed_bundle_ref is None
            or operation.committed_alignment_ref is None
            or operation.committed_manifest_checksum is None
        ):
            raise RuntimeStateConflictError("Committed registration has incomplete publication references")
        bundle = self.resolver.load_model(operation.committed_bundle_ref, ReconstructionBundle)
        alignment_ref = operation.committed_alignment_ref
        if (
            bundle.job_id != operation.target_job_id
            or bundle.alignment_record is None
            or bundle.alignment_record.artifact_uri != alignment_ref.artifact_uri
            or bundle.alignment_record.artifact_checksum != alignment_ref.artifact_checksum
            or bundle.canonical_geometry_ref != operation.request.target_rgb_geometry_ref
            or bundle.provenance.get("registration_operation_id") != operation.operation_id
            or bundle.provenance.get("registration_request_checksum") != operation.request_checksum
        ):
            raise RuntimeStateConflictError("Committed registration bundle no longer matches the operation")
        raw_confirmation_ref = bundle.alignment_record.provenance.get("registration_confirmation_ref")
        if not isinstance(raw_confirmation_ref, dict):
            raise RuntimeStateConflictError("Committed alignment has no exact confirmation reference")
        confirmation_ref = ProductArtifactRef.model_validate(raw_confirmation_ref)
        confirmation = self.resolver.load_model(confirmation_ref, RegistrationConfirmationRecord)
        if (
            confirmation.job_id != operation.target_job_id
            or confirmation.operation_id != operation.operation_id
            or confirmation.request_checksum != operation.request_checksum
            or confirmation.expected_scene_revision != operation.request.expected_scene_revision
            or confirmation.candidate_id != operation.confirmed_candidate_id
            or confirmation.confirmed_by_user_id != operation.confirmed_by_user_id
            or confirmation.confirmed_at != operation.confirmed_at
            or confirmation.confirmed_from_checksum != operation.confirmed_from_checksum
        ):
            raise RuntimeStateConflictError("Committed alignment confirmation differs from operation decision")
        alignment_service = self._alignment_service(operation, confirmation, confirmation_ref)
        alignment_service.load(alignment_ref)

    def _one_evidence_ref(self, report: RegistrationQAReport, artifact_type: str) -> ProductArtifactRef:
        matches = [reference for reference in report.evidence_refs if reference.artifact_type == artifact_type]
        if len(matches) != 1:
            raise RuntimeStateConflictError(f"Registration QA requires exactly one {artifact_type} reference")
        reference = matches[0]
        if (
            reference.job_id != report.job_id
            or reference.data_class != ArtifactDataClass.DERIVED
            or not reference.artifact_uri.startswith(f"artifact://jobs/{report.job_id}/")
        ):
            raise RuntimeStateConflictError(f"Registration {artifact_type} reference is not job-local")
        return reference

    def _publish_immutable(self, reference: ProductArtifactRef, payload: bytes) -> None:
        try:
            existing = self.resolver.require(reference)
        except ArtifactNotFoundError:
            self.writer.publish(reference, payload)
            self.resolver.require(reference)
            return
        if existing.read_bytes() != payload:
            raise RuntimeStateConflictError("Immutable registration confirmation bytes changed")


def _base_bundle_request(bundle: ReconstructionBundle) -> BundleBuildRequest:
    provenance = dict(bundle.provenance)
    provenance.pop("metric_verification_ref", None)
    return BundleBuildRequest(
        job_id=bundle.job_id,
        source_input_checksum=bundle.source_input_checksum,
        input_configuration=bundle.input_configuration,
        metric_scale=bundle.metric_scale,
        coordinate_system=bundle.coordinate_system,
        rgb_frame_refs=bundle.rgb_frame_refs,
        depth_frame_set=bundle.depth_frame_set,
        camera_pose_refs=bundle.camera_pose_refs,
        visual_artifact_ref=bundle.visual_artifact_ref,
        rgb_geometry_ref=bundle.rgb_geometry_ref,
        lidar_geometry_ref=bundle.lidar_geometry_ref,
        alignment_record=bundle.alignment_record,
        canonical_geometry_ref=bundle.canonical_geometry_ref,
        provenance=provenance,
    )
