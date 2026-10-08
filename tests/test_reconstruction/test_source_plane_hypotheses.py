from __future__ import annotations

import numpy as np

from src.services.reconstruction.alignment.source_planes import (
    SourcePlaneHypothesisProfile,
    discover_source_plane_hypotheses,
)

_SOURCE_CHECKSUM = "sha256:" + "a" * 64


def _grid_plane(axis: int, coordinate: float, *, count: int = 20, extent: float = 2.0) -> np.ndarray:
    values = np.linspace(-extent / 2, extent / 2, count)
    first, second = np.meshgrid(values, values)
    points = np.zeros((count * count, 3), dtype=np.float64)
    remaining_axes = [index for index in range(3) if index != axis]
    points[:, axis] = coordinate
    points[:, remaining_axes[0]] = first.ravel()
    points[:, remaining_axes[1]] = second.ravel()
    return points


def _profile(**overrides: object) -> SourcePlaneHypothesisProfile:
    return SourcePlaneHypothesisProfile(ransac_iterations=128, **overrides)


def test_reports_multiple_source_planes_without_calling_either_one_the_floor() -> None:
    floor = _grid_plane(2, 0.0, count=24)
    wall = _grid_plane(0, 3.0, count=18)
    outliers = np.random.default_rng(3).uniform(-4.0, 4.0, size=(120, 3))
    points = np.concatenate((floor, wall, outliers))

    result = discover_source_plane_hypotheses(
        points,
        source_checksum=_SOURCE_CHECKSUM,
        source_frame="lidar-map",
        profile=_profile(),
    )

    assert result.status == "hypotheses"
    assert result.reason == "orientation_unclassified"
    assert result.source_checksum == _SOURCE_CHECKSUM
    assert result.profile_checksum == _profile().checksum()
    assert len(result.candidates) == 2
    assert result.candidates[0].support_points > result.candidates[1].support_points
    normals = [np.asarray(candidate.normal_xyz) for candidate in result.candidates]
    assert any(abs(float(normal[2])) > 0.99 for normal in normals)
    assert any(abs(float(normal[0])) > 0.99 for normal in normals)
    assert all(candidate.frame == "lidar-map" for candidate in result.candidates)
    assert all(candidate.evidence_checksum.startswith("sha256:") for candidate in result.candidates)
    assert all(
        field not in result.candidates[0].__dataclass_fields__ for field in ("is_floor", "up_direction_xyz", "selected")
    )


def test_a_single_large_horizontal_plane_remains_unclassified() -> None:
    result = discover_source_plane_hypotheses(
        _grid_plane(2, 0.0, count=24),
        source_checksum=_SOURCE_CHECKSUM,
        source_frame="lidar-map",
        profile=_profile(),
    )

    assert result.status == "hypotheses"
    assert result.reason == "orientation_unclassified"
    assert len(result.candidates) == 1
    assert not hasattr(result.candidates[0], "up_direction_xyz")


def test_no_broad_supported_plane_returns_insufficient() -> None:
    points = np.random.default_rng(12).uniform(-5.0, 5.0, size=(800, 3))

    result = discover_source_plane_hypotheses(
        points,
        source_checksum=_SOURCE_CHECKSUM,
        source_frame="lidar-map",
        profile=_profile(),
    )

    assert result.status == "insufficient"
    assert result.reason == "no_supported_plane"
    assert result.candidates == ()


def test_point_sampling_and_evidence_are_deterministic_and_checksum_bound() -> None:
    plane = _grid_plane(2, 0.0, count=35, extent=4.0)
    noise = np.random.default_rng(7).uniform(-6.0, 6.0, size=(2_000, 3))
    points = np.concatenate((plane, noise))
    profile = _profile(maximum_points=1_000)

    first = discover_source_plane_hypotheses(
        points, source_checksum=_SOURCE_CHECKSUM, source_frame="lidar-map", profile=profile
    )
    second = discover_source_plane_hypotheses(
        points, source_checksum=_SOURCE_CHECKSUM, source_frame="lidar-map", profile=profile
    )
    other_source = discover_source_plane_hypotheses(
        points,
        source_checksum="sha256:" + "b" * 64,
        source_frame="lidar-map",
        profile=profile,
    )

    assert first == second
    assert first.input_point_count == len(points)
    assert first.sampled_point_count == profile.maximum_points
    assert first.evidence_checksum != other_source.evidence_checksum


def test_invalid_coordinates_or_frame_fail_closed() -> None:
    cases = (
        (np.ones((20, 2)), "lidar-map", "invalid_point_shape"),
        (np.full((120, 3), np.nan), "lidar-map", "non_finite_points"),
        (_grid_plane(2, 0.0), "world", "invalid_source_frame"),
        (_grid_plane(2, 0.0), "lidar-map", "invalid_source_checksum"),
    )

    for points, frame, reason in cases:
        checksum = "bad-checksum" if reason == "invalid_source_checksum" else _SOURCE_CHECKSUM
        result = discover_source_plane_hypotheses(
            points, source_checksum=checksum, source_frame=frame, profile=_profile()
        )
        assert result.status == "insufficient"
        assert result.reason == reason
        assert result.candidates == ()
