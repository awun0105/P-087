"""Deterministic floor plane fitting without changing canonical scene coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
from scipy.spatial import ConvexHull, QhullError

from src.models.contracts.artifacts import Checksum
from src.models.contracts.floor_model import (
    FloorFitFallbackReason,
    FloorFitProfile,
    FloorFitStatus,
    FloorModel,
    FloorPointClass,
    FloorPrior,
)

_CLASSIFY_CHUNK_SIZE = 250_000


@dataclass(frozen=True)
class _PlaneHypothesis:
    support: int
    median_residual_m: float
    normal: np.ndarray
    offset_m: float


def _angle_degrees(first: np.ndarray, second: np.ndarray) -> float:
    cosine = float(np.clip(np.dot(first, second), -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def _same_plane(first: _PlaneHypothesis, second: _PlaneHypothesis, prior: np.ndarray, profile: FloorFitProfile) -> bool:
    angle = _angle_degrees(first.normal, second.normal)
    offset_at_prior = abs(float(np.dot(first.normal - second.normal, prior) + first.offset_m - second.offset_m))
    return angle <= profile.ambiguity_angle_degrees and offset_at_prior <= profile.ambiguity_offset_m


def _oriented_plane(points: np.ndarray, up: np.ndarray) -> tuple[np.ndarray, float] | None:
    if len(points) < 3:
        return None
    centered = points - points.mean(axis=0)
    try:
        _, singular_values, vectors = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    if singular_values[0] <= 1e-12 or singular_values[1] <= 1e-9 * singular_values[0]:
        return None
    normal = vectors[-1]
    if float(np.dot(normal, up)) < 0:
        normal = -normal
    normal = normal / np.linalg.norm(normal)
    return normal, -float(np.dot(normal, points.mean(axis=0)))


def _coverage_area(points: np.ndarray, normal: np.ndarray) -> float:
    if len(points) < 3:
        return 0.0
    reference = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    axis_x = np.cross(normal, reference)
    axis_x /= np.linalg.norm(axis_x)
    axis_y = np.cross(normal, axis_x)
    projected = np.column_stack((points @ axis_x, points @ axis_y))
    try:
        return float(ConvexHull(projected).volume)
    except QhullError:
        return 0.0


def _result(
    *,
    source_checksum: Checksum,
    profile: FloorFitProfile,
    prior: FloorPrior | None,
    status: FloorFitStatus,
    reason: FloorFitFallbackReason | None,
    point_count: int,
    fit_point_count: int = 0,
    inlier_count: int = 0,
    coverage_area_m2: float = 0.0,
    median_abs_residual_m: float | None = None,
    robust_noise_sigma_m: float | None = None,
    floor_band_m: float | None = None,
    normal: np.ndarray | None = None,
    offset_m: float | None = None,
) -> FloorModel:
    return FloorModel(
        status=status,
        fallback_reason=reason,
        source_checksum=source_checksum,
        profile_checksum=profile.checksum(),
        profile=profile,
        prior=prior,
        point_count=point_count,
        fit_point_count=fit_point_count,
        inlier_count=inlier_count,
        inlier_ratio=inlier_count / fit_point_count if fit_point_count else 0.0,
        coverage_area_m2=coverage_area_m2,
        median_abs_residual_m=median_abs_residual_m,
        robust_noise_sigma_m=robust_noise_sigma_m,
        floor_band_m=floor_band_m,
        plane_normal_world=cast(tuple[float, float, float], tuple(float(value) for value in normal))
        if normal is not None
        else None,
        plane_offset_m=offset_m,
    )


def fit_floor_model(
    points_world_m: np.ndarray,
    source_checksum: Checksum,
    prior: FloorPrior | None,
    profile: FloorFitProfile = FloorFitProfile(),
) -> FloorModel:
    """Fit a supported floor plane, or return explicit uncertainty without moving points."""
    try:
        points = np.asarray(points_world_m)
    except (TypeError, ValueError):
        points = np.empty((0, 3), dtype=np.float64)
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="invalid_point_shape",
            point_count=0,
        )

    point_count = len(points) if points.ndim else 0
    if points.ndim != 2 or points.shape[1] != 3:
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="invalid_point_shape",
            point_count=point_count,
        )
    if not (np.issubdtype(points.dtype, np.integer) or np.issubdtype(points.dtype, np.floating)):
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="invalid_point_shape",
            point_count=point_count,
        )
    if prior is None:
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=None,
            status="uncertain",
            reason="missing_floor_prior",
            point_count=point_count,
        )
    if not np.isfinite(points).all():
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="non_finite_points",
            point_count=point_count,
        )
    if point_count < profile.min_inliers:
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="insufficient_points",
            point_count=point_count,
        )

    up = np.asarray(prior.up_direction_world, dtype=np.float64)
    prior_point = np.asarray(prior.point_on_floor_world, dtype=np.float64)
    if point_count > profile.max_fit_points:
        rng = np.random.default_rng(profile.seed)
        selected = np.sort(rng.choice(point_count, size=profile.max_fit_points, replace=False))
        fit_points = np.asarray(points[selected], dtype=np.float64)
    else:
        fit_points = np.asarray(points, dtype=np.float64)

    spread = np.linalg.svd(fit_points - fit_points.mean(axis=0), compute_uv=False)
    if spread[0] <= 1e-12 or spread[1] <= 1e-9 * spread[0]:
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="degenerate_points",
            point_count=point_count,
            fit_point_count=len(fit_points),
        )

    min_up_dot = math.cos(math.radians(profile.max_tilt_degrees))
    rng = np.random.default_rng(profile.seed)
    hypotheses: list[_PlaneHypothesis] = []
    for indices in (rng.choice(len(fit_points), size=3, replace=False) for _ in range(profile.iterations)):
        first, second, third = fit_points[indices]
        normal = np.cross(second - first, third - first)
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-10:
            continue
        normal /= norm
        if float(np.dot(normal, up)) < 0:
            normal = -normal
        if float(np.dot(normal, up)) < min_up_dot:
            continue
        offset = -float(np.dot(normal, first))
        if abs(float(np.dot(normal, prior_point) + offset)) > profile.prior_band_m:
            continue
        residuals = np.abs(fit_points @ normal + offset)
        inliers = residuals <= profile.ransac_threshold_m
        support = int(inliers.sum())
        if support < profile.min_inliers:
            continue
        hypothesis = _PlaneHypothesis(
            support=support,
            median_residual_m=float(np.median(residuals[inliers])),
            normal=normal.copy(),
            offset_m=offset,
        )
        for index, existing in enumerate(hypotheses):
            if _same_plane(hypothesis, existing, prior_point, profile):
                if (hypothesis.support, -hypothesis.median_residual_m) > (
                    existing.support,
                    -existing.median_residual_m,
                ):
                    hypotheses[index] = hypothesis
                break
        else:
            hypotheses.append(hypothesis)
        hypotheses.sort(key=lambda candidate: (candidate.support, -candidate.median_residual_m), reverse=True)
        hypotheses = hypotheses[:2]

    if not hypotheses:
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="no_floor_near_prior",
            point_count=point_count,
            fit_point_count=len(fit_points),
        )

    best = hypotheses[0]
    initial_inliers = np.abs(fit_points @ best.normal + best.offset_m) <= profile.ransac_threshold_m
    plane = _oriented_plane(fit_points[initial_inliers], up)
    if plane is None:
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="degenerate_points",
            point_count=point_count,
            fit_point_count=len(fit_points),
            inlier_count=int(initial_inliers.sum()),
        )

    normal, offset = plane
    if (
        _angle_degrees(normal, up) > profile.max_tilt_degrees
        or abs(float(np.dot(normal, prior_point) + offset)) > profile.prior_band_m
    ):
        return _result(
            source_checksum=source_checksum,
            profile=profile,
            prior=prior,
            status="uncertain",
            reason="no_floor_near_prior",
            point_count=point_count,
            fit_point_count=len(fit_points),
            normal=normal,
            offset_m=offset,
        )

    signed_residuals = fit_points @ normal + offset
    plausible = np.abs(signed_residuals) <= profile.max_floor_band_m
    scale_sample = (
        signed_residuals[plausible]
        if int(plausible.sum()) >= profile.min_inliers
        else signed_residuals[initial_inliers]
    )
    residual_center = float(np.median(scale_sample))
    robust_sigma = float(1.4826 * np.median(np.abs(scale_sample - residual_center)))
    offset -= residual_center
    floor_band = float(
        np.clip(
            max(profile.min_floor_band_m, profile.noise_sigma_multiplier * robust_sigma),
            profile.min_floor_band_m,
            profile.max_floor_band_m,
        )
    )
    residuals = np.abs(fit_points @ normal + offset)
    final_inliers = residuals <= floor_band
    inlier_count = int(final_inliers.sum())
    inlier_ratio = inlier_count / len(fit_points)
    inlier_points = fit_points[final_inliers]
    coverage = _coverage_area(inlier_points, normal)
    median_residual = float(np.median(residuals[final_inliers])) if inlier_count else None

    reason: str | None = None
    if inlier_count < profile.min_inliers:
        reason = "insufficient_inliers"
    elif inlier_ratio < profile.min_inlier_ratio:
        reason = "low_inlier_ratio"
    elif coverage < profile.min_coverage_area_m2:
        reason = "insufficient_coverage"
    elif robust_sigma > profile.max_noise_sigma_m:
        reason = "excessive_noise"
    elif len(hypotheses) > 1:
        alternative = hypotheses[1]
        distinct = not _same_plane(
            alternative, _PlaneHypothesis(inlier_count, median_residual or 0.0, normal, offset), prior_point, profile
        )
        if distinct and alternative.support >= profile.ambiguity_support_ratio * best.support:
            reason = "ambiguous_multiple_planes"

    return _result(
        source_checksum=source_checksum,
        profile=profile,
        prior=prior,
        status="supported" if reason is None else "uncertain",
        reason=reason,
        point_count=point_count,
        fit_point_count=len(fit_points),
        inlier_count=inlier_count,
        coverage_area_m2=coverage,
        median_abs_residual_m=median_residual,
        robust_noise_sigma_m=robust_sigma,
        floor_band_m=floor_band,
        normal=normal,
        offset_m=offset,
    )


def classify_floor_points(points_world_m: np.ndarray, model: FloorModel) -> np.ndarray:
    """Return compact labels; uncertain fits classify every point as UNKNOWN."""
    points = np.asarray(points_world_m)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("floor classification expects an (N, 3) point array")
    if not (np.issubdtype(points.dtype, np.integer) or np.issubdtype(points.dtype, np.floating)):
        raise ValueError("floor classification expects real-valued points")
    labels = np.full(len(points), FloorPointClass.UNKNOWN, dtype=np.uint8)
    if model.status != "supported" or model.plane_normal_world is None or model.plane_offset_m is None:
        return labels
    band = model.floor_band_m
    if band is None:
        return labels
    normal = np.asarray(model.plane_normal_world)
    for start in range(0, len(points), _CLASSIFY_CHUNK_SIZE):
        stop = min(start + _CLASSIFY_CHUNK_SIZE, len(points))
        chunk = np.asarray(points[start:stop], dtype=np.float64)
        finite = np.isfinite(chunk).all(axis=1)
        signed_distance = np.zeros(len(chunk), dtype=np.float64)
        signed_distance[finite] = chunk[finite] @ normal + model.plane_offset_m
        floor = finite & (np.abs(signed_distance) <= band)
        above = finite & (signed_distance > band)
        below = finite & (signed_distance < -band)
        labels[start:stop][floor] = FloorPointClass.FLOOR
        labels[start:stop][above] = FloorPointClass.ABOVE_FLOOR
        labels[start:stop][below] = FloorPointClass.BELOW_FLOOR
    return labels
