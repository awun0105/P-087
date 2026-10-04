"""Vá nền 3DGS ở vùng vật từng che (ADR 0007, chặng 7) — không train lại.

Sau khi tách Gaussian của các vật ra khỏi scene, nền có lỗ ở những chỗ chưa camera nào nhìn thấy
(sàn dưới pallet, kệ sau thùng). Với từng góc camera, theo thứ tự:

1. render nền hiện tại (màu, alpha, độ sâu) và render riêng các vật đã tách (alpha, độ sâu);
2. vùng thủng = chỗ vật che **và** nền phía sau gần như trống (alpha thấp);
3. vá màu vùng thủng bằng LaMa (TorchScript `big-lama.pt`; không có thì `cv2.inpaint`);
4. độ sâu vùng thủng = nội suy độ sâu nền xung quanh, ép nằm sau bề mặt vật;
5. chiếu ngược điểm ảnh đã vá thành Gaussian mới (đẳng hướng, SH bậc 0) và **thêm vào nền**.

Vì Gaussian mới được thêm ngay, góc camera kế tiếp đã nhìn thấy chúng nên vùng thủng nhỏ dần và
các góc khớp nhau mà không cần tối ưu. Gaussian vá được ghi ở **cuối** file PLY; số lượng nằm trong
result để app đánh dấu "hình suy đoán" (PRD v1.16 §4.3.1).

Ý tưởng vá 2D rồi đưa lên 3D theo Gaussian Grouping (`docs/edit_removal_inpaint.md`, Apache-2.0);
phần gieo Gaussian theo độ sâu thay cho bước fine-tune của bản gốc. Script độc lập (torch, gsplat,
numpy, cv2), chạy trong `data/scene_runtime`.

    <scene_runtime>/bin/python inpaint_runner.py --request request.json --result result.json
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from gsplat import rasterization

_PLY_TYPES = {"float": "f4", "float32": "f4", "double": "f8", "uchar": "u1", "int": "i4", "uint": "u4"}
_SH_C0 = 0.28209479177387814


def read_ply(path: Path) -> np.ndarray:
    """PLY 3DGS nhị phân → mảng có cấu trúc (bản sao ghi được)."""
    payload = path.read_bytes()
    end = payload.index(b"end_header\n") + len(b"end_header\n")
    header = payload[:end].decode("ascii").splitlines()
    count = next(int(line.split()[2]) for line in header if line.startswith("element vertex"))
    fields = [(line.split()[2], "<" + _PLY_TYPES[line.split()[1]]) for line in header if line.startswith("property")]
    return np.frombuffer(payload, dtype=np.dtype(fields), count=count, offset=end).copy()


def write_ply(path: Path, rows: np.ndarray) -> None:
    """Ghi PLY cùng thứ tự field (mọi field float32)."""
    lines = ["ply", "format binary_little_endian 1.0", f"element vertex {len(rows)}"]
    lines += [f"property float {name}" for name in rows.dtype.names or ()] + ["end_header"]
    path.write_bytes(("\n".join(lines) + "\n").encode("ascii") + np.ascontiguousarray(rows).tobytes())


class Splats:
    """Gaussian trên GPU ở dạng gsplat cần (đã kích hoạt), thêm được Gaussian mới."""

    def __init__(self, rows: np.ndarray, device: torch.device) -> None:
        names = rows.dtype.names or ()
        self.device = device
        rest = sorted((name for name in names if name.startswith("f_rest_")), key=lambda name: int(name[7:]))
        self.coefficients = len(rest) // 3 + 1
        self.degree = int(round(np.sqrt(self.coefficients))) - 1
        self.means = self._tensor(np.stack([rows["x"], rows["y"], rows["z"]], axis=1))
        self.quats = torch.nn.functional.normalize(
            self._tensor(np.stack([rows[f"rot_{i}"] for i in range(4)], axis=1)), dim=-1
        )
        self.scales = torch.exp(self._tensor(np.stack([rows[f"scale_{i}"] for i in range(3)], axis=1)))
        self.opacities = torch.sigmoid(self._tensor(rows["opacity"]))
        dc = np.stack([rows[f"f_dc_{i}"] for i in range(3)], axis=1)[:, None, :]
        if rest:
            higher = np.stack([rows[name] for name in rest], axis=1).reshape(len(rows), 3, -1).transpose(0, 2, 1)
            dc = np.concatenate([dc, higher], axis=1)
        self.colors = self._tensor(dc)

    def _tensor(self, array: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.ascontiguousarray(array, dtype=np.float32)).to(self.device)

    def append(self, means: torch.Tensor, scale: torch.Tensor, rgb: torch.Tensor, opacity: float) -> None:
        """Thêm Gaussian đẳng hướng màu `rgb` (0..1): chỉ có SH bậc 0."""
        count = len(means)
        colors = torch.zeros((count, self.coefficients, 3), device=self.device)
        colors[:, 0, :] = (rgb - 0.5) / _SH_C0
        identity = torch.zeros((count, 4), device=self.device)
        identity[:, 0] = 1.0
        self.means = torch.cat([self.means, means])
        self.quats = torch.cat([self.quats, identity])
        self.scales = torch.cat([self.scales, scale[:, None].expand(-1, 3)])
        self.opacities = torch.cat([self.opacities, torch.full((count,), opacity, device=self.device)])
        self.colors = torch.cat([self.colors, colors])

    @torch.no_grad()
    def render(self, viewmat: torch.Tensor, intrinsics: torch.Tensor, width: int, height: int) -> tuple:
        """(rgb HxWx3, alpha HxW, depth HxW kỳ vọng) trên GPU."""
        if not len(self.means):
            zeros = torch.zeros((height, width), device=self.device)
            return torch.zeros((height, width, 3), device=self.device), zeros, zeros
        image, alpha, _ = rasterization(
            self.means,
            self.quats,
            self.scales,
            self.opacities,
            self.colors,
            viewmat[None],
            intrinsics[None],
            width,
            height,
            sh_degree=self.degree,
            render_mode="RGB+ED",
        )
        return image[0, ..., :3].clamp(0, 1), alpha[0, ..., 0], image[0, ..., 3]

    def rows(self, template: np.ndarray, original: int) -> np.ndarray:
        """Mảng PLY: `original` hàng đầu giữ nguyên byte gốc, phần thêm ghi ở cuối."""
        added = len(self.means) - original
        out = np.zeros(original + added, dtype=template.dtype)
        out[:original] = template[:original]
        if not added:
            return out
        means = self.means[original:].cpu().numpy()
        out["x"][original:], out["y"][original:], out["z"][original:] = means[:, 0], means[:, 1], means[:, 2]
        out["rot_0"][original:] = 1.0
        log_scale = torch.log(self.scales[original:]).cpu().numpy()
        for axis in range(3):
            out[f"scale_{axis}"][original:] = log_scale[:, axis]
        opacity = self.opacities[original:].clamp(1e-4, 1 - 1e-4)
        out["opacity"][original:] = torch.log(opacity / (1 - opacity)).cpu().numpy()
        dc = self.colors[original:, 0, :].cpu().numpy()
        for channel in range(3):
            out[f"f_dc_{channel}"][original:] = dc[:, channel]
        return out


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


def camera(view: dict, width: int) -> tuple[np.ndarray, np.ndarray, int, int]:
    """(viewmat world→camera 4x4, K 3x3, width, height) đã co về `width`; bỏ qua méo ống kính.

    Ảnh render chỉ để vá và chiếu ngược bằng chính camera pinhole này nên tự nhất quán.
    """
    parameters = view["parameters"]
    if view["model"] in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL"):
        fx = fy = parameters[0]
        cx, cy = parameters[1], parameters[2]
    else:
        fx, fy, cx, cy = parameters[:4]
    ratio = width / view["width"]
    height = int(round(view["height"] * ratio))
    world_from_camera = rotation(view["rotation_xyzw"])
    viewmat = np.eye(4)
    viewmat[:3, :3] = world_from_camera.T
    viewmat[:3, 3] = -world_from_camera.T @ np.asarray(view["center"])
    intrinsics = np.array([[fx * ratio, 0, cx * ratio], [0, fy * ratio, cy * ratio], [0, 0, 1]])
    return viewmat, intrinsics, width, height


class Inpainter:
    """LaMa TorchScript nếu có trọng số, không thì `cv2.inpaint` (Telea)."""

    def __init__(self, checkpoint: str | None, device: torch.device) -> None:
        self.device = device
        self.model = None
        if checkpoint and Path(checkpoint).is_file():
            self.model = torch.jit.load(checkpoint, map_location=device).eval()
        self.method = "lama" if self.model is not None else "cv2_telea"

    @torch.no_grad()
    def __call__(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """image HxWx3 float 0..1, mask HxW bool → ảnh đã vá HxWx3 float 0..1."""
        if self.model is None:
            filled = cv2.inpaint((image * 255).astype(np.uint8), mask.astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA)
            return filled.astype(np.float32) / 255.0
        height, width = mask.shape
        pad_h, pad_w = (-height) % 8, (-width) % 8
        tensor = torch.from_numpy(image).permute(2, 0, 1)[None].float().to(self.device)
        hole = torch.from_numpy(mask)[None, None].float().to(self.device)
        tensor = torch.nn.functional.pad(tensor, (0, pad_w, 0, pad_h), mode="reflect")
        hole = torch.nn.functional.pad(hole, (0, pad_w, 0, pad_h), mode="reflect")
        output = self.model(tensor, hole)[0, :, :height, :width].permute(1, 2, 0)
        output = output.float().cpu().numpy()
        return np.clip(output / 255.0 if output.max() > 1.5 else output, 0, 1)


def hole_mask(object_alpha: np.ndarray, background_alpha: np.ndarray, config: dict) -> np.ndarray:
    """Vật che mà nền phía sau trống; bỏ đốm nhỏ, nới một chút để vá liền mép."""
    hole = (object_alpha > float(config.get("object_alpha", 0.5))) & (
        background_alpha < float(config.get("background_alpha", 0.5))
    )
    kernel = np.ones((3, 3), np.uint8)
    hole = cv2.morphologyEx(hole.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(hole, connectivity=8)
    keep = np.zeros_like(hole, dtype=bool)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= int(config.get("min_hole_px", 40)):
            keep |= labels == label
    return cv2.dilate(keep.astype(np.uint8), kernel, iterations=1).astype(bool)


def fill_depth(depth: np.ndarray, valid: np.ndarray, hole: np.ndarray, floor: np.ndarray) -> np.ndarray:
    """Độ sâu vùng thủng: nội suy từ nền hợp lệ quanh đó, không nông hơn `floor` (mặt sau của vật)."""
    unknown = (~valid).astype(np.uint8) * 255
    filled = cv2.inpaint(np.where(valid, depth, 0).astype(np.float32), unknown, 5, cv2.INPAINT_NS)
    return np.where(hole, np.maximum(filled, floor), depth)


def run(request: dict) -> dict:
    """Vá nền; trả số Gaussian thêm và thống kê theo góc nhìn."""
    config = request.get("config") or {}
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    template = read_ply(Path(request["background_ply"]))
    background = Splats(template, device)
    objects = Splats(read_ply(Path(request["objects_ply"])), device)
    original = len(template)
    inpaint = Inpainter(request.get("lama_checkpoint"), device)
    width = int(config.get("width", 640))
    stride = int(config.get("stride_px", 2))
    views = request["views"][:: max(1, int(config.get("view_step", 1)))]
    max_new = int(config.get("max_new_gaussians", 400_000))
    per_view = []
    debug_dir = Path(request["debug_dir"]) if request.get("debug_dir") else None
    for number, view in enumerate(views):
        viewmat_np, intrinsics_np, w, h = camera(view, width)
        viewmat = torch.from_numpy(viewmat_np).float().to(device)
        intrinsics = torch.from_numpy(intrinsics_np).float().to(device)
        rgb, alpha, depth = background.render(viewmat, intrinsics, w, h)
        _, object_alpha, object_depth = objects.render(viewmat, intrinsics, w, h)
        alpha_np, object_alpha_np = alpha.cpu().numpy(), object_alpha.cpu().numpy()
        hole = hole_mask(object_alpha_np, alpha_np, config)
        pixels = int(hole.sum())
        if not pixels or len(background.means) - original >= max_new:
            per_view.append({"frame_id": view.get("frame_id"), "hole_px": pixels, "added": 0})
            continue
        rgb_np = rgb.cpu().numpy()
        # LaMa vá mọi chỗ nền chưa đủ đục quanh lỗ để không lấy màu đen làm ngữ cảnh.
        painted = inpaint(rgb_np, hole | (alpha_np < 0.2))
        behind = object_depth.cpu().numpy() + float(config.get("behind_object_m", 0.05))
        depth_np = fill_depth(depth.cpu().numpy(), alpha_np >= 0.6, hole, np.where(object_alpha_np > 0.5, behind, 0))
        ys, xs = np.nonzero(hole[::stride, ::stride])
        ys, xs = ys * stride, xs * stride
        z = depth_np[ys, xs]
        good = np.isfinite(z) & (z > 0.05) & (z < float(config.get("max_depth_m", 30.0)))
        ys, xs, z = ys[good], xs[good], z[good]
        fx, fy, cx, cy = intrinsics_np[0, 0], intrinsics_np[1, 1], intrinsics_np[0, 2], intrinsics_np[1, 2]
        camera_points = np.stack([(xs + 0.5 - cx) / fx * z, (ys + 0.5 - cy) / fy * z, z], axis=1)
        world_from_camera = rotation(view["rotation_xyzw"])
        world = camera_points @ world_from_camera.T + np.asarray(view["center"])
        scale = z * stride / fx * float(config.get("scale_factor", 0.7))
        background.append(
            torch.from_numpy(world).float().to(device),
            torch.from_numpy(scale).float().to(device),
            torch.from_numpy(painted[ys, xs]).float().to(device),
            float(config.get("opacity", 0.9)),
        )
        per_view.append({"frame_id": view.get("frame_id"), "hole_px": pixels, "added": int(len(world))})
        if debug_dir is not None and number % max(1, len(views) // 6) == 0:
            debug_dir.mkdir(parents=True, exist_ok=True)
            after, _, _ = background.render(viewmat, intrinsics, w, h)
            strip = np.concatenate(
                [rgb_np, np.repeat(hole[..., None], 3, axis=2).astype(np.float32), after.cpu().numpy()], axis=1
            )
            cv2.imwrite(str(debug_dir / f"view_{number:04d}.jpg"), (strip[..., ::-1] * 255).astype(np.uint8))
    added = len(background.means) - original
    write_ply(Path(request["output_ply"]), background.rows(template, original))
    return {
        "method": f"seed_from_2d_inpaint_v1/{inpaint.method}",
        "original_gaussians": original,
        "inpainted_gaussians": added,
        "views": len(views),
        "views_with_holes": sum(1 for item in per_view if item["hole_px"]),
        "per_view": per_view,
    }


def main() -> int:
    """CLI: request JSON → PLY nền đã vá + result JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    summary = run(json.loads(args.request.read_text(encoding="utf-8")))
    args.result.write_text(json.dumps(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
