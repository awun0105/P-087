from __future__ import annotations

import hashlib
import math
from dataclasses import replace

import numpy as np
import pytest

from src.models.contracts.coordinates import Transform
from src.models.contracts.rgb_lidar_registration import (
    RegistrationFindingCode,
    RegistrationProfile,
    RegistrationProposalState,
    RegistrationQAStatus,
    seal_registration_profile,
)
from src.services.reconstruction.alignment.bev_search import (
    CoarseRegistrationCandidate,
    CoarseRegistrationSearchResult,
    RegistrationFloorPlane,
    RegistrationSearchDiagnostics,
)
from src.services.reconstruction.alignment.constrained_icp import ConstrainedICPResult, refine_registration_candidates
from src.services.reconstruction.alignment.similarity import _quaternion, rotation_matrix

_ZERO_CHECKSUM = "sha256:" + "0" * 64


def _checksum(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _profile(**overrides: object) -> RegistrationProfile:
    return seal_registration_profile(
        {
            "profile_id": "constrained-icp-test-v1",
            "profile_checksum": _ZERO_CHECKSUM,
            "minimum_source_coverage_ratio": 0.25,
            "minimum_target_coverage_ratio": 0.25,
            "minimum_overlap_ratio": 0.1,
            "minimum_candidate_margin": 0.01,
            "maximum_bidirectional_p95_residual_m": 0.2,
            "icp_voxel_sizes_m": (0.8, 0.4, 0.2),
            "icp_min_correspondences": 24,
            "icp_max_correspondence_distance_m": 1.0,
            "icp_trim_fraction": 0.8,
            "icp_iterations": 40,
            "max_refinement_points": 10_000,
            **overrides,
        }
    )


def _floor(frame: str) -> RegistrationFloorPlane:
    return RegistrationFloorPlane(
        frame=frame,
        normal_xyz=(0.0, 0.0, 1.0),
        offset_m=0.0,
        up_direction_xyz=(0.0, 0.0, 1.0),
        evidence_checksum=_checksum(frame + "-floor"),
    )


def _candidate(
    *,
    candidate_id: str = "coarse-0001",
    yaw: float = 0.07,
    translation: tuple[float, float, float] = (0.45, -0.25, 0.0),
    scale: float | None = None,
) -> CoarseRegistrationCandidate:
    rotation = np.array([[math.cos(yaw), -math.sin(yaw), 0.0], [math.sin(yaw), math.cos(yaw), 0.0], [0.0, 0.0, 1.0]])
    return CoarseRegistrationCandidate(
        candidate_id=candidate_id,
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame="lidar-map",
            translation_xyz=translation,
            rotation_quaternion_xyzw=_quaternion(rotation),
        ),
        score=0.8,
        source_coverage_ratio=0.8,
        target_coverage_ratio=0.8,
        overlap_ratio=0.7,
        yaw_radians=yaw,
        translation_xy_m=translation[:2],
        rgb_scale_factor=scale,
    )


def _coarse_result(
    profile: RegistrationProfile,
    candidates: tuple[CoarseRegistrationCandidate, ...],
    state: RegistrationProposalState = RegistrationProposalState.PROPOSED,
    findings: tuple[RegistrationFindingCode, ...] = (),
) -> CoarseRegistrationSearchResult:
    diagnostics = RegistrationSearchDiagnostics(
        profile_checksum=profile.profile_checksum,
        source_floor_evidence_checksum=_floor("lidar-map").evidence_checksum,
        target_floor_evidence_checksum=_floor("world").evidence_checksum,
        source_point_count=0,
        target_point_count=0,
        source_sample_count=0,
        target_sample_count=0,
        source_structural_cells=0,
        target_structural_cells=0,
        source_cells_by_height=(0, 0, 0, 0, 0, 0),
        target_cells_by_height=(0, 0, 0, 0, 0, 0),
        bev_resolution_m=0.25,
        fine_resolution_m=0.125,
        search_seed=profile.search_seed,
        yaw_hypotheses_evaluated=0,
        scale_hypotheses_evaluated=1,
        translation_hypotheses_evaluated=0,
        fine_hypotheses_evaluated=0,
        candidate_margin=None,
        elapsed_seconds=0.0,
        budget_exhausted=False,
        source_cropped_points=0,
        target_cropped_points=0,
    )
    return CoarseRegistrationSearchResult(state, candidates, findings, diagnostics)


