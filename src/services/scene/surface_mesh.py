"""Conservative surface cleanup, evidence-gated local caps and strict mesh quality checks.

No smoothing, decimation, largest-component selection, hull fallback or unconditional hole filling.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree


def load_surface(path: Path) -> trimesh.Trimesh:
    scene = trimesh.load(path, force="scene", process=False)
    parts = []
    for node in scene.graph.nodes_geometry:
        matrix, name = scene.graph[node]
        if (
            not np.isfinite(matrix).all()
            or not np.allclose(matrix[3], [0, 0, 0, 1])
            or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-6)
            or not np.isclose(np.linalg.det(matrix[:3, :3]), 1, atol=1e-6)
        ):
            raise ValueError("surface GLB nodes must have explicit rigid metre transforms")
        mesh = scene.geometry[name].copy()
        if not isinstance(mesh, trimesh.Trimesh):
            raise ValueError("surface layout contains unsupported non-triangle geometry")
        mesh.apply_transform(matrix)
        parts.append(mesh)
    if not parts:
        raise ValueError("surface contains no triangle mesh")
    return trimesh.util.concatenate(parts)


def _edges(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    edges = mesh.edges
    _, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True, return_counts=True)
    return edges[counts[inverse] == 1], counts


def _loops(edges: np.ndarray) -> tuple[list[np.ndarray], bool]:
    outgoing = {}
    incoming = {}
    for a, b in edges:
        outgoing.setdefault(int(a), []).append(int(b))
        incoming.setdefault(int(b), []).append(int(a))
    if any(len(outgoing.get(v, [])) != 1 or len(incoming.get(v, [])) != 1 for v in outgoing.keys() | incoming.keys()):
        return [], False
    remaining = set(outgoing)
    loops = []
    while remaining:
        start = min(remaining)
        loop, current = [], start
        while current in remaining:
            remaining.remove(current)
            loop.append(current)
            current = outgoing[current][0]
        if current != start:
            return [], False
        loops.append(np.asarray(loop, dtype=int))
    return loops, True


def _intersections(mesh: trimesh.Trimesh, budget: int = 250_000) -> tuple[int, bool]:
    """Triangle SAT with spatial broad phase; fail closed when the pair budget is exceeded.

    Shared-vertex triangle pairs are excluded as surface adjacency. This is not a proof against
    every possible fold inside a vertex one-ring; winding/manifold checks are separate gates.
    """
    triangles = mesh.triangles
    centers = triangles.mean(axis=1)
    radii = np.linalg.norm(triangles - centers[:, None], axis=2).max(axis=1)
    tree = cKDTree(centers)
    checked = 0
    intersections = 0
    low, high = triangles.min(axis=1), triangles.max(axis=1)
    for first in range(0, len(triangles), 128):
        counts = tree.query_ball_point(
            centers[first : first + 128], radii[first : first + 128] + radii.max(), return_length=True
        )
        if int(np.sum(counts)) + checked > 2 * budget:
            return intersections, False
        neighborhoods = tree.query_ball_point(centers[first : first + 128], radii[first : first + 128] + radii.max())
        pairs = [(i, j) for i, ids in enumerate(neighborhoods, first) for j in ids if j > i]
        checked += len(pairs)
        if checked > budget:
            return intersections, False
        if not pairs:
            continue
        pairs = np.asarray(pairs)
        a, b = pairs.T
        mask = ((high[a] >= low[b]) & (high[b] >= low[a])).all(axis=1)
        mask &= ~(mesh.faces[a, :, None] == mesh.faces[b, None, :]).any(axis=(1, 2))
        a, b = a[mask], b[mask]
        for start in range(0, len(a), 512):
            left, right = triangles[a[start : start + 512]], triangles[b[start : start + 512]]
            e = np.roll(left, -1, axis=1) - left
            f = np.roll(right, -1, axis=1) - right
            n, m = np.cross(e[:, 0], e[:, 1]), np.cross(f[:, 0], f[:, 1])
            axes = np.concatenate(
                [
                    n[:, None],
                    m[:, None],
                    np.cross(e[:, :, None], f[:, None, :]).reshape(-1, 9, 3),
                    np.cross(n[:, None], e),
                    np.cross(m[:, None], f),
                ],
                axis=1,
            )
            norm = np.linalg.norm(axes, axis=2)
            axes = np.divide(axes, norm[..., None], out=np.zeros_like(axes), where=norm[..., None] > 0)
            p = np.einsum("nvc,nac->nav", left, axes)
            q = np.einsum("nvc,nac->nav", right, axes)
            separated = ((p.max(axis=2) < q.min(axis=2) - 1e-12) | (q.max(axis=2) < p.min(axis=2) - 1e-12)).any(axis=1)
            intersections += int((~separated).sum())
    return intersections, True


def assess_surface(
    mesh: trimesh.Trimesh, *, expected_bounds: np.ndarray | None = None, tolerance_m: float = 0.0
) -> dict:
    reasons = []
    finite = bool(np.isfinite(mesh.vertices).all())
    metrics = dict(vertices=len(mesh.vertices), triangles=len(mesh.faces), finite=finite)
    if not finite or not len(mesh.vertices) or not len(mesh.faces):
        return dict(passed=False, reasons=["empty_or_nonfinite_surface"], metrics=metrics)
    degenerate = int((mesh.area_faces <= np.finfo(float).eps).sum())
    metrics["degenerate_triangles"] = degenerate
    if degenerate:
        reasons.append("degenerate_triangles")
    edges, counts = _edges(mesh)
    loops, simple = _loops(edges)
    parts = mesh.split(only_watertight=False, repair=False)
    metrics.update(
        bounds_m=mesh.bounds.tolist(),
        dimensions_m=mesh.extents.tolist(),
        area_m2=float(mesh.area),
        boundary_edges=len(edges),
        boundary_loops=len(loops),
        simple_boundary=simple,
        nonmanifold_edges=int((counts > 2).sum()),
        components=len(parts),
        component_triangles=[len(part.faces) for part in parts],
        watertight=bool(mesh.is_watertight),
        winding_consistent=bool(mesh.is_winding_consistent),
        euler_characteristic=int(mesh.euler_number),
    )
    metrics["component_euler_characteristics"] = [int(part.euler_number) for part in parts]
    metrics["component_genus"] = [
        (2 - int(part.euler_number)) / 2 if part.is_watertight and part.is_winding_consistent else None
        for part in parts
    ]
    metrics["volume_m3"] = float(mesh.volume) if mesh.is_watertight and mesh.is_winding_consistent else None
    if any(part.is_watertight and (part.euler_number > 2 or part.euler_number % 2) for part in parts):
        reasons.append("invalid_closed_component_topology")
    if len(edges):
        reasons.append("open_boundary")
    if (counts > 2).any():
        reasons.append("nonmanifold_edges")
    if not mesh.is_winding_consistent:
        reasons.append("inconsistent_winding")
    if not simple:
        reasons.append("branched_boundary")
    if any(not part.is_watertight or part.volume <= 0 for part in parts):
        reasons.append("open_or_nonpositive_component")
    # Face-disconnected shells touching at a vertex are not a manifold object surface.
    if sum(len(part.vertices) for part in parts) > len(mesh.vertices):
        reasons.append("shared_vertex_components")
    if np.any(mesh.extents <= 0):
        reasons.append("degenerate_dimensions")
    if expected_bounds is not None:
        bounds = np.asarray(expected_bounds)
        if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[1] < bounds[0]):
            raise ValueError("expected metric bounds must be finite ordered (2,3)")
        deviation = np.abs(mesh.bounds - bounds)
        metrics["source_bounds_deviation_m"] = deviation.tolist()
        if np.any(deviation > tolerance_m):
            reasons.append("source_bounds_or_metric_scale_mismatch")
    metrics["intersection_scope"] = "nonadjacent_non_shared_vertex_triangles"
    if not reasons:
        crossing, complete = _intersections(mesh)
        metrics.update(nonadjacent_triangle_intersections=crossing, intersection_check_complete=complete)
        if crossing:
            reasons.append("self_intersection")
        if not complete:
            reasons.append("intersection_budget_exceeded")
    else:
        metrics["intersection_check_complete"] = False
    return dict(passed=not reasons, reasons=reasons, metrics=metrics)


def _supported(samples: np.ndarray, support: dict | None, voxel_m: float) -> tuple[bool, str]:
    if support is None:
        return False, "no_depth_support"
    if support["metadata"].get("kind") != "objectgs_rendered_depth_estimate":
        return False, "unsupported_depth_origin"
    if support["metadata"].get("coordinate_frame") != "object_local" or support["metadata"].get("distance_unit") != "m":
        return False, "depth_support_frame_mismatch"
    if not np.isclose(support["metadata"].get("voxel_size_m", 0), voxel_m):
        return False, "depth_support_resolution_mismatch"
    points, views, centers = support["points"], support["view_ids"], support["camera_centers"]
    tree = cKDTree(points)
    for nearby in tree.query_ball_point(samples, voxel_m / 2):
        seen = np.unique(views[nearby])
        if len(seen) < 2:
            return False, "insufficient_multiview_depth_coverage"
        cameras = centers[seen]
        if np.linalg.norm(cameras[:, None] - cameras[None], axis=2).max() <= voxel_m:
            return False, "insufficient_camera_baseline"
    return True, "multiview_rendered_depth_supported"


def clean_surface(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    mesh = mesh.copy()
    # Exact positional welding cannot close a real gap. Never move or round source vertices.
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    faces = inverse[mesh.faces]
    finite = np.isfinite(vertices[faces]).all(axis=(1, 2))
    area = np.linalg.norm(
        np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]]), axis=1
    )
    faces = faces[finite & (area > np.finfo(float).eps)]
    _, first = np.unique(np.sort(faces, axis=1), axis=0, return_index=True)
    faces = faces[np.sort(first)]
    clean = trimesh.Trimesh(vertices, faces, process=False)
    clean.remove_unreferenced_vertices()
    return clean


def process_surface(
    mesh: trimesh.Trimesh,
    *,
    voxel_size_m: float,
    support: dict | None = None,
    expected_bounds: np.ndarray | None = None,
) -> tuple[trimesh.Trimesh, dict, dict]:
    if not np.isfinite(voxel_size_m) or voxel_size_m <= 0:
        raise ValueError("surface processing requires a positive metric TSDF voxel size")
    before_vertices, before_faces = len(mesh.vertices), len(mesh.faces)
    clean = clean_surface(mesh)
    before = assess_surface(clean, expected_bounds=expected_bounds, tolerance_m=5 * voxel_size_m)
    edges, _ = _edges(clean)
    loops, simple = _loops(edges)
    repair = dict(
        algorithm="depth_supported_planar_caps_v1",
        source_vertices=before_vertices,
        source_triangles=before_faces,
        cleanup=dict(
            removed_faces=before_faces - len(clean.faces), removed_vertices=before_vertices - len(clean.vertices)
        ),
        holes=[],
        inferred_face_indices=[],
        source_kind="objectgs_rendered_surface_estimate",
        evidence_kind="objectgs_rendered_depth_estimate",
        voxel_size_m=voxel_size_m,
        max_hole_diameter_m=2 * voxel_size_m,
        maximum_loops=128,
        holes_omitted=max(0, len(loops) - 128),
    )
    observed = len(clean.faces)
    for loop in loops[:128] if simple else []:
        polygon = clean.vertices[loop]
        center = polygon.mean(axis=0)
        diameter = float(np.linalg.norm(polygon[:, None] - polygon[None], axis=2).max())
        item = dict(boundary_vertices=loop.tolist(), diameter_m=diameter, repaired=False)
        repair["holes"].append(item)
        if len(loop) > 8 or diameter > 2 * voxel_size_m:
            item["reason"] = "large_or_complex_boundary"
            continue
        _, _, axes = np.linalg.svd(polygon - center)
        if np.abs((polygon - center) @ axes[-1]).max() > 0.1 * voxel_size_m:
            item["reason"] = "nonplanar_boundary"
            continue
        turns = (
            np.cross(
                np.roll(polygon, -1, axis=0) - polygon, np.roll(polygon, -2, axis=0) - np.roll(polygon, -1, axis=0)
            )
            @ axes[-1]
        )
        if not (np.all(turns >= -1e-12) or np.all(turns <= 1e-12)):
            item["reason"] = "nonconvex_boundary"
            continue
        samples = []
        for a, b in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
            for i in range(5):
                for j in range(5 - i):
                    samples.append((i * a + j * b + (4 - i - j) * center) / 4)
        supported, reason = _supported(np.asarray(samples), support, voxel_size_m)
        item["reason"] = reason
        if not supported:
            continue
        index = len(clean.vertices)
        cap = np.array([[int(b), int(a), index] for a, b in zip(loop, np.roll(loop, -1), strict=True)])
        start = len(clean.faces)
        clean = trimesh.Trimesh(np.vstack([clean.vertices, center]), np.vstack([clean.faces, cap]), process=False)
        item.update(
            repaired=True,
            added_faces=list(range(start, len(clean.faces))),
            inferred_area_m2=float(clean.area_faces[start:].sum()),
        )
    repair["inferred_face_indices"] = list(range(observed, len(clean.faces)))
    after = assess_surface(clean, expected_bounds=expected_bounds, tolerance_m=5 * voxel_size_m)
    quality = dict(
        algorithm="strict_surface_quality_v1",
        coordinate_frame="object_local",
        distance_unit="m",
        passed=after["passed"],
        reasons=after["reasons"],
        before=before,
        after=after,
        inferred_faces=len(clean.faces) - observed,
        bounds_tolerance_m=5 * voxel_size_m,
    )
    return clean, quality, repair


def load_support(
    path: Path, *, checksum: str, world_from_object_rotation: np.ndarray, object_translation: np.ndarray
) -> dict:
    import zipfile

    if path.stat().st_size > 16 * 1024**2:
        raise ValueError("depth support exceeds byte budget")
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 16 * 1024**2:
            raise ValueError("depth support exceeds decompressed byte budget")
    payload = path.read_bytes()
    if "sha256:" + hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError("surface depth support checksum mismatch")
    import json

    with np.load(path, allow_pickle=False) as data:
        metadata = json.loads(str(data["metadata"]))
        points, views, centers = data["points"], data["view_ids"], data["camera_centers"]
    if metadata.get("coordinate_frame") != "world" or metadata.get("distance_unit") != "m":
        raise ValueError("surface support must be explicit world metres")
    if (
        points.ndim != 2
        or points.shape[1:] != (3,)
        or len(points) > 200_000
        or views.shape != (len(points),)
        or centers.ndim != 2
        or centers.shape[1:] != (3,)
        or len(centers) > 16
        or not np.issubdtype(views.dtype, np.integer)
        or not np.isfinite(points).all()
        or not np.isfinite(centers).all()
        or (views.size and (views.min() < 0 or views.max() >= len(centers)))
    ):
        raise ValueError("invalid or oversized depth support arrays")
    return dict(
        points=(points - object_translation) @ world_from_object_rotation,
        view_ids=views,
        camera_centers=(centers - object_translation) @ world_from_object_rotation,
        metadata={**metadata, "source_coordinate_frame": "world", "coordinate_frame": "object_local"},
    )
