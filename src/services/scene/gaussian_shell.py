"""Closed shell of one object from its Gaussians: opacity and floater filters, voxel closing, strict QA."""

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree
from scipy.special import expit

MIN_GAUSSIANS = 50


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
