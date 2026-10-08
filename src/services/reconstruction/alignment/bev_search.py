"""Bounded floor-normalized BEV initialization for independent RGB/LiDAR maps.

This module only proposes coarse transforms. Input points must already be resolved
from the exact LiDAR ingest and RGB collision-geometry artifacts by a trusted caller.
Empty BEV cells are unknown, not observed free space; only supported surface cells
contribute to the score. The result is never a QA PASS or a committed alignment.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Literal

import numpy as np

from src.models.contracts.coordinates import Transform
from src.models.contracts.rgb_lidar_registration import (
    RegistrationFindingCode,
    RegistrationProfile,
    RegistrationProposalState,
    RegistrationROI,
)
from src.services.reconstruction.alignment.similarity import _quaternion

DistanceUnit = Literal["m", "cm", "mm"]
_UNIT_TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001}
_CHECKSUM_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_POINT_CHUNK = 250_000


@dataclass(frozen=True)
class RegistrationFloorPlane:
    """Verified floor plane in one input frame; normal and up both use that frame."""

    frame: str
    normal_xyz: tuple[float, float, float]
    offset_m: float
    up_direction_xyz: tuple[float, float, float]
    evidence_checksum: str

    def frame_to_floor_matrix(self) -> np.ndarray:
        """Rigid transform from metric frame coordinates into floor-local Z-up coordinates."""
        return _floor_to_local(self)


@dataclass(frozen=True)
class CoarseRegistrationCandidate:
    """One ranked, floor-constrained rigid transform from source frame to world."""

    candidate_id: str
    transform_target_from_source: Transform
    score: float
    source_coverage_ratio: float
    target_coverage_ratio: float
    overlap_ratio: float
    yaw_radians: float
    translation_xy_m: tuple[float, float]
    rgb_scale_factor: float | None


@dataclass(frozen=True)
class RegistrationSearchDiagnostics:
    """Search budgets and evidence provenance needed to interpret coarse candidates."""

    profile_checksum: str
    source_floor_evidence_checksum: str
    target_floor_evidence_checksum: str
    source_point_count: int
    target_point_count: int
    source_sample_count: int
    target_sample_count: int
    source_structural_cells: int
    target_structural_cells: int
    source_cells_by_height: tuple[int, ...]
    target_cells_by_height: tuple[int, ...]
    bev_resolution_m: float
    fine_resolution_m: float
    search_seed: int
    yaw_hypotheses_evaluated: int
    scale_hypotheses_evaluated: int
    translation_hypotheses_evaluated: int
    fine_hypotheses_evaluated: int
    candidate_margin: float | None
    elapsed_seconds: float
    budget_exhausted: bool
    source_cropped_points: int
    target_cropped_points: int


@dataclass(frozen=True)
class CoarseRegistrationSearchResult:
    """Ranked hypotheses and explicit ambiguity/insufficiency state."""

    state: RegistrationProposalState
    candidates: tuple[CoarseRegistrationCandidate, ...]
    findings: tuple[RegistrationFindingCode, ...]
    diagnostics: RegistrationSearchDiagnostics


def _rotation_to_up(normal: np.ndarray) -> np.ndarray:
    """Return the shortest rotation mapping a unit plane normal onto +Z."""
    up = np.array([0.0, 0.0, 1.0])
    cosine = float(np.clip(np.dot(normal, up), -1.0, 1.0))
    cross = np.cross(normal, up)
    sine = float(np.linalg.norm(cross))
    if sine <= 1e-10:
        if cosine > 0:
            return np.eye(3)
        axis = np.cross(normal, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(axis) <= 1e-10:
            axis = np.cross(normal, np.array([0.0, 1.0, 0.0]))
        axis /= np.linalg.norm(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    axis = cross / sine
    skew = np.array(
        [[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]],
        dtype=float,
    )
    return np.eye(3) + sine * skew + (1.0 - cosine) * (skew @ skew)


def _floor_to_local(plane: RegistrationFloorPlane) -> np.ndarray:
    if not plane.frame or not _CHECKSUM_RE.fullmatch(plane.evidence_checksum):
        raise ValueError("floor plane must bind a frame and a sha256 evidence checksum")
    normal = np.asarray(plane.normal_xyz, dtype=float)
    up = np.asarray(plane.up_direction_xyz, dtype=float)
    if normal.shape != (3,) or up.shape != (3,) or not np.isfinite(normal).all() or not np.isfinite(up).all():
        raise ValueError("floor plane normal and up direction must be finite 3D vectors")
    normal_norm, up_norm = float(np.linalg.norm(normal)), float(np.linalg.norm(up))
    if normal_norm <= 0 or up_norm <= 0 or not math.isfinite(plane.offset_m):
        raise ValueError("floor plane normal, up direction, and offset must be valid")
    normal, up = normal / normal_norm, up / up_norm
    offset = plane.offset_m / normal_norm
    if float(np.dot(normal, up)) < 0:
        normal, offset = -normal, -offset
    if float(np.dot(normal, up)) <= 1e-6:
        raise ValueError("floor plane normal must point along the declared up direction")
    rotation = _rotation_to_up(normal)
    point_on_plane = -offset * normal
    translation = -(rotation @ point_on_plane)
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = rotation, translation
    return transform


def _apply_transform(points: np.ndarray, transform: np.ndarray) -> np.ndarray:
    return points @ transform[:3, :3].T + transform[:3, 3]


def _validated_points(points: np.ndarray, name: str, point_limit: int, sample_limit: int, seed: int) -> np.ndarray:
    values = np.asarray(points)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"{name} must have shape (N, 3)")
    if len(values) == 0:
        raise ValueError(f"{name} is empty")
    if len(values) > point_limit:
        raise ValueError(f"{name} exceeds the frozen raw point budget")
    try:
        finite = np.isfinite(values).all()
    except TypeError as error:
        raise ValueError(f"{name} must contain numeric coordinates") from error
    if not finite:
        raise ValueError(f"{name} contains NaN or Inf")
    if len(values) > sample_limit:
        rng = np.random.default_rng(seed)
        selected = np.sort(rng.choice(len(values), size=sample_limit, replace=False))
        values = values[selected]
    return np.asarray(values, dtype=float)


def _scale_hypotheses(profile: RegistrationProfile, metric_state: Literal["confirmed", "unknown"]) -> list[float]:
    if metric_state == "confirmed":
        return [1.0]
    if profile.scale_policy != "bounded_rgb_scale_search" or profile.rgb_scale_factor_bounds is None:
        raise ValueError("unknown RGB scale requires the bounded scale policy")
    lower, upper = profile.rgb_scale_factor_bounds
    factors = np.linspace(lower, upper, profile.rgb_scale_hypotheses).tolist()
    if lower <= 1.0 <= upper:
        nearest = min(range(len(factors)), key=lambda index: abs(factors[index] - 1.0))
        factors[nearest] = 1.0
    return sorted(set(float(value) for value in factors))


def _grid_shape(min_xy: np.ndarray, max_xy: np.ndarray, profile: RegistrationProfile) -> tuple[int, int, float]:
    extent = max_xy - min_xy
    if np.any(extent <= 0) or not np.isfinite(extent).all():
        raise ValueError("floor-normalized target ROI has invalid horizontal bounds")
    resolution = profile.bev_cell_resolution_m
    width = max(2, int(math.ceil(float(extent[0]) / resolution)))
    height = max(2, int(math.ceil(float(extent[1]) / resolution)))
    if width * height > profile.max_bev_grid_cells:
        resolution = max(resolution, math.sqrt(float(extent[0] * extent[1]) / profile.max_bev_grid_cells))
        while True:
            width = max(2, int(math.ceil(float(extent[0]) / resolution)))
            height = max(2, int(math.ceil(float(extent[1]) / resolution)))
            if width * height <= profile.max_bev_grid_cells:
                break
            resolution *= 1.01
    return width, height, resolution


def _rasterize_target(
    points: np.ndarray,
    *,
    scale: float,
    min_xy: np.ndarray,
    width: int,
    height: int,
    resolution: float,
    height_edges: tuple[float, ...],
) -> tuple[np.ndarray, tuple[int, ...], int]:
    bands = len(height_edges) + 1
    grid = np.zeros((bands, height, width), dtype=bool)
    cropped = 0
    for start in range(0, len(points), _POINT_CHUNK):
        chunk = points[start : start + _POINT_CHUNK] * scale
        ix = np.floor((chunk[:, 0] - min_xy[0]) / resolution).astype(np.int64)
        iy = np.floor((chunk[:, 1] - min_xy[1]) / resolution).astype(np.int64)
        levels = np.searchsorted(height_edges, chunk[:, 2], side="right")
        valid = (chunk[:, 2] > height_edges[0]) & (ix >= 0) & (ix < width) & (iy >= 0) & (iy < height)
        cropped += int(len(chunk) - np.count_nonzero(valid))
        if np.any(valid):
            grid[levels[valid], iy[valid], ix[valid]] = True
    return grid, tuple(int(value) for value in grid.sum(axis=(1, 2))), cropped


def _rasterize_source(
    points: np.ndarray,
    *,
    center_xy: np.ndarray,
    yaw: float,
    width: int,
    height: int,
    resolution: float,
    height_edges: tuple[float, ...],
) -> tuple[np.ndarray, tuple[int, ...], int]:
    bands = len(height_edges) + 1
    grid = np.zeros((bands, height, width), dtype=bool)
    cosine, sine = math.cos(yaw), math.sin(yaw)
    x_origin, y_origin = -(width / 2) * resolution, -(height / 2) * resolution
    cropped = 0
    for start in range(0, len(points), _POINT_CHUNK):
        chunk = points[start : start + _POINT_CHUNK]
        delta = chunk[:, :2] - center_xy
        rotated_x = cosine * delta[:, 0] - sine * delta[:, 1]
        rotated_y = sine * delta[:, 0] + cosine * delta[:, 1]
        ix = np.floor((rotated_x - x_origin) / resolution).astype(np.int64)
        iy = np.floor((rotated_y - y_origin) / resolution).astype(np.int64)
        levels = np.searchsorted(height_edges, chunk[:, 2], side="right")
        valid = (chunk[:, 2] > height_edges[0]) & (ix >= 0) & (ix < width) & (iy >= 0) & (iy < height)
        cropped += int(len(chunk) - np.count_nonzero(valid))
        if np.any(valid):
            grid[levels[valid], iy[valid], ix[valid]] = True
    return grid, tuple(int(value) for value in grid.sum(axis=(1, 2))), cropped


def _next_power_of_two(value: int) -> int:
    return 1 << (value - 1).bit_length()


def _correlation_lags(values: np.ndarray, height: int, width: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pad_height, pad_width = values.shape
    rows = np.concatenate((np.arange(pad_height - (height - 1), pad_height), np.arange(height)))
    columns = np.concatenate((np.arange(pad_width - (width - 1), pad_width), np.arange(width)))
    return (
        values[np.ix_(rows, columns)],
        np.arange(-(height - 1), height),
        np.arange(-(width - 1), width),
    )


def _candidate_transform(
    *,
    target_floor_from_world: np.ndarray,
    source_floor_from_source: np.ndarray,
    source_frame: str,
    target_min_xy: np.ndarray,
    source_center_xy: np.ndarray,
    source_width: int,
    source_height: int,
    resolution: float,
    lag_x: int,
    lag_y: int,
    yaw: float,
) -> tuple[Transform, tuple[float, float]]:
    cosine, sine = math.cos(yaw), math.sin(yaw)
    rotation_local = np.array([[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]])
    translation_local = np.array(
        [
            target_min_xy[0] + lag_x * resolution + (source_width / 2) * resolution,
            target_min_xy[1] + lag_y * resolution + (source_height / 2) * resolution,
            0.0,
        ]
    ) - rotation_local @ np.array([source_center_xy[0], source_center_xy[1], 0.0])
    return (
        _candidate_transform_from_translation(
            target_floor_from_world=target_floor_from_world,
            source_floor_from_source=source_floor_from_source,
            source_frame=source_frame,
            translation_xy_m=(float(translation_local[0]), float(translation_local[1])),
            yaw=yaw,
        ),
        (float(translation_local[0]), float(translation_local[1])),
    )


def _candidate_transform_from_translation(
    *,
    target_floor_from_world: np.ndarray,
    source_floor_from_source: np.ndarray,
    source_frame: str,
    translation_xy_m: tuple[float, float],
    yaw: float,
) -> Transform:
    cosine, sine = math.cos(yaw), math.sin(yaw)
    rotation_local = np.array([[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]])
    translation_local = np.array([translation_xy_m[0], translation_xy_m[1], 0.0])
    target_floor_from_source_floor = np.eye(4)
    target_floor_from_source_floor[:3, :3] = rotation_local
    target_floor_from_source_floor[:3, 3] = translation_local
    world_from_source = (
        np.linalg.inv(target_floor_from_world) @ target_floor_from_source_floor @ source_floor_from_source
    )
    transform = Transform(
        parent_frame="world",
        local_frame=source_frame,
        translation_xyz=tuple(float(value) for value in world_from_source[:3, 3]),
        rotation_quaternion_xyzw=_quaternion(world_from_source[:3, :3]),
    )
    return transform


def _support_keys(
    points: np.ndarray,
    *,
    min_xy: np.ndarray,
    width: int,
    height: int,
    resolution: float,
    height_edges: tuple[float, ...],
) -> np.ndarray:
    ix = np.floor((points[:, 0] - min_xy[0]) / resolution).astype(np.int64)
    iy = np.floor((points[:, 1] - min_xy[1]) / resolution).astype(np.int64)
    levels = np.searchsorted(height_edges, points[:, 2], side="right")
    valid = (points[:, 2] > height_edges[0]) & (ix >= 0) & (ix < width) & (iy >= 0) & (iy < height)
    if not np.any(valid):
        return np.empty(0, dtype=np.int64)
    keys = (levels[valid] * height + iy[valid]) * width + ix[valid]
    return np.unique(keys)


def _deduplicate_candidates(
    values: list[CoarseRegistrationCandidate], *, limit: int, yaw_step: float, resolution: float
) -> list[CoarseRegistrationCandidate]:
    kept: list[CoarseRegistrationCandidate] = []
    for candidate in sorted(
        values,
        key=lambda value: (-value.score, -value.overlap_ratio, value.yaw_radians, value.translation_xy_m),
    ):
        duplicate = any(
            _yaw_difference(candidate.yaw_radians, current.yaw_radians) <= yaw_step * 1.01
            and math.dist(candidate.translation_xy_m, current.translation_xy_m) <= 2.0 * resolution
            and candidate.rgb_scale_factor == current.rgb_scale_factor
            for current in kept
        )
        if not duplicate:
            kept.append(candidate)
        if len(kept) >= limit:
            break
    return kept


def _yaw_difference(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def search_independent_map_registration(
    source_points: np.ndarray,
    target_collision_surface_points_world_m: np.ndarray,
    *,
    source_frame: str,
    source_distance_unit: DistanceUnit,
    source_floor: RegistrationFloorPlane,
    target_floor: RegistrationFloorPlane,
    target_roi_world: RegistrationROI,
    profile: RegistrationProfile,
    metric_state: Literal["confirmed", "unknown"] = "confirmed",
) -> CoarseRegistrationSearchResult:
    """Search bounded floor-constrained yaw/translation candidates for independent maps.

    ``target_collision_surface_points_world_m`` must come from the exact canonical
    collision geometry artifact (or another verified surface extractor). Gaussian
    centers alone are not accepted as surface evidence. Empty cells remain unknown;
    they are excluded from negative-space scoring.
    """
    started = time.monotonic()
    if profile.checksum() != profile.profile_checksum:
        raise ValueError("registration search profile checksum mismatch")
    if source_frame == "world" or source_floor.frame != source_frame:
        raise ValueError("source floor and map must share a non-world source frame")
    if target_floor.frame != "world":
        raise ValueError("target floor plane must use canonical world coordinates")
    if source_distance_unit not in _UNIT_TO_M:
        raise ValueError("unsupported source distance unit")
    roi_extent = [high - low for low, high in zip(target_roi_world.min_xyz_m, target_roi_world.max_xyz_m, strict=True)]
    if any(extent > profile.max_roi_extent_m for extent in roi_extent):
        raise ValueError("registration ROI exceeds the frozen profile extent")

    source_sample = _validated_points(
        source_points,
        "source point map",
        profile.max_source_points,
        profile.max_points_per_map,
        profile.search_seed,
    )
    target_sample = _validated_points(
        target_collision_surface_points_world_m,
        "target collision surface",
        profile.max_source_points,
        profile.max_points_per_map,
        profile.search_seed ^ 0x9E3779B9,
    )
    source_raw_count, target_raw_count = (
        len(np.asarray(source_points)),
        len(np.asarray(target_collision_surface_points_world_m)),
    )

    source_floor_from_source = _floor_to_local(source_floor)
    target_floor_from_world = _floor_to_local(target_floor)
    source_to_m = _UNIT_TO_M[source_distance_unit]
    source_local = _apply_transform(source_sample * source_to_m, source_floor_from_source)
    target_local = _apply_transform(target_sample, target_floor_from_world)

    roi_corners = np.array(
        [
            (x, y, z)
            for x in (target_roi_world.min_xyz_m[0], target_roi_world.max_xyz_m[0])
            for y in (target_roi_world.min_xyz_m[1], target_roi_world.max_xyz_m[1])
            for z in (target_roi_world.min_xyz_m[2], target_roi_world.max_xyz_m[2])
        ],
        dtype=float,
    )
    roi_local = _apply_transform(roi_corners, target_floor_from_world)
    source_center_xy = np.median(source_local[:, :2], axis=0)
    scales = _scale_hypotheses(profile, metric_state)
    max_scales = min(len(scales), profile.translation_hypotheses)
    if max_scales < len(scales):
        selected_scale_indices = np.linspace(0, len(scales) - 1, max_scales, dtype=int)
        scales = [scales[index] for index in selected_scale_indices]
    max_yaws = max(1, profile.translation_hypotheses // max(1, len(scales)))
    yaw_indices = np.linspace(0, profile.yaw_hypotheses - 1, min(profile.yaw_hypotheses, max_yaws), dtype=int)
    yaws = [2.0 * math.pi * int(index) / profile.yaw_hypotheses for index in yaw_indices]
    per_hypothesis_translation_budget = max(1, profile.translation_hypotheses // max(1, len(scales) * len(yaws)))
    bands = tuple(float(value) for value in profile.bev_height_edges_m)
    all_candidates: list[CoarseRegistrationCandidate] = []
    base_width = 0
    base_resolution = profile.bev_cell_resolution_m
    source_cells_by_height: tuple[int, ...] = (0,) * (len(bands) + 1)
    target_cells_by_height: tuple[int, ...] = (0,) * (len(bands) + 1)
    source_cropped_points = target_cropped_points = 0
    yaw_evaluated = translations_evaluated = 0
    fine_hypotheses_evaluated = 0
    fine_resolution_m = math.inf
    budget_exhausted = False

    for scale in scales:
        scale_roi = roi_local * scale
        min_xy, max_xy = scale_roi[:, :2].min(axis=0), scale_roi[:, :2].max(axis=0)
        width, height, resolution = _grid_shape(min_xy, max_xy, profile)
        if not base_width:
            base_width, base_resolution = width, resolution
        target_grid, target_counts, target_cropped = _rasterize_target(
            target_local,
            scale=scale,
            min_xy=min_xy,
            width=width,
            height=height,
            resolution=resolution,
            height_edges=bands,
        )
        target_count = int(target_grid.sum())
        if target_count == 0:
            continue
        if not any(target_cells_by_height):
            target_cells_by_height = target_counts
            target_cropped_points = target_cropped
        pad_height, pad_width = _next_power_of_two(2 * height - 1), _next_power_of_two(2 * width - 1)
        target_spectrum = np.fft.rfftn(target_grid, s=(pad_height, pad_width), axes=(-2, -1))
        for yaw in yaws:
            if time.monotonic() - started >= profile.runtime_budget_seconds:
                budget_exhausted = True
                break
            yaw_evaluated += 1
            source_grid, source_counts, cropped = _rasterize_source(
                source_local,
                center_xy=source_center_xy,
                yaw=yaw,
                width=width,
                height=height,
                resolution=resolution,
                height_edges=bands,
            )
            source_count = int(source_grid.sum())
            if sum(source_counts) > sum(source_cells_by_height):
                source_cells_by_height = source_counts
            source_cropped_points = max(source_cropped_points, cropped)
            if source_count < 3:
                continue
            source_spectrum = np.fft.rfftn(source_grid, s=(pad_height, pad_width), axes=(-2, -1))
            cyclic = np.fft.irfftn(
                np.sum(target_spectrum * np.conjugate(source_spectrum), axis=0),
                s=(pad_height, pad_width),
                axes=(-2, -1),
            )
            overlap_grid, lag_rows, lag_columns = _correlation_lags(cyclic, height, width)
            available = min(per_hypothesis_translation_budget, overlap_grid.size)
            scores = overlap_grid.copy()
            for _ in range(available):
                flat_index = int(np.argmax(scores))
                overlap = int(round(float(scores.flat[flat_index])))
                if overlap <= 0:
                    break
                row, column = np.unravel_index(flat_index, scores.shape)
                lag_y, lag_x = int(lag_rows[row]), int(lag_columns[column])
                if (
                    abs(lag_x * resolution) > profile.max_roi_extent_m
                    or abs(lag_y * resolution) > profile.max_roi_extent_m
                ):
                    scores[max(0, row - 1) : row + 2, max(0, column - 1) : column + 2] = -1
                    continue
                overlap = min(overlap, source_count, target_count)
                source_coverage = overlap / source_count
                target_coverage = overlap / target_count
                union = source_count + target_count - overlap
                overlap_ratio = overlap / union if union else 0.0
                coverage_score = (
                    2 * source_coverage * target_coverage / (source_coverage + target_coverage)
                    if source_coverage + target_coverage
                    else 0.0
                )
                transform, translation_xy = _candidate_transform(
                    target_floor_from_world=target_floor_from_world,
                    source_floor_from_source=source_floor_from_source,
                    source_frame=source_frame,
                    target_min_xy=min_xy,
                    source_center_xy=source_center_xy,
                    source_width=width,
                    source_height=height,
                    resolution=resolution,
                    lag_x=lag_x,
                    lag_y=lag_y,
                    yaw=yaw,
                )
                all_candidates.append(
                    CoarseRegistrationCandidate(
                        candidate_id="pending",
                        transform_target_from_source=transform,
                        score=float(np.clip(coverage_score, 0.0, 1.0)),
                        source_coverage_ratio=float(source_coverage),
                        target_coverage_ratio=float(target_coverage),
                        overlap_ratio=float(overlap_ratio),
                        yaw_radians=yaw,
                        translation_xy_m=translation_xy,
                        rgb_scale_factor=scale if metric_state == "unknown" else None,
                    )
                )
                translations_evaluated += 1
                scores[max(0, row - 1) : row + 2, max(0, column - 1) : column + 2] = -1
            if budget_exhausted:
                break
        if budget_exhausted:
            break

    yaw_step = 2.0 * math.pi / profile.yaw_hypotheses
    coarse_seeds = _deduplicate_candidates(
        all_candidates,
        limit=profile.max_refinement_candidates,
        yaw_step=yaw_step,
        resolution=base_resolution,
    )
    fine_candidates: list[CoarseRegistrationCandidate] = []
    translation_offsets = (-1.5, -0.75, 0.0, 0.75, 1.5)
    yaw_offsets = (-0.5 * yaw_step, 0.0, 0.5 * yaw_step)
    refinement_source = _validated_points(
        source_local,
        "refinement source map",
        profile.max_points_per_map,
        profile.max_refinement_points,
        profile.search_seed ^ 0x85EBCA6B,
    )
    refinement_target = _validated_points(
        target_local,
        "refinement target surface",
        profile.max_points_per_map,
        profile.max_refinement_points,
        profile.search_seed ^ 0xC2B2AE35,
    )
    for seed in coarse_seeds:
        if budget_exhausted:
            break
        scale = seed.rgb_scale_factor if seed.rgb_scale_factor is not None else 1.0
        scale_roi = roi_local * scale
        min_xy, max_xy = scale_roi[:, :2].min(axis=0), scale_roi[:, :2].max(axis=0)
        _, _, coarse_resolution = _grid_shape(min_xy, max_xy, profile)
        fine_resolution = coarse_resolution * 0.5
        fine_resolution_m = min(fine_resolution_m, fine_resolution)
        extent = max_xy - min_xy
        width = max(2, int(math.ceil(float(extent[0]) / fine_resolution)))
        height = max(2, int(math.ceil(float(extent[1]) / fine_resolution)))
        target_keys = _support_keys(
            refinement_target * scale,
            min_xy=min_xy,
            width=width,
            height=height,
            resolution=fine_resolution,
            height_edges=bands,
        )
        target_count = len(target_keys)
        if target_count == 0:
            continue
        for yaw_offset in yaw_offsets:
            yaw = (seed.yaw_radians + yaw_offset) % (2.0 * math.pi)
            cosine, sine = math.cos(yaw), math.sin(yaw)
            source_x = cosine * refinement_source[:, 0] - sine * refinement_source[:, 1]
            source_y = sine * refinement_source[:, 0] + cosine * refinement_source[:, 1]
            for offset_x in translation_offsets:
                for offset_y in translation_offsets:
                    if time.monotonic() - started >= profile.runtime_budget_seconds:
                        budget_exhausted = True
                        break
                    translation_xy = (
                        seed.translation_xy_m[0] + offset_x * coarse_resolution,
                        seed.translation_xy_m[1] + offset_y * coarse_resolution,
                    )
                    transformed = np.column_stack(
                        (
                            source_x + translation_xy[0],
                            source_y + translation_xy[1],
                            refinement_source[:, 2],
                        )
                    )
                    source_keys = _support_keys(
                        transformed,
                        min_xy=min_xy,
                        width=width,
                        height=height,
                        resolution=fine_resolution,
                        height_edges=bands,
                    )
                    source_count = len(source_keys)
                    if source_count < 3:
                        continue
                    overlap = int(np.intersect1d(source_keys, target_keys, assume_unique=True).size)
                    if overlap <= 0:
                        continue
                    source_coverage = overlap / source_count
                    target_coverage = overlap / target_count
                    overlap_ratio = overlap / (source_count + target_count - overlap)
                    score = (
                        2 * source_coverage * target_coverage / (source_coverage + target_coverage)
                        if source_coverage + target_coverage
                        else 0.0
                    )
                    fine_candidates.append(
                        CoarseRegistrationCandidate(
                            candidate_id="pending",
                            transform_target_from_source=_candidate_transform_from_translation(
                                target_floor_from_world=target_floor_from_world,
                                source_floor_from_source=source_floor_from_source,
                                source_frame=source_frame,
                                translation_xy_m=translation_xy,
                                yaw=yaw,
                            ),
                            score=float(np.clip(score, 0.0, 1.0)),
                            source_coverage_ratio=float(source_coverage),
                            target_coverage_ratio=float(target_coverage),
                            overlap_ratio=float(overlap_ratio),
                            yaw_radians=yaw,
                            translation_xy_m=translation_xy,
                            rgb_scale_factor=seed.rgb_scale_factor,
                        )
                    )
                    fine_hypotheses_evaluated += 1
                if budget_exhausted:
                    break
            if budget_exhausted:
                break
    if not math.isfinite(fine_resolution_m):
        fine_resolution_m = base_resolution * 0.5
    deduplicated = _deduplicate_candidates(
        all_candidates + fine_candidates,
        limit=profile.top_k_candidates,
        yaw_step=yaw_step,
        resolution=base_resolution,
    )
    candidates = tuple(
        CoarseRegistrationCandidate(
            candidate_id=f"coarse-{index:04d}",
            transform_target_from_source=item.transform_target_from_source,
            score=item.score,
            source_coverage_ratio=item.source_coverage_ratio,
            target_coverage_ratio=item.target_coverage_ratio,
            overlap_ratio=item.overlap_ratio,
            yaw_radians=item.yaw_radians,
            translation_xy_m=item.translation_xy_m,
            rgb_scale_factor=item.rgb_scale_factor,
        )
        for index, item in enumerate(deduplicated, start=1)
    )
    margin = candidates[0].score - candidates[1].score if len(candidates) > 1 else None
    findings: list[RegistrationFindingCode] = []
    if budget_exhausted:
        findings.append(RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED)
        state = RegistrationProposalState.INSUFFICIENT
    elif not candidates:
        findings.append(RegistrationFindingCode.UNOBSERVABLE)
        state = RegistrationProposalState.INSUFFICIENT
    elif candidates[0].overlap_ratio < profile.minimum_overlap_ratio:
        findings.append(RegistrationFindingCode.LOW_OVERLAP)
        state = RegistrationProposalState.INSUFFICIENT
    elif (
        candidates[0].source_coverage_ratio < profile.minimum_source_coverage_ratio
        or candidates[0].target_coverage_ratio < profile.minimum_target_coverage_ratio
    ):
        findings.append(RegistrationFindingCode.LOW_COVERAGE)
        state = RegistrationProposalState.INSUFFICIENT
    elif len(candidates) < 2:
        findings.append(RegistrationFindingCode.UNOBSERVABLE)
        state = RegistrationProposalState.INSUFFICIENT
    elif margin is not None and margin < profile.minimum_candidate_margin:
        findings.append(RegistrationFindingCode.AMBIGUOUS_CANDIDATES)
        state = RegistrationProposalState.AMBIGUOUS
    else:
        state = RegistrationProposalState.PROPOSED

    diagnostics = RegistrationSearchDiagnostics(
        profile_checksum=profile.profile_checksum,
        source_floor_evidence_checksum=source_floor.evidence_checksum,
        target_floor_evidence_checksum=target_floor.evidence_checksum,
        source_point_count=source_raw_count,
        target_point_count=target_raw_count,
        source_sample_count=len(source_sample),
        target_sample_count=len(target_sample),
        source_structural_cells=sum(source_cells_by_height),
        target_structural_cells=sum(target_cells_by_height),
        source_cells_by_height=source_cells_by_height,
        target_cells_by_height=target_cells_by_height,
        bev_resolution_m=base_resolution,
        fine_resolution_m=fine_resolution_m,
        search_seed=profile.search_seed,
        yaw_hypotheses_evaluated=yaw_evaluated,
        scale_hypotheses_evaluated=len(scales),
        translation_hypotheses_evaluated=translations_evaluated + fine_hypotheses_evaluated,
        fine_hypotheses_evaluated=fine_hypotheses_evaluated,
        candidate_margin=margin,
        elapsed_seconds=max(0.0, time.monotonic() - started),
        budget_exhausted=budget_exhausted,
        source_cropped_points=source_cropped_points,
        target_cropped_points=target_cropped_points,
    )
    return CoarseRegistrationSearchResult(
        state=state,
        candidates=candidates,
        findings=tuple(findings),
        diagnostics=diagnostics,
    )
