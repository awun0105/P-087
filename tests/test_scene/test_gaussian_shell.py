"""Gaussian shell filters and parameter contract; voxel, QA and acceptance tests follow in later stages."""

import numpy as np
import pytest

from src.services.scene.gaussian_shell import GaussianShellError, ShellParams, _filter_gaussians


def uniform(rng, low, high, count):
    return rng.uniform(low, high, size=(count, 3))


def test_opacity_filter_drops_low_logit_gaussians():
    rng = np.random.default_rng(5)
    points = uniform(rng, [0.0, 0.0, 0.0], [0.4, 0.6, 0.8], 100)
    logit = np.where(np.arange(100) < 70, 5.0, -5.0)
    kept, opacity_dropped, _ = _filter_gaussians(points, logit, ShellParams())
    assert opacity_dropped == 30
    kept_rows = {tuple(row) for row in kept}
    assert not kept_rows & {tuple(row) for row in points[70:]}


def test_floaters_far_from_the_object_are_rejected():
    rng = np.random.default_rng(6)
    object_points = uniform(rng, [0.0, 0.0, 0.0], [0.4, 0.6, 0.8], 20000)
    floaters = uniform(rng, [1.0, 0.0, 0.0], [2.0, 1.0, 1.0], 200)
    kept, opacity_dropped, outliers_dropped = _filter_gaussians(
        np.vstack([object_points, floaters]), None, ShellParams()
    )
    assert opacity_dropped == 0
    assert outliers_dropped >= 150
    assert kept[:, 0].max() < 0.5


def test_too_few_gaussians_after_opacity_filter_fail_closed():
    rng = np.random.default_rng(7)
    points = uniform(rng, [0.0, 0.0, 0.0], [0.4, 0.6, 0.8], 60)
    logit = np.where(np.arange(60) < 40, 5.0, -5.0)
    with pytest.raises(GaussianShellError, match="too few Gaussians"):
        _filter_gaussians(points, logit, ShellParams())


def test_shell_params_reject_invalid_values():
    with pytest.raises(ValueError, match="voxel_m"):
        ShellParams(voxel_m=0.0)
    with pytest.raises(ValueError, match="min_component_fraction"):
        ShellParams(min_component_fraction=0.0)
