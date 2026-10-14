from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import RuntimeComponent, RuntimeManifest
from src.models.contracts.validation_run import (
    IsaacValidationRuntimeProfile,
    ValidationConfig,
    ValidationPathPair,
    ValidationRunStatus,
)
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.review.simulation_package import current_package
from src.services.orchestration.review.validation_queue import (
    ValidationCandidateSnapshot,
    ValidationOperationStatus,
    ValidationQueue,
)

ZERO = "sha256:" + "0" * 64


def _sealed(model, checksum_field: str):
    return model.model_copy(update={checksum_field: canonical_content_checksum(model, checksum_field)})


def _config() -> ValidationConfig:
    return _sealed(
        ValidationConfig(
            schema_version="1.0",
            policy_id="isaac-validation-policy-test-v1",
            required_check_ids=["ISAAC_LOAD", "COLLISION_SCENE_LOAD"],
            warning_check_ids=["PATH_START_GOAL"],
            path_pairs=[
                ValidationPathPair(
                    pair_id="aisle-clearance",
                    start_xyz_m=(0.0, 0.0, 0.1),
                    goal_xyz_m=(2.0, 0.0, 0.1),
                    required=False,
                )
            ],
            config_checksum=ZERO,
        ),
        "config_checksum",
    )


def _profile(resolver: ArtifactResolver) -> IsaacValidationRuntimeProfile:
    store = FilesystemArtifactStore(resolver)
    runtime = _sealed(
        RuntimeManifest(
            schema_version="1.0",
            components={"isaac_sim": RuntimeComponent(status="VERIFIED", version="isaac-test-2026.1")},
            runtime_manifest_checksum=ZERO,
        ),
        "runtime_manifest_checksum",
    )
    runtime_payload = runtime.model_dump_json(indent=2).encode("utf-8")
    runtime_ref = ProductArtifactRef(
        artifact_type="RuntimeManifest",
        schema_version="1.0",
        artifact_uri="artifact://jobs/validation-runtime/runtime_manifest.json",
        artifact_checksum=sha256_bytes(runtime_payload),
        data_class="derived",
        producer_stage="ST-ISAAC-VALIDATE",
        job_id="validation-runtime",
    )
    store.publish(runtime_ref, runtime_payload)

    robot_payload = b"test-only robot USD asset"
    robot_ref = ProductArtifactRef(
        artifact_type="IsaacRobotAsset",
        schema_version="1.0",
        artifact_uri="artifact://jobs/validation-runtime/robot/amr.usd",
        artifact_checksum=sha256_bytes(robot_payload),
        data_class="derived",
        producer_stage="ST-ISAAC-VALIDATE",
        job_id="validation-runtime",
    )
    store.publish(robot_ref, robot_payload)
    return _sealed(
        IsaacValidationRuntimeProfile(
            schema_version="1.0",
            profile_id="test-amr-profile-v1",
            runtime_identity="isaac-test-2026.1",
            runtime_manifest_ref=runtime_ref,
            robot_asset_ref=robot_ref,
            robot_footprint_m=(0.62, 0.44),
            spawn_position_xyz_m=(0.0, 0.0, 0.1),
            spawn_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            physics_timestep_seconds=0.01,
            timeout_seconds=120.0,
            collision_tolerance_m=0.01,
            penetration_limit_m=0.02,
            profile_checksum=ZERO,
        ),
        "profile_checksum",
    )


@pytest.fixture
def world(tmp_path: Path):  # noqa: ANN201
    # Reuse the real persistent Studio job/package fixture so the validation FK and candidate
    # identity bind to the same committed scene state production uses.
    from tests.test_orchestration.test_review_workflow import _packaged

    registry, job, candidate_checksum = _packaged(tmp_path)
    package = current_package(registry, job.job_id)
    assert package is not None and package.candidate is not None
    snapshot = ValidationCandidateSnapshot(
        job_id=job.job_id,
        scene_revision=package.scene_revision,
        scene_ir_checksum=package.scene_ir_checksum,
        candidate_checksum=candidate_checksum,
    )
    database = registry.persistence.database
    queue = ValidationQueue(database, registry.runtime_resolver, lease_ttl=timedelta(seconds=30))
    config = _config()
    profile = _profile(registry.runtime_resolver)
    bound_config = queue.bind_profile(job.job_id, config, profile)
    return registry, job, database, queue, snapshot, config, profile, bound_config


def _submit(world, key: str = "validation-key-1"):  # noqa: ANN001
    _, _, _, queue, snapshot, config, profile, _ = world
    return queue.submit(
        snapshot,
        config,
        profile=profile,
        requester_id="user-editor",
        idempotency_key=key,
    )


