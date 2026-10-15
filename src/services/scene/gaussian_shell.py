"""Closed shell of one object from its Gaussians: opacity and floater filters, voxel closing, rim caps, strict QA.

A rim cap closes a face whose outer layers enclose a footprint in projection. It is a conservative approximation:
holes parallel to an axis are filled, pinholes also count as capped faces, and a closed object can list capped
directions. Faces that the scan never observed are not guaranteed to close; see report.md for the open cases.
Shell meshes use a larger intersection budget than other surfaces, and large objects use coarser voxels.
"""

import hashlib
import json
import math
from dataclasses import asdict, dataclass

import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree
from scipy.special import expit

from src.services.scene.object_aware_geometry import occupancy_surface
from src.services.scene.surface_mesh import assess_surface

MIN_GAUSSIANS = 50
_CROSS = ndimage.generate_binary_structure(3, 1)  # 6-connected neighbourhood for every morphology step
# Shell meshes are denser than the 250k pair budget that suits ObjectGS and CoACD surfaces; shells get their own.
SHELL_INTERSECTION_BUDGET = 2_000_000
_CROSS_2D = ndimage.generate_binary_structure(2, 1)
_DIRECTIONS = ("-x", "+x", "-y", "+y", "-z", "+z")


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
    # voxel_m grows for large objects so the longest extent spans at most this many cells.
    max_cells_per_axis: int = 96
    # Rim cap: close a face whose outer layers enclose a footprint in projection (see _cap_open_faces).
    cap_open_faces: bool = True

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
        if self.max_cells_per_axis < 1:
            raise ValueError("max_cells_per_axis must be at least 1")


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


def _cap_open_faces(grid: np.ndarray, band: int) -> tuple[np.ndarray, int, list[str]]:
    """Rim cap: close a face whose outermost `band` layers enclose a footprint in projection.

    Holes of the band projection become cells of the extreme layer, applied in direction order.
    Limits, both conservative approximations rather than evidence about the unseen face: a hole that
    runs parallel to an axis is filled too, and a pinhole in the projection also counts as a capped
    face, so `capped_directions` can name directions on a closed object.
    """
    grid = grid.copy()
    capped, directions = 0, []
    for direction in _DIRECTIONS:
        sign, axis = direction[0], "xyz".index(direction[1])
        layers = np.flatnonzero(grid.any(axis=tuple(other for other in range(3) if other != axis)))
        if sign == "-":
            extreme = int(layers[0])
            indices = np.arange(extreme, min(extreme + band, grid.shape[axis]))
        else:
            extreme = int(layers[-1])
            indices = np.arange(max(extreme - band + 1, 0), extreme + 1)
        projection = np.take(grid, indices, axis=axis).any(axis=axis)
        cap = ndimage.binary_fill_holes(projection, structure=_CROSS_2D) & ~projection
        if cap.any():
            selector = [slice(None)] * 3
            selector[axis] = extreme
            grid[tuple(selector)] |= cap
            capped += int(cap.sum())
            directions.append(direction)
    return grid, capped, directions


def _close_shell(
    grid: np.ndarray, dilate_voxels: int, close_iterations: int, *, cap_open_faces: bool = True
) -> tuple[np.ndarray, int, list[str]]:
    """Grow by dilate_voxels, close narrow gaps, cap open faces, then fill enclosed cavities.

    scipy treats iterations=0 as repeat-until-stable, so a zero count skips that operation.
    """
    if dilate_voxels:
        grid = ndimage.binary_dilation(grid, structure=_CROSS, iterations=dilate_voxels)
    if close_iterations:
        grid = ndimage.binary_closing(grid, structure=_CROSS, iterations=close_iterations)
    capped, directions = 0, []
    if cap_open_faces:
        grid, capped, directions = _cap_open_faces(grid, dilate_voxels + close_iterations + 1)
    return ndimage.binary_fill_holes(grid, structure=_CROSS), capped, directions


