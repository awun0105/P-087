"""Bước SAM2 của SAMPro3D (ADR 0006), chạy trong runtime riêng `data/scene_runtime` (torch + sam2).

ADAPT từ `R2G/src/sampro3d/3d_prompt_proposal.py` (Apache-2.0, Mutian Xu, Xingyilang Yin):
prompt 3D → chiếu vào từng frame → SAM point prompt → lưu mask. Khác bản gốc:
- SAM2 (`SAM2ImagePredictor`) thay SAM ViT-H;
- không có ảnh depth → lọc che khuất bằng z-buffer của chính point cloud;
- không lưu mask ảnh đầy đủ; chỉ lưu chỉ số điểm 3D nhìn thấy nằm trong mask (gọn, đủ để bỏ phiếu).

Script độc lập: chỉ dùng numpy/torch/PIL/sam2, không import code app (runtime không có pydantic).

    <scene_runtime>/bin/python sam2_runner.py --request request.json --output result.npz
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diagnostics import recorder  # noqa: E402


def _rotation(quaternion: list[float]) -> np.ndarray:
    x, y, z, w = quaternion
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def project(points: np.ndarray, view: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(u, v, depth) theo mô hình camera COLMAP; điểm sau camera có depth ≤ 0."""
    camera = (points - np.asarray(view["center"])) @ _rotation(view["rotation_xyzw"])  # R^T (p - c)
    depth = camera[:, 2]
    safe = np.where(depth > 1e-6, depth, 1e-6)
    x, y = camera[:, 0] / safe, camera[:, 1] / safe
    p = view["parameters"]
    model = view["model"]
    if model == "SIMPLE_PINHOLE":
        fx = fy = p[0]
        cx, cy = p[1], p[2]
        dx, dy = x, y
    elif model == "PINHOLE":
        fx, fy, cx, cy = p[:4]
        dx, dy = x, y
    elif model == "SIMPLE_RADIAL":
        fx = fy = p[0]
        cx, cy, k = p[1], p[2], p[3]
        radial = 1 + k * (x * x + y * y)
        dx, dy = x * radial, y * radial
    elif model == "OPENCV":
        fx, fy, cx, cy, k1, k2, p1, p2 = p[:8]
        r2 = x * x + y * y
        radial = 1 + k1 * r2 + k2 * r2 * r2
        dx = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        dy = y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
    else:
        raise ValueError(f"mô hình camera chưa hỗ trợ: {model}")
    return fx * dx + cx, fy * dy + cy, depth


def visible_points(points: np.ndarray, view: dict, cell: int, tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    """Chỉ số điểm nhìn thấy + toạ độ pixel nguyên; che khuất bằng z-buffer theo ô `cell` pixel."""
    u, v, depth = project(points, view)
    width, height = view["width"], view["height"]
    inside = (depth > 0.1) & (u >= 0) & (u < width) & (v >= 0) & (v < height)
    index = np.nonzero(inside)[0]
    if not len(index):
        return index, np.zeros((0, 2), dtype=np.int64)
    cu = (u[index] // cell).astype(np.int64)
    cv = (v[index] // cell).astype(np.int64)
    key = cv * (width // cell + 1) + cu
    nearest = np.full(key.max() + 1, np.inf)
    np.minimum.at(nearest, key, depth[index])
    front = depth[index] <= nearest[key] + np.maximum(tolerance, 0.03 * nearest[key])
    kept = index[front]
    pixels = np.stack([u[kept], v[kept]], axis=1).astype(np.int64)
    return kept, pixels


def run(request: dict, output: Path) -> None:
    import torch
    from PIL import Image
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    trace = recorder(request.get("evidence_dir"), "sam2")
    trace.emit("started", views=len(request["views"]), checkpoint_name=Path(request["checkpoint"]).name)
    data = np.load(request["points_npz"])
    points, prompts = data["points"].astype(float), data["prompts"].astype(np.int64)
    model = build_sam2(request["config"], request["checkpoint"], device="cuda")
    predictor = SAM2ImagePredictor(model)
    prompt_set = {int(p): i for i, p in enumerate(prompts)}
    rec_view, rec_prompt, rec_iou, offsets, members = [], [], [], [0], []
    vis_offsets, vis_members = [0], []
    batch = int(request.get("batch", 64))
    for view_index, view in enumerate(request["views"]):
        trace.emit(
            "view_binding",
            view=view_index,
            frame_id=view.get("frame_id", Path(view["image_path"]).name),
            width=view.get("width"),
            height=view.get("height"),
            camera_model=view.get("model"),
        )
        kept, pixels = visible_points(
            points, view, int(request["zbuffer_cell_px"]), float(request["depth_tolerance_m"])
        )
        vis_members.append(kept)
        vis_offsets.append(vis_offsets[-1] + len(kept))
        position = {int(point): row for row, point in enumerate(kept)}
        prompt_rows = [(prompt_set[int(p)], position[int(p)]) for p in prompts if int(p) in position]
        if not prompt_rows:
            continue
        image = np.array(Image.open(view["image_path"]).convert("RGB"))
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            predictor.set_image(image)
            for start in range(0, len(prompt_rows), batch):
                chunk = prompt_rows[start : start + batch]
                coords = pixels[[row for _, row in chunk]].astype(np.float32)[:, None, :]
                masks, scores, _ = predictor.predict(
                    point_coords=coords, point_labels=np.ones((len(chunk), 1)), multimask_output=False
                )
                masks = masks.reshape(len(chunk), masks.shape[-2], masks.shape[-1]) > 0
                hits = masks[:, pixels[:, 1], pixels[:, 0]]  # (chunk, visible points)
                for (prompt_id, _), hit, score, mask in zip(chunk, hits, scores.reshape(-1), masks, strict=True):
                    selected = kept[hit]
                    trace.emit(
                        "mask_generated",
                        view=view_index,
                        prompt=int(prompt_id),
                        predicted_iou=float(score),
                        points=len(selected),
                    )
                    if trace.enabled:
                        trace.mask(f"view:{view_index}/prompt:{prompt_id}", np.packbits(mask).tobytes(), mask.shape)
                    rec_view.append(view_index)
                    rec_prompt.append(prompt_id)
                    rec_iou.append(float(score))
                    members.append(selected)
                    offsets.append(offsets[-1] + len(selected))
        predictor.reset_predictor()
        print(json.dumps({"view": view_index, "visible": int(len(kept)), "prompts": len(prompt_rows)}), flush=True)
    trace.emit("completed", records=len(rec_view))
    np.savez_compressed(
        output,
        view=np.asarray(rec_view, dtype=np.int32),
        prompt=np.asarray(rec_prompt, dtype=np.int32),
        iou=np.asarray(rec_iou, dtype=np.float32),
        offsets=np.asarray(offsets, dtype=np.int64),
        members=np.concatenate(members) if members else np.zeros(0, dtype=np.int64),
        visible_offsets=np.asarray(vis_offsets, dtype=np.int64),
        visible_members=np.concatenate(vis_members) if vis_members else np.zeros(0, dtype=np.int64),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="SAMPro3D prompt proposal với SAM2")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.request.read_text()), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