def _room_surface() -> tuple[np.ndarray, np.ndarray]:
    points: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    ys = np.arange(-3.0, 3.01, 0.4)
    xs = np.arange(-4.0, 4.01, 0.4)
    zs = np.arange(0.4, 4.01, 0.4)
    for x, normal in ((-4.0, (-1.0, 0.0, 0.0)), (4.0, (1.0, 0.0, 0.0))):
        for y in ys:
            for z in zs:
                points.append((x, float(y), float(z)))
                normals.append(normal)
    for y, normal in ((-3.0, (0.0, -1.0, 0.0)), (3.0, (0.0, 1.0, 0.0))):
        for x in xs:
            for z in zs:
                points.append((float(x), y, float(z)))
                normals.append(normal)
    return np.asarray(points), np.asarray(normals)


def _source_from_world(world: np.ndarray, yaw: float, translation: tuple[float, float, float]) -> np.ndarray:
    rotation = np.array([[math.cos(yaw), -math.sin(yaw), 0.0], [math.sin(yaw), math.cos(yaw), 0.0], [0.0, 0.0, 1.0]])
    return (world - np.asarray(translation)) @ rotation


def _refine(
    profile: RegistrationProfile,
    source: np.ndarray,
    target: np.ndarray,
    normals: np.ndarray,
    candidates: tuple[CoarseRegistrationCandidate, ...] | None = None,
    state: RegistrationProposalState = RegistrationProposalState.PROPOSED,
) -> ConstrainedICPResult:
    return refine_registration_candidates(
        _coarse_result(profile, candidates or (_candidate(),), state),
        source,
        target,
        normals,
        source_frame="lidar-map",
        target_floor=_floor("world"),
        profile=profile,
    )


def test_constrained_icp_refines_yaw_and_xy_and_reports_regional_metrics() -> None:
    target, normals = _room_surface()
    true_yaw, true_translation = 0.12, (0.3, -0.1, 0.0)
    source = _source_from_world(target, true_yaw, true_translation)
    result = _refine(_profile(), source, target, normals)

    assert result.state == RegistrationProposalState.PROPOSED
    assert result.qa_status == RegistrationQAStatus.INCONCLUSIVE
    assert RegistrationFindingCode.UNQUALIFIED_PROFILE in result.findings
    assert len(result.candidates) == 1
    refined = result.candidates[0]
    rotation = rotation_matrix(refined.candidate.transform_target_from_source.rotation_quaternion_xyzw)
    estimated_yaw = math.atan2(rotation[1, 0], rotation[0, 0])
    assert abs(estimated_yaw - true_yaw) < 0.025
    np.testing.assert_allclose(
        refined.candidate.transform_target_from_source.translation_xyz[:2], true_translation[:2], atol=0.08
    )
    assert refined.observable_dof == 3
    assert refined.regions
    assert all(region.p95_residual_m is None or region.p95_residual_m >= 0 for region in refined.regions)
    assert refined.candidate.transform_target_from_source.translation_xyz[2] == pytest.approx(0.0)


