"""NumPy-only refinement shared by the worker and isolated lifting runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.models.contracts.floor_model import FloorModel


def object_point_mask(points: np.ndarray, floor: FloorModel) -> np.ndarray:
    """Allow positive near-plane evidence only outside the measured noise interval.

    This does not certify ownership. The caller must supply repeated object-mask support;
    Gaussian shape is checked separately before final membership publication.
    """
    keep = np.zeros(len(points), dtype=bool)
    if floor.status not in {"supported", "confirmed_prior_fallback"} or floor.plane_normal_world is None:
        return keep
    # A prior fallback has no measured noise: retain the existing protected band.
    limit = (
        floor.robust_noise_sigma_m * floor.profile.noise_sigma_multiplier
        if floor.status == "supported" and floor.robust_noise_sigma_m is not None
        else floor.floor_band_m
    )
    if limit is None or floor.plane_offset_m is None:
        return keep
    distance = points @ np.asarray(floor.plane_normal_world) + floor.plane_offset_m
    return np.isfinite(points).all(axis=1) & (distance > max(0.0, limit))


def exclusive_mask_labels(accepted: list[tuple[int, np.ndarray]], shape: tuple[int, int]) -> np.ndarray:
    """Conflicting object masks abstain (-2); area ordering is not ownership evidence."""
    labels = np.full(shape, -1, dtype=np.int32)
    for owner, mask in accepted:
        conflict = mask & (labels != -1) & (labels != owner)
        labels[mask & (labels == -1)] = owner
        labels[conflict] = -2
    return labels


def refine_owners(share: np.ndarray, seeds: list[np.ndarray], majority: float) -> np.ndarray:
    """Keep exclusive multiview seeds; abstain on non-seed score ties."""
    best = share.argmax(axis=1)
    score = share.max(axis=1)
    tied = (share == score[:, None]).sum(axis=1) != 1
    labels = np.where((score > majority) & ~tied & np.isfinite(score), best, -1).astype(np.int32)
    owner = np.full(len(share), -1, dtype=np.int32)
    for index, members in enumerate(seeds):
        if np.any(owner[members] >= 0):
            raise ValueError("refinement requires exclusive seed ownership")
        owner[members] = index
    anchored = owner >= 0
    labels[anchored] = owner[anchored]
    return labels
