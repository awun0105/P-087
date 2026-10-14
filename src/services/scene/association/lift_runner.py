"""Gán nhãn vật cho từng Gaussian theo đóng góp khi render (ADR 0007, chặng 4–5).

Hạt giống của bước tách vật (SAMPro3D) chỉ là các tâm Gaussian đủ đục được nhìn thấy; hình của một
vật lại do nhiều Gaussian chồng lên nhau tạo ra (cả Gaussian lớn và mờ). Gán theo khoảng cách bỏ sót
phần lớn → vật bị bỏ ra khỏi nền vẫn còn "bóng". Runner này gán theo cách của FlashSplat (lifting
mask 2D lên 3DGS không cần train):

1. mỗi góc camera: ảnh đã khử méo → SAM2; mỗi vật lấy vài hạt giống đang nhìn thấy làm điểm gợi ý →
   mask 2D của vật ở góc đó;
2. render tuyến tính theo màu: đặt màu mỗi Gaussian là biến c_i (C kênh), ảnh ra = Σ_i w_i(p)·c_i.
   Lấy loss = Σ_p ⟨ảnh(p), onehot(nhãn(p))⟩ thì ∂loss/∂c_i[k] = tổng trọng số trộn của Gaussian i trên
   các điểm ảnh thuộc vật k — một lượt backward cho toàn bộ ma trận đóng góp;
3. cộng dồn qua các góc; Gaussian thuộc vật k nếu, trong các góc mà k có mask, quá nửa đóng góp của
   nó rơi vào điểm ảnh của k.

Script độc lập (torch, gsplat, sam2, cv2), chạy trong `data/scene_runtime`.

    <scene_runtime>/bin/python lift_runner.py --request request.json --result result.json
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from gsplat import rasterization

_PLY_TYPES = {"float": "f4", "float32": "f4", "double": "f8", "uchar": "u1", "int": "i4", "uint": "u4"}
#: Số kênh gsplat hỗ trợ sẵn gần nhất: 31 vật + 1 kênh "còn lại".
_CHUNK = 31


def read_ply(path: Path) -> np.ndarray:
    """PLY 3DGS nhị phân → mảng có cấu trúc."""
    payload = path.read_bytes()
    end = payload.index(b"end_header\n") + len(b"end_header\n")
    header = payload[:end].decode("ascii").splitlines()
    count = next(int(line.split()[2]) for line in header if line.startswith("element vertex"))
    fields = [(line.split()[2], "<" + _PLY_TYPES[line.split()[1]]) for line in header if line.startswith("property")]
    return np.frombuffer(payload, dtype=np.dtype(fields), count=count, offset=end)


def rotation(quaternion: list[float]) -> np.ndarray:
    """Quaternion xyzw → ma trận xoay."""
    x, y, z, w = quaternion
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def pinhole(view: dict, width: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    """(viewmat, K đã co, hệ số méo OpenCV, width, height). K gốc dùng để khử méo ảnh."""
    parameters = view["parameters"]
    distortion = np.zeros(4)
    if view["model"] == "SIMPLE_PINHOLE":
        fx = fy = parameters[0]
        cx, cy = parameters[1], parameters[2]
    elif view["model"] == "SIMPLE_RADIAL":
        fx = fy = parameters[0]
        cx, cy = parameters[1], parameters[2]
        distortion[0] = parameters[3]
    elif view["model"] == "PINHOLE":
        fx, fy, cx, cy = parameters[:4]
    elif view["model"] == "OPENCV":
        fx, fy, cx, cy = parameters[:4]
        distortion = np.asarray(parameters[4:8], dtype=float)
    else:
        raise ValueError(f"mô hình camera chưa hỗ trợ: {view['model']}")
    ratio = width / view["width"]
    height = int(round(view["height"] * ratio))
    world_from_camera = rotation(view["rotation_xyzw"])
    viewmat = np.eye(4)
    viewmat[:3, :3] = world_from_camera.T
    viewmat[:3, 3] = -world_from_camera.T @ np.asarray(view["center"])
    intrinsics = np.array([[fx * ratio, 0, cx * ratio], [0, fy * ratio, cy * ratio], [0, 0, 1]])
    return viewmat, intrinsics, distortion, width, height


def undistorted_image(view: dict, distortion: np.ndarray, width: int, height: int) -> np.ndarray:
    """Ảnh RGB đã khử méo, co về (width, height) — cùng camera pinhole với ảnh render."""
    image = cv2.cvtColor(cv2.imread(view["image_path"], cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    if np.any(distortion):
        parameters = view["parameters"]
        fx = parameters[0]
        fy = fx if view["model"].startswith("SIMPLE") else parameters[1]
        cx, cy = (
            (parameters[1], parameters[2]) if view["model"].startswith("SIMPLE") else (parameters[2], parameters[3])
        )
        full = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
        image = cv2.undistort(image, full, distortion)
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def spread_prompts(pixels: np.ndarray, count: int) -> np.ndarray:
    """`count` điểm trải đều (farthest point) trong các điểm ảnh của hạt giống; lặp lại nếu thiếu."""
    chosen = [int(np.argmin(np.linalg.norm(pixels - np.median(pixels, axis=0), axis=1)))]
    distance = np.linalg.norm(pixels - pixels[chosen[0]], axis=1)
    while len(chosen) < min(count, len(pixels)):
        chosen.append(int(distance.argmax()))
        distance = np.minimum(distance, np.linalg.norm(pixels - pixels[chosen[-1]], axis=1))
    return pixels[(chosen * count)[:count]]


def run(request: dict) -> dict:
    """Tính nhãn cho mọi Gaussian; ghi `labels` (int32, -1 = nền) vào `output_npz`."""
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    config = request.get("config") or {}
    device = torch.device("cuda")
    rows = read_ply(Path(request["gaussians_ply"]))
    count = len(rows)
    means = torch.from_numpy(np.stack([rows["x"], rows["y"], rows["z"]], axis=1).astype(np.float32)).to(device)
    quats = torch.nn.functional.normalize(
        torch.from_numpy(np.stack([rows[f"rot_{i}"] for i in range(4)], axis=1).astype(np.float32)).to(device), dim=-1
    )
    scales = torch.exp(
        torch.from_numpy(np.stack([rows[f"scale_{i}"] for i in range(3)], axis=1).astype(np.float32)).to(device)
    )
    opacities = torch.sigmoid(torch.from_numpy(rows["opacity"].astype(np.float32)).to(device))

    seeds_file = np.load(request["seeds_npz"])
    offsets, members = seeds_file["offsets"], seeds_file["members"]
    seeds = [members[offsets[i] : offsets[i + 1]] for i in range(len(offsets) - 1)]
    objects = len(seeds)
    seed_label = np.full(count, -1, dtype=np.int32)
    for index in reversed(range(objects)):
        seed_label[seeds[index]] = index
    seed_index = np.nonzero(seed_label >= 0)[0]
    seed_xyz = means[torch.from_numpy(seed_index).to(device)]

    predictor = SAM2ImagePredictor(build_sam2(request["sam2_config"], request["sam2_checkpoint"], device="cuda"))
    width = int(config.get("width", 640))
    prompts_per_object = int(config.get("prompts", 4))
    #: Số vật hỏi SAM2 trong một lô; tự giảm khi hết VRAM (xem vòng lặp dự đoán).
    sam_batch = int(config.get("sam_batch", 32))
    min_visible = int(config.get("min_visible_seeds", 8))
    contribution = torch.zeros((count, objects), dtype=torch.float32)
    # Tổng đóng góp của Gaussian i trong các góc mà vật k có mask: mẫu số riêng cho từng vật, để góc
    # không có mask của k (điểm ảnh của k bị coi là nền) không kéo Gaussian của k về nền.
    seen_with = torch.zeros((count, objects), dtype=torch.float32)
    masks_per_object = np.zeros(objects, dtype=np.int32)
    objectgs_views: list[dict] = []
    observations_dir = Path(request["objectgs_observations_dir"]) if request.get("objectgs_observations_dir") else None
    views = request["views"][:: max(1, int(config.get("view_step", 1)))]
    debug_dir = Path(request["debug_dir"]) if request.get("debug_dir") else None
    depth_color = torch.zeros((count, 1), device=device)

    for number, view in enumerate(views):
        viewmat_np, intrinsics_np, distortion, w, h = pinhole(view, width)
        viewmat = torch.from_numpy(viewmat_np).float().to(device)
        intrinsics = torch.from_numpy(intrinsics_np).float().to(device)
        with torch.no_grad():
            rendered, _, _ = rasterization(
                means,
                quats,
                scales,
                opacities,
                depth_color,
                viewmat[None],
                intrinsics[None],
                w,
                h,
                sh_degree=None,
                render_mode="RGB+ED",
            )
            depth = rendered[0, ..., 1]
            camera_points = (seed_xyz @ viewmat[:3, :3].T) + viewmat[:3, 3]
            z = camera_points[:, 2]
            u = camera_points[:, 0] / z.clamp(min=1e-6) * intrinsics[0, 0] + intrinsics[0, 2]
            v = camera_points[:, 1] / z.clamp(min=1e-6) * intrinsics[1, 1] + intrinsics[1, 2]
            inside = (z > 0.1) & (u >= 0) & (u < w - 1) & (v >= 0) & (v < h - 1)
            ui, vi = u.long().clamp(0, w - 1), v.long().clamp(0, h - 1)
            visible = inside & (z <= depth[vi, ui] + torch.maximum(torch.full_like(z, 0.1), 0.05 * z))
        visible_np = visible.cpu().numpy()
        pixels = np.stack([u.cpu().numpy(), v.cpu().numpy()], axis=1)
        labels_of_visible = seed_label[seed_index]
        candidates = []
        for index in range(objects):
            chosen = visible_np & (labels_of_visible == index)
            if chosen.sum() >= min_visible:
                candidates.append((index, pixels[chosen]))
        if not candidates:
            continue
        image = undistorted_image(view, distortion, w, h)
        accepted: list[tuple[int, np.ndarray]] = []
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            predictor.set_image(image)
            start = 0
            while start < len(candidates):
                chunk = candidates[start : start + sam_batch]
                coords = np.stack([spread_prompts(points, prompts_per_object) for _, points in chunk]).astype(
                    np.float32
                )
                try:
                    masks, scores, _ = predictor.predict(
                        point_coords=coords, point_labels=np.ones(coords.shape[:2]), multimask_output=False
                    )
                except torch.cuda.OutOfMemoryError:
                    # Hết VRAM: giảm nửa lô và làm lại đúng lô này; lô nhỏ hơn được giữ cho các view sau.
                    if sam_batch == 1:
                        raise
                    torch.cuda.empty_cache()
                    sam_batch = max(1, sam_batch // 2)
                    continue
                start += len(chunk)
                masks = masks.reshape(len(chunk), h, w) > 0
                for (index, points), mask, score in zip(chunk, masks, scores.reshape(-1), strict=True):
                    hit = mask[points[:, 1].astype(int), points[:, 0].astype(int)].mean()
                    area = mask.mean()
                    if (
                        score >= float(config.get("min_score", 0.6))
                        and hit >= 0.5
                        and area <= float(config.get("max_area", 0.35))
                    ):
                        accepted.append((index, mask))
        if not accepted:
            continue
        # Mask nhỏ vẽ sau cùng: vật nhỏ nằm trước/trong vật lớn giữ được điểm ảnh của mình.
        accepted.sort(key=lambda item: item[1].sum(), reverse=True)
        label_image = np.full((h, w), -1, dtype=np.int32)
        for index, mask in accepted:
            label_image[mask] = index
            masks_per_object[index] += 1
        if observations_dir is not None:
            observations_dir.mkdir(parents=True, exist_ok=True)
            image_path = observations_dir / f"view-{number:06d}.png"
            mask_path = observations_dir / f"view-{number:06d}.labels.npy"
            if not cv2.imwrite(str(image_path), image[..., ::-1]):
                raise RuntimeError("could not persist calibrated ObjectGS observation")
            np.save(mask_path, label_image, allow_pickle=False)
            objectgs_views.append(
                {
                    "image_path": str(image_path),
                    "mask_path": str(mask_path),
                    "width": w,
                    "height": h,
                    "center": view["center"],
                    "rotation_xyzw": view["rotation_xyzw"],
                    "parameters": [
                        float(intrinsics_np[0, 0]),
                        float(intrinsics_np[1, 1]),
                        float(intrinsics_np[0, 2]),
                        float(intrinsics_np[1, 2]),
                    ],
                    "camera_model": "PINHOLE",
                    "coordinate_frame": "world",
                    "distance_unit": "m",
                }
            )
        present = sorted({index for index, _ in accepted})
        label_tensor = torch.from_numpy(label_image).to(device)
        for start in range(0, len(present), _CHUNK):
            chunk_ids = present[start : start + _CHUNK]
            channels = len(chunk_ids) + 1
            target = torch.zeros((h, w, channels), device=device)
            for channel, index in enumerate(chunk_ids):
                target[..., channel] = label_tensor == index
            target[..., -1] = 1.0 - target[..., :-1].sum(dim=-1)
            colors = torch.zeros((count, channels), device=device, requires_grad=True)
            image_out, _, _ = rasterization(
                means, quats, scales, opacities, colors, viewmat[None], intrinsics[None], w, h, sh_degree=None
            )
            (image_out[0] * target).sum().backward()
            gradient = colors.grad.detach().cpu()
            contribution[:, chunk_ids] += gradient[:, :-1]
            if start == 0:
                seen_with[:, present] += gradient.sum(dim=1, keepdim=True)
        if debug_dir is not None and number % max(1, len(views) // 6) == 0:
            debug_dir.mkdir(parents=True, exist_ok=True)
            palette = np.random.default_rng(0).integers(60, 255, size=(objects + 1, 3), dtype=np.uint8)
            overlay = np.where(label_image[..., None] >= 0, palette[label_image], image // 2).astype(np.uint8)
            cv2.imwrite(str(debug_dir / f"masks_{number:04d}.jpg"), np.concatenate([image, overlay], axis=1)[..., ::-1])

    share = contribution / seen_with.clamp(min=1e-6)
    share[contribution < float(config.get("min_contribution", 0.05))] = 0.0
    # Ràng buộc không gian: đóng góp render tính cả Gaussian nằm xa phía sau trên cùng tia nhìn (nền, đốm
    # lơ lửng). Chỉ nhận Gaussian nằm trong hộp bao hạt giống của vật, nới mỗi phía max(biên tối thiểu, tỉ lệ cạnh).
    positions = means.cpu()
    margin_min = float(config.get("box_margin_m", 0.15))
    margin_ratio = float(config.get("box_margin_ratio", 0.2))
    for index, seed in enumerate(seeds):
        points = positions[torch.from_numpy(np.asarray(seed, dtype=np.int64))]
        low, high = points.min(dim=0).values, points.max(dim=0).values
        margin = torch.clamp((high - low) * margin_ratio, min=margin_min)
        outside = ((positions < low - margin) | (positions > high + margin)).any(dim=1)
        share[outside, index] = 0.0
    best_share, best = share.max(dim=1)
    assigned = best_share > float(config.get("majority", 0.5))
    labels = torch.where(assigned, best, torch.full_like(best, -1)).numpy().astype(np.int32)
    np.savez(request["output_npz"], labels=labels)
    return {
        "method": "render_contribution_lift_v1",
        "gaussians": count,
        "objects": objects,
        "assigned": int((labels >= 0).sum()),
        "seed_gaussians": int(len(seed_index)),
        "views": len(views),
        "masks_per_object": masks_per_object.tolist(),
        "per_object": np.bincount(labels[labels >= 0], minlength=objects).tolist(),
        "objectgs_views": objectgs_views,
    }


def main() -> int:
    """CLI: request JSON → nhãn npz + result JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    summary = run(json.loads(args.request.read_text(encoding="utf-8")))
    args.result.write_text(json.dumps(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