def test_tilted_target_floor_keeps_pitch_roll_and_floor_height_fixed() -> None:
    target_floor_points, target_normals_floor = _room_surface()
    tilt = math.radians(7.0)
    target_floor = RegistrationFloorPlane(
        frame="world",
        normal_xyz=(0.0, math.sin(tilt), math.cos(tilt)),
        offset_m=0.0,
        up_direction_xyz=(0.0, 0.0, 1.0),
        evidence_checksum=_checksum("tilted-world-floor"),
    )
    floor_from_world = target_floor.frame_to_floor_matrix()
    world_from_floor_rotation = floor_from_world[:3, :3].T
    target_world = target_floor_points @ world_from_floor_rotation.T
    normals_world = target_normals_floor @ world_from_floor_rotation.T
    source = _source_from_world(target_floor_points, 0.12, (0.3, -0.1, 0.0))

    base_candidate = _candidate()
    base_world_from_source = np.eye(4)
    base_world_from_source[:3, :3] = rotation_matrix(
        base_candidate.transform_target_from_source.rotation_quaternion_xyzw
    )
    base_world_from_source[:3, 3] = base_candidate.transform_target_from_source.translation_xyz
    world_from_source = np.linalg.inv(floor_from_world) @ base_world_from_source
    tilted_candidate = replace(
        base_candidate,
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame="lidar-map",
            translation_xyz=tuple(float(value) for value in world_from_source[:3, 3]),
            rotation_quaternion_xyzw=_quaternion(world_from_source[:3, :3]),
        ),
    )
    profile = _profile()
    result = refine_registration_candidates(
        _coarse_result(profile, (tilted_candidate,)),
        source,
        target_world,
        normals_world,
        source_frame="lidar-map",
        target_floor=target_floor,
        profile=profile,
    )

    assert result.candidates
    refined_world_from_source = result.candidates[0].candidate.transform_target_from_source
    floor_from_refined_source = floor_from_world @ np.block(
        [
            [
                rotation_matrix(refined_world_from_source.rotation_quaternion_xyzw),
                np.asarray(refined_world_from_source.translation_xyz)[:, None],
            ],
            [np.array([[0.0, 0.0, 0.0, 1.0]])],
        ]
    )
    floor_rotation = floor_from_refined_source[:3, :3]
    refined_yaw = math.atan2(floor_rotation[1, 0], floor_rotation[0, 0])
    assert abs(refined_yaw - 0.12) < 0.025
    assert floor_rotation[2, 0] == pytest.approx(0.0, abs=1e-6)
    assert floor_rotation[2, 1] == pytest.approx(0.0, abs=1e-6)
    assert floor_from_refined_source[2, 3] == pytest.approx(0.0, abs=1e-6)


def test_parallel_floor_normals_are_unobservable() -> None:
    profile = _profile()
    floor_points = np.asarray([(x, y, 0.0) for x in range(-5, 6) for y in range(-5, 6)], dtype=float)
    floor_normals = np.repeat([[0.0, 0.0, 1.0]], len(floor_points), axis=0)
    result = _refine(profile, floor_points, floor_points, floor_normals)

    assert result.state == RegistrationProposalState.INSUFFICIENT
    assert result.qa_status == RegistrationQAStatus.INCONCLUSIVE
    assert not result.candidates
    assert ("coarse-0001", RegistrationFindingCode.UNOBSERVABLE) in result.diagnostics.candidate_findings


def test_repeated_coarse_hypotheses_remain_ambiguous_after_icp() -> None:
    target, normals = _room_surface()
    source = _source_from_world(target, 0.12, (0.3, -0.1, 0.0))
    first, second = _candidate(candidate_id="coarse-0001"), _candidate(candidate_id="coarse-0002")
    result = _refine(_profile(minimum_candidate_margin=0.05), source, target, normals, (first, second))

    assert result.state == RegistrationProposalState.AMBIGUOUS
    assert result.qa_status == RegistrationQAStatus.INCONCLUSIVE
    assert RegistrationFindingCode.AMBIGUOUS_CANDIDATES in result.findings
    assert len(result.candidates) == 2


def test_truncated_ambiguous_input_cannot_become_a_unique_proposal() -> None:
    target, normals = _room_surface()
    source = _source_from_world(target, 0.12, (0.3, -0.1, 0.0))
    result = _refine(
        _profile(top_k_candidates=1),
        source,
        target,
        normals,
        (_candidate(),),
        state=RegistrationProposalState.AMBIGUOUS,
    )

    assert result.state == RegistrationProposalState.AMBIGUOUS
    assert result.qa_status == RegistrationQAStatus.INCONCLUSIVE
    assert RegistrationFindingCode.AMBIGUOUS_CANDIDATES in result.findings


