"""MoGe2Backend (ADR 0001 §2): đoán độ sâu mét và pháp tuyến tại các pixel được hỏi.

Script độc lập chạy trong runtime GPU (`data/scene_runtime`): chỉ dùng numpy/torch/PIL/moge,
không import code app. App gọi qua subprocess:

    python moge_runner.py --request request.json --result result.npz

`request.json`:
    {"model": "<đường dẫn model.pt>", "device": "cuda",
     "frames": [{"frame_id": 3, "image": "<png>", "fov_x_degrees": 62.1, "pixels": [[u, v], ...]}]}

`result.npz`, với mỗi frame `<id>`:
    `<id>_depth`  (N,)   độ sâu z theo mét trong hệ camera (inf ở pixel mô hình đánh dấu không tin được)
    `<id>_normal` (N, 3) pháp tuyến trong hệ camera OpenCV (x phải, y xuống, z tới trước)
    `<id>_valid`  (N,)   mô hình tin pixel này (mask) và độ sâu hữu hạn, dương

Chỉ trả giá trị tại pixel được hỏi: app cần cặp (độ sâu SfM, độ sâu mét) ở điểm thưa của COLMAP,
không cần cả bản đồ. FoV lấy từ intrinsics COLMAP thay cho để mô hình tự đoán tiêu cự.
"""

import argparse
import json
from pathlib import Path

import numpy as np


def _sample(grid: np.ndarray, pixels: np.ndarray) -> np.ndarray:
    """Giá trị tại pixel chứa toạ độ; pixel ngoài ảnh bị kẹp về biên (COLMAP có thể báo keypoint sát mép).

    COLMAP đặt gốc ở góc trên-trái của pixel đầu (tâm pixel đầu là 0,5), nên chỉ số pixel là phần nguyên.
    """
    height, width = grid.shape[:2]
    u = np.clip(np.floor(pixels[:, 0]).astype(int), 0, width - 1)
    v = np.clip(np.floor(pixels[:, 1]).astype(int), 0, height - 1)
    return grid[v, u]


def main() -> None:
    """Nạp mô hình một lần rồi chạy lần lượt từng frame."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))

    import torch
    from moge.model.v2 import MoGeModel
    from PIL import Image

    device = torch.device(request.get("device", "cuda"))
    model = MoGeModel.from_pretrained(request["model"]).to(device).eval()
    arrays: dict[str, np.ndarray] = {}
    half_precision = device.type == "cuda"
    for frame in request["frames"]:
        pixels = np.asarray(frame["pixels"], dtype=np.float64).reshape(-1, 2)
        image = np.asarray(Image.open(frame["image"]).convert("RGB"), dtype=np.float32) / 255.0
        tensor = torch.from_numpy(image).permute(2, 0, 1).to(device)
        with torch.no_grad():
            output = model.infer(tensor, fov_x=frame.get("fov_x_degrees"), use_fp16=half_precision)
            if half_precision and not bool(torch.isfinite(output["depth"]).any()):
                # Một số GPU (vd. dòng TU117: Quadro T2000, GTX 1650) trả NaN với fp16: cả ảnh bị
                # mask. Chạy lại bằng fp32 và giữ fp32 cho các ảnh sau.
                half_precision = False
                output = model.infer(tensor, fov_x=frame.get("fov_x_degrees"), use_fp16=False)
        depth = _sample(output["depth"].float().cpu().numpy(), pixels)
        mask = _sample(output["mask"].cpu().numpy(), pixels)
        normal = (
            _sample(output["normal"].float().cpu().numpy(), pixels)
            if "normal" in output
            else np.zeros((len(pixels), 3), dtype=np.float32)
        )
        key = str(frame["frame_id"])
        arrays[f"{key}_depth"] = depth.astype(np.float32)
        arrays[f"{key}_normal"] = normal.astype(np.float32)
        arrays[f"{key}_valid"] = mask.astype(bool) & np.isfinite(depth) & (depth > 0)
    np.savez(args.result, **arrays)
    if device.type == "cuda":
        peak = torch.cuda.max_memory_allocated(device) / 1024**3
        print(json.dumps({"peak_vram_gb": peak, "half_precision": half_precision}))


if __name__ == "__main__":
    main()
