"""Gaussian shell filters and parameter contract; voxel, QA and acceptance tests follow in later stages."""

import numpy as np
import pytest
import trimesh

from src.services.scene.gaussian_shell import (
    GaussianShellError,
    ShellParams,
    _body_diagonal_targets,
    _close_shell,
    _filter_gaussians,
    _keep_large_components,
    _planar_diagonal_targets,
    _repair_diagonals,
    _voxelize,
    build_gaussian_shell,
)


def uniform(rng, low, high, count):
    return rng.uniform(low, high, size=(count, 3))


def test_opacity_filter_drops_low_logit_gaussians():
    rng = np.random.default_rng(5)
    points = uniform(rng, [0.0, 0.0, 0.0], [0.4, 0.6, 0.8], 100)
    logit = np.where(np.arange(100) < 70, 5.0, -5.0)
    kept, opacity_dropped, _ = _filter_gaussians(points, logit, ShellParams())
    assert opacity_dropped == 30
    kept_rows = {tuple(row) for row in kept}
    assert not kept_rows & {tuple(row) for row in points[70:]}


def test_floaters_far_from_the_object_are_rejected():
    rng = np.random.default_rng(6)
    object_points = uniform(rng, [0.0, 0.0, 0.0], [0.4, 0.6, 0.8], 20000)
    floaters = uniform(rng, [1.0, 0.0, 0.0], [2.0, 1.0, 1.0], 200)
    kept, opacity_dropped, outliers_dropped = _filter_gaussians(
        np.vstack([object_points, floaters]), None, ShellParams()
    )
    assert opacity_dropped == 0
    assert outliers_dropped >= 150
    assert kept[:, 0].max() < 0.5


def test_too_few_gaussians_after_opacity_filter_fail_closed():
    rng = np.random.default_rng(7)
    points = uniform(rng, [0.0, 0.0, 0.0], [0.4, 0.6, 0.8], 60)
    logit = np.where(np.arange(60) < 40, 5.0, -5.0)
    with pytest.raises(GaussianShellError, match="too few Gaussians"):
        _filter_gaussians(points, logit, ShellParams())


def test_shell_params_reject_invalid_values():
    with pytest.raises(ValueError, match="voxel_m"):
        ShellParams(voxel_m=0.0)
    with pytest.raises(ValueError, match="min_component_fraction"):
        ShellParams(min_component_fraction=0.0)
    with pytest.raises(ValueError, match="max_cells_per_axis"):
        ShellParams(max_cells_per_axis=0)


def test_voxel_grid_fails_closed_over_budget():
    rng = np.random.default_rng(8)
    points = uniform(rng, [0.0, 0.0, 0.0], [0.4, 0.6, 0.8], 500)
    with pytest.raises(GaussianShellError, match="max_grid_cells"):
        _voxelize(points, 0.02, pad=3, max_grid_cells=1000)


def test_voxel_grid_pads_occupied_cells_and_reports_origin():
    points = np.array([[0.05, 0.05, 0.05], [0.25, 0.05, 0.05]])
    grid, origin, occupied = _voxelize(points, 0.1, pad=2, max_grid_cells=10_000)
    assert grid.shape == (7, 5, 5)
    assert origin.tolist() == [-2, -2, -2]
    assert occupied == 2
    assert grid[2, 2, 2] and grid[4, 2, 2]


def test_closing_fills_enclosed_cavities():
    grid = np.zeros((12, 12, 12), dtype=bool)
    grid[2:10, 2:10, 2:10] = True
    grid[4:8, 4:8, 4:8] = False
    closed, _, _ = _close_shell(grid, dilate_voxels=0, close_iterations=0)
    assert closed[6, 6, 6]


def test_closing_does_not_bridge_wide_gaps():
    grid = np.zeros((40, 8, 8), dtype=bool)
    grid[2:10, 2:6, 2:6] = True
    grid[20:28, 2:6, 2:6] = True
    closed, _, _ = _close_shell(grid, dilate_voxels=1, close_iterations=2)
    assert closed[5, 4, 4] and closed[25, 4, 4]
    assert not closed[15, 4, 4]


