"""Durable Isaac validation consumer and immutable report publication."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from threading import Event, Thread
from typing import Protocol

from pydantic import ValidationError

from src.config import Settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import RuntimeComponent, RuntimeManifest
from src.models.contracts.validation import (
    ObservedPathResult,
    PathResult,
    RuleResult,
    ValidationCheck,
    ValidationReport,
)
from src.models.contracts.validation_run import (
    IsaacValidationRuntimeProfile,
    ValidationConfig,
    ValidationRunRecord,
    ValidationRunStatus,
)
from src.services.orchestration.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactResolver,
    ArtifactStoreError,
    FilesystemArtifactStore,
    sha256_bytes,
)
from src.services.orchestration.jobs.admission import (
    OperationAdmissionRequest,
    OperationResourceProfile,
    ResourceAdmission,
)
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.heartbeat import HeartbeatTolerance
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.review.simulation_package import SimulationPackage, current_package
from src.services.orchestration.review.validation_queue import (
    ValidationClaim,
    ValidationQueue,
    ValidationQueueError,
)
from src.services.process_control import ProcessCancelledError
from src.services.simulation.isaac.process import (
    IsaacExecutionObservations,
    IsaacValidationProcess,
    IsaacValidationProcessError,
    IsaacValidationRequest,
)

logger = logging.getLogger(__name__)
_ZERO_CHECKSUM = "sha256:" + "0" * 64
_HEARTBEAT_SECONDS = 20
_MAX_LOG_BYTES = 64 * 1024 * 1024
_MAX_OBSERVATION_BYTES = 16 * 1024 * 1024
_VALIDATOR_VERSION = "r2s-isaac-candidate-validator-1.0"


class IsaacProcess(Protocol):
    """Subprocess boundary, replaceable by a protocol-only fake in local tests."""

    def run(
        self,
        request: IsaacValidationRequest,
        resolver: ArtifactResolver,
        workspace: Path,
        *,
        cancel_event: Event | None = None,
    ) -> IsaacExecutionObservations: ...


class _ValidationHeartbeat:
    """Keep the durable worker lease and GPU reservation alive until publication ends."""

    def __init__(
        self,
        queue: ValidationQueue,
        admission: ResourceAdmission,
        claim: ValidationClaim,
        admission_request: OperationAdmissionRequest,
    ) -> None:
        self.queue = queue
        self.admission = admission
        self.claim = claim
        self.admission_request = admission_request
        self.stop_event = Event()
        self.cancel_event = Event()
        self.reason: str | None = None
        self.thread = Thread(target=self._run, name=f"isaac-validation-{claim.run.run_id[:12]}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=_HEARTBEAT_SECONDS + 1)

    def _abort(self, reason: str) -> None:
        self.reason = reason
        self.cancel_event.set()

    def _run(self) -> None:
        tolerance = HeartbeatTolerance(self.queue.lease_ttl)
        while not self.stop_event.wait(_HEARTBEAT_SECONDS):
            try:
                if self.queue.heartbeat(self.claim):
                    self._abort("cancelled")
                    return
                tolerance.succeeded()
            except RuntimeStateConflictError:
                self._abort("lease_lost")
                return
            except Exception as error:  # noqa: BLE001 - lease loss must terminate the child process
                if tolerance.tolerate(error):
                    continue  # DB chập chờn: thử lại nhịp sau trong khi lease còn hạn
                logger.warning(
                    "Isaac validation heartbeat failed run=%s cause=%s",
                    self.claim.run.run_id,
                    type(error).__name__,
                )
                self._abort("heartbeat_failed")
                return
            if not self.admission.touch_operation(self.admission_request):
                self._abort("reservation_lost")
                return


class IsaacValidationWorker:
    """Claim, admit, execute and publish one exact candidate validation attempt."""

    def __init__(
        self,
        registry: ProjectRegistry,
        settings: Settings,
        admission: ResourceAdmission,
        *,
        process: IsaacProcess | None = None,
        resource_profile: OperationResourceProfile | None = None,
    ) -> None:
        if registry.persistence is None:
            raise ValueError("Isaac validation worker requires durable project persistence")
        self.registry = registry
        self.settings = settings
        self.admission = admission
        self.queue = ValidationQueue(registry.persistence.database, registry.runtime_resolver)
        self.artifacts = FilesystemArtifactStore(registry.runtime_resolver)
        self.workspace_root = settings.product_worker_root.expanduser().resolve() / "isaac_validation"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.runtime_configured = process is not None or settings.product_isaac_validation_launcher is not None
        self.process: IsaacProcess = process or IsaacValidationProcess(
            [str(settings.product_isaac_validation_launcher)]
            if settings.product_isaac_validation_launcher is not None
            else None
        )
        self.resource_profile, self.resource_profile_error = self._load_resource_profile(resource_profile)

    def process_next(self) -> bool:
        """Process at most one validation; False means no work or resource wait."""
        claim = self.queue.claim_next(self.admission.worker_id)
        if claim is None:
            return False
        if not self.runtime_configured:
            self.queue.fail(claim, error_code="ISAAC_RUNTIME_NOT_CONFIGURED", retryable=False)
            return True
        if self.resource_profile_error is not None:
            self.queue.fail(claim, error_code="ISAAC_RESOURCE_PROFILE_INVALID", retryable=False)
            logger.error("Invalid Isaac resource profile run=%s", claim.run.run_id)
            return True

        try:
            package, config, profile = self._load_inputs(claim)
        except (ArtifactStoreError, OSError, ValidationError, ValidationQueueError, ValueError) as error:
            retryable = isinstance(error, ArtifactStoreError)
            self.queue.fail(
                claim,
                error_code="ISAAC_VALIDATION_INPUT_INVALID" if not retryable else "ISAAC_VALIDATION_INPUT_UNAVAILABLE",
                retryable=retryable,
            )
            logger.warning("Isaac validation input rejected run=%s cause=%s", claim.run.run_id, type(error).__name__)
            return True

        if package is None or package.candidate is None or package.package_ref is None:
            self.queue.start(claim, current_candidate_checksum=None)
            return True
        if (
            package.job_id != claim.run.job_id
            or package.scene_revision != claim.run.scene_revision
            or package.scene_ir_checksum != claim.run.scene_ir_checksum
            or package.candidate.candidate_checksum != claim.run.candidate_checksum
            or package.package_ref.job_id != claim.run.job_id
            or package.package_ref.artifact_type != "SimulationPackageArchive"
        ):
            self.queue.start(claim, current_candidate_checksum=None)
            return True

        admission_request = self.queue.admission_request(claim, self.resource_profile)
        admitted = self.admission.admit_operation(admission_request)
        if admitted.status != "admitted":
            if admitted.status == "identity_conflict":
                self.queue.fail(claim, error_code="ISAAC_RESOURCE_IDENTITY_CONFLICT", retryable=False)
                return True
            self.queue.wait_for_resources(claim)
            return False

        heartbeat: _ValidationHeartbeat | None = None
        workspace: Path | None = None
        completed = False
        try:
            running = self.queue.start(claim, current_candidate_checksum=package.candidate.candidate_checksum)
            if running.status != ValidationRunStatus.RUNNING:
                return True
            request = IsaacValidationRequest(
                run=running,
                candidate=package.candidate,
                candidate_package_ref=package.package_ref,
                config=config,
                profile=profile,
            )
            workspace = self._create_workspace(claim)
            heartbeat = _ValidationHeartbeat(self.queue, self.admission, claim, admission_request)
            heartbeat.start()
            observations = self.process.run(
                request,
                self.registry.runtime_resolver,
                workspace,
                cancel_event=heartbeat.cancel_event,
            )
            self._verify_observations(request, observations)
            if heartbeat.reason is not None:
                self._finish_abort(claim, heartbeat.reason)
                return True
            self._publish_completed_run(claim, request, observations, workspace)
            completed = True
            return True
        except ProcessCancelledError:
            reason = heartbeat.reason if heartbeat is not None else None
            self._finish_abort(claim, reason or "process_interrupted")
            return True
        except IsaacValidationProcessError as error:
            self._fail_or_cancel(claim, heartbeat, error.error_code, retryable=error.retryable)
            logger.warning("Isaac validation failed run=%s code=%s", claim.run.run_id, error.error_code)
            return True
        except (ArtifactStoreError, OSError) as error:
            self._fail_or_cancel(claim, heartbeat, "ISAAC_ARTIFACT_PUBLICATION_FAILED", retryable=True)
            logger.warning(
                "Isaac validation publication failed run=%s cause=%s", claim.run.run_id, type(error).__name__
            )
            return True
        except (ValidationError, ValueError, ValidationQueueError) as error:
            self._fail_or_cancel(claim, heartbeat, "ISAAC_VALIDATION_RESULT_INVALID", retryable=False)
            logger.warning("Isaac validation result rejected run=%s cause=%s", claim.run.run_id, type(error).__name__)
            return True
        except Exception:  # noqa: BLE001 - worker boundary persists unexpected failure, never reports PASS
            self._fail_or_cancel(claim, heartbeat, "ISAAC_WORKER_INTERNAL_ERROR", retryable=False)
            logger.exception("Isaac validation worker crashed run=%s", claim.run.run_id)
            return True
        finally:
            if heartbeat is not None:
                heartbeat.stop()
            self.admission.release_operation(admission_request)
            if completed and workspace is not None and not self.settings.product_worker_keep_scratch:
                shutil.rmtree(workspace, ignore_errors=True)

    def _load_inputs(
        self, claim: ValidationClaim
    ) -> tuple[SimulationPackage | None, ValidationConfig, IsaacValidationRuntimeProfile]:
        config = self.registry.runtime_resolver.load_model(claim.run.validation_config_ref, ValidationConfig)
        verify_content_checksum(config, "config_checksum")
        if config.config_checksum != claim.run.validation_config_checksum or config.runtime_profile_ref is None:
            raise ValidationQueueError("validation run does not bind its exact runtime profile")
        profile = self.registry.runtime_resolver.load_model(
            config.runtime_profile_ref,
            IsaacValidationRuntimeProfile,
        )
        verify_content_checksum(profile, "profile_checksum")
        base_runtime = self.registry.runtime_resolver.load_model(profile.runtime_manifest_ref, RuntimeManifest)
        verify_content_checksum(base_runtime, "runtime_manifest_checksum")
        package = current_package(self.registry, claim.run.job_id)
        return package, config, profile

    def _publish_completed_run(
        self,
        claim: ValidationClaim,
        request: IsaacValidationRequest,
        observations: IsaacExecutionObservations,
        workspace: Path,
    ) -> None:
        if observations.run_id != claim.run.run_id:
            raise ValidationQueueError("Isaac observations do not bind the claimed run")
        log_path = workspace / "isaac_execution.log"
        if log_path.is_symlink() or not log_path.is_file() or log_path.stat().st_size > _MAX_LOG_BYTES:
            raise ValidationQueueError("Isaac execution log is missing, unsafe or too large")
        log_payload = log_path.read_bytes()
        observations_payload = observations.model_dump_json(indent=2).encode("utf-8")
        if len(observations_payload) > _MAX_OBSERVATION_BYTES:
            raise ValidationQueueError("Isaac observations exceed the publication size limit")

        run = claim.run
        runtime_source = self.registry.runtime_resolver.load_model(
            request.profile.runtime_manifest_ref,
            RuntimeManifest,
        )
        verify_content_checksum(runtime_source, "runtime_manifest_checksum")
        runtime = self._runtime_manifest(runtime_source, observations)
        runtime_ref = self._publish_model_artifact(run, "RuntimeManifest", "runtime_manifest.json", runtime)
        log_ref = self._publish_bytes_artifact(run, "ValidationExecutionLog", "execution.log", log_payload)
        observations_ref = self._publish_bytes_artifact(
            run,
            "IsaacExecutionObservations",
            "observations.json",
            observations_payload,
        )
        report = self._build_report(request, observations, observations_ref, log_ref)
        report_ref = self._publish_model_artifact(run, "ValidationReport", "validation_report.json", report)
        self.queue.complete(
            claim,
            runtime_manifest_ref=runtime_ref,
            report_ref=report_ref,
            report_checksum=report.report_checksum,
            execution_log_ref=log_ref,
        )

    @staticmethod
    def _verify_observations(
        request: IsaacValidationRequest,
        observations: IsaacExecutionObservations,
    ) -> None:
        if (
            observations.run_id != request.run.run_id
            or observations.candidate_checksum != request.candidate.candidate_checksum
            or observations.config_checksum != request.config.config_checksum
            or observations.profile_checksum != request.profile.profile_checksum
            or observations.runtime_identity != request.profile.runtime_identity
            or observations.runtime_versions.get("isaac_sim") != request.profile.runtime_identity
        ):
            raise ValidationQueueError("Isaac observations do not match the bound run, candidate or runtime")
        expected_checks = set(request.config.required_check_ids) | set(request.config.warning_check_ids)
        expected_paths = {pair.pair_id for pair in request.config.path_pairs}
        if {item.check_id for item in observations.checks} != expected_checks:
            raise ValidationQueueError("Isaac observation check IDs differ from the bound validation policy")
        if {item.pair_id for item in observations.path_results} != expected_paths:
            raise ValidationQueueError("Isaac observed path IDs differ from the bound validation policy")

    @staticmethod
    def _runtime_manifest(
        source: RuntimeManifest,
        observations: IsaacExecutionObservations,
    ) -> RuntimeManifest:
        components = dict(source.components)
        for name, version in observations.runtime_versions.items():
            components[name] = RuntimeComponent(status="VERIFIED", version=version)
        draft = RuntimeManifest(
            schema_version=source.schema_version,
            components=components,
            runtime_manifest_checksum=_ZERO_CHECKSUM,
        )
        return draft.model_copy(
            update={"runtime_manifest_checksum": canonical_content_checksum(draft, "runtime_manifest_checksum")}
        )

    @staticmethod
    def _build_report(
        request: IsaacValidationRequest,
        observations: IsaacExecutionObservations,
        observations_ref: ProductArtifactRef,
        log_ref: ProductArtifactRef,
    ) -> ValidationReport:
        checks_by_id = {item.check_id: item for item in observations.checks}
        paths_by_id = {item.pair_id: item for item in observations.path_results}
        evidence_refs = [observations_ref, log_ref]
        checks = [
            ValidationCheck(
                check_id=check_id,
                result=checks_by_id[check_id].result,
                evidence_refs=evidence_refs,
                message=checks_by_id[check_id].message,
            )
            for check_id in (*request.config.required_check_ids, *request.config.warning_check_ids)
        ]
        paths = [
            PathResult(
                pair_id=pair.pair_id,
                result=paths_by_id[pair.pair_id].result,
                evidence_refs=evidence_refs,
                message=paths_by_id[pair.pair_id].message,
            )
            for pair in request.config.path_pairs
        ]
        results = [item.result for item in checks]
        results.extend(
            RuleResult.ERROR
            if path.result == ObservedPathResult.ERROR
            else RuleResult.FAIL
            if path.result == ObservedPathResult.BLOCKED
            and next(pair for pair in request.config.path_pairs if pair.pair_id == path.pair_id).required
            else RuleResult.PASS
            for path in paths
        )
        overall = (
            RuleResult.ERROR
            if RuleResult.ERROR in results
            else RuleResult.FAIL
            if RuleResult.FAIL in results
            else RuleResult.PASS
        )
        draft = ValidationReport(
            schema_version="1.0",
            candidate_checksum=request.run.candidate_checksum,
            validator_version=_VALIDATOR_VERSION,
            environment_versions=observations.runtime_versions,
            checks=checks,
            path_results=paths,
            overall_result=overall,
            report_checksum=_ZERO_CHECKSUM,
        )
        return draft.model_copy(update={"report_checksum": canonical_content_checksum(draft, "report_checksum")})

    def _publish_model_artifact(
        self,
        run: ValidationRunRecord,
        artifact_type: str,
        filename: str,
        model: RuntimeManifest | ValidationReport,
    ) -> ProductArtifactRef:
        payload = model.model_dump_json(indent=2).encode("utf-8")
        return self._publish_bytes_artifact(run, artifact_type, filename, payload)

    def _publish_bytes_artifact(
        self,
        run: ValidationRunRecord,
        artifact_type: str,
        filename: str,
        payload: bytes,
    ) -> ProductArtifactRef:
        candidate = run.candidate_checksum.removeprefix("sha256:")
        config = run.validation_config_checksum.removeprefix("sha256:")
        uri = f"artifact://jobs/{run.job_id}/validation/{candidate}/{config}/{run.run_id}/{filename}"
        reference = ProductArtifactRef(
            schema_version="1.0",
            artifact_type=artifact_type,
            data_class="derived",
            artifact_uri=uri,
            artifact_checksum=sha256_bytes(payload),
            producer_stage="ST-ISAAC-VALIDATE",
            job_id=run.job_id,
        )
        try:
            self.artifacts.publish(reference, payload)
        except ArtifactAlreadyExistsError:
            existing = self.registry.runtime_resolver.require(reference)
            if existing.read_bytes() != payload:
                raise ValidationQueueError("validation artifact URI already contains different bytes")
        return reference

    def _create_workspace(self, claim: ValidationClaim) -> Path:
        name = f"{claim.run.run_id}-{claim.fencing_token}"
        workspace = self.workspace_root / name
        workspace.mkdir(mode=0o700, exist_ok=False)
        return workspace

    def _load_resource_profile(
        self,
        provided: OperationResourceProfile | None,
    ) -> tuple[OperationResourceProfile, Exception | None]:
        if provided is not None:
            return provided, None
        path = self.settings.product_isaac_validation_resources
        if path is None:
            return (
                OperationResourceProfile(
                    required_gb={"vram": None, "ram": None, "disk": None},
                    danger_ratio=None,
                    measured=False,
                    gpu_required=True,
                ),
                None,
            )
        try:
            if not path.is_file():
                raise OSError("configured resource profile is missing")
            return OperationResourceProfile.model_validate_json(path.read_bytes()), None
        except (OSError, ValidationError, ValueError) as error:
            return (
                OperationResourceProfile(
                    required_gb={"vram": None, "ram": None, "disk": None},
                    danger_ratio=None,
                    measured=False,
                    gpu_required=True,
                ),
                error,
            )

    def _finish_abort(self, claim: ValidationClaim, reason: str) -> None:
        if reason == "cancelled":
            self.queue.finish_cancelled(claim)
        elif reason == "process_interrupted":
            self.queue.fail(claim, error_code="ISAAC_PROCESS_INTERRUPTED", retryable=True)
        else:
            logger.error("Isaac validation lost ownership run=%s reason=%s", claim.run.run_id, reason)

    def _fail_or_cancel(
        self,
        claim: ValidationClaim,
        heartbeat: _ValidationHeartbeat | None,
        error_code: str,
        *,
        retryable: bool,
    ) -> None:
        if heartbeat is not None and heartbeat.reason is not None:
            self._finish_abort(claim, heartbeat.reason)
            return
        try:
            if self.queue.heartbeat(claim):
                self.queue.finish_cancelled(claim)
            else:
                self.queue.fail(claim, error_code=error_code, retryable=retryable)
        except RuntimeStateConflictError:
            logger.info("Isaac validation lease already ended run=%s", claim.run.run_id)