def _keep_large_components(grid: np.ndarray, min_fraction: float) -> tuple[np.ndarray, int, int]:
    """Keep components holding at least min_fraction of all occupied cells; returns grid, kept and dropped counts."""
    labels, count = ndimage.label(grid, structure=_CROSS)
    sizes = np.bincount(labels.ravel(), minlength=count + 1)[1:]
    keep = sizes >= min_fraction * sizes.sum()
    if not keep.any():
        raise GaussianShellError("no connected component reaches min_component_fraction")
    lookup = np.concatenate(([False], keep))
    return lookup[labels], int(keep.sum()), int(count - keep.sum())


_MAX_DIAGONAL_ROUNDS = 10
_BODY_DIAGONALS = (((0, 0, 0), (1, 1, 1)), ((0, 1, 1), (1, 0, 0)), ((0, 1, 0), (1, 0, 1)), ((0, 0, 1), (1, 1, 0)))


def _window(shape: tuple[int, ...], axes: tuple[int, ...], offsets: tuple[int, ...]) -> tuple[slice, ...]:
    """Slices picking, for every block origin, the cell shifted by offsets on axes; other axes span fully."""
    index = [slice(None)] * len(shape)
    for axis, offset in zip(axes, offsets, strict=True):
        index[axis] = slice(offset, shape[axis] - 1 + offset)
    return tuple(index)


def _planar_diagonal_targets(grid: np.ndarray) -> np.ndarray:
    """Empty cells that break a 2x2 checkerboard in an axis-aligned plane (would make a non-manifold edge)."""
    targets = np.zeros_like(grid)
    for a, b in ((0, 1), (0, 2), (1, 2)):
        w00, w10, w01, w11 = (grid[_window(grid.shape, (a, b), shift)] for shift in ((0, 0), (1, 0), (0, 1), (1, 1)))
        # One diagonal occupied and the other empty: turn on the empty corner with the lower index.
        targets[_window(grid.shape, (a, b), (0, 1))] |= w00 & w11 & ~w10 & ~w01
        targets[_window(grid.shape, (a, b), (0, 0))] |= w10 & w01 & ~w00 & ~w11
    return targets


def _body_diagonal_targets(grid: np.ndarray) -> np.ndarray:
    """Repair 2x2x2 vertices where two body-diagonal cells touch, or two body-diagonal holes touch."""
    corners = {
        (dx, dy, dz): grid[_window(grid.shape, (0, 1, 2), (dx, dy, dz))]
        for dx in (0, 1)
        for dy in (0, 1)
        for dz in (0, 1)
    }
    occupied = sum(corner.astype(np.uint8) for corner in corners.values())
    targets = np.zeros_like(grid)
    for low, high in _BODY_DIAGONALS:
        # Two touching cells: occupy a face neighbour of the lower one. Two touching holes: occupy the lower hole.
        touching_cells = corners[low] & corners[high] & (occupied == 2)
        touching_holes = ~corners[low] & ~corners[high] & (occupied == 6)
        targets[_window(grid.shape, (0, 1, 2), (1 - low[0], low[1], low[2]))] |= touching_cells
        targets[_window(grid.shape, (0, 1, 2), low)] |= touching_holes
    return targets


def _repair_diagonals(grid: np.ndarray) -> tuple[np.ndarray, int]:
    """Turn on empty cells in rounds until no diagonal contact is left; returns grid and cells added."""
    fixes = 0
    for _ in range(_MAX_DIAGONAL_ROUNDS):
        targets = _planar_diagonal_targets(grid) | _body_diagonal_targets(grid)
        if not targets.any():
            return grid, fixes
        fixes += int(np.count_nonzero(targets & ~grid))
        grid = grid | targets
    if (_planar_diagonal_targets(grid) | _body_diagonal_targets(grid)).any():
        raise GaussianShellError("diagonal contacts remain after the repair round limit")
    return grid, fixes