def test_small_fragments_are_dropped_and_large_components_kept():
    grid = np.zeros((30, 30, 30), dtype=bool)
    grid[2:12, 2:12, 2:12] = True
    grid[20:22, 20:22, 20:22] = True
    kept, kept_count, dropped = _keep_large_components(grid, 0.05)
    assert (kept_count, dropped) == (1, 1)
    assert kept[5, 5, 5] and not kept[20, 20, 20]


def test_two_separate_blocks_are_both_kept():
    grid = np.zeros((30, 10, 10), dtype=bool)
    grid[2:6, 2:6, 2:6] = True
    grid[20:24, 2:6, 2:6] = True
    _, kept_count, dropped = _keep_large_components(grid, 0.05)
    assert (kept_count, dropped) == (2, 0)


def test_no_component_above_fraction_fails_closed():
    grid = np.zeros((20, 20, 20), dtype=bool)
    grid[::4, ::4, ::4] = True
    with pytest.raises(GaussianShellError, match="min_component_fraction"):
        _keep_large_components(grid, 0.05)


VOXEL = 0.02
BOX_LOW = np.zeros(3)
BOX_HIGH = np.array([0.4, 0.6, 0.8])


def open_face_points(rng, low, high, count, axis, side):
    """Uniform by area on every face except (axis, side), as if the camera never saw that face."""
    size = high - low
    faces = [(a, s) for a in range(3) for s in range(2) if (a, s) != (axis, side)]
    areas = np.array([np.prod(np.delete(size, a)) for a, _ in faces])
    choice = rng.choice(len(faces), size=count, p=areas / areas.sum())
    points = np.empty((count, 3))
    for index, (a, s) in enumerate(faces):
        mask = choice == index
        coords = rng.uniform(low, high, size=(int(mask.sum()), 3))
        coords[:, a] = high[a] if s else low[a]
        points[mask] = coords
    return points


def sample_parts(rng, parts):
    """Uniform samples inside each (low, high) box, about 10^6 points per cubic metre."""
    return np.vstack([rng.uniform(low, high, size=(int(np.prod(high - low) * 1e6), 3)) for low, high in parts])


def chair_points(rng):
    """Seat plate and four 4 cm legs spaced 40 cm apart, sampled uniformly inside each part."""
    parts = [(np.array([-0.24, -0.24, 0.40]), np.array([0.24, 0.24, 0.44]))]
    for x in (-0.2, 0.2):
        for y in (-0.2, 0.2):
            parts.append((np.array([x - 0.02, y - 0.02, 0.0]), np.array([x + 0.02, y + 0.02, 0.40])))
    return sample_parts(rng, parts)


def table_points(rng):
    """Tabletop and four 4 cm legs 0.7 m tall, sampled uniformly inside each part."""
    parts = [(np.array([-0.4, -0.25, 0.70]), np.array([0.4, 0.25, 0.74]))]
    for x in (-0.36, 0.36):
        for y in (-0.2, 0.2):
            parts.append((np.array([x - 0.02, y - 0.02, 0.0]), np.array([x + 0.02, y + 0.02, 0.70])))
    return sample_parts(rng, parts)


def mesh_of(shell):
    return trimesh.Trimesh(shell.vertices, shell.faces, process=False)


def inside(mesh, point):
    """Parity of ray crossings from point; trimesh.contains needs rtree, which the venv does not provide."""
    direction = np.array([1.0, 0.37, 0.19])
    triangles = mesh.triangles
    e1 = triangles[:, 1] - triangles[:, 0]
    e2 = triangles[:, 2] - triangles[:, 0]
    h = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, h)
    valid = np.abs(det) > 1e-12
    inv = np.divide(1.0, det, out=np.zeros_like(det), where=valid)
    s = np.asarray(point, dtype=float) - triangles[:, 0]
    u = inv * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = inv * (q @ direction)
    t = inv * np.einsum("ij,ij->i", e2, q)
    hits = valid & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
    return bool(hits.sum() % 2)


