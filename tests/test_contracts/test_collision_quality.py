"""Collision-source and quality-report identity contract regressions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.collision_quality import (
    CollisionAlignmentQAKind,
    CollisionInputMode,
    CollisionObservationState,
    CollisionPhysicsClaim,
    CollisionQualityReport,
    CollisionQualityResult,
    CollisionSourceMode,
    CollisionSourceSelection,
    CollisionSupportEvidence,
    ObstacleRetentionEvidence,
    seal_collision_quality_report,
    seal_collision_source_selection,
    validate_collision_source_binding,
)
from src.models.contracts.scene import SceneEnvironment

CHECKSUM = "sha256:" + "1" * 64


def _ref(
    name: str,
    checksum_digit: str,
    *,
    data_class: str = "derived",
    artifact_type: str = "CollisionGeometry",
) -> dict[str, str]:
    return {
        "artifact_type": artifact_type,
        "schema_version": "1.0",
        "artifact_uri": f"artifact://jobs/job-001/{name}",
        "artifact_checksum": "sha256:" + checksum_digit * 64,
        "data_class": data_class,
        "producer_stage": "AUD-12.S1-fixture",
    }


def _selection(
    *,
    mode: str = "rgb_cleaned",
    input_mode: str = "rgb_metric_geometry",
    alignment_qa_kind: str | None = None,
    alignment_qa_ref: dict[str, str] | None = None,
) -> CollisionSourceSelection:
    return seal_collision_source_selection(
        schema_version="1.0",
        mode=mode,
        input_mode=input_mode,
        alignment_qa_kind=alignment_qa_kind,
        source_geometry_ref=_ref("geometry/input.ply", "2"),
        source_qa_ref=_ref("quality/source.json", "3", artifact_type="CollisionSourceQA"),
        alignment_qa_ref=alignment_qa_ref,
        profile_checksum=CHECKSUM,
        config_checksum="sha256:" + "4" * 64,
        effective_resolution_m=0.05,
        output_collision_ref=_ref("collision/selected.glb", "5"),
    )


def _report(
    selection: CollisionSourceSelection,
    *,
    state: str = "observed_static",
    claim: str = "unverified",
    retained_obstacles: int = 2,
    reference_kind: str = "independent_surface_scan",
) -> CollisionQualityReport:
    observation_ids = ["scan-001"] if state == "observed_static" else []
    coverage_fraction = 1.0 if state == "observed_static" else 0.0
    retention = ObstacleRetentionEvidence.model_validate(
        {
            "reference_ref": _ref("reference/surface.ply", "6", data_class="ground_truth"),
            "reference_kind": reference_kind,
            "expected_obstacles": 2,
            "retained_obstacles": retained_obstacles,
        }
    )
    support = CollisionSupportEvidence.model_validate(
        {
            "reference_ref": _ref("reference/floor.ply", "a", data_class="ground_truth"),
            "reference_kind": "independent_surface_scan",
            "expected_support_samples": 4,
            "retained_support_samples": 4,
        }
    )
    return seal_collision_quality_report(
        schema_version="1.0",
        source_selection_checksum=selection.selection_checksum,
        source_geometry_ref=selection.source_geometry_ref,
        config_checksum=selection.config_checksum,
        output_collision_ref=selection.output_collision_ref,
        hardware_profile_ref=_ref("runtime/hardware.json", "b", artifact_type="HardwareProfile"),
        robot_profile_ref=_ref("runtime/robot.json", "c", artifact_type="RobotProfile"),
        effective_resolution_m=selection.effective_resolution_m,
        robot_radius_m=0.461,
        robot_height_m=0.308,
        acceptance_profile_ref=_ref("quality/acceptance.json", "d", artifact_type="CollisionAcceptanceProfile")
        if claim == "verified"
        else None,
        quality_result="pass" if claim == "verified" else "not_evaluated",
        free_space_proxy={
            "blocked_positions": 0,
            "tested_positions": 5,
            "trajectory_origin": "ground_truth",
        },
        obstacle_retention=retention,
        support_retention=support,
        regions=[
            {
                "region_id": "aisle-001",
                "state": state,
                "source_ref": selection.source_geometry_ref,
                "observation_ids": observation_ids,
                "coverage_fraction": coverage_fraction,
            }
        ],
        isaac_contact_ref=_ref("validation/contact.json", "7", artifact_type="IsaacValidationReport"),
        physics_claim=claim,
    )


def test_selection_binds_mode_profile_and_exact_collision_output() -> None:
    selection = _selection()
    environment = SceneEnvironment(
        geometry_ref=selection.source_geometry_ref,
        collider_ref=selection.output_collision_ref,
    )
    report = _report(selection)

    validate_collision_source_binding(environment, selection, report)
    assert selection.selection_checksum.startswith("sha256:")


def test_verified_claim_requires_a_frozen_passing_acceptance_profile() -> None:
    selection = _selection()
    report = _report(selection, claim="verified")

    assert report.quality_result == CollisionQualityResult.PASS
    assert report.acceptance_profile_ref is not None
    assert report.physics_claim == CollisionPhysicsClaim.VERIFIED


def test_lidar_selection_requires_its_alignment_qa_reference() -> None:
    with pytest.raises(ValidationError, match="requires alignment QA bound to its input mode"):
        _selection(mode="lidar_derived", input_mode="lidar_registered_map")

    selection = _selection(
        mode="lidar_derived",
        input_mode="lidar_registered_map",
        alignment_qa_kind="registered_map_registration",
        alignment_qa_ref=_ref("alignment/qa.json", "8", artifact_type="LidarAlignmentQA"),
    )
    assert selection.input_mode == CollisionInputMode.LIDAR_REGISTERED_MAP
    assert selection.mode == CollisionSourceMode.LIDAR_DERIVED
    assert selection.alignment_qa_kind == CollisionAlignmentQAKind.REGISTERED_MAP_REGISTRATION


def test_lidar_selection_rejects_qa_from_the_other_input_mode() -> None:
    with pytest.raises(ValidationError, match="bound to its input mode"):
        _selection(
            mode="lidar_derived",
            input_mode="lidar_registered_map",
            alignment_qa_kind="sensor_calibration_timing",
            alignment_qa_ref=_ref("alignment/qa.json", "8", artifact_type="LidarAlignmentQA"),
        )


def test_free_space_proxy_does_not_substitute_for_independent_obstacle_recall() -> None:
    selection = _selection()
    payload = _report(selection).model_dump(mode="python")
    payload["obstacle_retention"] = None
    payload.pop("report_checksum")
    report = seal_collision_quality_report(**payload)

    assert report.free_space_proxy is not None
    assert report.obstacle_retention is None
    assert report.physics_claim == CollisionPhysicsClaim.UNVERIFIED


def test_empty_world_free_path_cannot_be_upgraded_to_verified_physics() -> None:
    selection = _selection()
    payload = _report(selection, claim="verified").model_dump(mode="python")
    payload["obstacle_retention"] = None
    payload.pop("report_checksum")

    with pytest.raises(ValidationError, match="retained obstacles"):
        seal_collision_quality_report(**payload)


@pytest.mark.parametrize(
    "state",
    [
        CollisionObservationState.UNOBSERVED,
        CollisionObservationState.INFERRED,
        CollisionObservationState.MOTION_SUSPECTED,
    ],
)
def test_unsupported_or_motion_suspected_regions_cannot_claim_verified_physics(
    state: CollisionObservationState,
) -> None:
    selection = _selection()
    with pytest.raises(ValidationError, match="fully observed static coverage"):
        _report(selection, state=state.value, claim="verified")


def test_empty_collision_output_cannot_claim_verified_physics() -> None:
    selection = _selection()
    with pytest.raises(ValidationError, match="retained obstacles"):
        _report(selection, claim="verified", retained_obstacles=0)


def test_missing_floor_support_evidence_cannot_claim_verified_physics() -> None:
    selection = _selection()
    payload = _report(selection, claim="verified").model_dump(mode="python")
    payload["support_retention"] = None
    payload.pop("report_checksum")

    with pytest.raises(ValidationError, match="floor/support retention"):
        seal_collision_quality_report(**payload)


def test_synthetic_fixture_is_not_independent_physics_evidence() -> None:
    selection = _selection()
    with pytest.raises(ValidationError, match="same-input or synthetic"):
        _report(selection, claim="verified", reference_kind="synthetic_fixture")


def test_scene_environment_cannot_consume_a_different_collision_checksum() -> None:
    selection = _selection()
    other_collision = _ref("collision/other.glb", "9")
    environment = SceneEnvironment(geometry_ref=selection.source_geometry_ref, collider_ref=other_collision)

    with pytest.raises(ValueError, match="collider_ref differs"):
        validate_collision_source_binding(environment, selection, _report(selection))


def test_scene_environment_binds_selected_source_even_after_effective_collider_is_carved() -> None:
    selection = _selection()
    selection_ref = ProductArtifactRef.model_validate(
        _ref("collision/selection.json", "a", artifact_type="CollisionSourceSelection")
    )
    carved_collision = _ref("collision/carved.glb", "b")
    environment = SceneEnvironment(
        geometry_ref=selection.source_geometry_ref,
        collider_ref=carved_collision,
        collision_source_ref=selection.output_collision_ref,
        collision_selection_ref=selection_ref,
    )

    validate_collision_source_binding(environment, selection, _report(selection), selection_ref=selection_ref)


def test_scene_environment_rejects_missing_or_stale_selection_binding() -> None:
    selection = _selection()
    report = _report(selection)
    selection_ref = ProductArtifactRef.model_validate(
        _ref("collision/selection.json", "a", artifact_type="CollisionSourceSelection")
    )
    environment = SceneEnvironment(
        geometry_ref=selection.source_geometry_ref,
        collider_ref=selection.output_collision_ref,
        collision_source_ref=selection.output_collision_ref,
        collision_selection_ref=selection_ref,
    )

    with pytest.raises(ValueError, match="collision_selection_ref"):
        validate_collision_source_binding(environment, selection, report)
    with pytest.raises(ValueError, match="collision_selection_ref"):
        validate_collision_source_binding(
            environment,
            selection,
            report,
            selection_ref=ProductArtifactRef.model_validate(
                _ref("collision/other-selection.json", "c", artifact_type="CollisionSourceSelection")
            ),
        )


def test_scene_environment_requires_source_and_selection_refs_together() -> None:
    selection = _selection()

    with pytest.raises(ValidationError, match="must be set together"):
        SceneEnvironment(
            geometry_ref=selection.source_geometry_ref,
            collider_ref=selection.output_collision_ref,
            collision_source_ref=selection.output_collision_ref,
        )


def test_scene_environment_rejects_collision_selection_from_another_job() -> None:
    selection = _selection()
    other_job_selection_ref = {
        **_ref("collision/selection.json", "a", artifact_type="CollisionSourceSelection"),
        "artifact_uri": "artifact://jobs/job-foreign/collision/selection.json",
    }

    with pytest.raises(ValidationError, match="belong to the SceneIR job"):
        SceneEnvironment(
            geometry_ref=selection.source_geometry_ref,
            collider_ref=selection.output_collision_ref,
            collision_source_ref=selection.output_collision_ref,
            collision_selection_ref=other_job_selection_ref,
        )


def test_report_with_stale_source_checksum_is_rejected_by_consumer() -> None:
    selection = _selection()
    payload = _report(selection).model_dump(mode="python")
    payload["source_geometry_ref"] = _ref("geometry/stale.ply", "a")
    payload.pop("report_checksum")
    report = seal_collision_quality_report(**payload)
    environment = SceneEnvironment(
        geometry_ref=selection.source_geometry_ref,
        collider_ref=selection.output_collision_ref,
    )

    with pytest.raises(ValueError, match="source checksum differs"):
        validate_collision_source_binding(environment, selection, report)
