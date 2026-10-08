"""Floor-constrained robust point-to-plane refinement for registration proposals.

This module refines proposals only. It does not commit an alignment or declare a
provisional profile production-qualified.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from src.models.contracts.coordinates import Transform
from src.models.contracts.rgb_lidar_registration import (
    RegistrationCandidate,
    RegistrationFindingCode,
    RegistrationProfile,
    RegistrationProposalState,
    RegistrationQAStatus,
    RegistrationRegionMetric,
)
from src.services.reconstruction.alignment.bev_search import (
    CoarseRegistrationCandidate,
    CoarseRegistrationSearchResult,
    RegistrationFloorPlane,
)
from src.services.reconstruction.alignment.similarity import _quaternion, rotation_matrix

_MIN_NORMAL_NORM = 1e-6
_MIN_VOXEL_SIZE_M = 1e-3
_MIN_ROBUST_DELTA_M = 5e-3


@dataclass(frozen=True)
class RefinedRegistrationCandidate:
    """Refined transform and geometric evidence; confidence is not absolute accuracy."""

    candidate: RegistrationCandidate
    coarse_score: float
    source_coverage_ratio: float
    target_coverage_ratio: float
    overlap_ratio: float
    correspondence_count: int
    rejected_correspondence_count: int
    observable_dof: int
    point_to_plane_p95_residual_m: float
    bidirectional_p95_residual_m: float
    bidirectional_max_residual_m: float
    iterations: int
    converged: bool
    regions: tuple[RegistrationRegionMetric, ...]


@dataclass(frozen=True)
class ConstrainedICPDiagnostics:
    """Bounded-work accounting and per-candidate failure evidence."""

    profile_checksum: str
    source_point_count: int
    target_point_count: int
    source_sample_count: int
    target_sample_count: int
    candidates_considered: int
    candidates_refined: int
    iterations: int
    elapsed_seconds: float
    budget_exhausted: bool
    candidate_margin: float | None
    candidate_findings: tuple[tuple[str, RegistrationFindingCode], ...]


@dataclass(frozen=True)
class ConstrainedICPResult:
    """Ranked floor-constrained refinements and a separate QA disposition."""

    state: RegistrationProposalState
    qa_status: RegistrationQAStatus
    candidates: tuple[RefinedRegistrationCandidate, ...]
    findings: tuple[RegistrationFindingCode, ...]
    diagnostics: ConstrainedICPDiagnostics


class _ICPFailureError(ValueError):
    def __init__(self, finding: RegistrationFindingCode) -> None:
        super().__init__(finding.value)
        self.finding = finding


def _validated_clouds(
    source_points: np.ndarray,
    target_points_world_m: np.ndarray,
    target_normals_world: np.ndarray,
    profile: RegistrationProfile,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    source = np.asarray(source_points, dtype=float)
    target = np.asarray(target_points_world_m, dtype=float)
    normals = np.asarray(target_normals_world, dtype=float)
    if source.ndim != 2 or source.shape[1] != 3 or target.ndim != 2 or target.shape[1] != 3:
        raise ValueError("ICP source and target points must have shape (N, 3)")
    if normals.shape != target.shape:
        raise ValueError("target normals must match the target point array")
    if len(source) == 0 or len(target) == 0:
        raise ValueError("ICP source and target surfaces must be nonempty")
    if len(source) > profile.max_source_points or len(target) > profile.max_source_points:
        raise ValueError("ICP input exceeds the frozen raw point budget")
    if not (np.isfinite(source).all() and np.isfinite(target).all() and np.isfinite(normals).all()):
        raise ValueError("ICP points and normals must contain only finite coordinates")
    normal_lengths = np.linalg.norm(normals, axis=1)
    if np.any(normal_lengths <= _MIN_NORMAL_NORM):
        raise ValueError("target normals must be nonzero vectors")
    return source, target, normals / normal_lengths[:, None]


def _sample_indices(count: int, limit: int, seed: int) -> np.ndarray:
    if count <= limit:
        return np.arange(count)
    selected = np.random.default_rng(seed).choice(count, size=limit, replace=False)
    return np.sort(selected)


def _voxel_sample(
    points: np.ndarray, voxel_size_m: float, normals: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray | None]:
    origin = np.median(points, axis=0)
    keys = np.floor((points - origin) / max(voxel_size_m, _MIN_VOXEL_SIZE_M)).astype(np.int64)
    _, indices = np.unique(keys, axis=0, return_index=True)
    indices.sort()
    return points[indices], None if normals is None else normals[indices]


def _transform_points(points: np.ndarray, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    return points @ rotation.T + translation


def _rotation_z(yaw: float) -> np.ndarray:
    cosine, sine = math.cos(yaw), math.sin(yaw)
    return np.array([[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]])


def _floor_transform(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    value = np.eye(4)
    value[:3, :3] = rotation
    value[:3, 3] = translation
    return value


def _rank_and_solve(
    transformed: np.ndarray,
    target_matches: np.ndarray,
    normals: np.ndarray,
    profile: RegistrationProfile,
) -> tuple[np.ndarray, int]:
    residuals = np.einsum("ij,ij->i", normals, transformed - target_matches)
    keep_count = min(
        len(residuals),
        max(profile.icp_min_correspondences, int(math.floor(len(residuals) * profile.icp_trim_fraction))),
    )
    keep = np.argsort(np.abs(residuals), kind="stable")[:keep_count]
    q = transformed[keep]
    n = normals[keep]
    r = residuals[keep]

    median = float(np.median(np.abs(r)))
    mad = float(np.median(np.abs(np.abs(r) - median)))
    robust_delta = max(_MIN_ROBUST_DELTA_M, 1.345 * 1.4826 * mad)
    weights = np.minimum(1.0, robust_delta / np.maximum(np.abs(r), 1e-12))

    pivot = np.median(q[:, :2], axis=0)
    relative = q[:, :2] - pivot
    jacobian = np.column_stack((-n[:, 0] * relative[:, 1] + n[:, 1] * relative[:, 0], n[:, 0], n[:, 1]))
    characteristic_radius = max(float(np.median(np.linalg.norm(relative, axis=1))), _MIN_VOXEL_SIZE_M)
    normalized = jacobian.copy()
    normalized[:, 0] /= characteristic_radius
    weighted_normalized = normalized * np.sqrt(weights[:, None])
    singular = np.linalg.svd(weighted_normalized, compute_uv=False)
    rank = int(np.count_nonzero(singular > singular[0] * profile.icp_min_singular_ratio)) if singular.size else 0
    required_rank = profile.minimum_observable_dof
    if rank < required_rank:
        raise _ICPFailureError(RegistrationFindingCode.UNOBSERVABLE)

    weighted_jacobian = jacobian * np.sqrt(weights[:, None])
    update, _, solve_rank, _ = np.linalg.lstsq(weighted_jacobian, -r * np.sqrt(weights), rcond=None)
    if solve_rank < 3 or not np.isfinite(update).all():
        raise _ICPFailureError(RegistrationFindingCode.UNOBSERVABLE)
    return update, rank


def _apply_update(
    rotation: np.ndarray,
    translation: np.ndarray,
    pivot_xy: np.ndarray,
    update: np.ndarray,
    profile: RegistrationProfile,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    yaw = float(np.clip(update[0], -profile.icp_max_yaw_step_rad, profile.icp_max_yaw_step_rad))
    dx, dy = np.clip(update[1:], -profile.icp_max_translation_step_m, profile.icp_max_translation_step_m)
    delta_rotation = _rotation_z(yaw)
    pivot = np.array([pivot_xy[0], pivot_xy[1], translation[2]])
    delta_translation = np.array([dx, dy, 0.0])
    next_translation = pivot + delta_rotation @ (translation - pivot) + delta_translation
    return delta_rotation @ rotation, next_translation, math.hypot(float(dx), float(dy)), abs(yaw)


def _refine_one(
    candidate: CoarseRegistrationCandidate,
    source: np.ndarray,
    target_floor_points: np.ndarray,
    target_floor_normals: np.ndarray,
    target_floor_from_world: np.ndarray,
    profile: RegistrationProfile,
    deadline: float,
) -> RefinedRegistrationCandidate:
    scale = candidate.rgb_scale_factor if candidate.rgb_scale_factor is not None else 1.0
    if candidate.rgb_scale_factor is not None:
        bounds = profile.rgb_scale_factor_bounds
        if profile.scale_policy != "bounded_rgb_scale_search" or bounds is None or not bounds[0] <= scale <= bounds[1]:
            raise _ICPFailureError(RegistrationFindingCode.METRIC_CONFIRMATION_REQUIRED)

    target_points = target_floor_points * scale
    target_normals = target_floor_normals

    world_from_source = _floor_transform(
        rotation_matrix(candidate.transform_target_from_source.rotation_quaternion_xyzw),
        np.asarray(candidate.transform_target_from_source.translation_xyz, dtype=float),
    )
    floor_from_source = target_floor_from_world @ world_from_source
    rotation, translation = floor_from_source[:3, :3], floor_from_source[:3, 3]
    source_samples, _ = _voxel_sample(source, profile.icp_voxel_sizes_m[-1])
    initial_transformed = _transform_points(source_samples, rotation, translation)
    pivot_xy = np.median(initial_transformed[:, :2], axis=0)
    tree_cache: list[tuple[np.ndarray, np.ndarray, np.ndarray, cKDTree]] = []
    for voxel_size in profile.icp_voxel_sizes_m:
        source_level, _ = _voxel_sample(source, voxel_size)
        target_level, normal_level = _voxel_sample(target_points, voxel_size, target_normals)
        if normal_level is None:
            raise RuntimeError("target normal sampling unexpectedly failed")
        source_indices = _sample_indices(len(source_level), profile.max_refinement_points, profile.search_seed)
        target_indices = _sample_indices(
            len(target_level), profile.max_refinement_points, profile.search_seed ^ 0x9E3779B9
        )
        source_level = source_level[source_indices]
        target_level = target_level[target_indices]
        normal_level = normal_level[target_indices]
        if len(source_level) < profile.icp_min_correspondences or len(target_level) < profile.icp_min_correspondences:
            raise _ICPFailureError(RegistrationFindingCode.LOW_COVERAGE)
        tree_cache.append((source_level, target_level, normal_level, cKDTree(target_level)))

    iterations = 0
    converged_levels = 0
    observable_dof = 0
    for source_level, target_level, normal_level, tree in tree_cache:
        level_converged = False
        for _ in range(profile.icp_iterations):
            if time.monotonic() >= deadline:
                raise _ICPFailureError(RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED)
            transformed = _transform_points(source_level, rotation, translation)
            distances, indices = tree.query(
                transformed,
                k=1,
                distance_upper_bound=profile.icp_max_correspondence_distance_m,
                workers=1,
            )
            valid = np.isfinite(distances) & (indices < len(target_level))
            if np.count_nonzero(valid) < profile.icp_min_correspondences:
                raise _ICPFailureError(RegistrationFindingCode.LOW_COVERAGE)
            matches = transformed[valid]
            target_matches = target_level[indices[valid]]
            normals = normal_level[indices[valid]]
            update, observable_dof = _rank_and_solve(matches, target_matches, normals, profile)
            rotation, translation, translation_step, yaw_step = _apply_update(
                rotation, translation, pivot_xy, update, profile
            )
            iterations += 1
            if (
                translation_step <= profile.icp_convergence_translation_m
                and yaw_step <= profile.icp_convergence_yaw_rad
            ):
                level_converged = True
                break
        converged_levels += int(level_converged)
    converged = converged_levels == len(tree_cache)

    source_metric_points, _ = _voxel_sample(source, profile.icp_voxel_sizes_m[-1])
    target_metric_points, target_metric_normals = _voxel_sample(
        target_points, profile.icp_voxel_sizes_m[-1], target_normals
    )
    if target_metric_normals is None:
        raise RuntimeError("final target normal sampling unexpectedly failed")
    final_transform = _transform_points(source_metric_points, rotation, translation)
    tree = cKDTree(target_metric_points, compact_nodes=True, balanced_tree=True)
    correspondence_distances, indices = tree.query(
        final_transform,
        k=1,
        distance_upper_bound=profile.icp_max_correspondence_distance_m,
        workers=1,
    )
    valid = np.isfinite(correspondence_distances) & (indices < len(target_metric_points))
    if np.count_nonzero(valid) < profile.icp_min_correspondences:
        raise _ICPFailureError(RegistrationFindingCode.LOW_COVERAGE)
    matched_source_indices = np.flatnonzero(valid)
    matched_target_indices = indices[valid]
    residuals = np.abs(
        np.einsum(
            "ij,ij->i",
            target_metric_normals[matched_target_indices],
            final_transform[matched_source_indices] - target_metric_points[matched_target_indices],
        )
    )
    keep_count = min(
        len(residuals),
        max(profile.icp_min_correspondences, int(math.floor(len(residuals) * profile.icp_trim_fraction))),
    )
    retained = np.argsort(residuals, kind="stable")[:keep_count]
    retained_source = matched_source_indices[retained]
    retained_target = matched_target_indices[retained]
    retained_residuals = residuals[retained]
    source_coverage = len(np.unique(retained_source)) / len(source_metric_points)
    target_coverage = len(np.unique(retained_target)) / len(target_metric_points)
    support = min(len(np.unique(retained_source)), len(np.unique(retained_target)))
    overlap = support / max(1, len(source_metric_points) + len(target_metric_points) - support)

    source_distances, _ = tree.query(final_transform, k=1, workers=1)
    reverse_tree = cKDTree(final_transform, compact_nodes=True, balanced_tree=True)
    reverse_distances, _ = reverse_tree.query(target_metric_points, k=1, workers=1)
    bidirectional_p95 = max(float(np.quantile(source_distances, 0.95)), float(np.quantile(reverse_distances, 0.95)))
    bidirectional_max = max(float(np.max(source_distances)), float(np.max(reverse_distances)))
    point_to_plane_p95 = float(np.quantile(retained_residuals, 0.95))
    coverage_score = (
        2 * source_coverage * target_coverage / (source_coverage + target_coverage)
        if source_coverage + target_coverage
        else 0.0
    )
    residual_score = math.exp(-bidirectional_p95 / profile.maximum_bidirectional_p95_residual_m)
    score = float(np.clip(coverage_score * residual_score, 0.0, 1.0))

    region_metrics = _region_metrics(
        source_metric_points,
        final_transform,
        target_metric_points,
        retained_source,
        retained_target,
        retained_residuals,
    )
    world_from_source = np.linalg.inv(target_floor_from_world) @ _floor_transform(rotation, translation)
    refined_transform = Transform(
        parent_frame="world",
        local_frame=candidate.transform_target_from_source.local_frame,
        translation_xyz=tuple(float(value) for value in world_from_source[:3, 3]),
        rotation_quaternion_xyzw=_quaternion(world_from_source[:3, :3]),
    )
    return RefinedRegistrationCandidate(
        candidate=RegistrationCandidate(
            candidate_id=candidate.candidate_id,
            transform_target_from_source=refined_transform,
            score=score,
            rgb_scale_factor=candidate.rgb_scale_factor,
        ),
        coarse_score=candidate.score,
        source_coverage_ratio=float(source_coverage),
        target_coverage_ratio=float(target_coverage),
        overlap_ratio=float(overlap),
        correspondence_count=int(keep_count),
        rejected_correspondence_count=int(len(source_metric_points) - keep_count),
        observable_dof=observable_dof,
        point_to_plane_p95_residual_m=point_to_plane_p95,
        bidirectional_p95_residual_m=bidirectional_p95,
        bidirectional_max_residual_m=bidirectional_max,
        iterations=iterations,
        converged=converged,
        regions=region_metrics,
    )


def _region_metrics(
    source_points: np.ndarray,
    transformed_source: np.ndarray,
    target_points: np.ndarray,
    matched_source_indices: np.ndarray,
    matched_target_indices: np.ndarray,
    residuals: np.ndarray,
) -> tuple[RegistrationRegionMetric, ...]:
    median_xy = np.median(target_points[:, :2], axis=0)
    target_regions = np.column_stack((target_points[:, 0] >= median_xy[0], target_points[:, 1] >= median_xy[1]))
    source_tree = cKDTree(target_points, compact_nodes=True, balanced_tree=True)
    _, nearest_target = source_tree.query(transformed_source, k=1, workers=1)
    source_regions = target_regions[nearest_target]
    if len(source_regions) != len(source_points):
        raise RuntimeError("region attribution lost source point correspondence")
    metrics: list[RegistrationRegionMetric] = []
    for x_high in (False, True):
        for y_high in (False, True):
            region = (target_regions[:, 0] == x_high) & (target_regions[:, 1] == y_high)
            source_region = (source_regions[:, 0] == x_high) & (source_regions[:, 1] == y_high)
            matched_region = (target_regions[matched_target_indices, 0] == x_high) & (
                target_regions[matched_target_indices, 1] == y_high
            )
            if not np.any(region) and not np.any(source_region):
                continue
            matched_source_region = matched_source_indices[matched_region]
            matched_target_region = matched_target_indices[matched_region]
            residual_region = residuals[matched_region]
            metrics.append(
                RegistrationRegionMetric(
                    region_id=f"floor-q-{int(x_high)}-{int(y_high)}",
                    source_coverage_ratio=(
                        len(np.unique(matched_source_region)) / np.count_nonzero(source_region)
                        if np.any(source_region)
                        else 0.0
                    ),
                    target_coverage_ratio=(
                        len(np.unique(matched_target_region)) / np.count_nonzero(region) if np.any(region) else 0.0
                    ),
                    correspondence_count=int(np.count_nonzero(matched_region)),
                    p95_residual_m=(float(np.quantile(residual_region, 0.95)) if len(residual_region) else None),
                )
            )
    return tuple(metrics)


def refine_registration_candidates(
    coarse_result: CoarseRegistrationSearchResult,
    source_points_metric_m: np.ndarray,
    target_collision_surface_points_world_m: np.ndarray,
    target_normals_world: np.ndarray,
    *,
    source_frame: str,
    target_floor: RegistrationFloorPlane,
    profile: RegistrationProfile,
) -> ConstrainedICPResult:
    """Refine metric S2 points in floor-local yaw/x/y only; never unlocks other axes.

    A visually plausible fit is not an absolute accuracy result. Provisional profiles
    always produce INCONCLUSIVE QA until a separate held-out qualification record exists.
    The source map must already be converted to meters by the S2 input binding.
    """
    started = time.monotonic()
    if profile.checksum() != profile.profile_checksum:
        raise ValueError("registration search profile checksum mismatch")
    if target_floor.frame != "world":
        raise ValueError("target floor evidence must use canonical world coordinates")
    if not source_frame or source_frame == "world":
        raise ValueError("ICP source frame must be explicit and distinct from world")
    candidate_ids = [candidate.candidate_id for candidate in coarse_result.candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("coarse candidates must have unique IDs")
    if any(
        candidate.transform_target_from_source.local_frame != source_frame for candidate in coarse_result.candidates
    ):
        raise ValueError("coarse candidate source frame does not match the supplied point cloud")
    source, target_world, normals_world = _validated_clouds(
        source_points_metric_m, target_collision_surface_points_world_m, target_normals_world, profile
    )
    source_indices = _sample_indices(len(source), profile.max_refinement_points, profile.search_seed ^ 0xA511E9B3)
    target_indices = _sample_indices(len(target_world), profile.max_refinement_points, profile.search_seed ^ 0x63D83595)
    source = source[source_indices]
    target_world = target_world[target_indices]
    normals_world = normals_world[target_indices]

    floor_from_world = target_floor.frame_to_floor_matrix()
    target_floor_points = target_world @ floor_from_world[:3, :3].T + floor_from_world[:3, 3]
    target_floor_normals = normals_world @ floor_from_world[:3, :3].T
    target_floor_normals /= np.linalg.norm(target_floor_normals, axis=1)[:, None]

    candidate_findings: list[tuple[str, RegistrationFindingCode]] = []
    refined: list[RefinedRegistrationCandidate] = []
    iterations = 0
    budget_exhausted = False
    deadline = started + profile.runtime_budget_seconds
    candidates_to_refine = coarse_result.candidates[: profile.top_k_candidates]
    if coarse_result.state in {RegistrationProposalState.FAILED, RegistrationProposalState.INSUFFICIENT}:
        candidates_to_refine = ()
    for candidate in candidates_to_refine:
        if time.monotonic() >= deadline:
            budget_exhausted = True
            candidate_findings.append((candidate.candidate_id, RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED))
            break
        try:
            item = _refine_one(
                candidate,
                source,
                target_floor_points,
                target_floor_normals,
                floor_from_world,
                profile,
                deadline,
            )
            refined.append(item)
            iterations += item.iterations
        except _ICPFailureError as error:
            candidate_findings.append((candidate.candidate_id, error.finding))
            if error.finding == RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED:
                budget_exhausted = True
                break

    refined.sort(key=lambda item: (-item.candidate.score, -item.overlap_ratio, item.candidate.candidate_id))
    margin = refined[0].candidate.score - refined[1].candidate.score if len(refined) > 1 else None
    findings: list[RegistrationFindingCode] = []
    if budget_exhausted:
        findings.append(RegistrationFindingCode.SEARCH_BUDGET_EXCEEDED)
        state = RegistrationProposalState.INSUFFICIENT
        qa_status = RegistrationQAStatus.INCONCLUSIVE
    elif not refined:
        findings.extend(dict.fromkeys(code for _, code in candidate_findings))
        if not findings:
            findings.extend(coarse_result.findings or (RegistrationFindingCode.UNOBSERVABLE,))
        state = RegistrationProposalState.INSUFFICIENT
        qa_status = RegistrationQAStatus.INCONCLUSIVE
    else:
        best = refined[0]
        if (
            best.source_coverage_ratio < profile.minimum_source_coverage_ratio
            or best.target_coverage_ratio < profile.minimum_target_coverage_ratio
            or best.overlap_ratio < profile.minimum_overlap_ratio
            or any(
                region.source_coverage_ratio < profile.minimum_source_coverage_ratio
                or region.target_coverage_ratio < profile.minimum_target_coverage_ratio
                for region in best.regions
            )
        ):
            findings.append(RegistrationFindingCode.LOW_COVERAGE)
        if best.bidirectional_p95_residual_m > profile.maximum_bidirectional_p95_residual_m or any(
            region.p95_residual_m is not None and region.p95_residual_m > profile.maximum_bidirectional_p95_residual_m
            for region in best.regions
        ):
            findings.append(RegistrationFindingCode.HIGH_RESIDUAL)
        unresolved_coarse_ambiguity = coarse_result.state == RegistrationProposalState.AMBIGUOUS and (
            margin is None or margin < profile.minimum_candidate_margin
        )
        if unresolved_coarse_ambiguity or (margin is not None and margin < profile.minimum_candidate_margin):
            findings.append(RegistrationFindingCode.AMBIGUOUS_CANDIDATES)
        if findings and any(
            finding in {RegistrationFindingCode.LOW_COVERAGE, RegistrationFindingCode.HIGH_RESIDUAL}
            for finding in findings
        ):
            state = RegistrationProposalState.INSUFFICIENT
            qa_status = RegistrationQAStatus.FAIL
        elif RegistrationFindingCode.AMBIGUOUS_CANDIDATES in findings:
            state = RegistrationProposalState.AMBIGUOUS
            qa_status = RegistrationQAStatus.INCONCLUSIVE
        else:
            state = RegistrationProposalState.PROPOSED
            if not best.converged:
                qa_status = RegistrationQAStatus.INCONCLUSIVE
                findings.append(RegistrationFindingCode.ICP_NOT_CONVERGED)
            elif profile.qualification_state == "qualified":
                qa_status = RegistrationQAStatus.PASS
            else:
                qa_status = RegistrationQAStatus.INCONCLUSIVE
                findings.append(RegistrationFindingCode.UNQUALIFIED_PROFILE)

    diagnostics = ConstrainedICPDiagnostics(
        profile_checksum=profile.profile_checksum,
        source_point_count=len(source_points_metric_m),
        target_point_count=len(target_collision_surface_points_world_m),
        source_sample_count=len(source),
        target_sample_count=len(target_world),
        candidates_considered=len(candidates_to_refine),
        candidates_refined=len(refined),
        iterations=iterations,
        elapsed_seconds=max(0.0, time.monotonic() - started),
        budget_exhausted=budget_exhausted,
        candidate_margin=margin,
        candidate_findings=tuple(candidate_findings),
    )
    return ConstrainedICPResult(
        state=state,
        qa_status=qa_status,
        candidates=tuple(refined),
        findings=tuple(dict.fromkeys(findings)),
        diagnostics=diagnostics,
    )
