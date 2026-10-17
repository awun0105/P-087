"""User-authored source-bound planes and conservative planar hole triangulation."""

from typing import Literal, Self

import numpy as np
from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel
from src.models.contracts.floor_model import Vector3
from src.services.scene.collision_ownership import SourceCollisionOwnershipError


class CollisionSurfacePlane(ContractModel):
    id: str = Field(min_length=1, max_length=80)
    frame: Literal["world"] = "world"
    distance_unit: Literal["m"] = "m"
    origin: Literal["user_authored"] = "user_authored"
    kind: Literal["floor", "wall"]
    source_checksum: Checksum
    points: tuple[Vector3, Vector3, Vector3]
    fill_regions: bool = False

    @model_validator(mode="after")
    def validate_plane(self) -> Self:
        normal, _ = self.equation()
        if self.kind == "floor" and abs(normal[2]) < np.cos(np.deg2rad(15)):
            raise ValueError("floor plane must be within 15 degrees of canonical horizontal")
        if self.kind == "wall" and abs(normal[2]) > np.sin(np.deg2rad(15)):
            raise ValueError("wall plane must be within 15 degrees of canonical vertical")
        return self

    def equation(self) -> tuple[np.ndarray, float]:
        points = np.asarray(self.points)
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        length = float(np.linalg.norm(normal))
        if length < 1e-8 or not np.isfinite(length):
            raise ValueError("surface triangle must have finite non-collinear points")
        normal /= length
        if self.kind == "floor" and normal[2] < 0:
            normal *= -1
        return normal, -float(normal @ points[0])


def surface_planes(provenance: dict, checksum: str) -> list[CollisionSurfacePlane]:
    planes = [CollisionSurfacePlane.model_validate(value) for value in provenance.get("collision_surface_planes", [])]
    if len(planes) > 32 or any(plane.source_checksum != checksum for plane in planes):
        raise SourceCollisionOwnershipError("surface planes are stale or exceed the 32-plane limit")
    return planes


