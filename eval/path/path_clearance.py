"""Benchmark `collision_path_clearance`: collision mesh có chặn giả đường robot đã thật sự đi không.

Camera Aisle_CW gắn trên robot OTTO, nên capsule robot đặt tại mọi vị trí camera (chiếu
xuống sàn) phải trống. Mesh chiếm chỗ trong capsule đó là vật cản giả (ghost-block, REC-05
§tiêu chí 1). Dùng pipeline REC-05 (lọc + fill theo profile + clearance + carve) ở nhiều mức voxel.

Không dùng GT: chỉ dùng camera canonical của chính scene (sản phẩm) và mesh REC-05.

    python -m eval.path.path_clearance --input-ply <metric input.ply> --poses <canonical camera_poses.json> \\
        --profile configs/product/geometry_v1.json --gpu 1 --label aisle-cw-local-t2000 \\
        --work <scratch dir> --out eval/results/collision_path_clearance/aisle-cw-local-t2000.jsonl
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from src.services.reconstruction.adapters.collision_glb import canonicalize_collision, topology
from src.services.reconstruction.adapters.voxel import SplatTransformVoxelAdapter
from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess, VoxelRuntimeSettings
from src.services.reconstruction.finalize import GeometryProfile, build_voxel_config, floor_seed


def blocked_positions(vertices: np.ndarray, centers: np.ndarray, radius: float, height: float) -> list[int]:
    """Chỉ số camera có đỉnh mesh nằm trong capsule robot (trục đứng qua camera, từ sàn lên)."""
    body = vertices[(vertices[:, 2] > 0.03) & (vertices[:, 2] < height)]
    blocked = []
    for index, center in enumerate(centers):
        gaps = np.hypot(body[:, 0] - center[0], body[:, 1] - center[1])
        if (gaps < radius).any():
            blocked.append(index)
    return blocked


def run(args: argparse.Namespace) -> list[dict]:
    profile = GeometryProfile.model_validate_json(args.profile.read_text())
    poses = json.loads(args.poses.read_text())["poses"]
    centers = np.array([pose["translation"] for pose in sorted(poses, key=lambda item: item["frame_id"])])
    seed = floor_seed(tuple(centers[0]), profile)
    crop = (
        (
            centers[:, 0].min() - profile.crop_margin_m,
            centers[:, 1].min() - profile.crop_margin_m,
            -profile.crop_below_floor_m,
        ),
        (
            centers[:, 0].max() + profile.crop_margin_m,
            centers[:, 1].max() + profile.crop_margin_m,
            profile.crop_height_m,
        ),
    )
    process = VoxelProcess(VoxelRuntimeSettings())
    adapter = SplatTransformVoxelAdapter(process)
    rows = []
    for resolution in args.resolutions:
        workspace = args.work / f"res-{resolution}"
        workspace.mkdir(parents=True, exist_ok=False)
        (workspace / "input.ply").symlink_to(args.input_ply.resolve())
        start = time.monotonic()
        row: dict = {"resolution_m": resolution}
        try:
            config = build_voxel_config(
                profile.model_copy(update={"resolution_m": resolution, "gpu_index": args.gpu}), crop, seed
            )
            # Technical evaluation of an already metric input; no product confirmation or publication is asserted.
            adapter._pipeline(config, workspace)
            mesh = canonicalize_collision(workspace / "geometry.collision.glb", workspace / "collision.glb")
            vertices = np.array(mesh.positions, dtype=float)
            blocked = blocked_positions(vertices, centers, profile.capsule_radius_m, profile.capsule_height_m)
            row |= {
                "status": "ok",
                "seconds": round(time.monotonic() - start, 2),
                "triangles": topology(mesh)["triangles"],
                "camera_positions": len(centers),
                "blocked_positions": len(blocked),
                "blocked_fraction": round(len(blocked) / len(centers), 4),
                "blocked_frame_indices": blocked,
            }
        except (ValueError, OSError) as error:
            row |= {"status": "failed", "seconds": round(time.monotonic() - start, 2), "error": type(error).__name__}
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    """Ghi mỗi mức voxel một dòng JSONL (append) theo quy ước eval/protocols/BENCHMARKS.md."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-ply", type=Path, required=True)
    parser.add_argument("--poses", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--resolutions", type=float, nargs="+", default=[0.10, 0.05, 0.025])
    parser.add_argument("--label", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = run(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    measured_at = datetime.now(UTC).isoformat()
    with args.out.open("a", encoding="utf-8") as stream:
        for row in rows:
            record = {"benchmark": "collision_path_clearance", "label": args.label, "measured_at": measured_at, **row}
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(json.dumps({k: v for k, v in record.items() if k != "blocked_frame_indices"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
