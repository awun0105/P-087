"""Gaussian shell filters and parameter contract; voxel, QA and acceptance tests follow in later stages."""

import numpy as np
import pytest

from src.services.scene.gaussian_shell import (
    GaussianShellError,
    ShellParams,
    _close_shell,
    _filter_gaussians,
    _keep_large_components,
    _voxelize,
)


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


def test_voxel_grid_fails_closed_over_budget():
    rng = np.random.default_rng(8)
    points = uniform(rng, [0.0, 0.0, 0.0], [0.4, 0.6, 0.8], 500)
    with pytest.raises(GaussianShellError, match="max_grid_cells"):
        _voxelize(points, 0.02, pad=3, max_grid_cells=1000)


def test_voxel_grid_pads_occupied_cells_and_reports_origin():
    points = np.array([[0.05, 0.05, 0.05], [0.25, 0.05, 0.05]])
    grid, origin, occupied = _voxelize(points, 0.1, pad=2, max_grid_cells=10_000)
    assert grid.shape == (7, 5, 5)
    assert origin.tolist() == [-2, -2, -2]
    assert occupied == 2
    assert grid[2, 2, 2] and grid[4, 2, 2]


def test_closing_fills_enclosed_cavities():
    grid = np.zeros((12, 12, 12), dtype=bool)
    grid[2:10, 2:10, 2:10] = True
    grid[4:8, 4:8, 4:8] = False
    assert _close_shell(grid, dilate_voxels=0, close_iterations=0)[6, 6, 6]


def test_closing_does_not_bridge_wide_gaps():
    grid = np.zeros((40, 8, 8), dtype=bool)
    grid[2:10, 2:6, 2:6] = True
    grid[20:28, 2:6, 2:6] = True
    closed = _close_shell(grid, dilate_voxels=1, close_iterations=2)
    assert closed[5, 4, 4] and closed[25, 4, 4]
    assert not closed[15, 4, 4]


def test_small_fragments_are_dropped_and_large_components_kept():
    grid = np.zeros((30, 30, 30), dtype=bool)
    grid[2:12, 2:12, 2:12] = True
    grid[20:22, 20:22, 20:22] = True
    kept, kept_count, dropped = _keep_large_components(grid, 0.05)
    assert (kept_count, dropped) == (1, 1)
    assert kept[5, 5, 5] and not kept[20, 20, 20]


def test_two_separate_blocks_are_both_kept():
    grid = np.zeros((30, 10, 10), dtype=bool)
    grid[2:6, 2:6, 2:6] = True
    grid[20:24, 2:6, 2:6] = True
    _, kept_count, dropped = _keep_large_components(grid, 0.05)
    assert (kept_count, dropped) == (2, 0)


def test_no_component_above_fraction_fails_closed():
    grid = np.zeros((20, 20, 20), dtype=bool)
    grid[::4, ::4, ::4] = True
    with pytest.raises(GaussianShellError, match="min_component_fraction"):
        _keep_large_components(grid, 0.05)
