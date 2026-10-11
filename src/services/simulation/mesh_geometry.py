"""Strict triangle-mesh loading shared by USD capability checks and the runtime writer."""

from pathlib import Path

import numpy as np
import trimesh


class MeshValidationError(ValueError):
    """Mesh bytes exist but cannot represent a valid triangle collider."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_mesh_arrays(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return USD-compatible arrays after checking topology, indices, and finite coordinates."""
    points = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int64)
    if points.ndim != 2 or points.shape[1:] != (3,) or not len(points):
        raise MeshValidationError("COLLIDER_GEOMETRY_HAS_NO_TOPOLOGY", "mesh has no 3D vertices")
    if not np.isfinite(points).all():
        raise MeshValidationError("COLLIDER_GEOMETRY_HAS_INVALID_VERTICES", "mesh vertices contain NaN or infinity")
    if triangles.ndim != 2 or triangles.shape[1:] != (3,) or not len(triangles):
        raise MeshValidationError("COLLIDER_GEOMETRY_HAS_NO_TOPOLOGY", "mesh has no triangular faces")
    if triangles.min() < 0 or triangles.max() >= len(points) or triangles.max() > np.iinfo(np.int32).max:
        raise MeshValidationError(
            "COLLIDER_GEOMETRY_HAS_INVALID_TOPOLOGY", "mesh face index is outside its vertex array"
        )
    if np.any(
        (triangles[:, 0] == triangles[:, 1])
        | (triangles[:, 1] == triangles[:, 2])
        | (triangles[:, 0] == triangles[:, 2])
    ):
        raise MeshValidationError("COLLIDER_GEOMETRY_HAS_INVALID_TOPOLOGY", "mesh contains repeated face indices")
    tri_points = points[triangles]
    areas = np.linalg.norm(np.cross(tri_points[:, 1] - tri_points[:, 0], tri_points[:, 2] - tri_points[:, 0]), axis=1)
    if not np.isfinite(areas).all() or np.any(areas <= 0):
        raise MeshValidationError("COLLIDER_GEOMETRY_HAS_INVALID_TOPOLOGY", "mesh contains degenerate triangles")
    points32 = points.astype(np.float32)
    if not np.isfinite(points32).all():
        raise MeshValidationError("COLLIDER_GEOMETRY_HAS_INVALID_VERTICES", "mesh vertices exceed USD float range")
    return points32, triangles.astype(np.int32)


def load_mesh_parts(path: Path) -> list[tuple[np.ndarray, np.ndarray]]:
    """Load each scene-graph instance as a separate mesh with its node transform baked in."""
    loaded = trimesh.load(path, process=False)
    if isinstance(loaded, trimesh.Trimesh):
        meshes = [loaded]
    elif isinstance(loaded, trimesh.Scene):
        meshes = []
        for node in sorted(loaded.graph.nodes_geometry, key=str):
            transform, geometry_name = loaded.graph[node]
            mesh = loaded.geometry[geometry_name].copy()
            mesh.apply_transform(transform)
            meshes.append(mesh)
    else:
        raise MeshValidationError("COLLIDER_GEOMETRY_HAS_NO_TOPOLOGY", "file does not contain triangle meshes")
    if not meshes:
        raise MeshValidationError("COLLIDER_GEOMETRY_HAS_NO_TOPOLOGY", "file contains no triangle mesh parts")
    return [validate_mesh_arrays(mesh.vertices, mesh.faces) for mesh in meshes]
