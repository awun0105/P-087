"""Host-side protocol tests; fake executables here are not Isaac evidence."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Event, Timer
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.isaac.validate_candidate import (
    _path_execution_observation,
    _path_points,
    _record_check,
    _required_route_observation,
    _result,
)
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import RuntimeComponent, RuntimeManifest
from src.models.contracts.validation import ObservedPathResult, RuleResult
from src.models.contracts.validation_run import (
    IsaacValidationRuntimeProfile,
    ValidationConfig,
    ValidationPathPair,
    ValidationRunOrigin,
    ValidationRunRecord,
    ValidationRunStatus,
)
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.review.simulation_package import build_simulation_package
from src.services.orchestration.scene.objects import apply_object_action
from src.services.process_control import ProcessCancelledError
from src.services.simulation.isaac.process import (
    IsaacValidationProcess,
    IsaacValidationProcessError,
    IsaacValidationRequest,
)
from tests.test_orchestration.test_simulation_package import _scene_job

ZERO = "sha256:" + "0" * 64


def test_path_sampling_covers_both_endpoints_without_gaps_larger_than_limit() -> None:
    points = _path_points([0.0, 0.0, 0.1], [1.0, 0.0, 0.1], 0.25)

    assert points[0] == (0.0, 0.0, 0.1)
    assert points[-1] == (1.0, 0.0, 0.1)
    assert all(points[index + 1][0] - points[index][0] <= 0.25 for index in range(len(points) - 1))


def test_runner_marks_unimplemented_policy_checks_as_error() -> None:
    request = {
        "run_id": "run-1",
        "candidate_checksum": ZERO,
        "config_checksum": ZERO,
        "profile_checksum": ZERO,
        "runtime_identity": "isaac-5.1.0",
        "required_check_ids": ["UNKNOWN_PROVIDER_CHECK"],
        "warning_check_ids": [],
    }

    result = _result(request, "5.1.0", {}, [], None)

    assert result["checks"] == [
        {
            "check_id": "UNKNOWN_PROVIDER_CHECK",
            "result": "ERROR",
            "message": "Isaac runner does not implement this configured check ID",
        }
    ]


@pytest.mark.parametrize(
    ("check_id", "semantic_id", "observation"),
    [
        ("ISAAC_LOAD_ERROR", "scene_load", ("PASS", "observed")),
        ("ROBOT_SPAWN_INVALID", "robot_spawn", ("PASS", "observed")),
        ("PATH_VALIDATION_ERROR", "path_start_goal", ("PASS", "observed")),
        (
            "PENETRATION_DEPTH",
            "penetration",
            (
                "ERROR",
                "PhysX overlap queries expose collider intersections but not penetration depth; no depth was inferred",
            ),
        ),
        ("REQUIRED_ROUTE_BLOCKED", "required_route_blocked", ("PASS", "observed")),
    ],
)
def test_runner_emits_contract_check_ids_from_observations(
    check_id: str, semantic_id: str, observation: tuple[str, str]
) -> None:
    request = {
        "run_id": "run-1",
        "candidate_checksum": ZERO,
        "config_checksum": ZERO,
        "profile_checksum": ZERO,
        "runtime_identity": "isaac-5.1.0",
        "required_check_ids": [check_id],
        "warning_check_ids": [],
    }
    checks: dict[str, tuple[str, str]] = {}
    _record_check(checks, semantic_id, observation)

    result = _result(request, "5.1.0", checks, [], None)

    assert result["checks"] == [{"check_id": check_id, "result": observation[0], "message": observation[1]}]


def test_required_route_observation_uses_only_required_pairs() -> None:
    pairs = [
        {"pair_id": "required", "required": True},
        {"pair_id": "optional", "required": False},
    ]

    result = _required_route_observation(
        pairs,
        [
            {"pair_id": "required", "result": "CLEAR"},
            {"pair_id": "optional", "result": "BLOCKED"},
        ],
    )

    assert result == ("PASS", "All configured required routes were observed clear")


@pytest.mark.parametrize(
    ("path_results", "expected"),
    [
        ([{"pair_id": "required", "result": "BLOCKED"}], "FAIL"),
        ([{"pair_id": "required", "result": "ERROR"}], "ERROR"),
        ([], "ERROR"),
    ],
)
def test_required_route_observation_fails_closed(path_results: list[dict[str, str]], expected: str) -> None:
    result, _message = _required_route_observation([{"pair_id": "required", "required": True}], path_results)

    assert result == expected


@pytest.mark.parametrize(
    ("path_pairs", "path_errors", "check_requested", "expected"),
    [
        ([], 0, True, "ERROR"),
        ([{"pair_id": "clear", "required": True}], 0, True, "PASS"),
        ([{"pair_id": "error", "required": True}], 1, True, "ERROR"),
        ([], 0, False, "PASS"),
    ],
)
def test_path_execution_observation_rejects_configured_empty_route_set(
    path_pairs: list[dict[str, object]], path_errors: int, check_requested: bool, expected: str
) -> None:
    result, _message = _path_execution_observation(path_pairs, path_errors, check_requested)

    assert result == expected


def _seal(model, field: str):
    return model.model_copy(update={field: canonical_content_checksum(model, field)})


def _publish_model(store: FilesystemArtifactStore, reference: ProductArtifactRef, model: object) -> None:
    payload = model.model_dump_json(indent=2).encode("utf-8")
    store.publish(reference, payload)


def _ref(job_id: str, artifact_type: str, relative_path: str, payload: bytes) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/{relative_path}",
        artifact_checksum=sha256_bytes(payload),
        data_class="derived",
        producer_stage="ST-ISAAC-VALIDATE",
        job_id=job_id,
    )


def _validation_request(
    tmp_path: Path, *, timeout_seconds: float = 10.0
) -> tuple[IsaacValidationRequest, ArtifactResolver]:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    (candidate_object,) = scene.objects
    apply_object_action(registry.scene, job.job_id, candidate_object.id, "confirm", scene.scene_revision)
    package = build_simulation_package(registry, job.job_id)
    candidate = package.candidate
    assert candidate is not None
    assert package.package_ref is not None

    resolver = registry.runtime_resolver
    store = FilesystemArtifactStore(resolver)
    runtime = _seal(
        RuntimeManifest(
            schema_version="1.0",
            components={"isaac_sim": RuntimeComponent(status="VERIFIED", version="isaac-test-2026.1")},
            runtime_manifest_checksum=ZERO,
        ),
        "runtime_manifest_checksum",
    )
    runtime_payload = runtime.model_dump_json(indent=2).encode("utf-8")
    runtime_ref = _ref(job.job_id, "RuntimeManifest", "validation/runtime_manifest.json", runtime_payload)
    store.publish(runtime_ref, runtime_payload)

    robot_payload = b"test-only robot USD bytes; fake child does not load them"
    robot_ref = _ref(job.job_id, "IsaacRobotAsset", "validation/robot.usd", robot_payload)
    store.publish(robot_ref, robot_payload)

    profile_draft = IsaacValidationRuntimeProfile(
        schema_version="1.0",
        profile_id="test-amr-profile-v1",
        runtime_identity="isaac-test-2026.1",
        runtime_manifest_ref=runtime_ref,
        robot_asset_ref=robot_ref,
        robot_footprint_m=(0.62, 0.44),
        spawn_position_xyz_m=(0.0, 0.0, 0.1),
        spawn_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
        physics_timestep_seconds=0.01,
        timeout_seconds=timeout_seconds,
        collision_tolerance_m=0.01,
        penetration_limit_m=0.02,
        profile_checksum=ZERO,
    )
    profile = _seal(profile_draft, "profile_checksum")
    profile_payload = profile.model_dump_json(indent=2).encode("utf-8")
    profile_ref = _ref(job.job_id, "IsaacValidationRuntimeProfile", "validation/profile.json", profile_payload)
    store.publish(profile_ref, profile_payload)

    config_draft = ValidationConfig(
        schema_version="1.0",
        policy_id="test-isaac-policy-v1",
        required_check_ids=["ISAAC_LOAD"],
        warning_check_ids=[],
        path_pairs=[
            ValidationPathPair(
                pair_id="aisle-clearance",
                start_xyz_m=(0.0, 0.0, 0.1),
                goal_xyz_m=(1.0, 0.0, 0.1),
                required=True,
            )
        ],
        runtime_profile_ref=profile_ref,
        config_checksum=ZERO,
    )
    config = _seal(config_draft, "config_checksum")
    config_payload = config.model_dump_json(indent=2).encode("utf-8")
    config_ref = _ref(job.job_id, "ValidationConfig", "validation/config.json", config_payload)
    store.publish(config_ref, config_payload)

    now = datetime.now(UTC)
    run = _seal(
        ValidationRunRecord(
            schema_version="1.0",
            run_id="isaac-process-test-run",
            attempt=1,
            job_id=job.job_id,
            scene_revision=package.scene_revision,
            scene_ir_checksum=package.scene_ir_checksum,
            candidate_checksum=candidate.candidate_checksum,
            validation_config_checksum=config.config_checksum,
            validation_config_ref=config_ref,
            origin=ValidationRunOrigin.WORKER,
            status=ValidationRunStatus.RUNNING,
            requested_at=now - timedelta(seconds=1),
            started_at=now,
            worker_id="isaac-process-test-worker",
            lease_id="isaac-process-test-lease",
            fencing_token=1,
            run_checksum=ZERO,
        ),
        "run_checksum",
    )
    request = IsaacValidationRequest(
        run=run,
        candidate=candidate,
        candidate_package_ref=package.package_ref,
        config=config,
        profile=profile,
    )
    return request, resolver


def _fake_runner(path: Path, *, result_mode: str = "ok", sleep_seconds: float = 0.0) -> Path:
    source = "\n".join(
        [
            "import argparse, json, time",
            "parser = argparse.ArgumentParser()",
            "parser.add_argument('--request', required=True)",
            "parser.add_argument('--output', required=True)",
            "args = parser.parse_args()",
            f"time.sleep({sleep_seconds!r})",
            "request = json.load(open(args.request, encoding='utf-8'))",
            f"mode = {result_mode!r}",
            "checks = [{'check_id': check_id, 'result': 'PASS', 'message': None} for check_id in request['required_check_ids'] + request['warning_check_ids']]",
            "paths = [{'pair_id': pair['pair_id'], 'result': 'CLEAR', 'sample_count': 2, 'collision_prim_paths': []} for pair in request['path_pairs']]",
            "result = {'schema_version': '1.0', 'run_id': request['run_id'], 'candidate_checksum': request['candidate_checksum'], 'config_checksum': request['config_checksum'], 'profile_checksum': request['profile_checksum'], 'runtime_identity': request['runtime_identity'], 'runtime_versions': {'isaac_sim': request['runtime_identity']}, 'checks': checks, 'path_results': paths, 'max_penetration_m': None}",
            "if mode == 'wrong_run': result['run_id'] = 'another-run'",
            "with open(args.output, 'x', encoding='utf-8') as stream: json.dump(result, stream)",
        ]
    )
    path.write_text(source + "\n", encoding="utf-8")
    return path


def test_host_process_accepts_exact_fake_child_protocol_but_not_as_isaac_evidence(tmp_path: Path) -> None:
    request, resolver = _validation_request(tmp_path)
    child = _fake_runner(tmp_path / "fake-child.py")
    process = IsaacValidationProcess([sys.executable], runner_script=child)

    result = process.run(request, resolver, tmp_path / "attempt")

    assert result.run_id == request.run.run_id
    assert result.runtime_versions["isaac_sim"] == request.profile.runtime_identity
    assert result.checks[0].result == RuleResult.PASS
    assert result.path_results[0].result == ObservedPathResult.CLEAR
    assert result.max_penetration_m is None


def test_host_process_rejects_child_result_bound_to_another_run(tmp_path: Path) -> None:
    request, resolver = _validation_request(tmp_path)
    child = _fake_runner(tmp_path / "fake-child.py", result_mode="wrong_run")
    process = IsaacValidationProcess([sys.executable], runner_script=child)

    with pytest.raises(IsaacValidationProcessError) as error:
        process.run(request, resolver, tmp_path / "attempt")

    assert error.value.error_code == "ISAAC_RESULT_IDENTITY_MISMATCH"


@pytest.mark.parametrize("member_name", ["scene.usda", "environment_collision.usda"])
def test_host_process_rejects_package_dependency_bytes_that_do_not_match_inventory(
    tmp_path: Path, member_name: str
) -> None:
    request, resolver = _validation_request(tmp_path)
    archive_path = resolver.require(request.candidate_package_ref)
    rebuilt = BytesIO()
    with ZipFile(archive_path) as source, ZipFile(rebuilt, "w", compression=ZIP_DEFLATED) as target:
        for entry in source.infolist():
            contents = source.read(entry.filename)
            if entry.filename == member_name:
                contents = b"#usda 1.0\n# substituted after candidate inventory was sealed\n"
            target.writestr(entry, contents)
    forged_bytes = rebuilt.getvalue()
    forged_ref = _ref(
        request.run.job_id,
        "SimulationPackageArchive",
        "validation/forged-package.zip",
        forged_bytes,
    )
    FilesystemArtifactStore(resolver).publish(forged_ref, forged_bytes)
    forged_request = request.model_copy(update={"candidate_package_ref": forged_ref})
    child = _fake_runner(tmp_path / "fake-child.py")
    process = IsaacValidationProcess([sys.executable], runner_script=child)

    with pytest.raises(IsaacValidationProcessError) as error:
        process.run(forged_request, resolver, tmp_path / "attempt")

    assert error.value.error_code == "ISAAC_CANDIDATE_PACKAGE_INVALID"
    assert not (tmp_path / "attempt" / "isaac_request.json").exists()


def test_host_process_rejects_archive_path_traversal_before_launch(tmp_path: Path) -> None:
    request, resolver = _validation_request(tmp_path)
    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
        package.writestr("../escaped.txt", b"outside the package root")
    unsafe_bytes = archive.getvalue()
    unsafe_ref = _ref(
        request.run.job_id,
        "SimulationPackageArchive",
        "validation/unsafe-package.zip",
        unsafe_bytes,
    )
    FilesystemArtifactStore(resolver).publish(unsafe_ref, unsafe_bytes)
    unsafe_request = request.model_copy(update={"candidate_package_ref": unsafe_ref})
    child = _fake_runner(tmp_path / "fake-child.py")
    process = IsaacValidationProcess([sys.executable], runner_script=child)

    with pytest.raises(IsaacValidationProcessError) as error:
        process.run(unsafe_request, resolver, tmp_path / "attempt")

    assert error.value.error_code == "ISAAC_CANDIDATE_PACKAGE_INVALID"
    assert not (tmp_path / "attempt" / "escaped.txt").exists()
    assert not (tmp_path / "escaped.txt").exists()


def test_host_process_timeout_is_retryable(tmp_path: Path) -> None:
    request, resolver = _validation_request(tmp_path, timeout_seconds=0.1)
    child = _fake_runner(tmp_path / "fake-child.py", sleep_seconds=5.0)
    process = IsaacValidationProcess([sys.executable], runner_script=child)

    with pytest.raises(IsaacValidationProcessError) as error:
        process.run(request, resolver, tmp_path / "attempt")

    assert error.value.error_code == "ISAAC_RUNTIME_TIMEOUT"
    assert error.value.retryable


def test_host_process_cancel_kills_the_fake_child_and_propagates_cancellation(tmp_path: Path) -> None:
    request, resolver = _validation_request(tmp_path)
    child = _fake_runner(tmp_path / "fake-child.py", sleep_seconds=5.0)
    process = IsaacValidationProcess([sys.executable], runner_script=child)
    cancel_event = Event()
    timer = Timer(0.2, cancel_event.set)
    timer.start()
    try:
        with pytest.raises(ProcessCancelledError):
            process.run(request, resolver, tmp_path / "attempt", cancel_event=cancel_event)
    finally:
        timer.cancel()
