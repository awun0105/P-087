from __future__ import annotations

import hashlib
import math
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from src.models.contracts.rgb_lidar_registration import (
    RegistrationFindingCode,
    RegistrationProfile,
    RegistrationProposalState,
    RegistrationROI,
    seal_registration_profile,
)
from src.services.reconstruction.alignment import bev_search as bev_search_module
from src.services.reconstruction.alignment.bev_search import (
    RegistrationCancelledError,
    RegistrationFloorPlane,
    search_independent_map_registration,
)
from src.services.reconstruction.alignment.similarity import rotation_matrix

_ZERO_CHECKSUM = "sha256:" + "0" * 64


def _checksum(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _profile(**overrides: object) -> RegistrationProfile:
    return seal_registration_profile(
        {
            "profile_id": "bev-test-v1",
            "profile_checksum": _ZERO_CHECKSUM,
            "yaw_hypotheses": 72,
            "translation_hypotheses": 2_000,
            "max_bev_grid_cells": 65_536,
            "bev_cell_resolution_m": 0.25,
            "minimum_overlap_ratio": 0.05,
            "minimum_source_coverage_ratio": 0.05,
            "minimum_target_coverage_ratio": 0.05,
            "minimum_candidate_margin": 0.01,
            **overrides,
        }
    )


def _floor(frame: str, evidence: str) -> RegistrationFloorPlane:
    return RegistrationFloorPlane(
        frame=frame,
        normal_xyz=(0.0, 0.0, 1.0),
        offset_m=0.0,
        up_direction_xyz=(0.0, 0.0, 1.0),
        evidence_checksum=_checksum(evidence),
    )


def _roi(extent: float = 12.0) -> RegistrationROI:
    return RegistrationROI(
        min_xyz_m=(-extent, -extent, -1.0),
        max_xyz_m=(extent, extent, 8.0),
    )


def _warehouse_surface() -> np.ndarray:
    posts = [
        (-8.0, -5.0, (0.4, 1.0, 2.0, 4.0)),
        (-5.0, 3.0, (0.4, 1.0, 2.0)),
        (-2.0, -7.0, (0.4, 2.0, 4.0)),
        (1.0, -3.0, (0.4, 1.0, 2.0, 4.0)),
        (3.0, 6.0, (0.4, 2.0)),
        (6.0, -1.0, (0.4, 1.0, 4.0)),
        (8.0, 5.0, (0.4, 1.0, 2.0)),
        (-7.0, 8.0, (0.4, 2.0, 4.0)),
        (5.0, 9.0, (0.4, 1.0, 2.0, 4.0)),
        (10.0, -6.0, (0.4, 1.0, 2.0)),
        (-10.0, -1.0, (0.4, 2.0)),
        (0.0, 10.0, (0.4, 1.0, 2.0, 4.0)),
    ]
    return np.asarray([(x, y, z) for x, y, heights in posts for z in heights], dtype=float)


def _source_from_target(target: np.ndarray, yaw: float, translation: tuple[float, float, float]) -> np.ndarray:
    cosine, sine = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]])
    return (target - np.asarray(translation)) @ rotation


def _search(
    source: np.ndarray,
    target: np.ndarray,
    *,
    profile: RegistrationProfile | None = None,
    metric_state: str = "confirmed",
    source_frame: str = "lidar-map-frame",
    extent: float = 12.0,
    runtime_budget_seconds: int | None = None,
    cancel_event: Event | None = None,
):
    return search_independent_map_registration(
        source,
        target,
        source_frame=source_frame,
        source_distance_unit="m",
        source_floor=_floor(source_frame, "source-floor"),
        target_floor=_floor("world", "target-floor"),
        target_roi_world=_roi(extent),
        profile=profile or _profile(),
        metric_state=metric_state,  # type: ignore[arg-type]
        runtime_budget_seconds=runtime_budget_seconds,
        cancel_event=cancel_event,
    )


def test_bev_search_recovers_known_yaw_translation_and_keeps_top_candidate() -> None:
    target = _warehouse_surface()
    yaw = math.radians(37.5)
    shift = (3.3, -2.4, 0.0)
    source = _source_from_target(target, yaw, shift)

    result = _search(source, target)

    assert result.state in {RegistrationProposalState.PROPOSED, RegistrationProposalState.AMBIGUOUS}
    assert result.candidates
    candidate = result.candidates[0]
    matrix = rotation_matrix(candidate.transform_target_from_source.rotation_quaternion_xyzw)
    estimated_yaw = math.atan2(matrix[1, 0], matrix[0, 0])
    assert abs((estimated_yaw - yaw + math.pi) % (2 * math.pi) - math.pi) <= math.radians(2.6)
    np.testing.assert_allclose(candidate.transform_target_from_source.translation_xyz[:2], shift[:2], atol=0.4)
    assert candidate.transform_target_from_source.local_frame == "lidar-map-frame"
    assert result.diagnostics.search_seed == 0
    assert result.diagnostics.fine_hypotheses_evaluated > 0
    assert result.diagnostics.source_floor_evidence_checksum != result.diagnostics.target_floor_evidence_checksum


def test_rotated_source_is_not_rejected_by_zero_yaw_crop() -> None:
    target = np.asarray([(x, 0.0, 0.4) for x in np.arange(-8.0, 8.01, 0.5)], dtype=float)
    source = np.asarray([(0.0, y, 0.4) for y in np.arange(-8.0, 8.01, 0.5)], dtype=float)
    frame = "rotated-source"
    profile = _profile(yaw_hypotheses=4, translation_hypotheses=64)
    roi = RegistrationROI(min_xyz_m=(-10.0, -0.1, -0.1), max_xyz_m=(10.0, 0.1, 5.0))

    result = search_independent_map_registration(
        source,
        target,
        source_frame=frame,
        source_distance_unit="m",
        source_floor=_floor(frame, "rotated-floor"),
        target_floor=_floor("world", "rotated-target-floor"),
        target_roi_world=roi,
        profile=profile,
    )

    assert result.candidates
    assert result.diagnostics.source_structural_cells >= 3
    assert max(candidate.yaw_radians for candidate in result.candidates) > math.pi / 4