def test_submission_binds_exact_candidate_policy_and_profile_and_replays(world) -> None:  # noqa: ANN001
    registry, job, database, queue, snapshot, _, _, bound_config = world
    first = _submit(world)
    restarted_queue = ValidationQueue(database, registry.runtime_resolver)
    replay = restarted_queue.submit(
        snapshot,
        world[5],
        profile=world[6],
        requester_id="user-editor",
        idempotency_key="validation-key-1",
    )
    second = restarted_queue.submit(
        snapshot,
        world[5],
        profile=world[6],
        requester_id="user-editor",
        idempotency_key="validation-key-2",
    )

    assert replay.run_id == first.run_id
    assert second.run_id != first.run_id
    assert second.attempt == first.attempt + 1
    assert first.candidate_checksum == snapshot.candidate_checksum
    assert first.validation_config_checksum == bound_config.config_checksum
    assert first.run_status == ValidationRunStatus.QUEUED
    assert [item.run_id for item in restarted_queue.list_for_job(job.job_id)] == [second.run_id, first.run_id]
    stored = restarted_queue.runs.get_run(first.run_id)
    stored_config = ValidationConfig.model_validate_json(
        registry.runtime_resolver.require(stored.validation_config_ref).read_bytes()
    )
    verify_content_checksum(stored_config, "config_checksum")
    assert stored_config.runtime_profile_ref is not None
    assert stored_config.runtime_profile_ref.artifact_uri.endswith(
        world[6].profile_checksum.removeprefix("sha256:") + "/isaac_validation_profile.json"
    )


def test_two_workers_cannot_claim_one_run_and_expired_claim_is_fenced(world) -> None:  # noqa: ANN001
    registry, _, database, first_queue, _, _, _, _ = world
    _submit(world)
    second_queue = ValidationQueue(database, registry.runtime_resolver)

    first_claim = first_queue.claim_next("worker-a")
    assert first_claim is not None
    assert second_queue.claim_next("worker-b") is None

    assert second_queue.recover_expired(now=first_claim.lease_expires_at + timedelta(seconds=1)) == 1
    reclaimed = second_queue.claim_next("worker-b")
    assert reclaimed is not None
    assert reclaimed.fencing_token == first_claim.fencing_token + 1
    with pytest.raises(RuntimeStateConflictError, match="stale or fenced"):
        first_queue.heartbeat(first_claim)


def test_worker_rechecks_candidate_before_starting_and_stale_run_is_cancelled(world) -> None:  # noqa: ANN001
    _, _, _, queue, _, _, _, _ = world
    accepted = _submit(world)
    claim = queue.claim_next("worker-a")
    assert claim is not None

    stale = queue.start(claim, current_candidate_checksum="sha256:" + "f" * 64)

    assert stale.status == ValidationRunStatus.CANCELLED
    current = queue.get(accepted.job_id, accepted.run_id)
    assert current.status == ValidationOperationStatus.CANCELLED
    assert current.error_code == "STALE_CANDIDATE"


def test_queued_cancel_and_running_cancel_wait_for_worker_acknowledgement(world) -> None:  # noqa: ANN001
    _, _, _, queue, snapshot, config, profile, _ = world
    queued = _submit(world)
    cancelled = queue.cancel(queued.job_id, queued.run_id)
    assert cancelled.status == ValidationRunStatus.CANCELLED
    assert cancelled.status == ValidationOperationStatus.CANCELLED

    running = queue.submit(
        snapshot,
        config,
        profile=profile,
        requester_id="user-editor",
        idempotency_key="validation-key-running",
    )
    claim = queue.claim_next("worker-a")
    assert claim is not None
    assert (
        queue.start(claim, current_candidate_checksum=snapshot.candidate_checksum).status == ValidationRunStatus.RUNNING
    )
    requested = queue.cancel(running.job_id, running.run_id)
    assert requested.run_status == ValidationRunStatus.RUNNING
    assert requested.status == ValidationOperationStatus.CANCEL_REQUESTED
    finished = queue.finish_cancelled(claim)
    assert finished.run_status == ValidationRunStatus.CANCELLED
    assert finished.status == ValidationOperationStatus.CANCELLED


def test_resource_wait_requeues_and_only_retryable_worker_failure_can_retry(world) -> None:  # noqa: ANN001
    _, _, _, queue, snapshot, config, profile, _ = world
    accepted = _submit(world)
    claim = queue.claim_next("worker-a")
    assert claim is not None
    waiting = queue.wait_for_resources(claim)
    assert waiting.status == ValidationOperationStatus.WAITING_RESOURCES

    claim = queue.claim_next("worker-a")
    assert claim is not None
    queue.start(claim, current_candidate_checksum=snapshot.candidate_checksum)
    failed = queue.fail(claim, error_code="WORKER_LEASE_EXPIRED", retryable=True)
    assert failed.run_status == ValidationRunStatus.FAILED
    retry = queue.retry(
        accepted.job_id,
        accepted.run_id,
        requester_id="user-editor",
        idempotency_key="validation-key-retry",
        current_candidate_checksum=snapshot.candidate_checksum,
    )
    assert retry.attempt == accepted.attempt + 1
    assert retry.validation_config_checksum == accepted.validation_config_checksum

    claim = queue.claim_next("worker-a")
    assert claim is not None
    queue.start(claim, current_candidate_checksum=snapshot.candidate_checksum)
    queue.fail(claim, error_code="INVALID_SCENE", retryable=False)
    with pytest.raises(RuntimeStateConflictError, match="transient"):
        queue.retry(
            retry.job_id,
            retry.run_id,
            requester_id="user-editor",
            idempotency_key="validation-key-not-allowed",
            current_candidate_checksum=snapshot.candidate_checksum,
        )
