"""Durable validation-attempt identities and run-specific evidence selection."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import RuntimeComponent, RuntimeManifest
from src.models.contracts.validation import RuleResult, ValidationCheck, ValidationReport
from src.models.contracts.validation_run import (
    ValidationConfig,
    ValidationRunOrigin,
    ValidationRunRecord,
    ValidationRunStatus,
)
from src.services.orchestration.artifacts import (
    ArtifactChecksumError,
    ArtifactResolver,
    FilesystemArtifactStore,
    sha256_bytes,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.review.validation_runs import ValidationRunError, ValidationRunRepository

ZERO = "sha256:" + "0" * 64
REQUESTED = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)


def _sealed(model, checksum_field: str):
    return model.model_copy(update={checksum_field: canonical_content_checksum(model, checksum_field)})


def _config() -> ValidationConfig:
    draft = ValidationConfig(
        schema_version="1.0",
        policy_id="test-public-validation-policy-v1",
        required_check_ids=["ISAAC_LOAD"],
        warning_check_ids=[],
        path_pairs=[],
        config_checksum=ZERO,
    )
    return _sealed(draft, "config_checksum")


def _publish_json(
    store: FilesystemArtifactStore, *, job_id: str, artifact_type: str, uri: str, model
) -> ProductArtifactRef:
    payload = model.model_dump_json(indent=2).encode()
    ref = ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=uri,
        artifact_checksum=sha256_bytes(payload),
        data_class="derived",
        producer_stage="ST-ISAAC-VALIDATE",
        job_id=job_id,
    )
    store.publish(ref, payload)
    return ref


def _world(tmp_path):
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'validation-runs.db'}")
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    repository = ValidationRunRepository(database, resolver)
    config = _config()
    config_ref = _publish_json(
        store,
        job_id="job-a",
        artifact_type="ValidationConfig",
        uri=repository.config_uri("job-a", config.config_checksum),
        model=config,
    )
    return repository, resolver, store, config, config_ref


def _report(candidate_checksum: str) -> ValidationReport:
    draft = ValidationReport(
        schema_version="1.0",
        candidate_checksum=candidate_checksum,
        validator_version="fixture-1",
        environment_versions={"isaac_sim": "fixture"},
        checks=[ValidationCheck(check_id="ISAAC_LOAD", result=RuleResult.PASS, evidence_refs=[])],
        path_results=[],
        overall_result=RuleResult.PASS,
        report_checksum=ZERO,
    )
    return _sealed(draft, "report_checksum")


def _queue(
    repository: ValidationRunRepository,
    config: ValidationConfig,
    config_ref: ProductArtifactRef,
    *,
    run_id: str,
    attempt: int,
    candidate_checksum: str = "sha256:" + "a" * 64,
    origin: ValidationRunOrigin = ValidationRunOrigin.WORKER,
) -> ValidationRunRecord:
    record = ValidationRunRecord(
        schema_version="1.0",
        run_id=run_id,
        attempt=attempt,
        job_id="job-a",
        scene_revision="rev-001",
        scene_ir_checksum="sha256:" + "b" * 64,
        candidate_checksum=candidate_checksum,
        validation_config_checksum=config.config_checksum,
        validation_config_ref=config_ref,
        origin=origin,
        synthetic_fixture_id="synthetic-review-fixture-v1" if origin == ValidationRunOrigin.SYNTHETIC_FIXTURE else None,
        status=ValidationRunStatus.QUEUED,
        requested_at=REQUESTED,
        run_checksum=ZERO,
    )
    record = _sealed(record, "run_checksum")
    repository.save_run(record)
    return record


def _complete(
    repository: ValidationRunRepository,
    store: FilesystemArtifactStore,
    config: ValidationConfig,
    config_ref: ProductArtifactRef,
    *,
    run_id: str,
    attempt: int,
    origin: ValidationRunOrigin = ValidationRunOrigin.WORKER,
    candidate_checksum: str = "sha256:" + "a" * 64,
    report_candidate_checksum: str | None = None,
    report_checksum_override: str | None = None,
    worker_id: str = "validator-01",
) -> ValidationRunRecord:
    queued = _queue(
        repository,
        config,
        config_ref,
        run_id=run_id,
        attempt=attempt,
        candidate_checksum=candidate_checksum,
        origin=origin,
    )
    running = queued.model_copy(
        update={
            "status": ValidationRunStatus.RUNNING,
            "started_at": REQUESTED + timedelta(seconds=1),
            "worker_id": worker_id if origin == ValidationRunOrigin.WORKER else None,
            "lease_id": "lease-01" if origin == ValidationRunOrigin.WORKER else None,
            "fencing_token": 1 if origin == ValidationRunOrigin.WORKER else None,
            "run_checksum": ZERO,
        }
    )
    running = _sealed(running, "run_checksum")
    repository.save_run(running, expected_run_checksum=queued.run_checksum)

    report = _report(report_candidate_checksum or candidate_checksum)
    report_ref = _publish_json(
        store,
        job_id="job-a",
        artifact_type="ValidationReport",
        uri=repository.report_uri("job-a", candidate_checksum, config.config_checksum, run_id),
        model=report,
    )
    runtime = RuntimeManifest(
        schema_version="1.0",
        components={"isaac_sim": RuntimeComponent(status="VERIFIED", version="fixture-only")},
        runtime_manifest_checksum=ZERO,
    )
    runtime = _sealed(runtime, "runtime_manifest_checksum")
    runtime_ref = _publish_json(
        store,
        job_id="job-a",
        artifact_type="RuntimeManifest",
        uri=repository.runtime_manifest_uri("job-a", candidate_checksum, config.config_checksum, run_id),
        model=runtime,
    )
    log_payload = f"synthetic test log for {run_id}\n".encode()
    log_ref = ProductArtifactRef(
        artifact_type="ValidationExecutionLog",
        schema_version="1.0",
        artifact_uri=repository.execution_log_uri("job-a", candidate_checksum, config.config_checksum, run_id),
        artifact_checksum=sha256_bytes(log_payload),
        data_class="derived",
        producer_stage="ST-ISAAC-VALIDATE",
        job_id="job-a",
    )
    store.publish(log_ref, log_payload)

    complete = running.model_copy(
        update={
            "status": ValidationRunStatus.COMPLETED,
            "completed_at": REQUESTED + timedelta(seconds=2),
            "runtime_manifest_ref": runtime_ref,
            "report_ref": report_ref,
            "report_checksum": report_checksum_override or report.report_checksum,
            "execution_log_ref": log_ref,
            "run_checksum": ZERO,
        }
    )
    complete = _sealed(complete, "run_checksum")
    repository.save_run(complete, expected_run_checksum=running.run_checksum)
    return complete


def test_config_checksum_and_ids_are_stable_and_unique(tmp_path) -> None:
    repository, resolver, _, config, config_ref = _world(tmp_path)
    loaded = ValidationConfig.model_validate_json(resolver.require(config_ref).read_bytes())
    assert loaded == config
    assert loaded.config_checksum == canonical_content_checksum(loaded, "config_checksum")
    with pytest.raises(ValidationError, match="both required and warning-only"):
        ValidationConfig(
            schema_version="1.0",
            policy_id="invalid",
            required_check_ids=["same"],
            warning_check_ids=["same"],
            path_pairs=[],
            config_checksum=ZERO,
        )
    assert repository.config_uri("job-a", config.config_checksum).endswith("validation_config.json")


def test_two_attempts_have_immutable_report_uris_and_selection_uses_exact_run(tmp_path) -> None:
    repository, _, store, config, config_ref = _world(tmp_path)
    first = _complete(repository, store, config, config_ref, run_id="run-001", attempt=1)
    second = _complete(repository, store, config, config_ref, run_id="run-002", attempt=2)

    listed = repository.list_runs("job-a", first.candidate_checksum, config.config_checksum)
    assert [record.attempt for record in listed] == [1, 2]
    assert first.report_ref and second.report_ref
    assert first.report_ref.artifact_uri != second.report_ref.artifact_uri

    selected = repository.select_run(
        "job-a", first.candidate_checksum, config.config_checksum, first.run_id, selected_at=REQUESTED
    )
    assert selected.run_id == first.run_id and selected.report_checksum == first.report_checksum
    updated = repository.select_run(
        "job-a",
        first.candidate_checksum,
        config.config_checksum,
        second.run_id,
        expected_selected_run_id=first.run_id,
        selected_at=REQUESTED + timedelta(seconds=3),
    )
    assert updated.run_id == second.run_id and updated.generation == 2
    assert repository.get_selection("job-a", first.candidate_checksum, config.config_checksum) == updated
    with pytest.raises(RuntimeStateConflictError, match="đã thay đổi"):
        repository.select_run("job-a", first.candidate_checksum, config.config_checksum, first.run_id)


def test_synthetic_fixture_can_be_persisted_but_never_selected(tmp_path) -> None:
    repository, _, store, config, config_ref = _world(tmp_path)
    synthetic = _complete(
        repository,
        store,
        config,
        config_ref,
        run_id="fixture-run",
        attempt=1,
        origin=ValidationRunOrigin.SYNTHETIC_FIXTURE,
    )
    assert synthetic.synthetic_fixture_id == "synthetic-review-fixture-v1"
    with pytest.raises(ValidationRunError, match="completed worker"):
        repository.select_run("job-a", synthetic.candidate_checksum, config.config_checksum, synthetic.run_id)


def test_rejects_wrong_config_candidate_report_checksum_and_worker_lease(tmp_path) -> None:
    repository, _, store, config, config_ref = _world(tmp_path)
    queued = _queue(repository, config, config_ref, run_id="wrong-config", attempt=1)
    wrong_config = queued.model_copy(update={"validation_config_checksum": "sha256:" + "c" * 64, "run_checksum": ZERO})
    wrong_config = _sealed(wrong_config, "run_checksum")
    # A ref cannot be rebound to another config checksum, and the queued identity cannot be rewritten.
    with pytest.raises(ValidationRunError, match="run-specific URI"):
        repository.save_run(wrong_config, expected_run_checksum=queued.run_checksum)
    wrong_candidate = queued.model_copy(update={"candidate_checksum": "sha256:" + "d" * 64, "run_checksum": ZERO})
    wrong_candidate = _sealed(wrong_candidate, "run_checksum")
    with pytest.raises(RuntimeStateConflictError, match="identity/worker provenance"):
        repository.save_run(wrong_candidate, expected_run_checksum=queued.run_checksum)

    with pytest.raises(ValidationRunError, match="report does not match|report không khớp"):
        _complete(
            repository,
            store,
            config,
            config_ref,
            run_id="wrong-report-candidate",
            attempt=2,
            report_candidate_checksum="sha256:" + "d" * 64,
        )

    with pytest.raises(ValidationRunError, match="report does not match|report không khớp"):
        _complete(
            repository,
            store,
            config,
            config_ref,
            run_id="wrong-report-checksum",
            attempt=3,
            report_checksum_override="sha256:" + "e" * 64,
        )

    worker_queued = _queue(repository, config, config_ref, run_id="wrong-worker", attempt=4)
    worker_running = worker_queued.model_copy(
        update={
            "status": ValidationRunStatus.RUNNING,
            "started_at": REQUESTED + timedelta(seconds=1),
            "worker_id": "validator-01",
            "lease_id": "lease-01",
            "fencing_token": 1,
            "run_checksum": ZERO,
        }
    )
    worker_running = _sealed(worker_running, "run_checksum")
    repository.save_run(worker_running, expected_run_checksum=worker_queued.run_checksum)
    # A changed worker identity is rejected before report artifacts could be selected.
    forged = worker_running.model_copy(update={"worker_id": "validator-02", "run_checksum": ZERO})
    forged = _sealed(forged, "run_checksum")
    with pytest.raises(RuntimeStateConflictError, match="worker lease/fencing token"):
        repository.save_run(forged, expected_run_checksum=worker_running.run_checksum)


def test_requires_log_and_rejects_corrupt_persisted_checksum_or_bytes(tmp_path) -> None:
    repository, resolver, store, config, config_ref = _world(tmp_path)
    queued = _queue(repository, config, config_ref, run_id="missing-log", attempt=1)
    with pytest.raises(ValidationError, match="execution-log"):
        ValidationRunRecord.model_validate(
            {
                **queued.model_dump(mode="json"),
                "status": "COMPLETED",
                "started_at": (REQUESTED + timedelta(seconds=1)).isoformat(),
                "completed_at": (REQUESTED + timedelta(seconds=2)).isoformat(),
                "worker_id": "validator-01",
                "lease_id": "lease-01",
                "fencing_token": 1,
            }
        )

    corrupted = queued.model_copy(update={"run_checksum": "sha256:" + "f" * 64})
    with pytest.raises(ValidationRunError, match="run_checksum"):
        repository.save_run(corrupted)

    complete = _complete(repository, store, config, config_ref, run_id="corrupt-bytes", attempt=2)
    assert complete.execution_log_ref
    log_path = resolver.resolve(complete.execution_log_ref.artifact_uri)
    log_path.write_bytes(b"tampered execution log")
    with pytest.raises(ArtifactChecksumError, match="checksum mismatch"):
        repository.get_run(complete.run_id)
