"""Collider phân rã lồi cho từng vật từ Gaussian của nó (ADR 0007, chặng 6).

Isaac không cho rigid body động dùng triangle mesh (rơi về convex hull) → mỗi vật cần vài khối lồi.
Quy trình: tâm Gaussian đủ đục → lưới chiếm chỗ (voxel) → đóng lỗ → marching cubes → CoACD.
Thể tích các khối lồi dùng để suy khối lượng (mật độ × thể tích).

Chạy trong runtime có `coacd`, `scikit-image`, `trimesh` (`data/scene_runtime`); script độc lập.
Mỗi vật ghi một GLB chứa các khối lồi (mỗi khối một mesh), toạ độ cục bộ của vật.

    <scene_runtime>/bin/python convex_runner.py --request request.json --result result.json
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import coacd
import numpy as np
import trimesh
from scipy import ndimage
from skimage import measure

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


def convex_parts(mesh: trimesh.Trimesh, config: dict) -> list[trimesh.Trimesh]:
    """CoACD; lỗi hoặc mesh suy biến → một convex hull (vẫn hợp lệ cho Isaac)."""
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
        hulls = [hull for hull in hulls if len(hull.faces) >= 4 and hull.volume > 0]
    except (RuntimeError, ValueError):
        hulls = []
    return _limit(hulls, limit) or [mesh.convex_hull]


def build_one(item: dict, config: dict) -> dict:
    """Collider của một vật; lỗi của một vật không làm hỏng cả lượt."""
    coacd.set_log_level("error")
    entry: dict = {"id": item["id"], "parts": 0, "volume_m3": 0.0}
    points = object_points(Path(item["gaussians_ply"]), float(config.get("min_opacity", 0.3)))
    if len(points) < int(config.get("min_points", 30)):
        return {**entry, "error": "too_few_points"}
    hulls = convex_parts(occupancy_mesh(points, float(config.get("voxel_m", 0.04))), config)
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
    config = request.get("config") or {}
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
