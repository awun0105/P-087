"""Closed shell of one object from its Gaussians: opacity and floater filters, voxel closing, strict QA."""

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from scipy.special import expit

MIN_GAUSSIANS = 50
_CROSS = ndimage.generate_binary_structure(3, 1)  # 6-connected neighbourhood for every morphology step


class GaussianShellError(ValueError):
    pass


@dataclass(frozen=True)
class ShellParams:
    voxel_m: float = 0.02
    opacity_min: float = 0.1
    outlier_k: int = 8
    outlier_std: float = 2.0
    dilate_voxels: int = 1
    close_iterations: int = 2
    min_component_fraction: float = 0.05
    smooth_iterations: int = 10
    max_grid_cells: int = 32_000_000

    def __post_init__(self) -> None:
        if not np.isfinite(self.voxel_m) or self.voxel_m <= 0:
            raise ValueError("voxel_m must be finite and positive")
        if not np.isfinite(self.opacity_min) or not 0 <= self.opacity_min <= 1:
            raise ValueError("opacity_min must be within [0, 1]")
        if self.outlier_k < 1 or not np.isfinite(self.outlier_std) or self.outlier_std < 0:
            raise ValueError("outlier_k must be at least 1 and outlier_std a finite non-negative number")
        if min(self.dilate_voxels, self.close_iterations, self.smooth_iterations) < 0:
            raise ValueError("dilate_voxels, close_iterations and smooth_iterations must be non-negative")
        if not np.isfinite(self.min_component_fraction) or not 0 < self.min_component_fraction <= 1:
            raise ValueError("min_component_fraction must be within (0, 1]")
        if self.max_grid_cells <= 0:
            raise ValueError("max_grid_cells must be positive")


def _filter_gaussians(points: np.ndarray, logit: np.ndarray | None, params: ShellParams) -> tuple[np.ndarray, int, int]:
    """Drop low-opacity rows, then floaters whose mean k-neighbour distance is an outlier."""
    keep = np.ones(len(points), dtype=bool) if logit is None else expit(logit) >= params.opacity_min
    opacity_dropped = int(len(points) - np.count_nonzero(keep))
    points = points[keep]
    if len(points) < MIN_GAUSSIANS or len(points) <= params.outlier_k:
        raise GaussianShellError("too few Gaussians after filtering")
    distances, _ = cKDTree(points).query(points, k=params.outlier_k + 1)
    mean_distance = distances[:, 1:].mean(axis=1)
    inlier = mean_distance <= mean_distance.mean() + params.outlier_std * mean_distance.std()
    outliers_dropped = int(len(points) - np.count_nonzero(inlier))
    points = points[inlier]
    if len(points) < MIN_GAUSSIANS:
        raise GaussianShellError("too few Gaussians after filtering")
    return points, opacity_dropped, outliers_dropped


def _voxelize(points: np.ndarray, voxel_m: float, pad: int, max_grid_cells: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Occupancy grid with `pad` empty cells on each side; returns grid, origin in world cells, occupied count."""
    scaled = points / voxel_m
    if not np.isfinite(scaled).all() or np.max(np.abs(scaled)) > 2**52:
        raise GaussianShellError("source coordinates exceed the exact occupancy grid range")
    cells = np.floor(scaled).astype(np.int64)
    low, high = cells.min(axis=0), cells.max(axis=0)
    shape = (high - low + 1 + 2 * pad).tolist()
    if math.prod(shape) > max_grid_cells:
        raise GaussianShellError("shell grid exceeds max_grid_cells budget")
    grid = np.zeros(shape, dtype=bool)
    grid[tuple((cells - low + pad).T)] = True
    return grid, low - pad, int(np.count_nonzero(grid))


def _close_shell(grid: np.ndarray, dilate_voxels: int, close_iterations: int) -> np.ndarray:
    """Grow by dilate_voxels, close narrow gaps, then fill enclosed cavities.

    scipy treats iterations=0 as repeat-until-stable, so a zero count skips that operation.
    """
    if dilate_voxels:
        grid = ndimage.binary_dilation(grid, structure=_CROSS, iterations=dilate_voxels)
    if close_iterations:
        grid = ndimage.binary_closing(grid, structure=_CROSS, iterations=close_iterations)
    return ndimage.binary_fill_holes(grid, structure=_CROSS)


def _keep_large_components(grid: np.ndarray, min_fraction: float) -> tuple[np.ndarray, int, int]:
    """Keep components holding at least min_fraction of all occupied cells; returns grid, kept and dropped counts."""
    labels, count = ndimage.label(grid, structure=_CROSS)
    sizes = np.bincount(labels.ravel(), minlength=count + 1)[1:]
    keep = sizes >= min_fraction * sizes.sum()
    if not keep.any():
        raise GaussianShellError("no connected component reaches min_component_fraction")
    lookup = np.concatenate(([False], keep))
    return lookup[labels], int(keep.sum()), int(count - keep.sum())
