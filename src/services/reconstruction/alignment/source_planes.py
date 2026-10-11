"""Bounded, diagnostic-only plane hypotheses for independent LiDAR maps.

The map contract does not declare gravity/up, so a geometric plane cannot safely be
called the floor. This module reports checksum-bound, unoriented hypotheses only;
it deliberately does not construct ``RegistrationFloorPlane`` or select a floor.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class SourcePlaneHypothesisProfile:
    """Fixed compute and support limits for diagnostic source-plane discovery."""

    distance_threshold_m: float = 0.03
    minimum_support_points: int = 100
    minimum_support_ratio: float = 0.01
    minimum_minor_span_m: float = 0.5
    maximum_points: int = 50_000
    ransac_iterations: int = 256
    maximum_hypotheses: int = 8
    random_seed: int = 19

    def __post_init__(self) -> None:
        if not math.isfinite(self.distance_threshold_m) or not 0.001 <= self.distance_threshold_m <= 0.25:
            raise ValueError("distance_threshold_m must be finite and between 0.001 and 0.25")
        if self.minimum_support_points < 3 or self.minimum_support_points > self.maximum_points:
            raise ValueError("minimum_support_points must fit the bounded point budget")
        if not math.isfinite(self.minimum_support_ratio) or not 0 < self.minimum_support_ratio <= 1:
            raise ValueError("minimum_support_ratio must be in (0, 1]")
        if not math.isfinite(self.minimum_minor_span_m) or not 0.1 <= self.minimum_minor_span_m <= 100:
            raise ValueError("minimum_minor_span_m must be finite and between 0.1 and 100")
        if not 3 <= self.maximum_points <= 50_000:
            raise ValueError("maximum_points must be between 3 and 50000")
        if not 1 <= self.ransac_iterations <= 512:
            raise ValueError("ransac_iterations must be between 1 and 512")
        if not 1 <= self.maximum_hypotheses <= 8:
            raise ValueError("maximum_hypotheses must be between 1 and 8")

    def checksum(self) -> str:
        return _checksum(asdict(self))


@dataclass(frozen=True)
class SourcePlaneHypothesis:
    """One supported plane in the declared source frame, without floor/up semantics."""

    candidate_id: str
    frame: str
    normal_xyz: tuple[float, float, float]
    offset_m: float
    support_points: int
    support_ratio: float
    median_residual_m: float
    p95_residual_m: float
    major_span_m: float
    minor_span_m: float
    evidence_checksum: str


@dataclass(frozen=True)
class SourcePlaneHypothesisReport:
    """Diagnostic result. ``hypotheses`` never means a floor was identified."""

    status: Literal["hypotheses", "insufficient"]
    reason: Literal[
        "orientation_unclassified",
        "invalid_source_checksum",
        "invalid_source_frame",
        "invalid_point_shape",
        "non_finite_points",
        "too_few_points",
        "no_supported_plane",
    ]
    source_checksum: str
    source_frame: str
    profile_checksum: str
    input_point_count: int
    sampled_point_count: int
    candidates: tuple[SourcePlaneHypothesis, ...]
    evidence_checksum: str


_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_METHOD_VERSION = "source-plane-hypotheses-ransac-v1"
_DUPLICATE_PLANE_ANGLE_RAD = math.radians(5.0)


def discover_source_plane_hypotheses(
    points_xyz_m: object,
    *,
    source_checksum: str,
    source_frame: str,
    profile: SourcePlaneHypothesisProfile = SourcePlaneHypothesisProfile(),
) -> SourcePlaneHypothesisReport:
    """Find a bounded set of broad planes without guessing which one is the floor.

    Points must already be decoded in meters from the exact source. The report binds
    the caller-supplied source checksum and profile, but does not independently read
    or verify source bytes. Invalid input and unsupported geometry return an explicit
    ``insufficient`` report rather than a partial floor claim.
    """
    profile_checksum = profile.checksum()
    try:
        raw_points = np.asarray(points_xyz_m, dtype=np.float64)
    except (OverflowError, TypeError, ValueError):
        raw_points = np.empty((0, 3), dtype=np.float64)
        return _report(
            status="insufficient",
            reason="invalid_point_shape",
            source_checksum=source_checksum,
            source_frame=source_frame,
            profile_checksum=profile_checksum,
            input_point_count=0,
            sampled_point_count=0,
            candidates=(),
        )

    input_count = len(raw_points) if raw_points.ndim else 0
    if not isinstance(source_checksum, str) or not _SHA256.fullmatch(source_checksum):
        reason: Literal["invalid_source_checksum"] = "invalid_source_checksum"
    elif not isinstance(source_frame, str) or not source_frame.strip() or source_frame == "world":
        reason = "invalid_source_frame"
    elif raw_points.ndim != 2 or raw_points.shape[1] != 3:
        reason = "invalid_point_shape"
    elif not np.isfinite(raw_points).all():
        reason = "non_finite_points"
    elif input_count < profile.minimum_support_points:
        reason = "too_few_points"
    else:
        reason = "orientation_unclassified"

    if reason != "orientation_unclassified":
        return _report(
            status="insufficient",
            reason=reason,
            source_checksum=source_checksum,
            source_frame=source_frame,
            profile_checksum=profile_checksum,
            input_point_count=input_count,
            sampled_point_count=0,
            candidates=(),
        )

    points = _bounded_sample(raw_points, profile)
    if len(points) < profile.minimum_support_points:
        return _report(
            status="insufficient",
            reason="too_few_points",
            source_checksum=source_checksum,
            source_frame=source_frame,
            profile_checksum=profile_checksum,
            input_point_count=input_count,
            sampled_point_count=len(points),
            candidates=(),
        )

    candidates = _ransac_hypotheses(points, source_checksum, source_frame, profile, profile_checksum)
    if not candidates:
        return _report(
            status="insufficient",
            reason="no_supported_plane",
            source_checksum=source_checksum,
            source_frame=source_frame,
            profile_checksum=profile_checksum,
            input_point_count=input_count,
            sampled_point_count=len(points),
            candidates=(),
        )
    return _report(
        status="hypotheses",
        reason="orientation_unclassified",
        source_checksum=source_checksum,
        source_frame=source_frame,
        profile_checksum=profile_checksum,
        input_point_count=input_count,
        sampled_point_count=len(points),
        candidates=tuple(candidates),
    )


def _bounded_sample(points: np.ndarray, profile: SourcePlaneHypothesisProfile) -> np.ndarray:
    if len(points) <= profile.maximum_points:
        return points
    indices = np.random.default_rng(profile.random_seed).choice(len(points), size=profile.maximum_points, replace=False)
    return points[np.sort(indices)]


def _ransac_hypotheses(
    points: np.ndarray,
    source_checksum: str,
    source_frame: str,
    profile: SourcePlaneHypothesisProfile,
    profile_checksum: str,
) -> list[SourcePlaneHypothesis]:
    remaining = points
    found: list[SourcePlaneHypothesis] = []
    for hypothesis_index in range(profile.maximum_hypotheses):
        if len(remaining) < profile.minimum_support_points:
            break
        rng = np.random.default_rng(profile.random_seed + hypothesis_index * 104_729)
        best_mask: np.ndarray | None = None
        best_count = 0
        for _ in range(profile.ransac_iterations):
            sample = remaining[rng.choice(len(remaining), size=3, replace=False)]
            normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
            norm = float(np.linalg.norm(normal))
            if norm <= 1e-10:
                continue
            normal = normal / norm
            offset = -float(np.dot(normal, sample[0]))
            mask = np.abs(remaining @ normal + offset) <= profile.distance_threshold_m
            count = int(mask.sum())
            if count > best_count:
                best_mask, best_count = mask, count

        if best_mask is None or best_count < profile.minimum_support_points:
            break
        refined = _refine_plane(remaining[best_mask], points, profile)
        # Discard even a narrow unsupported plane so bounded RANSAC does not rediscover it.
        remaining = remaining[~best_mask]
        if refined is None:
            continue
        normal, offset, inlier_mask, major_span, minor_span = refined
        support_count = int(inlier_mask.sum())
        support_ratio = support_count / len(points)
        if support_ratio < profile.minimum_support_ratio:
            continue
        residuals = np.abs(points[inlier_mask] @ normal + offset)
        if not len(residuals) or minor_span < profile.minimum_minor_span_m:
            continue
        if _duplicates_any(normal, offset, found):
            continue
        geometry = {
            "method": _METHOD_VERSION,
            "source_checksum": source_checksum,
            "source_frame": source_frame,
            "profile_checksum": profile_checksum,
            "normal_xyz": [float(value) for value in normal],
            "offset_m": float(offset),
            "support_points": support_count,
            "support_ratio": support_ratio,
            "median_residual_m": float(np.median(residuals)),
            "p95_residual_m": float(np.quantile(residuals, 0.95)),
            "major_span_m": major_span,
            "minor_span_m": minor_span,
        }
        evidence_checksum = _checksum(geometry)
        found.append(
            SourcePlaneHypothesis(
                candidate_id=f"plane-{evidence_checksum[7:19]}",
                frame=source_frame,
                normal_xyz=tuple(float(value) for value in normal),
                offset_m=float(offset),
                support_points=support_count,
                support_ratio=support_ratio,
                median_residual_m=float(np.median(residuals)),
                p95_residual_m=float(np.quantile(residuals, 0.95)),
                major_span_m=major_span,
                minor_span_m=minor_span,
                evidence_checksum=evidence_checksum,
            )
        )
        remaining = remaining[np.abs(remaining @ normal + offset) > profile.distance_threshold_m]

    return sorted(
        found, key=lambda candidate: (-candidate.support_points, -candidate.major_span_m, candidate.candidate_id)
    )


def _refine_plane(
    seed_inliers: np.ndarray, all_points: np.ndarray, profile: SourcePlaneHypothesisProfile
) -> tuple[np.ndarray, float, np.ndarray, float, float] | None:
    plane_points = seed_inliers
    normal: np.ndarray | None = None
    offset = 0.0
    inlier_mask = np.zeros(len(all_points), dtype=bool)
    axes = np.empty((0, 3), dtype=np.float64)
    for _ in range(2):
        if len(plane_points) < profile.minimum_support_points:
            return None
        centered = plane_points - plane_points.mean(axis=0)
        try:
            _, singular_values, vectors = np.linalg.svd(centered, full_matrices=False)
        except np.linalg.LinAlgError:
            return None
        if len(singular_values) < 2 or singular_values[0] <= 1e-10 or singular_values[1] <= 1e-8:
            return None
        axes = vectors
        normal = _canonical_normal(vectors[-1])
        offset = -float(np.dot(normal, plane_points.mean(axis=0)))
        inlier_mask = np.abs(all_points @ normal + offset) <= profile.distance_threshold_m
        plane_points = all_points[inlier_mask]

    if normal is None or len(plane_points) < profile.minimum_support_points:
        return None
    projected = (plane_points - plane_points.mean(axis=0)) @ axes[:2].T
    spans = np.quantile(projected, 0.95, axis=0) - np.quantile(projected, 0.05, axis=0)
    major_span, minor_span = sorted((float(spans[0]), float(spans[1])), reverse=True)
    return normal, offset, inlier_mask, major_span, minor_span


def _canonical_normal(normal: np.ndarray) -> np.ndarray:
    normalized = normal / np.linalg.norm(normal)
    first_nonzero = next((value for value in normalized if abs(value) > 1e-9), 1.0)
    return -normalized if first_nonzero < 0 else normalized


def _duplicates_any(normal: np.ndarray, offset: float, candidates: list[SourcePlaneHypothesis]) -> bool:
    for candidate in candidates:
        previous = np.asarray(candidate.normal_xyz, dtype=np.float64)
        alignment = float(np.dot(normal, previous))
        if abs(alignment) < math.cos(_DUPLICATE_PLANE_ANGLE_RAD):
            continue
        comparable_offset = candidate.offset_m if alignment >= 0 else -candidate.offset_m
        if abs(offset - comparable_offset) <= 0.06:
            return True
    return False


def _report(
    *,
    status: Literal["hypotheses", "insufficient"],
    reason: Literal[
        "orientation_unclassified",
        "invalid_source_checksum",
        "invalid_source_frame",
        "invalid_point_shape",
        "non_finite_points",
        "too_few_points",
        "no_supported_plane",
    ],
    source_checksum: str,
    source_frame: str,
    profile_checksum: str,
    input_point_count: int,
    sampled_point_count: int,
    candidates: tuple[SourcePlaneHypothesis, ...],
) -> SourcePlaneHypothesisReport:
    report_identity = {
        "method": _METHOD_VERSION,
        "status": status,
        "reason": reason,
        "source_checksum": source_checksum,
        "source_frame": source_frame,
        "profile_checksum": profile_checksum,
        "input_point_count": input_point_count,
        "sampled_point_count": sampled_point_count,
        "candidate_checksums": [candidate.evidence_checksum for candidate in candidates],
    }
    return SourcePlaneHypothesisReport(
        status=status,
        reason=reason,
        source_checksum=source_checksum,
        source_frame=source_frame,
        profile_checksum=profile_checksum,
        input_point_count=input_point_count,
        sampled_point_count=sampled_point_count,
        candidates=candidates,
        evidence_checksum=_checksum(report_identity),
    )


def _checksum(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
