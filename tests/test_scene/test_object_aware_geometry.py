"""Connected floor/table/wall fixture tests ownership before meshing, not triangle carving."""

import hashlib

import numpy as np
import pytest
import trimesh

from src.services.scene.object_aware_geometry import build_background_collision


def fixture():
    cells = []
    labels = []

    def add(x, y, z, label):
        cells.append([x, y, z])
        labels.append(label)

    for x in range(-10, 11):
        for y in range(-10, 11):
            add(x, y, 0, -1)
    for y in range(-10, 11):
        for z in range(1, 16):
            add(-10, y, z, -1)
    for x in range(-3, 4):
        for y in range(-3, 4):
            add(x, y, 10, 1)
    for x in [-3, 3]:
        for y in [-3, 3]:
            for z in range(0, 10):
                add(x, y, z, 1)
    for x in range(7, 10):
        for y in range(7, 10):
            for z in range(1, 5):
                add(x, y, z, 2)
    return (np.asarray(cells) + 0.5) * 0.1, np.asarray(labels, dtype=np.int32)


def ray(mesh, origin, direction):
    triangles = mesh.vertices[mesh.faces]
    e1 = triangles[:, 1] - triangles[:, 0]
    e2 = triangles[:, 2] - triangles[:, 0]
    h = np.cross(np.asarray(direction), e2)
    det = np.sum(e1 * h, axis=1)
    valid = np.abs(det) > 1e-10
    inv = np.zeros(len(det))
    inv[valid] = 1 / det[valid]
    s = np.asarray(origin) - triangles[:, 0]
    u = inv * np.sum(s * h, axis=1)
    q = np.cross(s, e1)
    v = inv * np.sum(np.asarray(direction) * q, axis=1)
    distance = inv * np.sum(e2 * q, axis=1)
    hits = distance[valid & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (distance > 1e-8)]
    return None if not len(hits) else float(hits.min())


def test_environment_preserves_floor_wall_and_unselected_object_without_table_ghost():
    points, labels = fixture()
    source = build_background_collision(points, labels, set(), voxel_m=0.1)
    source_mesh = trimesh.Trimesh(source.vertices, source.faces, process=False)
    assert len(source_mesh.split(only_watertight=False, repair=False)) == 1
    result = build_background_collision(points, labels, {1}, voxel_m=0.1)
    mesh = trimesh.Trimesh(result.vertices, result.faces, process=False)
    assert mesh.is_watertight and mesh.is_winding_consistent
    # From above old table position, the first retained hit is the floor top, not the tabletop.
    assert ray(source_mesh, [0.05, 0.05, 1.5], [0, 0, -1]) == pytest.approx(0.4)
    assert ray(mesh, [0.05, 0.05, 1.5], [0, 0, -1]) == pytest.approx(1.4)
    assert ray(mesh, [0.05, 0.05, 0.5], [-1, 0, 0]) == pytest.approx(0.95)
    assert ray(mesh, [0.85, 0.85, 0.8], [0, 0, -1]) == pytest.approx(0.3)
    # Shared floor/leg contact cells survive; no whole source triangles are deleted.
    assert result.statistics["shared_cells"] == 4
    assert result.statistics["excluded_object_only_cells"] > 0
    assert result.statistics["inferred_support_cells"] == 0


def test_unknown_shared_and_authored_support_are_explicit_and_conservative():
    points = np.array([[0.05, 0.05, 0.05], [0.05, 0.05, 0.05], [0.25, 0.05, 0.05], [0.45, 0.05, 0.05]])
    labels = np.array([-1, 1, 1, 1])
    result = build_background_collision(
        points,
        labels,
        {1},
        voxel_m=0.1,
        unknown=np.array([False, False, True, False]),
        inferred_support_points=np.array([[0.65, 0.05, 0.05]]),
    )
    assert result.statistics["shared_cells"] == 1
    assert result.statistics["unknown_rows"] == 1
    assert result.statistics["inferred_support_cells"] == 1
    assert result.statistics["retained_cells"] == 3
    with pytest.raises(ValueError, match="conflicts"):
        build_background_collision(points, labels, {1}, voxel_m=0.1, observed_free_cells=np.array([[0, 0, 0]]))


def test_budget_and_invalid_membership_fail_without_mesh_or_fill_fallback():
    points, labels = fixture()
    with pytest.raises(ValueError, match="budget"):
        build_background_collision(points, labels, {1}, voxel_m=0.1, max_grid_cells=10)
    with pytest.raises(ValueError, match="integer membership"):
        build_background_collision(points, labels.astype(float), {1}, voxel_m=0.1)
    with pytest.raises(ValueError, match="background cannot"):
        build_background_collision(points, labels, {-1}, voxel_m=0.1)


def test_background_collision_checksum_unchanged_after_refactor():
    points, labels = fixture()
    result = build_background_collision(points, labels, {1}, voxel_m=0.1)
    # Golden values captured before occupancy_surface() was extracted. occupancy_checksum hashes only the kept
    # cells, so the mesh digest is what pins the emitted vertices and faces.
    mesh_digest = hashlib.sha256(result.vertices.astype("<f8").tobytes() + result.faces.astype("<i8").tobytes())
    assert result.occupancy_checksum == "sha256:caea4ebef4569c056cc8a0b551e8ced62e95a5234ae5826cb4c0f255cf7ae1ab"
    assert mesh_digest.hexdigest() == "a2bedb2a16b128bf4658b2760f5f00f1c6f38298b46652acc97dc0141af9850d"
