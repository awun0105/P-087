"""ADR 0006 fallback: khối cỡ vật thể trên sàn thành ứng viên, khối lớn (tường/kệ) để lại."""

import math

import numpy as np

from src.models.contracts.floor_model import FloorModel
from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum
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


def _floor_model(points: np.ndarray) -> FloorModel:
    return fit_canonical_floor_model(points, point_cloud_checksum(points))


def test_pallet_sized_block_becomes_candidate_and_wall_does_not() -> None:
    floor = _box_surface((0.0, 0.0, 0.0), (12.0, 12.0, 0.02), step=0.2)
    pallet = _box_surface((2.0, 2.0, 0.6), (1.2, 0.8, 1.0))
    wall = _box_surface((-4.0, 0.0, 1.5), (0.2, 10.0, 3.0))
    vertices = np.vstack([floor, pallet, wall])
    found = find_candidates(vertices, _floor_model(vertices))
    assert len(found) == 1
    candidate = found[0]
    assert math.dist(candidate.center[:2], (2.0, 2.0)) < 0.15
    # Lượng tử voxel 0,1 m: kích thước hộp nằm trong [thật, thật + 0,25 m].
    short, long = sorted(candidate.dimensions[:2])
    assert 0.8 <= short <= 1.05 and 1.2 <= long <= 1.45
    assert 0.9 <= candidate.dimensions[2] <= 1.2


def test_empty_scene_has_no_candidates() -> None:
    vertices = np.zeros((0, 3))
    assert find_candidates(vertices, _floor_model(vertices)) == []


def test_candidate_filter_follows_sloped_floor_and_keeps_low_obstacle() -> None:
    rng = np.random.default_rng(8)
    floor_xy = rng.uniform([-2.0, -2.0], [2.0, 2.0], size=(1200, 2))
    floor = np.column_stack([floor_xy, 0.12 * floor_xy[:, 0]])
    x = rng.uniform(0.8, 1.2, size=500)
    y = rng.uniform(-0.2, 0.2, size=500)
    base = 0.12 * x
    low_obstacle = np.column_stack([x, y, base + rng.uniform(0.15, 0.3, size=len(x))])
    vertices = np.vstack([floor, low_obstacle])

    found = find_candidates(vertices, _floor_model(vertices))

    assert len(found) == 1
    assert found[0].dimensions[2] < 0.5
