"""ADR 0006 fallback: khối cỡ vật thể trên sàn thành ứng viên, khối lớn (tường/kệ) để lại."""

import math

import numpy as np

from src.services.scene.geometric import find_candidates


def _box_surface(
    center: tuple[float, float, float], size: tuple[float, float, float], step: float = 0.05
) -> np.ndarray:
    axes = [np.arange(c - s / 2, c + s / 2 + 1e-9, step) for c, s in zip(center, size, strict=True)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    low = np.array(center) - np.array(size) / 2
    high = np.array(center) + np.array(size) / 2
    on_face = np.any(np.isclose(grid, low, atol=step / 2) | np.isclose(grid, high, atol=step / 2), axis=1)
    return grid[on_face]


def test_pallet_sized_block_becomes_candidate_and_wall_does_not() -> None:
    floor = _box_surface((0.0, 0.0, 0.0), (12.0, 12.0, 0.02), step=0.2)
    pallet = _box_surface((2.0, 2.0, 0.6), (1.2, 0.8, 1.0))
    wall = _box_surface((-4.0, 0.0, 1.5), (0.2, 10.0, 3.0))
    found = find_candidates(np.vstack([floor, pallet, wall]))
    assert len(found) == 1
    candidate = found[0]
    assert math.dist(candidate.center[:2], (2.0, 2.0)) < 0.15
    # Lượng tử voxel 0,1 m: kích thước hộp nằm trong [thật, thật + 0,25 m].
    short, long = sorted(candidate.dimensions[:2])
    assert 0.8 <= short <= 1.05 and 1.2 <= long <= 1.45
    assert 0.9 <= candidate.dimensions[2] <= 1.2


def test_empty_scene_has_no_candidates() -> None:
    assert find_candidates(np.zeros((0, 3))) == []
