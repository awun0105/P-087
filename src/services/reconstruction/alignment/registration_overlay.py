"""Build deterministic, bounded BEV previews from exact registration evidence."""

from __future__ import annotations

from itertools import product

import numpy as np

from src.models.contracts.rgb_lidar_registration import (
    RegistrationCandidate,
    RegistrationOverlayPreview,
    RegistrationProposal,
    RegistrationRequest,
    seal_registration_overlay_preview,
    validate_registration_overlay_binding,
    validate_registration_proposal_binding,
)
from src.services.reconstruction.alignment.bev_search import RegistrationFloorPlane
from src.services.reconstruction.alignment.similarity import rotation_matrix

_PREVIEW_SAMPLE_CAP = 512
_PROJECTION_CHUNK_SIZE = 65_536


def _transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def _inside_roi(points: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.all((points >= low) & (points <= high), axis=1)


def _sample_xy(points: np.ndarray) -> list[tuple[float, float]]:
    if not len(points):
        return []
    indices = np.linspace(0, len(points) - 1, min(len(points), _PREVIEW_SAMPLE_CAP), dtype=np.int64)
    return [(float(x), float(y)) for x, y in points[indices, :2]]


def _project_roi_samples(
    points: np.ndarray,
    points_to_floor: np.ndarray,
    roi_min: np.ndarray,
    roi_max: np.ndarray,
    *,
    scale: float = 1.0,
) -> tuple[int, np.ndarray]:
    """Count ROI points and collect deterministic samples using bounded working memory."""
    count = 0
    for start in range(0, len(points), _PROJECTION_CHUNK_SIZE):
        chunk = np.asarray(points[start : start + _PROJECTION_CHUNK_SIZE], dtype=float)
        floor_points = _transform_points(chunk, points_to_floor)
        if scale != 1.0:
            floor_points *= scale
        count += int(np.count_nonzero(_inside_roi(floor_points, roi_min, roi_max)))

    if count == 0:
        return 0, np.empty((0, 3), dtype=float)
    sample_indices = np.linspace(0, count - 1, min(count, _PREVIEW_SAMPLE_CAP), dtype=np.int64)
    selected: list[np.ndarray] = []
    cursor = 0
    for start in range(0, len(points), _PROJECTION_CHUNK_SIZE):
        chunk = np.asarray(points[start : start + _PROJECTION_CHUNK_SIZE], dtype=float)
        floor_points = _transform_points(chunk, points_to_floor)
        if scale != 1.0:
            floor_points *= scale
        in_roi = floor_points[_inside_roi(floor_points, roi_min, roi_max)]
        next_cursor = cursor + len(in_roi)
        local_indices = sample_indices[(sample_indices >= cursor) & (sample_indices < next_cursor)] - cursor
        if len(local_indices):
            selected.extend(in_roi[local_indices])
        cursor = next_cursor
    return count, np.asarray(selected, dtype=float)


def build_registration_overlay_preview(
    request: RegistrationRequest,
    proposal: RegistrationProposal,
    candidate: RegistrationCandidate,
    operation_id: str,
    source_points_m: np.ndarray,
    target_points_world_m: np.ndarray,
    target_floor: RegistrationFloorPlane,
) -> RegistrationOverlayPreview:
    """Project one exact candidate and target into a capped world-XY inspection view."""
    validate_source = np.asarray(source_points_m)
    validate_target = np.asarray(target_points_world_m)
    roi = request.target_roi_world
    if roi is None:
        raise ValueError("registration overlay requires the sealed target ROI")
    if (
        validate_source.ndim != 2
        or validate_source.shape[1] != 3
        or not len(validate_source)
        or len(validate_source) > request.profile.max_source_points
        or not (np.issubdtype(validate_source.dtype, np.floating) or np.issubdtype(validate_source.dtype, np.integer))
        or not np.isfinite(validate_source).all()
    ):
        raise ValueError("registration overlay source points are invalid or over budget")
    if (
        validate_target.ndim != 2
        or validate_target.shape[1] != 3
        or not len(validate_target)
        or len(validate_target) > request.profile.max_points_per_map
        or not (np.issubdtype(validate_target.dtype, np.floating) or np.issubdtype(validate_target.dtype, np.integer))
        or not np.isfinite(validate_target).all()
    ):
        raise ValueError("registration overlay target points are invalid or over budget")
    validate_registration_proposal_binding(request, proposal)
    if (
        candidate not in proposal.candidates
        or not operation_id
        or target_floor.evidence_checksum not in {ref.artifact_checksum for ref in request.floor_evidence_refs}
    ):
        raise ValueError("registration overlay requires an exact proposal candidate and target-floor evidence")

    world_from_source = np.eye(4, dtype=float)
    world_from_source[:3, :3] = rotation_matrix(candidate.transform_target_from_source.rotation_quaternion_xyzw)
    world_from_source[:3, 3] = np.asarray(candidate.transform_target_from_source.translation_xyz, dtype=float)
    floor_from_world = target_floor.frame_to_floor_matrix()
    world_from_floor = np.linalg.inv(floor_from_world)
    source_to_floor = floor_from_world @ world_from_source
    scale = candidate.rgb_scale_factor if candidate.rgb_scale_factor is not None else 1.0
    roi_corners_world = np.asarray(
        list(
            product(
                (roi.min_xyz_m[0], roi.max_xyz_m[0]),
                (roi.min_xyz_m[1], roi.max_xyz_m[1]),
                (roi.min_xyz_m[2], roi.max_xyz_m[2]),
            )
        ),
        dtype=float,
    )
    roi_floor = _transform_points(roi_corners_world, floor_from_world) * scale
    roi_min = roi_floor.min(axis=0)
    roi_max = roi_floor.max(axis=0)

    source_count, source_samples_floor = _project_roi_samples(
        validate_source,
        source_to_floor,
        roi_min,
        roi_max,
    )
    target_count, target_samples_floor = _project_roi_samples(
        validate_target,
        floor_from_world,
        roi_min,
        roi_max,
        scale=scale,
    )
    source_samples_world = _transform_points(source_samples_floor, world_from_floor)
    target_samples_world = _transform_points(target_samples_floor, world_from_floor)
    preview_roi_world = _transform_points(roi_floor, world_from_floor)
    bounds_min = tuple(float(value) for value in preview_roi_world[:, :2].min(axis=0))
    bounds_max = tuple(float(value) for value in preview_roi_world[:, :2].max(axis=0))
    preview = seal_registration_overlay_preview(
        {
            "job_id": request.target_job_id,
            "operation_id": operation_id,
            "input_mode": request.source.mode,
            "request_checksum": request.request_checksum,
            "source_input_checksum": request.source.source_input_checksum,
            "source_geometry_ref": proposal.source_geometry_ref,
            "target_rgb_geometry_ref": request.target_rgb_geometry_ref,
            "target_scene_revision": request.expected_scene_revision,
            "request_target_roi_world": roi,
            "target_floor_evidence_checksum": target_floor.evidence_checksum,
            "profile_checksum": request.profile_checksum,
            "candidate_id": candidate.candidate_id,
            "source_frame": proposal.source_frame,
            "transform_target_from_source": candidate.transform_target_from_source,
            "rgb_scale_factor": candidate.rgb_scale_factor,
            "bounds_min_xy_m": bounds_min,
            "bounds_max_xy_m": bounds_max,
            "source_in_roi_point_count": source_count,
            "target_in_roi_point_count": target_count,
            "source_points_xy_world_m": _sample_xy(source_samples_world),
            "target_points_xy_world_m": _sample_xy(target_samples_world),
            "sample_cap_per_cloud": _PREVIEW_SAMPLE_CAP,
            "sampling_method": "uniform_order_indices_v1",
            "diagnostic_only": True,
            "preview_checksum": "sha256:" + "0" * 64,
        }
    )
    validate_registration_overlay_binding(request, proposal, preview, operation_id)
    return preview