def _as_float_array(value: object, message: str) -> np.ndarray:
    try:
        return np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise GaussianShellError(message) from error


def _validated_rows(positions: np.ndarray, opacity_logit: np.ndarray | None) -> tuple[np.ndarray, np.ndarray | None]:
    points = _as_float_array(positions, "positions must be numeric (n, 3)")
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < MIN_GAUSSIANS or not np.isfinite(points).all():
        raise GaussianShellError(f"shell needs at least {MIN_GAUSSIANS} finite (n, 3) Gaussian positions")
    if opacity_logit is None:
        return points, None
    logit = _as_float_array(opacity_logit, "opacity logit must be numeric")
    if logit.shape != (len(points),) or not np.isfinite(logit).all():
        raise GaussianShellError("opacity logit must be finite with one value per position")
    return points, logit


def _checksum(params: ShellParams, voxel_m: float, cells: np.ndarray, origin: np.ndarray) -> str:
    payload = {**asdict(params), "voxel_m_effective": voxel_m}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    digest.update((cells + origin).astype("<i8").tobytes())
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class GaussianShell:
    vertices: np.ndarray  # (N, 3) float64, object-local metres
    faces: np.ndarray  # (M, 3) int64
    checksum: str  # "sha256:" of the params JSON plus the final occupied cells
    statistics: dict[str, int | float | list[str] | list[float | None]]
    quality: dict  # assess_surface result


def build_gaussian_shell(
    positions: np.ndarray, opacity_logit: np.ndarray | None, params: ShellParams = ShellParams()
) -> GaussianShell:
    """Closed, QA-passed shell of one object's Gaussians; raises GaussianShellError rather than return an unsound mesh."""
    points, logit = _validated_rows(positions, opacity_logit)
    rows = len(points)
    points, opacity_dropped, outliers_dropped = _filter_gaussians(points, logit, params)
    extent = float(np.max(points.max(axis=0) - points.min(axis=0)))
    voxel_m = max(params.voxel_m, extent / params.max_cells_per_axis)
    pad = params.dilate_voxels + params.close_iterations + 1
    grid, origin, occupied = _voxelize(points, voxel_m, pad, params.max_grid_cells)
    grid, capped_cells, capped_directions = _close_shell(
        grid, params.dilate_voxels, params.close_iterations, cap_open_faces=params.cap_open_faces
    )
    filled = int(np.count_nonzero(grid)) - occupied - capped_cells
    grid, components_kept, components_dropped = _keep_large_components(grid, params.min_component_fraction)
    grid, diagonal_fixes = _repair_diagonals(grid)
    cells = np.argwhere(grid)
    vertices, faces = occupancy_surface({tuple(cell) for cell in cells.tolist()}, voxel_m)
    mesh = trimesh.Trimesh(vertices + origin * voxel_m, faces, process=False)
    if params.smooth_iterations:
        mesh = trimesh.smoothing.filter_taubin(mesh, iterations=params.smooth_iterations)
    quality = assess_surface(mesh, intersection_budget=SHELL_INTERSECTION_BUDGET)
    if not quality["passed"]:
        raise GaussianShellError("gaussian shell failed surface QA: " + ", ".join(quality["reasons"]))
    return GaussianShell(
        vertices=np.asarray(mesh.vertices, dtype=np.float64),
        faces=np.asarray(mesh.faces, dtype=np.int64),
        checksum=_checksum(params, voxel_m, cells, origin),
        statistics={
            "input_rows": rows,
            "opacity_dropped": opacity_dropped,
            "outliers_dropped": outliers_dropped,
            "occupied_cells": occupied,
            "filled_cells": filled,
            "components_kept": components_kept,
            "components_dropped": components_dropped,
            "diagonal_fixes": diagonal_fixes,
            "voxel_m_effective": voxel_m,
            "capped_cells": capped_cells,
            "capped_directions": capped_directions,
            "component_genus": quality["metrics"]["component_genus"],
        },
        quality=quality,
    )
