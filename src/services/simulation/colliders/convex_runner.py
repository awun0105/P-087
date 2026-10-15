"""Collider phân rã lồi cho từng vật từ Gaussian của nó (ADR 0007, chặng 6).

Isaac không cho rigid body động dùng triangle mesh (rơi về convex hull) → mỗi vật cần vài khối lồi.
Quy trình: tâm Gaussian đủ đục → lưới chiếm chỗ (voxel) → đóng lỗ → marching cubes → CoACD.
Thể tích các khối lồi dùng để suy khối lượng (mật độ × thể tích).

Chạy trong runtime có `coacd`, `scikit-image`, `trimesh` (`data/scene_runtime`); script độc lập.
Mỗi vật ghi một GLB chứa các khối lồi (mỗi khối một mesh), toạ độ cục bộ của vật.

    <scene_runtime>/bin/python convex_runner.py --request request.json --result result.json
"""

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import coacd
import numpy as np
import trimesh
from scipy import ndimage
from skimage import measure

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scene"))
from diagnostics import recorder  # noqa: E402
from surface_mesh import assess_surface, clean_surface, load_surface  # noqa: E402

_PLY_TYPES = {"float": "f4", "float32": "f4", "double": "f8", "uchar": "u1", "int": "i4", "uint": "u4"}


def object_points(path: Path, min_opacity: float) -> np.ndarray:
    """Tâm Gaussian đủ đục của một vật (toạ độ cục bộ)."""
    payload = path.read_bytes()
    end = payload.index(b"end_header\n") + len(b"end_header\n")
    header = payload[:end].decode("ascii").splitlines()
    count = next(int(line.split()[2]) for line in header if line.startswith("element vertex"))
    fields = [(line.split()[2], "<" + _PLY_TYPES[line.split()[1]]) for line in header if line.startswith("property")]
    rows = np.frombuffer(payload, dtype=np.dtype(fields), count=count, offset=end)
    xyz = np.stack([rows["x"], rows["y"], rows["z"]], axis=1).astype(np.float64)
    return xyz[1.0 / (1.0 + np.exp(-rows["opacity"].astype(np.float64))) >= min_opacity]


def occupancy_mesh(points: np.ndarray, voxel_m: float) -> trimesh.Trimesh:
    """Mặt bao của đám điểm: lưới chiếm chỗ → đóng lỗ → lấp ruột → marching cubes.

    Gaussian chỉ nằm trên bề mặt nhìn thấy nên ruột vật rỗng; lấp ruột để thể tích có nghĩa.
    """
    low = points.min(axis=0) - 2 * voxel_m
    shape = np.ceil((points.max(axis=0) + 2 * voxel_m - low) / voxel_m).astype(int) + 1
    grid = np.zeros(shape, dtype=bool)
    index = np.floor((points - low) / voxel_m).astype(int)
    grid[index[:, 0], index[:, 1], index[:, 2]] = True
    grid = ndimage.binary_closing(grid, iterations=2)
    grid = ndimage.binary_fill_holes(grid)
    vertices, faces, _, _ = measure.marching_cubes(np.pad(grid, 1).astype(np.float32), level=0.5)
    mesh = trimesh.Trimesh((vertices - 1) * voxel_m + low, faces, process=True)
    return mesh


def _limit(hulls: list[trimesh.Trimesh], limit: int) -> list[trimesh.Trimesh]:
    """CoACD không luôn tôn trọng `max_convex_hull`: giữ các khối lớn nhất, gộp phần còn lại thành một hull."""
    if len(hulls) <= limit:
        return hulls
    ordered = sorted(hulls, key=lambda hull: hull.volume, reverse=True)
    rest = trimesh.Trimesh(np.vstack([hull.vertices for hull in ordered[limit - 1 :]]), process=False).convex_hull
    return [*ordered[: limit - 1], rest]


def convex_parts(
    mesh: trimesh.Trimesh, config: dict, *, strict: bool = False, diagnostics: dict | None = None
) -> list[trimesh.Trimesh]:
    """CoACD; lỗi hoặc mesh suy biến → một convex hull (vẫn hợp lệ cho Isaac)."""
    if diagnostics is not None:
        diagnostics.update(method="coacd", fallback_reason=None)
    limit = int(config.get("max_convex_hull", 8))
    try:
        parts = coacd.run_coacd(
            coacd.Mesh(np.asarray(mesh.vertices), np.asarray(mesh.faces)),
            threshold=float(config.get("threshold", 0.08)),
            max_convex_hull=limit,
            preprocess_resolution=int(config.get("preprocess_resolution", 30)),
            seed=0,
        )
        hulls = [trimesh.Trimesh(vertices, faces, process=True) for vertices, faces in parts]
        valid = [
            hull for hull in hulls if len(hull.faces) >= 4 and hull.volume > 0 and np.isfinite(hull.vertices).all()
        ]
        if diagnostics is not None:
            diagnostics.update(raw_parts=len(hulls), invalid_parts_discarded=len(hulls) - len(valid))
        if strict and len(valid) != len(hulls):
            raise ValueError("CoACD returned invalid convex parts")
        hulls = valid
    except (RuntimeError, ValueError) as error:
        if diagnostics is not None:
            diagnostics.update(fallback_reason="coacd_error", error_type=type(error).__name__)
        if strict:
            raise
        hulls = []
    if strict:
        if not hulls or len(hulls) > limit:
            raise ValueError("CoACD returned no parts or exceeded the part budget; hull fallback is forbidden")
        return hulls
    if diagnostics is not None:
        diagnostics["raw_valid_parts"] = len(hulls)
        if not hulls:
            diagnostics.update(
                method="convex_hull", fallback_reason=diagnostics.get("fallback_reason") or "no_valid_coacd_parts"
            )
        elif len(hulls) > limit:
            diagnostics.update(method="coacd_with_hull_budget", fallback_reason="part_budget")
    return _limit(hulls, limit) or [mesh.convex_hull]