def test_partial_overlap_and_rgb_ghosts_keep_candidates_without_claiming_qa_pass() -> None:
    target = _warehouse_surface()
    yaw = math.radians(20.0)
    shift = (-1.5, 2.25, 0.0)
    partial = target[:-8]
    source = _source_from_target(partial, yaw, shift)
    ghosts = np.asarray([(-9.0, -9.0, 0.4), (-8.5, 10.0, 3.0), (9.5, -10.0, 2.0), (11.0, 8.0, 4.0)], dtype=float)

    result = _search(source, np.concatenate((target, ghosts)))

    assert result.candidates
    assert result.candidates[0].score <= 1.0
    assert result.diagnostics.target_point_count == len(target) + len(ghosts)
    assert not hasattr(result, "qa_status")
    assert result.candidates[0].source_coverage_ratio > 0.5


def test_bounded_rgb_scale_search_retains_known_scale_hypothesis() -> None:
    metric_target = _warehouse_surface()
    source = metric_target.copy()
    unscaled_rgb = metric_target / 1.1
    profile = _profile(scale_policy="bounded_rgb_scale_search", rgb_scale_factor_bounds=(0.8, 1.2))

    result = _search(source, unscaled_rgb, profile=profile, metric_state="unknown")

    assert result.candidates
    assert result.candidates[0].rgb_scale_factor == 1.1
    assert result.diagnostics.scale_hypotheses_evaluated == 5


def test_symmetric_repeating_racks_are_returned_as_ambiguous() -> None:
    posts = [(-7.0, -3.0), (-7.0, 3.0), (-3.0, -7.0), (-3.0, 7.0), (3.0, -7.0), (3.0, 7.0), (7.0, -3.0), (7.0, 3.0)]
    target = np.asarray([(x, y, z) for x, y in posts for z in (0.4, 1.0, 2.0, 4.0)], dtype=float)

    result = _search(target, target)

    assert result.state == RegistrationProposalState.AMBIGUOUS
    assert RegistrationFindingCode.AMBIGUOUS_CANDIDATES in result.findings
    assert len(result.candidates) >= 2
    assert result.diagnostics.candidate_margin is not None
    assert result.diagnostics.candidate_margin < 0.01


def test_straight_corridor_has_multiple_supported_translation_candidates() -> None:
    target = np.asarray(
        [(x, y, z) for x in np.arange(-20.0, 20.01, 0.5) for y in (-3.0, 3.0) for z in (0.4, 1.0, 2.0, 4.0)],
        dtype=float,
    )
    source = np.asarray(
        [(x, y, z) for x in np.arange(-5.0, 5.01, 0.5) for y in (-3.0, 3.0) for z in (0.4, 1.0, 2.0, 4.0)],
        dtype=float,
    )
    profile = _profile(translation_hypotheses=5_000, minimum_candidate_margin=0.05)

    result = _search(source, target, profile=profile, extent=25.0)

    assert len(result.candidates) >= 2
    assert result.state == RegistrationProposalState.AMBIGUOUS
    assert RegistrationFindingCode.AMBIGUOUS_CANDIDATES in result.findings


def test_floor_only_clouds_are_unobservable_and_not_aligned() -> None:
    floor = np.asarray([(x, y, 0.0) for x in range(-5, 6) for y in range(-5, 6)], dtype=float)

    result = _search(floor, floor)

    assert result.state == RegistrationProposalState.INSUFFICIENT
    assert result.candidates == ()
    assert RegistrationFindingCode.UNOBSERVABLE in result.findings


def test_source_distance_unit_is_converted_to_meters_before_search() -> None:
    target = _warehouse_surface()
    source_cm = target * 100.0
    source_frame = "lidar-centimeters"

    result = search_independent_map_registration(
        source_cm,
        target,
        source_frame=source_frame,
        source_distance_unit="cm",
        source_floor=RegistrationFloorPlane(
            frame=source_frame,
            normal_xyz=(0.0, 0.0, 1.0),
            offset_m=0.0,
            up_direction_xyz=(0.0, 0.0, 1.0),
            evidence_checksum=_checksum("cm-floor"),
        ),
        target_floor=_floor("world", "target-floor"),
        target_roi_world=_roi(),
        profile=_profile(),
    )

    assert result.candidates
    np.testing.assert_allclose(
        result.candidates[0].transform_target_from_source.translation_xyz, (0.0, 0.0, 0.0), atol=0.3
    )


def test_bev_search_stops_when_cancelled_before_search_work() -> None:
    cancelled = Event()
    cancelled.set()

    with pytest.raises(RegistrationCancelledError, match="cancelled"):
        _search(_warehouse_surface(), _warehouse_surface(), cancel_event=cancelled)


def test_bev_search_honors_worker_runtime_budget_override(monkeypatch) -> None:
    timestamps = iter((0.0, 2.0, 2.0))
    monkeypatch.setattr(
        bev_search_module,
        "time",
        SimpleNamespace(monotonic=lambda: next(timestamps, 2.0)),
    )

    result = _search(
        _warehouse_surface(),
        _warehouse_surface(),
        profile=_profile(runtime_budget_seconds=300),
        runtime_budget_seconds=1,
    )

    assert result.diagnostics.budget_exhausted is True
    assert result.diagnostics.yaw_hypotheses_evaluated == 0
