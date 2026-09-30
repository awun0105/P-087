"""LPIPS giữa ảnh render và ảnh thật cùng tên — chạy trong runtime riêng có torch (`data/scene_runtime`).

Dùng gói `lpips` 0.1.4 chính thức (BSD-2, Zhang et al. 2018), mạng VGG như quy ước báo cáo của
3DGS/SuGaR/Frosting. Không import code app (runtime không có pydantic). In một dòng JSON.

    <scene_runtime>/bin/python eval/visual/lpips_score.py --renders <dir> --gt <dir> [--net vgg]
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
    """Trung bình LPIPS trên mọi ảnh render có ảnh thật cùng tên; ảnh thật đổi cỡ theo render nếu lệch."""
    import lpips
    import torch
    from PIL import Image

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = lpips.LPIPS(net=net, verbose=False).to(device).eval()
    values: dict[str, float] = {}
    with torch.no_grad():
        for render in sorted(renders.glob("*.png")):
            truth = gt / render.name
            if not truth.is_file():
                continue
            size = Image.open(render).size
            distance = model(_tensor(render).to(device), _tensor(truth, size).to(device))
            values[render.stem] = float(distance.item())
    if not values:
        raise SystemExit("không có cặp render/ảnh thật nào trùng tên")
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