def test_filled_box_gives_watertight_shell_that_passes_qa():
    rng = np.random.default_rng(11)
    shell = build_gaussian_shell(rng.uniform(BOX_LOW, BOX_HIGH, size=(20000, 3)), None)
    mesh = mesh_of(shell)
    assert mesh.is_watertight
    assert shell.quality["passed"]
    assert np.all(np.abs(mesh.bounds - [BOX_LOW, BOX_HIGH]) <= 2 * VOXEL)


def test_open_bottom_face_is_detected_as_open():
    rng = np.random.default_rng(12)
    shell = build_gaussian_shell(open_face_points(rng, BOX_LOW, BOX_HIGH, 20000, axis=2, side=0), None)
    assert mesh_of(shell).is_watertight
    assert shell.quality["passed"]
    assert "-z" in shell.statistics["capped_directions"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Open question Q4 in report.md: the reviewed rim-cap rule leaves wall through-holes open (volume ~58%)",
)
def test_open_bottom_scan_is_closed_watertight():
    rng = np.random.default_rng(12)
    shell = build_gaussian_shell(open_face_points(rng, BOX_LOW, BOX_HIGH, 20000, axis=2, side=0), None)
    mesh = mesh_of(shell)
    assert mesh.is_watertight
    assert shell.quality["passed"]
    assert mesh.volume >= 0.8 * np.prod(BOX_HIGH - BOX_LOW)


def test_box_missing_back_face_is_detected_as_capped():
    rng = np.random.default_rng(21)
    shell = build_gaussian_shell(open_face_points(rng, BOX_LOW, BOX_HIGH, 20000, axis=1, side=1), None)
    assert mesh_of(shell).is_watertight
    assert shell.quality["passed"]
    assert "+y" in shell.statistics["capped_directions"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Open question Q4 in report.md: the reviewed rim-cap rule leaves wall through-holes open (volume ~55%)",
)
def test_box_missing_back_face_is_capped():
    rng = np.random.default_rng(21)
    shell = build_gaussian_shell(open_face_points(rng, BOX_LOW, BOX_HIGH, 20000, axis=1, side=1), None)
    mesh = mesh_of(shell)
    assert mesh.is_watertight
    assert shell.quality["passed"]
    assert mesh.volume >= 0.8 * np.prod(BOX_HIGH - BOX_LOW)


def test_table_underside_stays_open():
    rng = np.random.default_rng(20)
    shell = build_gaussian_shell(table_points(rng), None)
    mesh = mesh_of(shell)
    assert shell.quality["passed"]
    assert "-z" not in shell.statistics["capped_directions"]
    assert not inside(mesh, [0.0, 0.0, 0.3])
    assert inside(mesh, [0.36, 0.2, 0.35]) and inside(mesh, [-0.36, -0.2, 0.35])
    assert inside(mesh, [0.0, 0.0, 0.72])


def test_cap_can_be_disabled():
    rng = np.random.default_rng(12)
    shell = build_gaussian_shell(
        open_face_points(rng, BOX_LOW, BOX_HIGH, 20000, axis=2, side=0), None, ShellParams(cap_open_faces=False)
    )
    assert shell.statistics["capped_directions"] == []
    assert 0.4 * np.prod(BOX_HIGH - BOX_LOW) < mesh_of(shell).volume < 0.6 * np.prod(BOX_HIGH - BOX_LOW)


def test_chair_leg_gaps_stay_open():
    rng = np.random.default_rng(13)
    shell = build_gaussian_shell(chair_points(rng), None)
    mesh = mesh_of(shell)
    assert shell.quality["passed"]
    assert not inside(mesh, [0.0, -0.2, 0.2])
    assert inside(mesh, [-0.2, -0.2, 0.2]) and inside(mesh, [0.2, 0.2, 0.2])


def test_floaters_are_rejected():
    rng = np.random.default_rng(14)
    obj = rng.uniform(BOX_LOW, BOX_HIGH, size=(20000, 3))
    floaters = rng.uniform([1.0, 0.0, 0.0], [2.0, 1.0, 1.0], size=(200, 3))
    shell = build_gaussian_shell(np.vstack([obj, floaters]), None)
    assert shell.statistics["outliers_dropped"] >= 150
    assert np.all(np.abs(mesh_of(shell).bounds - [BOX_LOW, BOX_HIGH]) <= 2 * VOXEL)


