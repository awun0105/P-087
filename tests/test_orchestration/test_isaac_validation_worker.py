from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.validation import (
    ObservedPathResult,
    RuleResult,
    ValidationReport,
)
from src.models.contracts.validation_run import ValidationRunStatus
from src.services.orchestration.artifacts import ArtifactChecksumError
from src.services.orchestration.jobs.admission import OperationResourceProfile
from src.services.orchestration.review import validation_worker as worker_module
from src.services.orchestration.review.validation_queue import ValidationQueue
from src.services.orchestration.review.validation_worker import IsaacValidationWorker
from src.services.simulation.isaac.process import (
    IsaacCheckObservation,
    IsaacExecutionObservations,
    IsaacPathObservation,
    IsaacValidationProcessError,
)


class _Admission:
    worker_id = "isaac-worker-test"

    def __init__(self, *, status: str = "admitted") -> None:
        self.status = status
        self.requests = []
        self.released = []

    def admit_operation(self, request):  # noqa: ANN001
        self.requests.append(request)
        return SimpleNamespace(status=self.status)

    def touch_operation(self, request):  # noqa: ANN001
        return True

    def release_operation(self, request):  # noqa: ANN001
        self.released.append(request)
        return True


class _Process:
    def run(self, request, resolver, workspace, *, cancel_event=None):  # noqa: ANN001
        assert cancel_event is not None
        (workspace / "isaac_execution.log").write_text("Isaac validation child completed\n", encoding="utf-8")
        return IsaacExecutionObservations(
            schema_version="1.0",
            run_id=request.run.run_id,
            candidate_checksum=request.candidate.candidate_checksum,
            config_checksum=request.config.config_checksum,
            profile_checksum=request.profile.profile_checksum,
            runtime_identity=request.profile.runtime_identity,
            runtime_versions={"isaac_sim": request.profile.runtime_identity, "physx": "test-physx"},
            checks=[
                IsaacCheckObservation(check_id=check_id, result=RuleResult.PASS, message="observed")
                for check_id in (*request.config.required_check_ids, *request.config.warning_check_ids)
            ],
            path_results=[
                IsaacPathObservation(
                    pair_id=pair.pair_id,
                    result=ObservedPathResult.BLOCKED,
                    message="optional route intersects the environment",
                    sample_count=3,
                    collision_prim_paths=["/World/Environment/Collider"],
                )
                for pair in request.config.path_pairs
            ],
            max_penetration_m=None,
        )


class _TransientFailure:
    def run(self, request, resolver, workspace, *, cancel_event=None):  # noqa: ANN001
        raise IsaacValidationProcessError(
            "ISAAC_RUNTIME_TIMEOUT",
            "Isaac validation exceeded its timeout",
            retryable=True,
        )


def _world(tmp_path: Path):  # noqa: ANN201
    from tests.test_orchestration.test_review_workflow import _packaged
    from tests.test_orchestration.test_validation_queue import _config, _profile

    registry, job, _ = _packaged(tmp_path)
    package = worker_module.current_package(registry, job.job_id)
    assert package is not None and package.candidate is not None
    from src.services.orchestration.review.validation_queue import ValidationCandidateSnapshot

    snapshot = ValidationCandidateSnapshot(
        job_id=job.job_id,
        scene_revision=package.scene_revision,
        scene_ir_checksum=package.scene_ir_checksum,
        candidate_checksum=package.candidate.candidate_checksum,
    )
    queue = ValidationQueue(registry.persistence.database, registry.runtime_resolver)
    config, profile = _config(), _profile(registry.runtime_resolver)
    submitted = queue.submit(
        snapshot,
        config,
        profile=profile,
        requester_id="test-editor",
        idempotency_key="isaac-worker-request",
    )
    settings = Settings(
        openai_api_key="test-only-key",
        product_worker_root=tmp_path / "worker",
        product_isaac_validation_launcher=Path("/test/isaac/python.sh"),
    )
    resources = OperationResourceProfile(
        required_gb={"vram": 4.0, "ram": 8.0, "disk": 10.0},
        danger_ratio=0.9,
        measured=False,
        gpu_required=True,
    )
    admission = _Admission()
    worker = IsaacValidationWorker(
        registry,
        settings,
        admission,
        process=_Process(),
        resource_profile=resources,
    )
    return registry, submitted, worker, admission, settings


