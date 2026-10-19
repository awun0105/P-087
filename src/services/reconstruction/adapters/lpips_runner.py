"""LPIPS giữa ảnh render và ảnh thật cùng frame — chạy trong runtime riêng có torch (`data/scene_runtime`).

Dùng gói `lpips` 0.1.4 chính thức (BSD-2, Zhang et al. 2018), mạng VGG như quy ước báo cáo của
3DGS/SuGaR/Frosting. Không import code app (runtime không có pydantic). In một dòng JSON.

    <scene_runtime>/bin/python src/services/reconstruction/adapters/lpips_runner.py --renders <dir> --gt <dir> [--net vgg]
"""

import argparse
import json
from pathlib import Path

import numpy as np


def _tensor(path: Path, size: tuple[int, int] | None = None):  # noqa: ANN202 - torch chỉ có trong runtime
    import torch
    from PIL import Image

    image = Image.open(path).convert("RGB")
    if size is not None and image.size != size:
        image = image.resize(size, Image.BICUBIC)
    array = np.asarray(image, dtype=np.float32) / 255.0
    # LPIPS nhận ảnh [-1, 1], NCHW.
    return torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0) * 2 - 1


def score(renders: Path, gt: Path, net: str) -> dict:
    """Chấm đủ ảnh render, ghép frame không phụ thuộc đuôi PNG/JPEG; đổi cỡ ảnh thật trong bộ nhớ."""
    import lpips
    import torch
    from PIL import Image

    sources: dict[str, list[Path]] = {}
    for path in gt.iterdir():
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            sources.setdefault(path.stem, []).append(path)
    pairs: list[tuple[Path, Path]] = []
    for render in sorted(renders.glob("*.png")):
        matches = sources.get(render.stem, [])
        if len(matches) != 1:
            raise ValueError(f"frame {render.stem}: cần đúng một ảnh gốc, tìm thấy {len(matches)}")
        pairs.append((render, matches[0]))
    if not pairs:
        raise SystemExit("không có ảnh render để chấm LPIPS")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = lpips.LPIPS(net=net, verbose=False).to(device).eval()
    values: dict[str, float] = {}
    with torch.no_grad():
        for render, truth in pairs:
            size = Image.open(render).size
            distance = model(_tensor(render).to(device), _tensor(truth, size).to(device))
            values[render.stem] = float(distance.item())
    return {"net": net, "count": len(values), "lpips": float(np.mean(list(values.values()))), "per_view": values}


def main() -> int:
    parser = argparse.ArgumentParser(description="LPIPS cho ảnh render 3DGS")
    parser.add_argument("--renders", type=Path, required=True)
    parser.add_argument("--gt", type=Path, required=True)
    parser.add_argument("--net", default="vgg", choices=("vgg", "alex"))
    args = parser.parse_args()
    print(json.dumps(score(args.renders, args.gt, args.net)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