def test_low_opacity_gaussians_do_not_contribute():
    rng = np.random.default_rng(15)
    obj = rng.uniform(BOX_LOW, BOX_HIGH, size=(20000, 3))
    stray = rng.uniform([3.0, 0.0, 0.0], [4.0, 1.0, 1.0], size=(500, 3))
    logit = np.concatenate([np.full(len(obj), 5.0), np.full(len(stray), -5.0)])
    with_stray = build_gaussian_shell(np.vstack([obj, stray]), logit)
    alone = build_gaussian_shell(obj, None)
    assert with_stray.statistics["opacity_dropped"] == 500
    assert with_stray.checksum == alone.checksum
    np.testing.assert_array_equal(with_stray.vertices, alone.vertices)


def test_two_separate_blocks_keep_two_components():
    rng = np.random.default_rng(16)
    blocks = np.vstack(
        [
            rng.uniform([0.0, 0.0, 0.0], [0.2, 0.2, 0.2], size=(8000, 3)),
            rng.uniform([0.7, 0.0, 0.0], [0.9, 0.2, 0.2], size=(8000, 3)),  # 0.5 m apart
        ]
    )
    shell = build_gaussian_shell(blocks, None)
    assert shell.statistics["components_kept"] == 2
    assert mesh_of(shell).is_watertight
    assert shell.quality["passed"]


def test_invalid_inputs_fail_without_returning_a_mesh():
    rng = np.random.default_rng(17)
    points = rng.uniform(BOX_LOW, BOX_HIGH, size=(20000, 3))
    with pytest.raises(GaussianShellError, match="at least 50"):
        build_gaussian_shell(points[:49], None)
    nan_points = points.copy()
    nan_points[0, 0] = np.nan
    with pytest.raises(GaussianShellError, match="finite"):
        build_gaussian_shell(nan_points, None)
    with pytest.raises(GaussianShellError, match="opacity logit"):
        build_gaussian_shell(points, np.zeros(10))
    with pytest.raises(GaussianShellError, match="max_grid_cells"):
        build_gaussian_shell(points, None, ShellParams(max_grid_cells=1000))


def test_planar_checkerboard_gets_one_bridging_cell():
    grid = np.zeros((5, 5, 5), dtype=bool)
    grid[1, 1, 1] = grid[2, 2, 1] = True
    repaired, fixes = _repair_diagonals(grid)
    assert fixes == 1
    assert repaired[1, 2, 1]


def test_body_diagonal_contact_is_repaired_until_no_pattern_remains():
    grid = np.zeros((5, 5, 5), dtype=bool)
    grid[1, 1, 1] = grid[2, 2, 2] = True
    repaired, fixes = _repair_diagonals(grid)
    assert fixes >= 1
    assert not _planar_diagonal_targets(repaired).any()
    assert not _body_diagonal_targets(repaired).any()


def test_same_input_and_params_give_same_checksum():
    rng = np.random.default_rng(18)
    points = rng.uniform(BOX_LOW, BOX_HIGH, size=(20000, 3))
    first = build_gaussian_shell(points, None)
    second = build_gaussian_shell(points, None)
    assert first.checksum == second.checksum
    np.testing.assert_array_equal(first.vertices, second.vertices)
    np.testing.assert_array_equal(first.faces, second.faces)
    assert build_gaussian_shell(points, None, ShellParams(voxel_m=0.03)).checksum != first.checksum


def test_large_object_uses_adaptive_voxel_and_passes_qa():
    rng = np.random.default_rng(19)
    shell = build_gaussian_shell(rng.uniform([0.0, 0.0, 0.0], [2.0, 0.9, 0.8], size=(200000, 3)), None)
    assert shell.statistics["voxel_m_effective"] > 0.02
    assert shell.quality["passed"]
    assert mesh_of(shell).is_watertight
