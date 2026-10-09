"""Durable worker for independent RGB/LiDAR map-registration proposals."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Event, Thread
from typing import Any

import numpy as np

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import artifact_model_payload, canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.models.contracts.rgb_lidar_registration import (
    RegistrationFindingCode,
    RegistrationInputMode,
    RegistrationOperationState,
    RegistrationOverlayPreview,
    RegistrationProposal,
    RegistrationProposalState,
    RegistrationQAReport,
    RegistrationRequest,
    seal_registration_proposal,
    seal_registration_source_cloud_manifest,
)
from src.services.orchestration.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactNotFoundError,
    ArtifactResolver,
    FilesystemArtifactStore,
    StreamingPublication,
    sha256_bytes,
    sha256_file,
)
from src.services.orchestration.inputs import InputAssemblyService
from src.services.orchestration.jobs.admission import (
    OperationAdmissionRequest,
    OperationResourceProfile,
    ResourceAdmission,
)
from src.services.orchestration.jobs.registration_operations import (
    RegistrationOperationCancellationRequestedError,
    RegistrationOperationLeaseLostError,
    RegistrationOperationRecord,
    RegistrationOperationStore,
)
from src.services.orchestration.jobs.registration_sources import (
    RegistrationSourceResolutionError,
    RegistrationSourceResolver,
    VerifiedRegistrationSource,
    load_registration_source_points,
)
from src.services.orchestration.jobs.registration_targets import (
    RegistrationTargetResolutionError,
    RegistrationTargetResolver,
    VerifiedRegistrationTarget,
)
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction.alignment.bev_search import (
    RegistrationCancelledError,
    RegistrationFloorPlane,
    search_independent_map_registration,
)
from src.services.reconstruction.alignment.constrained_icp import (
    RefinedRegistrationCandidate,
    refine_registration_candidates,
)
from src.services.reconstruction.alignment.registration_overlay import build_registration_overlay_preview
from src.services.reconstruction.alignment.registration_qa import build_registration_qa_report
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.reconstruction.alignment.source_planes import (
    SourcePlaneHypothesis,
    SourcePlaneHypothesisProfile,
    SourcePlaneHypothesisReport,
    discover_source_plane_hypotheses,
)

logger = logging.getLogger(__name__)

_LEASE_SECONDS = 180
_HEARTBEAT_SECONDS = 20
_COPY_CHUNK_BYTES = 1024 * 1024
_WORKER_VERSION = "aud19-registration-worker-v1"
_SOURCE_PLANE_VERSION = "source-plane-hypotheses-ransac-v1"
_BEV_VERSION = "floor-constrained-bev-multicandidate-v1"
_ICP_VERSION = "floor-constrained-point-to-plane-icp-v1"
_METER_BYTES_PER_SOURCE_POINT = 64
_TARGET_RAM_MULTIPLIER = 6.0
_GIB = 1_000_000_000


@dataclass(frozen=True)
class _MeasuredCandidate:
    refined: RefinedRegistrationCandidate
    source_plane: SourcePlaneHypothesis


class _OperationHeartbeat:
    """Keep the operation lease and its resource reservation alive while work runs."""

    def __init__(
        self,
        store: RegistrationOperationStore,
        admission: ResourceAdmission,
        operation: RegistrationOperationRecord,
    ) -> None:
        self.store = store
        self.admission = admission
        self.operation = operation
        self.admission_request: OperationAdmissionRequest | None = None
        self.stop_event = Event()
        self.cancel_event = Event()
        self.reason: str | None = None
        self.thread = Thread(
            target=self._run, name=f"registration-heartbeat-{operation.operation_id[:12]}", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def set_admission_request(self, request: OperationAdmissionRequest) -> None:
        self.admission_request = request

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=_HEARTBEAT_SECONDS + 1)

    def _fail(self, reason: str) -> None:
        self.reason = reason
        self.cancel_event.set()

    def _run(self) -> None:
        while not self.stop_event.wait(_HEARTBEAT_SECONDS):
            try:
                current = self.store.heartbeat(
                    self.operation.operation_id,
                    lease_token=self.operation.lease_token or "",
                    fencing_token=self.operation.fencing_token,
                    lease_seconds=_LEASE_SECONDS,
                )
            except RegistrationOperationLeaseLostError:
                self._fail("lease_lost")
                return
            except Exception as error:  # noqa: BLE001 - loss of durable ownership must stop solver work
                logger.warning(
                    "Registration heartbeat failed operation=%s cause=%s",
                    self.operation.operation_id,
                    type(error).__name__,
                )
                self._fail("heartbeat_failed")
                return
            if current.cancellation_requested:
                self._fail("cancelled")
                return
            request = self.admission_request
            if request is not None and not self.admission.touch_operation(request):
                self._fail("reservation_lost")
                return


class RegistrationOperationWorker:
    """Claim, admit, solve, and publish one independent-map registration operation."""

    def __init__(self, registry: ProjectRegistry, settings: Settings, admission: ResourceAdmission) -> None:
        if registry.persistence is None:
            raise ValueError("Registration operation worker requires durable project persistence")
        self.registry = registry
        self.settings = settings
        self.admission = admission
        self.database = registry.persistence.database
        self.store = RegistrationOperationStore(self.database)
        self.resolver: ArtifactResolver = registry.runtime_resolver
        self.writer = FilesystemArtifactStore(self.resolver)
        self.assemblies = InputAssemblyService(
            self.database,
            str(settings.product_input_runtime_registry)
            if settings.product_input_runtime_registry is not None
            else None,
            self.resolver,
        )
        self.source_resolver = RegistrationSourceResolver(self.assemblies, registry.persistence)
        self.target_resolver = RegistrationTargetResolver(
            self.resolver,
            max_collision_glb_bytes=min((1 << 32) - 1, settings.product_upload_max_bytes * 2),
        )
        self.workspace_root = settings.product_worker_root.expanduser().resolve() / "registrations"
        self.max_source_bytes = settings.product_upload_max_bytes * 2

    def process_next(self) -> bool:
        """Handle one operation; false also tells the poll loop to pause after a resource wait."""
        operation = self.store.claim_next(self.admission.worker_id, lease_seconds=_LEASE_SECONDS)
        if operation is None:
            return False
        heartbeat = _OperationHeartbeat(self.store, self.admission, operation)
        heartbeat.start()
        admitted = False
        admission_request: OperationAdmissionRequest | None = None
        try:
            if operation.request.source.mode not in {
                RegistrationInputMode.REGISTERED_MAP,
                RegistrationInputMode.STATIC_CLOUD,
                RegistrationInputMode.ESTIMATED_TRAJECTORY_MAP,
            }:
                self._finish(operation, RegistrationOperationState.FAILED, error="UNSUPPORTED_REGISTRATION_INPUT_MODE")
                return True
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="registration-", dir=self.workspace_root) as workspace_name:
                workspace = Path(workspace_name)
                source = self.source_resolver.resolve(operation.request, workspace)
                self._check_cancelled(heartbeat)
                self._assert_target_revision(operation.request)
                source_size = source.path.stat().st_size
                if source_size < 1 or source_size > self.max_source_bytes:
                    raise RegistrationSourceResolutionError("source cloud exceeds the worker byte limit")
                target_path = self.resolver.require_uri(
                    operation.request.target_rgb_geometry_ref.artifact_uri,
                    operation.request.target_rgb_geometry_ref.artifact_checksum,
                )
                resources = self._resource_profile(operation, source, source_size, target_path.stat().st_size)
                admission_request = self._admission_request(operation, resources)
                admission_result = self.admission.admit_operation(admission_request)
                if admission_result.status != "admitted":
                    heartbeat.stop()
                    if admission_result.status == "identity_conflict":
                        self._finish(
                            operation,
                            RegistrationOperationState.FAILED,
                            error="REGISTRATION_RESOURCE_IDENTITY_CONFLICT",
                        )
                        return True
                    reason = self._wait_reason(admission_result)
                    self.store.wait_for_resources(
                        operation.operation_id,
                        lease_token=operation.lease_token or "",
                        fencing_token=operation.fencing_token,
                        reason=reason,
                    )
                    return False

                admitted = True
                heartbeat.set_admission_request(admission_request)
                self._check_cancelled(heartbeat)
                source_ref, source_manifest_ref = self._publish_source_cloud(
                    operation.request,
                    source,
                    heartbeat.cancel_event,
                )
                copied_path = self.resolver.require_uri(source_ref.artifact_uri, source_ref.artifact_checksum)
                verified_source = replace(source, path=copied_path)
                source_points = load_registration_source_points(verified_source, operation.request.profile)
                self._check_cancelled(heartbeat)
                target = self.target_resolver.resolve(operation.request)
                self._assert_target_revision(operation.request)
                plane_report = discover_source_plane_hypotheses(
                    source_points,
                    source_checksum=verified_source.source_checksum,
                    source_frame=verified_source.source_frame,
                    profile=SourcePlaneHypothesisProfile(
                        maximum_points=max(3, min(50_000, operation.request.profile.max_source_points)),
                        minimum_support_points=min(100, max(3, operation.request.profile.max_source_points)),
                        maximum_hypotheses=min(
                            8,
                            max(1, operation.request.profile.max_refinement_candidates // 2),
                        ),
                    ),
                )
                self._check_cancelled(heartbeat)
                measured, diagnostics, proposal_state, proposal_findings, candidate_margin = self._solve(
                    operation.request,
                    source_points,
                    target,
                    plane_report,
                    verified_source.same_scene_lineage_verified,
                    heartbeat.cancel_event,
                )
                self._assert_target_revision(operation.request)
                source_planes_ref = self._publish_json_artifact(
                    operation,
                    "RegistrationSourcePlaneHypotheses",
                    "source-plane-hypotheses.json",
                    asdict(plane_report),
                )
                worker_diagnostics_ref = self._publish_json_artifact(
                    operation,
                    "RegistrationWorkerDiagnostics",
                    "worker-diagnostics.json",
                    diagnostics,
                )
                self._check_cancelled(heartbeat)
                proposal = self._proposal(
                    operation,
                    source_ref,
                    proposal_state,
                    proposal_findings,
                    [item.refined.candidate for item in measured],
                )
                proposal_ref = self._publish_model_artifact(operation, proposal, "proposal.json")
                overlay_refs: list[ProductArtifactRef] = []
                for candidate in proposal.candidates:
                    self._check_cancelled(heartbeat)
                    overlay = build_registration_overlay_preview(
                        operation.request,
                        proposal,
                        candidate,
                        operation.operation_id,
                        source_points,
                        target.collision_surface_points_world_m,
                        target.target_floor,
                    )
                    overlay_refs.append(
                        self._publish_model_artifact(
                            operation,
                            overlay,
                            f"overlay-{candidate.candidate_id}.json",
                        )
                    )
                selected = None
                floor_difference = None
                if proposal_state == RegistrationProposalState.PROPOSED and proposal.selected_candidate_id is not None:
                    selected = next(
                        item
                        for item in measured
                        if item.refined.candidate.candidate_id == proposal.selected_candidate_id
                    )
                    floor_difference = self._floor_difference(selected, target)
                same_scene_verified: bool | None = (
                    True
                    if verified_source.same_scene_lineage_verified
                    else False
                    if operation.request.source.same_scene_attestation is False
                    else None
                )
                qa_report = build_registration_qa_report(
                    operation.request,
                    proposal,
                    proposal_ref,
                    selected.refined if selected is not None else None,
                    candidate_margin=candidate_margin,
                    floor_difference_m=floor_difference,
                    same_scene_verified=same_scene_verified,
                    # Qualification records are not yet loaded by this worker; fail closed.
                    server_qualification_verified=False,
                    evidence_refs=[source_manifest_ref, source_planes_ref, worker_diagnostics_ref, *overlay_refs],
                )
                qa_ref = self._publish_model_artifact(operation, qa_report, "qa-report.json")
                self._check_cancelled(heartbeat)
                self._assert_target_revision(operation.request)
                heartbeat.stop()
                state = self._operation_state(proposal_state)
                try:
                    self._finish(operation, state, proposal_ref=proposal_ref, qa_report_ref=qa_ref)
                except RegistrationOperationCancellationRequestedError:
                    self._finish(operation, RegistrationOperationState.CANCELLED)
                return True
        except RegistrationCancelledError:
            heartbeat.stop()
            self._finish_cancelled_or_failed(operation, heartbeat.reason)
            return True
        except Exception as error:  # noqa: BLE001 - operation boundary stores only a safe stable failure code
            heartbeat.stop()
            logger.warning(
                "Registration worker failed operation=%s cause=%s",
                operation.operation_id,
                type(error).__name__,
            )
            error_code = self._failure_code(error)
            self._finish_cancelled_or_failed(operation, heartbeat.reason, error_code=error_code)
            return True
        finally:
            heartbeat.stop()
            if admitted and admission_request is not None:
                self.admission.release_operation(admission_request)

    def _resource_profile(
        self,
        operation: RegistrationOperationRecord,
        source: VerifiedRegistrationSource,
        source_size: int,
        target_size: int,
    ) -> OperationResourceProfile:
        job = self.registry.get_job(operation.target_job_id)
        if job.project_id != operation.request.target_project_id:
            raise RegistrationSourceResolutionError("target project differs from the persisted job")
        baseline = self.admission.operation_profile_for_job(job, gpu_required=False)
        points = max(source.point_count, 1)
        ram_floor = 0.5 + points * _METER_BYTES_PER_SOURCE_POINT / _GIB + target_size * _TARGET_RAM_MULTIPLIER / _GIB
        disk_floor = 0.1 + 2.0 * source_size / _GIB
        ram = self._rounded_gb(max(ram_floor, baseline.required_gb["ram"] or 0.0))
        disk = self._rounded_gb(max(disk_floor, baseline.required_gb["disk"] or 0.0))
        measured = bool(
            baseline.measured
            and baseline.required_gb["ram"] is not None
            and baseline.required_gb["disk"] is not None
            and baseline.required_gb["ram"] >= ram_floor
            and baseline.required_gb["disk"] >= disk_floor
        )
        return OperationResourceProfile(
            required_gb={"vram": 0.0, "ram": ram, "disk": disk},
            danger_ratio=baseline.danger_ratio,
            measured=measured,
            gpu_required=False,
        )

    @staticmethod
    def _rounded_gb(value: float) -> float:
        return max(0.1, math.ceil(value * 100.0) / 100.0)

    @staticmethod
    def _admission_request(
        operation: RegistrationOperationRecord,
        resources: OperationResourceProfile,
    ) -> OperationAdmissionRequest:
        return OperationAdmissionRequest(
            operation_kind="rgb_lidar_register",
            operation_id=operation.operation_id,
            parent_kind="job",
            parent_id=operation.target_job_id,
            input_checksum=operation.request_checksum,
            config_checksum=operation.request.profile_checksum,
            resources=resources,
            lease_token=operation.lease_token,
            lease_generation=operation.fencing_token,
        )

    @staticmethod
    def _wait_reason(result: Any) -> str:
        waiting = ",".join(sorted(getattr(result, "waiting_on", ()))) or "capacity"
        reasons = getattr(result, "reasons", {})
        detail = ",".join(f"{name}:{reasons[name]}" for name in sorted(reasons))
        return f"{result.status}; waiting={waiting}" + (f"; reasons={detail}" if detail else "")

    def _publish_source_cloud(
        self,
        request: RegistrationRequest,
        source: VerifiedRegistrationSource,
        cancel_event: Event,
    ) -> tuple[ProductArtifactRef, ProductArtifactRef]:
        if source.point_count < 1:
            raise RegistrationSourceResolutionError("source cloud is empty")
        lineage = {
            "source_input_checksum": source.source_checksum,
            "input_assembly_id": source.input_assembly_id,
            "input_assembly_revision": source.input_assembly_revision,
            "input_assembly_checksum": source.input_assembly_checksum,
            "source_header_checksum": source.header_checksum,
        }
        if source.estimated_map_cloud_ref is not None:
            if source.estimated_trajectory_product_ref is None:
                raise RegistrationSourceResolutionError("estimated map source has no trajectory product receipt")
            lineage.update(
                {
                    "source_scan_file_ids": list(source.source_scan_file_ids),
                    "source_scan_checksums": list(source.source_scan_checksums),
                    "estimated_trajectory_product_ref": source.estimated_trajectory_product_ref.model_dump(mode="json"),
                    "estimated_map_cloud_ref": source.estimated_map_cloud_ref.model_dump(mode="json"),
                    "odometry_runtime_qualification_status": source.odometry_runtime_qualification_status,
                }
            )
            identity_input = (
                f"{source.input_assembly_checksum}:{source.source_checksum}:"
                f"{source.estimated_trajectory_product_ref.artifact_checksum}"
            )
        else:
            if source.file_id is None:
                raise RegistrationSourceResolutionError("staged map source has no bound input file ID")
            lineage["source_file_id"] = source.file_id
            identity_input = f"{source.input_assembly_checksum}:{source.source_checksum}"
        identity = hashlib.sha256(identity_input.encode()).hexdigest()[:24]
        extension = source.geometry_format
        cloud_ref = ProductArtifactRef(
            artifact_type="RegistrationSourcePointCloud",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{request.target_job_id}/rec08/registration-source/{identity}.{extension}",
            artifact_checksum=source.source_checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.LIDAR_INGEST,
            job_id=request.target_job_id,
            source_provenance=lineage,
        )
        self._copy_exact_source(source.path, cloud_ref, cancel_event)
        manifest = seal_registration_source_cloud_manifest(
            {
                "job_id": request.target_job_id,
                "source_geometry_ref": cloud_ref,
                "input_mode": request.source.mode,
                "source_input_checksum": source.source_checksum,
                "input_assembly_id": source.input_assembly_id,
                "input_assembly_revision": source.input_assembly_revision,
                "input_assembly_checksum": source.input_assembly_checksum,
                "source_file_id": source.file_id,
                "source_scan_file_ids": list(source.source_scan_file_ids),
                "source_scan_checksums": list(source.source_scan_checksums),
                "estimated_trajectory_product_ref": source.estimated_trajectory_product_ref,
                "estimated_map_cloud_ref": source.estimated_map_cloud_ref,
                "source_format": source.geometry_format,
                "source_header_checksum": source.header_checksum,
                "source_point_count": source.point_count,
                "source_distance_unit": source.distance_unit,
                "source_frame": source.source_frame,
                "same_scene_lineage_verified": source.same_scene_lineage_verified,
                "schema_version": "1.1" if source.estimated_map_cloud_ref is not None else "1.0",
                "manifest_checksum": "sha256:" + "0" * 64,
            }
        )
        manifest_payload = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
        manifest_ref = ProductArtifactRef(
            artifact_type=manifest.artifact_type,
            schema_version=manifest.schema_version,
            artifact_uri=f"artifact://jobs/{request.target_job_id}/rec08/registration-source/{identity}.json",
            artifact_checksum=sha256_bytes(manifest_payload),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.LIDAR_INGEST,
            job_id=request.target_job_id,
            source_provenance=lineage,
        )
        self._publish_immutable(manifest_ref, manifest_payload)
        return cloud_ref, manifest_ref

    def _copy_exact_source(self, source_path: Path, reference: ProductArtifactRef, cancel_event: Event) -> None:
        try:
            self.resolver.require_uri(reference.artifact_uri, reference.artifact_checksum)
            return
        except ArtifactNotFoundError:
            pass
        publication = StreamingPublication(self.resolver, reference.artifact_uri, max_bytes=self.max_source_bytes)
        try:
            with source_path.open("rb") as stream:
                while chunk := stream.read(_COPY_CHUNK_BYTES):
                    if cancel_event.is_set():
                        raise RegistrationCancelledError("registration worker cancelled while copying source")
                    publication.write(chunk)
            staged_path = publication.staged_path()
            if sha256_file(staged_path) != reference.artifact_checksum:
                raise RegistrationSourceResolutionError("source cloud changed before job-local publication")
            actual = publication.commit()
            if actual != reference.artifact_checksum:
                raise RegistrationSourceResolutionError("published source cloud checksum differs from the request")
        except ArtifactAlreadyExistsError:
            publication.abort()
            self.resolver.require_uri(reference.artifact_uri, reference.artifact_checksum)
        except Exception:
            publication.abort()
            raise

    def _publish_immutable(self, reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        try:
            self.resolver.require_uri(reference.artifact_uri, reference.artifact_checksum)
            return reference
        except ArtifactNotFoundError:
            pass
        try:
            self.writer.publish(reference, payload)
        except ArtifactAlreadyExistsError:
            self.resolver.require_uri(reference.artifact_uri, reference.artifact_checksum)
        return reference

    def _publish_json_artifact(
        self,
        operation: RegistrationOperationRecord,
        artifact_type: str,
        filename: str,
        value: dict[str, Any],
    ) -> ProductArtifactRef:
        payload = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
            + b"\n"
        )
        return self._publish_artifact_payload(operation, artifact_type, filename, payload)

    def _publish_model_artifact(
        self,
        operation: RegistrationOperationRecord,
        value: RegistrationOverlayPreview | RegistrationProposal | RegistrationQAReport,
        filename: str,
    ) -> ProductArtifactRef:
        return self._publish_artifact_payload(
            operation,
            value.artifact_type,
            filename,
            artifact_model_payload(value),
        )

    def _publish_artifact_payload(
        self,
        operation: RegistrationOperationRecord,
        artifact_type: str,
        filename: str,
        payload: bytes,
    ) -> ProductArtifactRef:
        operation_segment = hashlib.sha256(operation.operation_id.encode("utf-8")).hexdigest()[:24]
        reference = ProductArtifactRef(
            artifact_type=artifact_type,
            schema_version="1.0",
            artifact_uri=(
                f"artifact://jobs/{operation.target_job_id}/rgb-lidar-align/{operation_segment}/"
                f"attempt-{operation.attempt}-{operation.fencing_token}/{filename}"
            ),
            artifact_checksum=sha256_bytes(payload),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.RGB_LIDAR_ALIGN,
            job_id=operation.target_job_id,
            source_provenance={
                "registration_request_checksum": operation.request_checksum,
                "operation_id": operation.operation_id,
                "attempt": operation.attempt,
                "fencing_token": operation.fencing_token,
            },
        )
        return self._publish_immutable(reference, payload)

    def _solve(
        self,
        request: RegistrationRequest,
        source_points_m: np.ndarray,
        target: VerifiedRegistrationTarget,
        plane_report: SourcePlaneHypothesisReport,
        same_scene_lineage_verified: bool,
        cancel_event: Event,
    ) -> tuple[
        list[_MeasuredCandidate],
        dict[str, Any],
        RegistrationProposalState,
        list[RegistrationFindingCode],
        float | None,
    ]:
        if not plane_report.candidates:
            return (
                [],
                {"orientation_hypotheses": 0, "source_plane_report": plane_report.evidence_checksum},
                (RegistrationProposalState.INSUFFICIENT),
                [RegistrationFindingCode.FLOOR_UNSUPPORTED],
                None,
            )
        if not same_scene_lineage_verified:
            finding = (
                RegistrationFindingCode.DIFFERENT_SCENE
                if request.source.same_scene_attestation is False
                else RegistrationFindingCode.SAME_SCENE_CONTEXT_MISSING
            )
            return (
                [],
                {"orientation_hypotheses": 0, "source_plane_report": plane_report.evidence_checksum},
                (RegistrationProposalState.INSUFFICIENT),
                [finding],
                None,
            )
        if request.target_roi_world is None:
            return (
                [],
                {"orientation_hypotheses": 0, "source_plane_report": plane_report.evidence_checksum},
                (RegistrationProposalState.INSUFFICIENT),
                [RegistrationFindingCode.LOW_COVERAGE],
                None,
            )

        orientations = [(candidate, sign) for candidate in plane_report.candidates for sign in (1, -1)]
        if len(orientations) > request.profile.max_refinement_candidates:
            return (
                [],
                {
                    "worker_version": _WORKER_VERSION,
                    "source_plane_report_checksum": plane_report.evidence_checksum,
                    "orientation_hypotheses": len(orientations),
                    "maximum_refinement_candidates": request.profile.max_refinement_candidates,
                    "budget_exhausted": True,
                },
                RegistrationProposalState.INSUFFICIENT,
                [RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED],
                None,
            )
        minimum_solver_budget = len(orientations) * 2
        if request.profile.runtime_budget_seconds < minimum_solver_budget:
            return (
                [],
                {
                    "worker_version": _WORKER_VERSION,
                    "source_plane_report_checksum": plane_report.evidence_checksum,
                    "orientation_hypotheses": len(orientations),
                    "minimum_solver_budget_seconds": minimum_solver_budget,
                    "budget_exhausted": True,
                },
                RegistrationProposalState.INSUFFICIENT,
                [RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED],
                None,
            )
        search_budget = max(1, (request.profile.runtime_budget_seconds // 2) // len(orientations))
        icp_budget = max(
            1,
            (request.profile.runtime_budget_seconds - request.profile.runtime_budget_seconds // 2) // len(orientations),
        )
        candidate_budget = max(1, request.profile.max_refinement_candidates // len(orientations))
        measured: list[_MeasuredCandidate] = []
        solver_records: list[dict[str, Any]] = []
        aggregate_findings: list[RegistrationFindingCode] = []
        force_ambiguous = False
        budget_exhausted = False

        for plane, up_sign in orientations:
            self._check_cancelled_event(cancel_event)
            orientation_id = f"{plane.candidate_id}-up-{up_sign}"
            up_direction = tuple(float(value * up_sign) for value in plane.normal_xyz)
            source_floor = RegistrationFloorPlane(
                frame=plane.frame,
                normal_xyz=plane.normal_xyz,
                offset_m=plane.offset_m,
                up_direction_xyz=up_direction,
                evidence_checksum=canonical_content_checksum(
                    {
                        "plane_evidence_checksum": plane.evidence_checksum,
                        "up_sign": up_sign,
                        "checksum": "sha256:" + "0" * 64,
                    },
                    "checksum",
                ),
            )
            coarse = search_independent_map_registration(
                source_points_m,
                target.collision_surface_points_world_m,
                source_frame=plane.frame,
                source_distance_unit="m",
                source_floor=source_floor,
                target_floor=target.target_floor,
                target_roi_world=request.target_roi_world,
                profile=request.profile,
                metric_state=request.metric_state,
                runtime_budget_seconds=search_budget,
                cancel_event=cancel_event,
            )
            budget_exhausted = budget_exhausted or coarse.diagnostics.budget_exhausted
            force_ambiguous = force_ambiguous or coarse.state == RegistrationProposalState.AMBIGUOUS
            aggregate_findings.extend(coarse.findings)
            if not coarse.candidates:
                solver_records.append(
                    {
                        "orientation_id": orientation_id,
                        "source_plane_evidence_checksum": plane.evidence_checksum,
                        "up_sign": up_sign,
                        "search_state": coarse.state.value,
                        "search_diagnostics": asdict(coarse.diagnostics),
                        "candidate_count": 0,
                    }
                )
                continue

            renamed_candidates = tuple(
                replace(
                    candidate,
                    candidate_id=self._candidate_id(orientation_id, candidate.candidate_id),
                )
                for candidate in coarse.candidates
            )
            named_coarse = replace(coarse, candidates=renamed_candidates)
            refined = refine_registration_candidates(
                named_coarse,
                source_points_m,
                target.collision_surface_points_world_m,
                target.collision_surface_normals_world,
                source_frame=plane.frame,
                target_floor=target.target_floor,
                profile=request.profile,
                runtime_budget_seconds=icp_budget,
                maximum_candidates=candidate_budget,
                cancel_event=cancel_event,
            )
            budget_exhausted = budget_exhausted or refined.diagnostics.budget_exhausted
            force_ambiguous = force_ambiguous or refined.state == RegistrationProposalState.AMBIGUOUS
            aggregate_findings.extend(refined.findings)
            if refined.state in {RegistrationProposalState.PROPOSED, RegistrationProposalState.AMBIGUOUS}:
                measured.extend(_MeasuredCandidate(item, plane) for item in refined.candidates)
            solver_records.append(
                {
                    "orientation_id": orientation_id,
                    "source_plane_evidence_checksum": plane.evidence_checksum,
                    "up_sign": up_sign,
                    "search_state": coarse.state.value,
                    "search_diagnostics": asdict(coarse.diagnostics),
                    "icp_state": refined.state.value,
                    "icp_diagnostics": asdict(refined.diagnostics),
                }
            )

        measured = self._deduplicate_measured(measured, request.profile.bev_cell_resolution_m)
        measured.sort(
            key=lambda item: (
                -item.refined.candidate.score,
                -item.refined.overlap_ratio,
                item.refined.candidate.candidate_id,
            )
        )
        measured = measured[: request.profile.top_k_candidates]
        margin = (
            measured[0].refined.candidate.score - measured[1].refined.candidate.score if len(measured) > 1 else None
        )
        if budget_exhausted:
            aggregate_findings.append(RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED)
            if len(measured) >= 2:
                state = RegistrationProposalState.AMBIGUOUS
                findings = [RegistrationFindingCode.AMBIGUOUS_CANDIDATES]
            else:
                state = RegistrationProposalState.INSUFFICIENT
                findings = [RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED]
                measured = []
        elif not measured:
            state = RegistrationProposalState.INSUFFICIENT
            findings = list(dict.fromkeys(aggregate_findings)) or [RegistrationFindingCode.UNOBSERVABLE]
        elif (force_ambiguous or (margin is not None and margin < request.profile.minimum_candidate_margin)) and len(
            measured
        ) >= 2:
            state = RegistrationProposalState.AMBIGUOUS
            findings = [RegistrationFindingCode.AMBIGUOUS_CANDIDATES]
        elif force_ambiguous:
            state = RegistrationProposalState.INSUFFICIENT
            findings = [RegistrationFindingCode.AMBIGUOUS_CANDIDATES]
            measured = []
        else:
            state = RegistrationProposalState.PROPOSED
            findings = []

        diagnostics = {
            "worker_version": _WORKER_VERSION,
            "source_plane_method": _SOURCE_PLANE_VERSION,
            "bev_method": _BEV_VERSION,
            "icp_method": _ICP_VERSION,
            "profile_checksum": request.profile_checksum,
            "source_plane_report_checksum": plane_report.evidence_checksum,
            "orientation_hypotheses": len(orientations),
            "search_budget_seconds_per_hypothesis": search_budget,
            "icp_budget_seconds_per_hypothesis": icp_budget,
            "icp_candidate_limit_per_hypothesis": candidate_budget,
            "budget_exhausted": budget_exhausted,
            "solver_records": solver_records,
        }
        return measured, diagnostics, state, findings, margin

    @staticmethod
    def _candidate_id(orientation_id: str, candidate_id: str) -> str:
        digest = hashlib.sha256(f"{orientation_id}:{candidate_id}".encode()).hexdigest()[:24]
        return f"registration-{digest}"

    @staticmethod
    def _deduplicate_measured(candidates: list[_MeasuredCandidate], resolution_m: float) -> list[_MeasuredCandidate]:
        unique: list[_MeasuredCandidate] = []
        translation_limit = max(0.03, resolution_m * 0.5)
        rotation_limit = math.radians(2.0)
        for candidate in sorted(candidates, key=lambda item: -item.refined.candidate.score):
            transform = candidate.refined.candidate.transform_target_from_source
            rotation = rotation_matrix(transform.rotation_quaternion_xyzw)
            translation = np.asarray(transform.translation_xyz, dtype=float)
            duplicate = False
            for kept in unique:
                other = kept.refined.candidate.transform_target_from_source
                other_rotation = rotation_matrix(other.rotation_quaternion_xyzw)
                other_translation = np.asarray(other.translation_xyz, dtype=float)
                cosine = float(np.clip((np.trace(rotation @ other_rotation.T) - 1.0) / 2.0, -1.0, 1.0))
                angle = math.acos(cosine)
                same_scale = candidate.refined.candidate.rgb_scale_factor == kept.refined.candidate.rgb_scale_factor
                if (
                    same_scale
                    and np.linalg.norm(translation - other_translation) <= translation_limit
                    and angle <= rotation_limit
                ):
                    duplicate = True
                    break
            if not duplicate:
                unique.append(candidate)
        return unique

    @staticmethod
    def _proposal(
        operation: RegistrationOperationRecord,
        source_ref: ProductArtifactRef,
        state: RegistrationProposalState,
        findings: list[RegistrationFindingCode],
        candidates: list[Any],
    ) -> RegistrationProposal:
        request = operation.request
        selected_candidate_id = candidates[0].candidate_id if state == RegistrationProposalState.PROPOSED else None
        return seal_registration_proposal(
            {
                "job_id": operation.target_job_id,
                "input_mode": request.source.mode,
                "request_checksum": request.request_checksum,
                "source_input_checksum": request.source.source_input_checksum,
                "source_geometry_ref": source_ref,
                "target_rgb_geometry_ref": request.target_rgb_geometry_ref,
                "target_scene_revision": request.expected_scene_revision,
                "profile_checksum": request.profile_checksum,
                "tool_checksum": canonical_content_checksum(
                    {
                        "worker": _WORKER_VERSION,
                        "source_planes": _SOURCE_PLANE_VERSION,
                        "bev": _BEV_VERSION,
                        "icp": _ICP_VERSION,
                        "tool_checksum": "sha256:" + "0" * 64,
                    },
                    "tool_checksum",
                ),
                "source_frame": request.source.source_frame,
                "state": state,
                "candidates": candidates if state != RegistrationProposalState.INSUFFICIENT else [],
                "selected_candidate_id": selected_candidate_id,
                "findings": findings,
                "proposal_checksum": "sha256:" + "0" * 64,
            }
        )

    @staticmethod
    def _floor_difference(candidate: _MeasuredCandidate, target: VerifiedRegistrationTarget) -> float:
        plane = candidate.source_plane
        normal = np.asarray(plane.normal_xyz, dtype=float)
        norm_squared = float(np.dot(normal, normal))
        point_on_source_plane = -plane.offset_m * normal / norm_squared
        transform = candidate.refined.candidate.transform_target_from_source
        point_world = rotation_matrix(transform.rotation_quaternion_xyzw) @ point_on_source_plane + np.asarray(
            transform.translation_xyz, dtype=float
        )
        target_normal = np.asarray(target.target_floor.normal_xyz, dtype=float)
        target_norm = float(np.linalg.norm(target_normal))
        return abs(float(np.dot(target_normal, point_world) + target.target_floor.offset_m)) / target_norm

    def _assert_target_revision(self, request: RegistrationRequest) -> None:
        current = self.registry.scene.current(request.target_job_id).scene.scene_revision
        if current != request.expected_scene_revision:
            raise RegistrationTargetResolutionError("registration target scene revision is stale")

    @staticmethod
    def _check_cancelled(heartbeat: _OperationHeartbeat) -> None:
        if heartbeat.cancel_event.is_set():
            raise RegistrationCancelledError("registration worker lost cancellation-safe ownership")

    @staticmethod
    def _check_cancelled_event(cancel_event: Event) -> None:
        if cancel_event.is_set():
            raise RegistrationCancelledError("registration worker lost cancellation-safe ownership")

    @staticmethod
    def _operation_state(state: RegistrationProposalState) -> RegistrationOperationState:
        return {
            RegistrationProposalState.PROPOSED: RegistrationOperationState.PROPOSED,
            RegistrationProposalState.AMBIGUOUS: RegistrationOperationState.AMBIGUOUS,
            RegistrationProposalState.INSUFFICIENT: RegistrationOperationState.INSUFFICIENT,
            RegistrationProposalState.FAILED: RegistrationOperationState.FAILED,
        }[state]

    def _finish_cancelled_or_failed(
        self,
        operation: RegistrationOperationRecord,
        heartbeat_reason: str | None,
        *,
        error_code: str = "REGISTRATION_WORKER_FAILED",
    ) -> None:
        if heartbeat_reason == "cancelled":
            self._finish(operation, RegistrationOperationState.CANCELLED)
        elif heartbeat_reason in {"lease_lost", "heartbeat_failed"}:
            logger.warning(
                "Registration lease unavailable operation=%s reason=%s", operation.operation_id, heartbeat_reason
            )
        else:
            self._finish(operation, RegistrationOperationState.FAILED, error=error_code)

    def _finish(
        self,
        operation: RegistrationOperationRecord,
        state: RegistrationOperationState,
        *,
        proposal_ref: ProductArtifactRef | None = None,
        qa_report_ref: ProductArtifactRef | None = None,
        error: str | None = None,
    ) -> None:
        try:
            self.store.finish(
                operation.operation_id,
                lease_token=operation.lease_token or "",
                fencing_token=operation.fencing_token,
                state=state,
                proposal_ref=proposal_ref,
                qa_report_ref=qa_report_ref,
                error=error,
            )
        except RegistrationOperationCancellationRequestedError:
            self.store.finish(
                operation.operation_id,
                lease_token=operation.lease_token or "",
                fencing_token=operation.fencing_token,
                state=RegistrationOperationState.CANCELLED,
            )
        except RegistrationOperationLeaseLostError:
            logger.warning("Registration result fenced by a newer lease operation=%s", operation.operation_id)

    @staticmethod
    def _failure_code(error: Exception) -> str:
        if isinstance(error, RegistrationSourceResolutionError):
            return "REGISTRATION_SOURCE_INVALID"
        if isinstance(error, RegistrationTargetResolutionError):
            return "REGISTRATION_TARGET_INVALID_OR_STALE"
        if isinstance(error, ArtifactNotFoundError):
            return "REGISTRATION_ARTIFACT_MISSING"
        return "REGISTRATION_WORKER_FAILED"
