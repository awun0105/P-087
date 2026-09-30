"""Khoét vật đã xác nhận khỏi collision mesh môi trường và layer USD của mesh đó."""

import math

import numpy as np
import trimesh

from src.services.simulation.colliders.carve import CarveBox, carve_boxes
from src.services.simulation.usd.usda import generate_mesh_layer_usda


def _scene_mesh() -> tuple[np.ndarray, np.ndarray]:
    wall = trimesh.creation.box(extents=(4, 0.2, 2))
    wall.apply_translation((0, 3, 1))
    pallet = trimesh.creation.box(extents=(1.0, 0.8, 0.6)).subdivide_to_size(0.1)
    pallet.apply_translation((0, 0, 0.3))
    mesh = trimesh.util.concatenate([wall, pallet])
    return np.asarray(mesh.vertices), np.asarray(mesh.faces)


def test_carving_removes_only_triangles_inside_confirmed_box() -> None:
    vertices, faces = _scene_mesh()
    box = CarveBox(center=(0, 0, 0.3), rotation_xyzw=(0, 0, 0, 1), dimensions=(1.0, 0.8, 0.6))
    kept_vertices, kept_faces, removed = carve_boxes(vertices, faces, [box])
    assert removed == len(faces) - 12  # còn đúng 12 tam giác của bức tường
    assert kept_faces.max() < len(kept_vertices)
    assert (kept_vertices[:, 1] > 2.8).all()  # chỉ còn đỉnh của tường


def test_rotated_box_and_no_box_keep_the_rest() -> None:
    vertices, faces = _scene_mesh()
    same_vertices, same_faces, removed = carve_boxes(vertices, faces, [])
    assert removed == 0 and same_faces is faces
    # Hộp xoay 90° quanh Z đặt ở chỗ trống: không chạm gì.
    yaw = (0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4))
    far = CarveBox(center=(10, 10, 0.3), rotation_xyzw=yaw, dimensions=(1, 1, 1))
    assert carve_boxes(vertices, faces, [far])[2] == 0


def test_mesh_layer_and_scene_reference() -> None:
    vertices, faces = _scene_mesh()
    layer = generate_mesh_layer_usda(vertices, faces)
    assert layer.startswith("#usda 1.0") and 'upAxis = "Z"' in layer and "metersPerUnit = 1.0" in layer
    assert 'prepend apiSchemas = ["PhysicsCollisionAPI", "PhysicsMeshCollisionAPI"]' in layer
    counts = next(line for line in layer.splitlines() if "faceVertexCounts" in line)
    assert counts.count("3") == len(faces)  # mỗi mặt là một tam giác
    indices = next(line for line in layer.splitlines() if "faceVertexIndices" in line)
    assert len(indices.split("= [")[1].split(",")) == 3 * len(faces)
