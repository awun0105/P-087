"""Surface QA and inferred/observed separation; no renderer, training or inpainting."""

import numpy as np
import pytest
import trimesh

from src.services.scene.surface_mesh import assess_surface, process_surface


def missing_patch():
    # Box face divided into a 3x3 grid; remove only its central two triangles.
    mesh = trimesh.creation.box(extents=[0.03, 0.03, 0.03])
    mesh = mesh.subdivide().subdivide()
    centers = mesh.triangles_center
    on_top = np.isclose(centers[:, 2], 0.015)
    chosen = np.flatnonzero(on_top)[len(np.flatnonzero(on_top)) // 2]
    removed = mesh.triangles[chosen].copy()
    mesh.update_faces(np.arange(len(mesh.faces)) != chosen)
    return mesh, removed


def support_for(triangle, voxel=0.01, views=2):
    points = []
    for i in range(21):
        for j in range(21 - i):
            points.append((i * triangle[0] + j * triangle[1] + (20 - i - j) * triangle[2]) / 20)
    points = np.asarray(points)
    return dict(
        points=np.tile(points, (views, 1)),
        view_ids=np.repeat(np.arange(views), len(points)),
        camera_centers=np.array([[i, 0, 1] for i in range(views)]),
        metadata=dict(
            kind="objectgs_rendered_depth_estimate",
            coordinate_frame="object_local",
            distance_unit="m",
            voxel_size_m=voxel,
        ),
    )


def test_closed_asymmetric_mesh_preserves_frame_dimensions_and_all_geometry():
    source = trimesh.creation.box(extents=[1, 2, 3])
    source.apply_transform(trimesh.transformations.rotation_matrix(0.4, [0, 0, 1]))
    source.apply_translation([0.3, -0.2, 0.8])
    result, quality, repair = process_surface(source, voxel_size_m=0.01, expected_bounds=source.bounds)
    assert quality["passed"], quality
    np.testing.assert_array_equal(result.bounds, source.bounds)
    assert result.volume == pytest.approx(6)
    assert len(result.faces) == len(source.faces) and not repair["inferred_face_indices"]
    assert quality["after"]["metrics"]["components"] == 1


def test_small_missing_patch_requires_multiview_depth_support_and_records_inferred_faces():
    source, triangle = missing_patch()
    original = source.vertices.copy()
    unchanged, rejected, report = process_surface(source, voxel_size_m=0.01)
    assert not rejected["passed"] and "open_boundary" in rejected["reasons"]
    assert report["holes"][0]["reason"] == "no_depth_support"
    assert len(unchanged.faces) == len(source.faces)
    repaired, quality, repair = process_surface(source, voxel_size_m=0.01, support=support_for(triangle))
    assert quality["passed"], quality
    assert repaired.is_watertight and repair["holes"][0]["repaired"]
    assert len(repair["inferred_face_indices"]) == 3
    assert quality["before"]["metrics"]["boundary_edges"] == 3
    assert quality["after"]["metrics"]["boundary_edges"] == 0
    np.testing.assert_array_equal(source.vertices, original)
    np.testing.assert_allclose(repaired.bounds, source.bounds)


@pytest.mark.parametrize("failure", ["single_view", "no_baseline", "missing_depth", "visual_inpaint", "frame"])
def test_insufficient_or_wrong_support_never_authorizes_a_cap(failure):
    mesh, triangle = missing_patch()
    support = support_for(triangle, views=1 if failure == "single_view" else 2)
    if failure == "no_baseline":
        support["camera_centers"][:] = [0, 0, 1]
    if failure == "missing_depth":
        support["points"] += [1, 0, 0]
    if failure == "visual_inpaint":
        support["metadata"]["kind"] = "visual_inpainting"
    if failure == "frame":
        support["metadata"]["coordinate_frame"] = "world"
    result, quality, repair = process_surface(mesh, voxel_size_m=0.01, support=support)
    assert not quality["passed"] and not repair["inferred_face_indices"]
    assert len(result.faces) == len(mesh.faces)


def test_large_open_surface_stays_rejected_even_with_depth_samples():
    mesh = trimesh.creation.box()
    triangle = mesh.triangles[0]
    mesh.update_faces(np.arange(len(mesh.faces)) != 0)
    _, quality, repair = process_surface(mesh, voxel_size_m=0.01, support=support_for(triangle))
    assert not quality["passed"]
    assert repair["holes"][0]["reason"] == "large_or_complex_boundary"


def test_two_disconnected_components_are_preserved_without_bridging_the_gap():
    a, b = trimesh.creation.box(), trimesh.creation.box()
    a.apply_translation([-1, 0, 0])
    b.apply_translation([1, 0, 0])
    source = trimesh.util.concatenate([a, b])
    result, quality, repair = process_surface(source, voxel_size_m=0.01)
    assert quality["passed"] and quality["after"]["metrics"]["components"] == 2
    assert len(result.split()) == 2 and result.volume == pytest.approx(2)
    assert not repair["inferred_face_indices"]


def test_cleanup_removes_duplicate_degenerate_and_nonfinite_noise_without_losing_valid_shell():
    mesh = trimesh.creation.box()
    source = trimesh.Trimesh(
        np.vstack([mesh.vertices, [np.nan, 0, 0], [99, 99, 99]]),
        np.vstack([mesh.faces, mesh.faces[0], [0, 0, 0], [0, 1, 8]]),
        process=False,
    )
    result, quality, report = process_surface(source, voxel_size_m=0.01)
    assert quality["passed"] and report["cleanup"]["removed_faces"] == 3
    assert len(result.faces) == 12 and len(result.vertices) == 8
    np.testing.assert_array_equal(result.bounds, mesh.bounds)


def test_degenerate_surface_scale_mismatch_and_intersecting_shells_fail_closed():
    _, quality, _ = process_surface(
        trimesh.Trimesh([[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 1, 2]], process=False), voxel_size_m=0.01
    )
    assert not quality["passed"]
    box = trimesh.creation.box()
    assert not assess_surface(box, expected_bounds=box.bounds * 1000, tolerance_m=0.05)["passed"]
    other = box.copy()
    other.apply_translation([0.3, 0.2, 0.1])
    report = assess_surface(trimesh.util.concatenate([box, other]))
    assert not report["passed"] and "self_intersection" in report["reasons"]
