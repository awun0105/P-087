"""Floor fitting must follow the measured plane and fail closed on weak evidence."""

import numpy as np
import pytest

from src.models.contracts.floor_model import FloorFitProfile, FloorModel, FloorPointClass, FloorPrior
from src.services.scene.floor_model import (
    above_floor_mask,
    classify_floor_points,
    fit_canonical_floor_model,
    fit_floor_model,
    point_cloud_checksum,
)

SOURCE_CHECKSUM = "sha256:" + "a" * 64


def _prior(point: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> FloorPrior:
    return FloorPrior(up_direction_world=(0.0, 0.0, 1.0), point_on_floor_world=point)


def _grid(size: int = 24, *, slope_x: float = 0.0, slope_y: float = 0.0, noise_m: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(19)
    axis = np.linspace(-2.0, 2.0, size)
    x, y = np.meshgrid(axis, axis, indexing="xy")
    z = slope_x * x + slope_y * y + rng.normal(0.0, noise_m, x.shape)
    return np.column_stack((x.ravel(), y.ravel(), z.ravel()))


def test_fits_sloped_floor_and_classifies_without_rotating_input() -> None:
    floor = _grid(size=30, slope_x=0.12, slope_y=-0.08, noise_m=0.003)
    original = floor.copy()
    model = fit_floor_model(floor, SOURCE_CHECKSUM, _prior())

    expected_normal = np.array([-0.12, 0.08, 1.0])
    expected_normal /= np.linalg.norm(expected_normal)
    assert model.status == "supported"
    assert np.asarray(model.plane_normal_world) == pytest.approx(expected_normal, abs=0.01)
    assert model.distance_unit == "m" and model.frame == "world"
    assert model.inlier_count > 800 and model.coverage_area_m2 > 15
    assert np.array_equal(floor, original)  # fitting never changes canonical points

    samples = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.3], [0.0, 0.0, -0.3]])
    labels = classify_floor_points(samples, model)
    assert labels.tolist() == [FloorPointClass.FLOOR, FloorPointClass.ABOVE_FLOOR, FloorPointClass.BELOW_FLOOR]


def test_seeded_ransac_is_repeatable_and_resists_outliers() -> None:
    floor = _grid(size=30, noise_m=0.004)
    rng = np.random.default_rng(77)
    outliers = rng.uniform([-5, -5, 1], [5, 5, 4], size=(350, 3))
    points = np.vstack((floor, outliers))

    first = fit_floor_model(points, SOURCE_CHECKSUM, _prior())
    second = fit_floor_model(points, SOURCE_CHECKSUM, _prior())

    assert first.status == "supported"
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.profile_checksum == FloorFitProfile().checksum()
    assert first.inlier_ratio > 0.5


def test_excessive_floor_noise_is_not_reported_as_supported() -> None:
    noisy_floor = _grid(size=30, noise_m=0.05)
    model = fit_floor_model(noisy_floor, SOURCE_CHECKSUM, _prior())

    assert model.status == "uncertain"
    assert model.fallback_reason == "excessive_noise"
    assert model.robust_noise_sigma_m is not None and model.robust_noise_sigma_m > 0.03
    assert not above_floor_mask(noisy_floor, model).any()


def test_sparse_fit_uses_explicit_confirmed_prior_fallback() -> None:
    line = np.column_stack((np.linspace(-1, 1, 12), np.zeros(12), np.zeros(12)))
    model = fit_canonical_floor_model(line, point_cloud_checksum(line))

    assert model.schema_version == "1.1"
    assert model.status == "confirmed_prior_fallback"
    assert model.fallback_reason == "insufficient_points"
    assert model.robust_noise_sigma_m is None
    assert model.floor_band_m == model.profile.max_floor_band_m
    samples = np.array([[0.0, 0.0, 0.05], [0.0, 0.0, 0.12], [0.0, 0.0, -0.1]])
    assert classify_floor_points(samples, model).tolist() == [
        FloorPointClass.FLOOR,
        FloorPointClass.ABOVE_FLOOR,
        FloorPointClass.BELOW_FLOOR,
    ]
    assert above_floor_mask(samples, model).tolist() == [False, True, False]
    legacy = model.model_dump(mode="json")
    legacy["schema_version"] = "1.0"
    with pytest.raises(ValueError, match="requires FloorModel schema 1.1"):
        FloorModel.model_validate(legacy)


def test_vertical_wall_does_not_override_confirmed_floor_prior() -> None:
    floor = _grid(size=20)
    wall_y, wall_z = np.meshgrid(np.linspace(-5, 5, 60), np.linspace(0, 4, 40), indexing="xy")
    wall = np.column_stack((np.zeros(wall_y.size), wall_y.ravel(), wall_z.ravel()))
    model = fit_floor_model(np.vstack((wall, floor)), SOURCE_CHECKSUM, _prior())

    assert model.status == "supported"
    assert model.plane_normal_world == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)


