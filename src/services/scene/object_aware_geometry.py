"""Separate ownership before meshing; never refill excluded object occupancy afterwards."""

import hashlib
import json
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ObjectAwareGeometry:
    vertices: np.ndarray
    faces: np.ndarray
    occupancy_checksum: str
    statistics: dict[str, int]


def occupancy_surface(cells: set[tuple[int, int, int]], voxel_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Exposed voxel faces of an occupancy set, outward winding, metres. Raises ValueError if empty."""
    if not cells:
        raise ValueError("occupancy is empty")
    if not np.isfinite(voxel_m) or voxel_m <= 0:
        raise ValueError("voxel_m must be finite and positive")
    corner_ids: dict[tuple[int, int, int], int] = {}
    vertices = []
    faces = []
    for cell in sorted(cells):
        for axis in range(3):
            u, v = (axis + 1) % 3, (axis + 2) % 3
            for sign in [-1, 1]:
                neighbor = list(cell)
                neighbor[axis] += sign
                if tuple(neighbor) in cells:
                    continue
                corners = []
                for a, b in [(0, 0), (1, 0), (1, 1), (0, 1)]:
                    point = list(cell)
                    point[axis] += int(sign > 0)
                    point[u] += a
                    point[v] += b
                    key = tuple(point)
                    if key not in corner_ids:
                        corner_ids[key] = len(vertices)
                        vertices.append(point)
                    corners.append(corner_ids[key])
                if sign < 0:
                    corners.reverse()
                faces.extend([(corners[0], corners[1], corners[2]), (corners[0], corners[2], corners[3])])
    return np.asarray(vertices, dtype=float) * voxel_m, np.asarray(faces, dtype=np.int64)


def build_background_collision(
    points: np.ndarray,
    labels: np.ndarray,
    removed_labels: set[int],
    *,
    voxel_m: float,
    unknown: np.ndarray | None = None,
    observed_free_cells: np.ndarray | None = None,
    inferred_support_points: np.ndarray | None = None,
    max_grid_cells: int = 4_000_000_000,
    max_occupied_cells: int = 32_000_000,
) -> ObjectAwareGeometry:
    """Keep background/shared/unknown/support occupancy, exclude object-only cells before extraction.

    Unknown ownership stays conservative and is reported. Free cells must be measured evidence,
    not visibility guesses. Support points are explicit authored inputs and reported as inferred.
    No exterior fill, binary hole fill, inpainted Gaussians or triangle ownership carving is used.
    """
    points = np.asarray(points, dtype=np.float64)
    labels = np.asarray(labels)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
        raise ValueError("background geometry needs finite source points")
    if labels.shape != (len(points),) or not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("one integer membership label is required per source point")
    if not np.isfinite(voxel_m) or voxel_m <= 0 or max_grid_cells <= 0 or max_occupied_cells <= 0:
        raise ValueError("invalid voxel resolution or occupancy budget")
    if -1 in removed_labels or any(label < 0 for label in removed_labels):
        raise ValueError("background cannot be an excluded object label")
    if unknown is None:
        unknown = np.zeros(len(points), dtype=bool)
    unknown = np.asarray(unknown)
    if unknown.shape != labels.shape or unknown.dtype != np.bool_:
        raise ValueError("unknown ownership must be an explicit boolean source-row mask")
    scaled = points / voxel_m
    if not np.isfinite(scaled).all() or np.max(np.abs(scaled)) > 2**52:
        raise ValueError("source coordinates exceed the exact occupancy grid range")
    if np.any(labels < -1):
        raise ValueError("unknown membership needs an explicit unknown-row mask")
    cells = np.floor(scaled).astype(np.int64)
    removed = np.isin(labels, list(removed_labels)) & ~unknown
    background = {tuple(row) for row in cells[~removed]}
    owned = {tuple(row) for row in cells[removed]}
    shared = background & owned
    support: set[tuple[int, int, int]] = set()
    if inferred_support_points is not None:
        support_points = np.asarray(inferred_support_points, dtype=float)
        if support_points.ndim != 2 or support_points.shape[1] != 3 or not np.isfinite(support_points).all():
            raise ValueError("inferred support points must be finite metre coordinates")
        support = {tuple(row) for row in np.floor(support_points / voxel_m).astype(np.int64)}
    free: set[tuple[int, int, int]] = set()
    if observed_free_cells is not None:
        values = np.asarray(observed_free_cells)
        if values.ndim != 2 or values.shape[1] != 3 or not np.issubdtype(values.dtype, np.integer):
            raise ValueError("observed free-space cells must use integer grid coordinates")
        free = {tuple(row) for row in values}
        if free & (background | support):
            raise ValueError("measured free-space conflicts with retained background/support occupancy")
    kept = (background | support) - free
    if not kept:
        raise ValueError("object-aware environment occupancy is empty")
    # Meshing uses sparse occupancy; a large empty span does not allocate a dense grid.
    if len(kept) > max_occupied_cells:
        raise ValueError(
            f"object-aware occupancy needs {len(kept)} occupied cells, exceeds budget {max_occupied_cells}"
        )
    kept_cells = np.asarray(sorted(kept), dtype=np.int64)
    low, high = kept_cells.min(axis=0), kept_cells.max(axis=0)
    dimensions = high - low + 3
    grid_cells = int(np.prod(dimensions.astype(object)))
    if grid_cells > max_grid_cells:
        raise ValueError(
            f"object-aware occupancy needs {grid_cells} bounding grid cells, exceeds budget {max_grid_cells}"
        )
    # Emit only exposed voxel faces. No smoothing/fill step can reintroduce excluded occupancy.
    vertices, faces = occupancy_surface(kept, voxel_m)
    digest = hashlib.sha256(
        json.dumps({"algorithm": "object_aware_occupancy_v1", "voxel_m": voxel_m}, sort_keys=True).encode()
    )
    digest.update(kept_cells.astype("<i8").tobytes())
    return ObjectAwareGeometry(
        vertices,
        faces,
        "sha256:" + digest.hexdigest(),
        {
            "source_points": len(points),
            "background_cells": len(background),
            "excluded_object_only_cells": len(owned - background),
            "shared_cells": len(shared),
            "unknown_rows": int(unknown.sum()),
            "inferred_support_cells": len(support),
            "retained_cells": len(kept),
            "observed_free_cells": len(free),
        },
    )