def test_bounded_rgb_scale_is_applied_about_the_floor_without_auto_qa_pass() -> None:
    metric_target, normals = _room_surface()
    unscaled_rgb = metric_target / 1.1
    profile = _profile(scale_policy="bounded_rgb_scale_search", rgb_scale_factor_bounds=(0.8, 1.2))
    candidate = _candidate(yaw=0.0, translation=(0.0, 0.0, 0.0), scale=1.1)
    source = metric_target.copy()
    result = _refine(profile, source, unscaled_rgb, normals, (candidate,))

    assert result.candidates
    assert result.candidates[0].candidate.rgb_scale_factor == pytest.approx(1.1)
    assert result.candidates[0].bidirectional_p95_residual_m < 0.05
    assert result.qa_status == RegistrationQAStatus.INCONCLUSIVE


def test_density_changes_do_not_weight_one_target_region_by_duplicate_points() -> None:
    target, normals = _room_surface()
    source = _source_from_world(target, 0.12, (0.3, -0.1, 0.0))
    duplicated_target = np.repeat(target, 4, axis=0)
    duplicated_normals = np.repeat(normals, 4, axis=0)
    result = _refine(_profile(), source, duplicated_target, duplicated_normals)

    assert result.candidates
    assert result.candidates[0].source_coverage_ratio >= 0.5
    assert result.candidates[0].target_coverage_ratio >= 0.5


def test_wrong_scale_is_rejected_by_residual_qa() -> None:
    metric_target, normals = _room_surface()
    unscaled_rgb = metric_target / 1.3
    profile = _profile(scale_policy="bounded_rgb_scale_search", rgb_scale_factor_bounds=(0.8, 1.4))
    candidate = _candidate(yaw=0.0, translation=(0.0, 0.0, 0.0), scale=1.1)
    result = _refine(profile, metric_target, unscaled_rgb, normals, (candidate,))

    assert result.state == RegistrationProposalState.INSUFFICIENT
    assert result.qa_status == RegistrationQAStatus.FAIL
    assert RegistrationFindingCode.HIGH_RESIDUAL in result.findings


def test_unmatched_ghost_points_are_included_in_residual_and_rejection_evidence() -> None:
    target, normals = _room_surface()
    source = _source_from_world(target, 0.12, (0.3, -0.1, 0.0))
    ghost_count = max(30, len(source) // 8)
    ghosts = np.column_stack(
        (np.linspace(20.0, 25.0, ghost_count), np.linspace(-20.0, -25.0, ghost_count), np.full(ghost_count, 2.0))
    )
    result = _refine(_profile(), np.concatenate((source, ghosts)), target, normals)

    assert result.qa_status == RegistrationQAStatus.FAIL
    assert RegistrationFindingCode.HIGH_RESIDUAL in result.findings
    assert result.candidates[0].rejected_correspondence_count >= len(ghosts)
    assert result.candidates[0].bidirectional_p95_residual_m > 0.2


def test_invalid_normals_and_wrong_candidate_frame_are_rejected() -> None:
    target, normals = _room_surface()
    profile = _profile()
    with pytest.raises(ValueError, match="nonzero"):
        _refine(profile, target, target, np.zeros_like(normals))

    wrong_frame = _candidate()
    wrong_transform = wrong_frame.transform_target_from_source.model_copy(update={"local_frame": "other-map"})
    wrong_candidate = CoarseRegistrationCandidate(
        **{
            **wrong_frame.__dict__,
            "transform_target_from_source": wrong_transform,
            "candidate_id": "wrong-frame",
        }
    )
    with pytest.raises(ValueError, match="source frame"):
        _refine(profile, target, target, normals, (wrong_candidate,))


def test_sparse_surface_fails_closed_on_correspondence_budget() -> None:
    target, normals = _room_surface()
    profile = _profile(icp_min_correspondences=24)
    result = _refine(profile, target[:12], target[:12], normals[:12])

    assert result.state == RegistrationProposalState.INSUFFICIENT
    assert RegistrationFindingCode.LOW_COVERAGE in {finding for _, finding in result.diagnostics.candidate_findings}