def test_worker_publishes_exact_report_and_completes_only_after_artifacts_verify(tmp_path: Path) -> None:
    registry, submitted, worker, admission, settings = _world(tmp_path)

    assert worker.process_next() is True

    queue = ValidationQueue(registry.persistence.database, registry.runtime_resolver)
    view = queue.get(submitted.job_id, submitted.run_id)
    run = queue.runs.get_run(submitted.run_id)
    assert view.status.value == "COMPLETED"
    assert run.status == ValidationRunStatus.COMPLETED
    assert run.runtime_manifest_ref is not None
    assert run.report_ref is not None
    assert run.execution_log_ref is not None
    report = registry.runtime_resolver.load_model(run.report_ref, ValidationReport)
    verify_content_checksum(report, "report_checksum")
    assert report.candidate_checksum == run.candidate_checksum
    assert report.overall_result == RuleResult.PASS
    assert report.path_results[0].result == ObservedPathResult.BLOCKED
    assert report.checks[0].evidence_refs[0].artifact_type == "IsaacExecutionObservations"
    assert report.checks[0].evidence_refs[1].artifact_type == "ValidationExecutionLog"
    assert registry.runtime_resolver.require(run.execution_log_ref).read_text() == "Isaac validation child completed\n"
    assert len(admission.requests) == 1 and len(admission.released) == 1
    assert not list((settings.product_worker_root / "isaac_validation").glob("*"))
    observation_ref = report.checks[0].evidence_refs[0]
    registry.runtime_resolver.require(observation_ref).write_bytes(b"tampered after publication")
    with pytest.raises(ArtifactChecksumError):
        queue.runs.get_run(submitted.run_id)


def test_resource_wait_requeues_without_starting_or_releasing_an_unheld_reservation(tmp_path: Path) -> None:
    registry, submitted, worker, admission, _ = _world(tmp_path)
    admission.status = "waiting_resources"

    assert worker.process_next() is False

    queue = ValidationQueue(registry.persistence.database, registry.runtime_resolver)
    view = queue.get(submitted.job_id, submitted.run_id)
    assert view.status.value == "WAITING_RESOURCES"
    assert view.run_status == ValidationRunStatus.QUEUED
    assert admission.released == []


def test_stale_current_package_is_cancelled_before_resource_admission(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    registry, submitted, worker, admission, _ = _world(tmp_path)
    monkeypatch.setattr(worker_module, "current_package", lambda _registry, _job_id: None)

    assert worker.process_next() is True

    queue = ValidationQueue(registry.persistence.database, registry.runtime_resolver)
    view = queue.get(submitted.job_id, submitted.run_id)
    assert view.run_status == ValidationRunStatus.CANCELLED
    assert view.error_code == "STALE_CANDIDATE"
    assert admission.requests == []


def test_retryable_runtime_failure_stays_failed_and_retains_attempt_scratch(tmp_path: Path) -> None:
    registry, submitted, worker, _, settings = _world(tmp_path)
    worker.process = _TransientFailure()

    assert worker.process_next() is True

    queue = ValidationQueue(registry.persistence.database, registry.runtime_resolver)
    view = queue.get(submitted.job_id, submitted.run_id)
    assert view.run_status == ValidationRunStatus.FAILED
    assert view.status.value == "FAILED"
    assert view.error_code == "ISAAC_RUNTIME_TIMEOUT"
    assert view.retryable is True
    assert list((settings.product_worker_root / "isaac_validation").glob(f"{submitted.run_id}-*"))