def patch_planar_holes(
    vertices: np.ndarray,
    faces: np.ndarray,
    planes: list[tuple[np.ndarray, float, float]],
    regions: list[np.ndarray],
    *,
    source_faces: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Cap simple closed source-bound holes only; never close the outer scene boundary.

    Each region is an immutable source-region AABB. With source_faces, new planar cut boundaries
    define their own planes without semantic labels; original source openings are excluded.
    Exact position welding reconnects GLB normal seams without changing any source triangle identity.
    """
    if (not planes and source_faces is None) or not regions or not len(faces):
        return vertices, np.empty((0, 3), dtype=np.int64)
    _, representatives, labels = np.unique(vertices, axis=0, return_index=True, return_inverse=True)
    welded = labels[faces]
    original_boundary = _boundary_edges(labels[source_faces]) if source_faces is not None else set()
    edges = np.sort(np.concatenate([welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]]), axis=1)
    edges, counts = np.unique(edges, axis=0, return_counts=True)
    adjacent: dict[int, list[int]] = {}
    for a, b in edges[counts == 1]:
        adjacent.setdefault(int(a), []).append(int(b))
        adjacent.setdefault(int(b), []).append(int(a))
    visited: set[int] = set()
    patches: list[tuple[int, int, int]] = []
    extra_vertices: list[np.ndarray] = []
    for start in sorted(adjacent):
        if start in visited:
            continue
        component: set[int] = set()
        pending = [start]
        while pending:
            node = pending.pop()
            if node in component:
                continue
            component.add(node)
            pending.extend(adjacent[node])
        visited |= component
        # Branches, tiny loops, and very large boundaries require explicit mesh repair, not a guessed cap.
        if not 3 <= len(component) <= 512 or any(len(adjacent[node]) != 2 for node in component):
            continue
        loop = [start]
        previous, current = start, min(adjacent[start])
        while current != start:
            loop.append(current)
            next_node = next(node for node in adjacent[current] if node != previous)
            previous, current = current, next_node
        indices = representatives[loop]
        points = vertices[indices]
        loop_edges = {tuple(sorted((loop[k], loop[(k + 1) % len(loop)]))) for k in range(len(loop))}
        # Never treat an original opening or a cut joined to one as an automatically fillable hole.
        if loop_edges & original_boundary:
            continue
        # All boundary vertices must fit one source footprint. No caps over unrelated doors/stairs.
        if not any(((points >= region[0] - 0.05) & (points <= region[1] + 0.05)).all() for region in regions):
            continue
        candidates = list(planes)
        if source_faces is not None:
            # The cut boundary defines its plane; no floor/wall classification is required.
            center = points.mean(axis=0)
            _, singular, basis = np.linalg.svd(points - center, full_matrices=False)
            normal = basis[-1]
            offset = -float(normal @ center)
            if singular[1] > 1e-8:
                candidates.append((normal, offset, 0.01))
        for normal, offset, tolerance in candidates:
            if np.max(np.abs(points @ normal + offset)) > tolerance:
                continue
            axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
            u = np.cross(normal, axis)
            u /= np.linalg.norm(u)
            v = np.cross(normal, u)
            projected = np.column_stack([points @ u, points @ v])
            # A floor/wall outer perimeter encloses existing faces. A hole encloses empty surface.
            planar_faces = (np.abs(vertices[faces] @ normal + offset) <= tolerance).all(axis=1)
            centers = vertices[faces[planar_faces]].mean(axis=1)
            centers_2d = np.column_stack([centers @ u, centers @ v])
            if _inside_polygon(centers_2d, projected).any():
                break
            triangles = _ear_clip(projected)
            if triangles is not None:
                cap_indices = indices.copy()
                for k, point in enumerate(points):
                    distance = float(point @ normal + offset)
                    if abs(distance) > 1e-8:
                        cap_indices[k] = len(vertices) + len(extra_vertices)
                        extra_vertices.append(point - distance * normal)
                patches.extend(tuple(int(cap_indices[i]) for i in triangle) for triangle in triangles)
                # Close the tiny seam to noisy source vertices without moving measured geometry.
                for k in range(len(indices)):
                    j = (k + 1) % len(indices)
                    a, b, c, d = int(indices[k]), int(indices[j]), int(cap_indices[j]), int(cap_indices[k])
                    if a != d and b != c:
                        patches.extend([(a, b, c), (a, c, d)])
                    elif a != d:
                        patches.append((a, b, d))
                    elif b != c:
                        patches.append((a, b, c))
            break
    extended = np.concatenate([vertices, np.asarray(extra_vertices).reshape(-1, 3)]) if extra_vertices else vertices
    return extended, np.asarray(patches, dtype=np.int64).reshape(-1, 3)


def _boundary_edges(faces: np.ndarray) -> set[tuple[int, int]]:
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    edges, counts = np.unique(edges, axis=0, return_counts=True)
    return {tuple(map(int, edge)) for edge in edges[counts == 1]}


def require_closed_cuts(vertices: np.ndarray, source_faces: np.ndarray, result_faces: np.ndarray) -> None:
    """Reject newly exposed edges; existing source openings are not automatic repair targets."""
    _, labels = np.unique(vertices, axis=0, return_inverse=True)
    unresolved = _boundary_edges(labels[result_faces]) - _boundary_edges(labels[source_faces])
    if unresolved:
        raise SourceCollisionOwnershipError(
            f"UNREPAIRED_COLLISION_CUT: {len(unresolved)} new boundary edges remain; "
            "cut boundary cannot be safely closed on a plane"
        )


def _ear_clip(points: np.ndarray) -> list[tuple[int, int, int]] | None:
    """Triangulate a simple concave polygon; reject self intersections and degenerate ears."""

    def cross(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
        x, y = b - a, c - a
        return float(x[0] * y[1] - x[1] * y[0])

    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            if j in {i, (i + 1) % n} or (j + 1) % n == i:
                continue
            a, b, c, d = points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]
            if cross(a, b, c) * cross(a, b, d) <= 0 and cross(c, d, a) * cross(c, d, b) <= 0:
                # Collinear disjoint segments are allowed; overlapping ones are not.
                if (
                    np.maximum(np.minimum(a, b), np.minimum(c, d)) <= np.minimum(np.maximum(a, b), np.maximum(c, d))
                ).all():
                    return None
    area = sum(cross(np.zeros(2), points[i], points[(i + 1) % n]) for i in range(n))
    if abs(area) < 1e-10:
        return None
    order = list(range(n)) if area > 0 else list(reversed(range(n)))
    result: list[tuple[int, int, int]] = []
    while len(order) > 3:
        found = False
        for k, b in enumerate(order):
            a, c = order[k - 1], order[(k + 1) % len(order)]
            if cross(points[a], points[b], points[c]) <= 1e-10:
                continue
            if any(
                min(
                    cross(points[a], points[b], points[p]),
                    cross(points[b], points[c], points[p]),
                    cross(points[c], points[a], points[p]),
                )
                >= -1e-10
                for p in order
                if p not in {a, b, c}
            ):
                continue
            result.append((a, b, c))
            order.pop(k)
            found = True
            break
        if not found:
            return None
    result.append(tuple(order))
    return result


def _inside_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    inside = np.zeros(len(points), dtype=bool)
    for i in range(len(polygon)):
        a, b = polygon[i], polygon[(i + 1) % len(polygon)]
        if abs(b[1] - a[1]) < 1e-12:
            continue
        crosses = (a[1] > points[:, 1]) != (b[1] > points[:, 1])
        x = a[0] + (points[:, 1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        inside ^= crosses & (points[:, 0] < x)
    return inside


def authored_plane_infill(
    vertices: np.ndarray,
    faces: np.ndarray,
    plane: CollisionSurfacePlane,
    regions: list[np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Explicit user-requested planar infill, bounded by immutable removed-object footprints.

    This is authored collision geometry, not reconstructed ground truth. Skip footprints already
    covered at a 3x3 support grid and never project a footprint onto a distant wall.
    """
    if not plane.fill_regions:
        return vertices, np.empty((0, 3), dtype=np.int64)
    normal, offset = plane.equation()
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    u = np.cross(normal, axis)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    points_on_plane = vertices[faces]
    planar = (np.abs(points_on_plane @ normal + offset) <= 0.01).all(axis=1)
    triangles = points_on_plane[planar]
    triangles_2d = np.stack([triangles @ u, triangles @ v], axis=-1)
    extra: list[np.ndarray] = []
    caps: list[tuple[int, int, int]] = []
    seen: set[tuple[float, ...]] = set()
    for region in regions:
        corners = np.array([[x, y, z] for x in region[:, 0] for y in region[:, 1] for z in region[:, 2]])
        distances = corners @ normal + offset
        if plane.kind == "wall" and (distances.min() > 0.05 or distances.max() < -0.05):
            continue
        projected = np.column_stack([corners @ u, corners @ v])
        low, high = projected.min(axis=0), projected.max(axis=0)
        if np.any(high - low < 0.001):
            continue
        key = tuple(np.concatenate([low, high]))
        if key in seen:
            continue
        seen.add(key)
        samples = np.array([[x, y] for x in np.linspace(low[0], high[0], 3) for y in np.linspace(low[1], high[1], 3)])
        if all(_covered_by_triangles(point, triangles_2d) for point in samples):
            continue
        base = len(vertices) + len(extra)
        for x, y in [(low[0], low[1]), (high[0], low[1]), (high[0], high[1]), (low[0], high[1])]:
            extra.append(u * x + v * y - normal * offset)
        caps.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    extended = np.concatenate([vertices, np.asarray(extra).reshape(-1, 3)]) if extra else vertices
    return extended, np.asarray(caps, dtype=np.int64).reshape(-1, 3)


def _covered_by_triangles(point: np.ndarray, triangles: np.ndarray) -> bool:
    if not len(triangles):
        return False
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]

    def cross(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return x[:, 0] * y[:, 1] - x[:, 1] * y[:, 0]

    area = cross(b - a, c - a)
    nondegenerate = np.abs(area) > 1e-12
    first, second, third = cross(b - a, point - a), cross(c - b, point - b), cross(a - c, point - c)
    inside = (np.minimum(np.minimum(first, second), third) >= -1e-9) | (
        np.maximum(np.maximum(first, second), third) <= 1e-9
    )
    return bool(np.any(nondegenerate & inside))