@pytest.mark.parametrize("reason", ["low_inlier_ratio", "insufficient_coverage"])
def test_measured_failed_fit_can_use_confirmed_prior_without_claiming_noise(reason: str) -> None:
    rng = np.random.default_rng(23)
    if reason == "low_inlier_ratio":
        points = np.vstack((_grid(size=20, noise_m=0.002), rng.uniform([-5, -5, 1], [5, 5, 4], (1000, 3))))
        profile = FloorFitProfile(min_inlier_ratio=0.9)
    else:
        points = _grid(size=20, noise_m=0.002)
        profile = FloorFitProfile(min_coverage_area_m2=100)
    checksum = point_cloud_checksum(points)
    fitted = fit_floor_model(points, checksum, _prior(), profile)
    assert fitted.fallback_reason == reason
    assert fitted.robust_noise_sigma_m is not None

    fallback = fit_canonical_floor_model(points, checksum, profile)

    assert fallback.status == "confirmed_prior_fallback"
    assert fallback.fallback_reason == reason
    assert fallback.robust_noise_sigma_m is None
    assert fallback.source_checksum == checksum
    assert fallback.profile_checksum == fitted.profile_checksum
    assert fallback.plane_normal_world == (0.0, 0.0, 1.0)
    assert fallback.plane_offset_m == 0.0
    assert FloorModel.model_validate_json(fallback.model_dump_json()) == fallback
    assert above_floor_mask(np.array([[0, 0, 0.05], [0, 0, 0.12]]), fallback).tolist() == [False, True]


def test_canonical_fit_keeps_excessive_noise_uncertain() -> None:
    points = _grid(size=30, noise_m=0.05)
    model = fit_canonical_floor_model(points, point_cloud_checksum(points))

    assert model.status == "uncertain"
    assert model.fallback_reason == "excessive_noise"
    assert model.robust_noise_sigma_m is not None
    assert not above_floor_mask(points, model).any()


def test_low_support_does_not_hide_excessive_noise_in_canonical_fallback() -> None:
    points = _grid(size=30, noise_m=0.05)
    profile = FloorFitProfile(min_inlier_ratio=0.99)
    model = fit_canonical_floor_model(points, point_cloud_checksum(points), profile)

    assert model.status == "uncertain"
    assert model.fallback_reason == "excessive_noise"
    assert model.robust_noise_sigma_m > profile.max_noise_sigma_m
    assert not above_floor_mask(points, model).any()


def test_low_coverage_does_not_hide_competing_planes_in_canonical_fallback() -> None:
    lower = _grid(size=24)
    upper = lower.copy()
    upper[:, 2] += 0.3
    points = np.vstack((lower, upper))
    profile = FloorFitProfile(prior_band_m=0.4, min_coverage_area_m2=100)
    model = fit_canonical_floor_model(points, point_cloud_checksum(points), profile)

    assert model.status == "uncertain"
    assert model.fallback_reason == "ambiguous_multiple_planes"
    assert not above_floor_mask(points, model).any()


def test_missing_floor_near_prior_is_uncertain_not_wall_plane() -> None:
    wall_y, wall_z = np.meshgrid(np.linspace(-4, 4, 30), np.linspace(1.0, 4.0, 20), indexing="xy")
    wall = np.column_stack((np.full(wall_y.size, 2.0), wall_y.ravel(), wall_z.ravel()))
    model = fit_floor_model(wall, SOURCE_CHECKSUM, _prior())

    assert model.status == "uncertain"
    assert model.fallback_reason == "no_floor_near_prior"
    assert (classify_floor_points(wall, model) == FloorPointClass.UNKNOWN).all()


def test_missing_prior_degenerate_and_non_finite_inputs_fail_closed() -> None:
    points = _grid()
    missing_prior = fit_floor_model(points, SOURCE_CHECKSUM, None)
    line = np.column_stack((np.linspace(0, 1, 100), np.zeros(100), np.zeros(100)))
    degenerate = fit_floor_model(line, SOURCE_CHECKSUM, _prior())
    non_finite = points.copy()
    non_finite[3, 0] = np.nan
    invalid = fit_floor_model(non_finite, SOURCE_CHECKSUM, _prior())

    assert (missing_prior.status, missing_prior.fallback_reason) == ("uncertain", "missing_floor_prior")
    assert (degenerate.status, degenerate.fallback_reason) == ("uncertain", "degenerate_points")
    assert (invalid.status, invalid.fallback_reason) == ("uncertain", "non_finite_points")
    assert (classify_floor_points(points, invalid) == FloorPointClass.UNKNOWN).all()


def test_multiple_floor_levels_are_reported_as_ambiguous() -> None:
    lower = _grid(size=24)
    upper = lower.copy()
    upper[:, 2] += 0.3
    profile = FloorFitProfile(prior_band_m=0.4)
    model = fit_floor_model(np.vstack((lower, upper)), SOURCE_CHECKSUM, _prior(), profile)

    assert model.status == "uncertain"
    assert model.fallback_reason == "ambiguous_multiple_planes"


def test_narrow_support_is_uncertain_even_when_residuals_are_small() -> None:
    x = np.linspace(-2, 2, 300)
    rng = np.random.default_rng(23)
    y = rng.uniform(-0.01, 0.01, len(x))
    points = np.column_stack((x, y, np.zeros_like(x)))
    model = fit_floor_model(points, SOURCE_CHECKSUM, _prior())

    assert model.status == "uncertain"
    assert model.fallback_reason == "insufficient_coverage"
    assert model.coverage_area_m2 < FloorFitProfile().min_coverage_area_m2


def test_contract_rejects_non_unit_up_and_profile_has_bounded_metric_thresholds() -> None:
    with pytest.raises(ValueError, match="normalized"):
        FloorPrior(up_direction_world=(0.0, 0.0, 2.0), point_on_floor_world=(0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="minimum floor band"):
        FloorFitProfile(min_floor_band_m=0.1, max_floor_band_m=0.05)


def test_supported_floor_contract_rechecks_embedded_support_and_coverage() -> None:
    model = fit_floor_model(_grid(size=30), SOURCE_CHECKSUM, _prior())
    payload = model.model_dump(mode="json")
    payload["coverage_area_m2"] = 0.0

    with pytest.raises(ValueError, match="coverage threshold"):
        FloorModel.model_validate(payload)