def surface_parts(item: dict, config: dict, diagnostics: dict | None = None) -> list[trimesh.Trimesh]:
    """Decompose verified object-local metre surface components without bridging their gaps."""
    if item.get("coordinate_frame") != "object_local" or item.get("distance_unit") != "m":
        raise ValueError("surface mesh input requires explicit object_local frame and metre units")
    path = Path(item["surface_mesh"])
    payload = path.read_bytes()
    if item.get("surface_checksum") != f"sha256:{hashlib.sha256(payload).hexdigest()}":
        raise ValueError("surface mesh checksum mismatch")
    mesh = load_surface(path)
    if not len(mesh.vertices) or not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError("surface mesh must contain finite vertices and triangles")
    mesh = clean_surface(mesh)
    quality = assess_surface(mesh)
    if diagnostics is not None:
        diagnostics["quality"] = quality
    if not quality["passed"]:
        raise ValueError("strict surface quality gate failed: " + ", ".join(quality["reasons"]))
    components = mesh.split(only_watertight=False, repair=False)
    if diagnostics is not None:
        diagnostics["surface_validation"] = {
            "components": len(components),
            "open_components": sum(not component.is_watertight for component in components),
            "vertices": len(mesh.vertices),
            "triangles": len(mesh.faces),
        }
    if not len(components) or any(not component.is_watertight for component in components):
        raise ValueError("surface mesh requires controlled repair before CoACD; open components are unsupported")
    hulls: list[trimesh.Trimesh] = []
    for component in components:
        if component.volume < 0:
            component.invert()
        if component.volume <= 0:
            raise ValueError("surface component has no positive volume")
        component_diagnostics = {} if diagnostics is not None else None
        try:
            hulls.extend(convex_parts(component, config, strict=True, diagnostics=component_diagnostics))
        finally:
            if diagnostics is not None:
                diagnostics.setdefault("component_decompositions", []).append(component_diagnostics)
    if len(hulls) > int(config.get("max_convex_hull", 8)):
        raise ValueError("surface parts exceed budget; merging disconnected components is forbidden")
    return hulls


def build_one(item: dict, config: dict) -> dict:
    """Collider của một vật; lỗi của một vật không làm hỏng cả lượt."""
    coacd.set_log_level("error")
    entry: dict = {"id": item["id"], "parts": 0, "volume_m3": 0.0, "method": "coacd", "fallback_reason": None}
    if "surface_mesh" in item:
        if "gaussians_ply" in item:
            return {**entry, "error": "ambiguous surface and Gaussian collider inputs"}
        if Path(item["surface_mesh"]).resolve() == Path(item["output_glb"]).resolve():
            return {**entry, "error": "surface input and collider output paths must differ"}
        Path(item["output_glb"]).unlink(missing_ok=True)
        try:
            hulls = surface_parts(item, config, entry)
        except (ValueError, RuntimeError, OSError) as error:
            return {
                **entry,
                "error": str(error),
                "source": "surface_mesh",
                "method": "failed",
                "fallback_allowed": False,
            }
    else:
        points = object_points(Path(item["gaussians_ply"]), float(config.get("min_opacity", 0.3)))
        if len(points) < int(config.get("min_points", 30)):
            return {**entry, "error": "too_few_points", "method": "failed"}
        hulls = convex_parts(occupancy_mesh(points, float(config.get("voxel_m", 0.04))), config, diagnostics=entry)
    scene = trimesh.Scene()
    for number, hull in enumerate(hulls):
        scene.add_geometry(hull, geom_name=f"part_{number:03d}")
    Path(item["output_glb"]).write_bytes(scene.export(file_type="glb"))
    return {
        **entry,
        "parts": len(hulls),
        "volume_m3": float(sum(hull.volume for hull in hulls)),
        "triangles": int(sum(len(hull.faces) for hull in hulls)),
    }


def build(request: dict) -> dict:
    """Dựng collider cho mọi vật trong request (song song theo vật); trả tóm tắt từng vật."""
    trace = recorder(request.get("evidence_dir"), "collider")
    config = request.get("config") or {}
    trace.emit(
        "config",
        thresholds=config,
        inputs=[
            {
                "seed": item["id"],
                "source": "surface_mesh" if "surface_mesh" in item else "gaussians",
                "surface_checksum": item.get("surface_checksum"),
            }
            for item in request["objects"]
        ],
    )
    # Mặc định dùng gần hết số nhân được cấp (theo affinity/cgroup của tiến trình), chừa 1 nhân cho bước GPU
    # chạy song song; không cần nhiều tiến trình hơn số vật.
    cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 2)
    workers = int(config.get("workers") or max(1, min(len(request["objects"]), cores - 1)))
    items = request["objects"]
    if workers <= 1 or len(items) <= 1:
        results = [build_one(item, config) for item in items]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(build_one, items, [config] * len(items)))
    for item in results:
        trace.emit("result", **item)
    return {"voxel_m": float(config.get("voxel_m", 0.04)), "objects": results}


def main() -> int:
    """CLI: request JSON → GLB collider từng vật + result JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    summary = build(json.loads(args.request.read_text(encoding="utf-8")))
    args.result.write_text(json.dumps(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
