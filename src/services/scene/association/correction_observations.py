"""Re-render corrected categorical ownership with the existing Gaussian rasterizer.

No SAM prediction, pose editing or membership voting occurs here. RGB/cameras are
calibrated by lift_runner's existing adapter; occlusion uses full source geometry.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from gsplat import rasterization
from lift_runner import pinhole, read_ply, undistorted_image


def run(request: dict) -> dict:
    rows = read_ply(Path(request["gaussians_ply"]))
    labels = np.fromfile(request["labels_path"], dtype="<i4")
    mapping = {int(key): value for key, value in request["label_to_object_id"].items()}
    if len(labels) != len(rows) or not set(np.unique(labels)) <= {-1, *mapping}:
        raise ValueError("corrected observation source ownership mismatch")
    directory = Path(request["output_dir"])
    directory.mkdir(parents=True, exist_ok=False)
    device = torch.device("cuda")
    means = torch.tensor(np.stack([rows[axis] for axis in ("x", "y", "z")], axis=1).astype(np.float32), device=device)
    quats = torch.nn.functional.normalize(
        torch.tensor(np.stack([rows[f"rot_{axis}"] for axis in range(4)], axis=1).astype(np.float32), device=device),
        dim=-1,
    )
    scales = torch.exp(
        torch.tensor(np.stack([rows[f"scale_{axis}"] for axis in range(3)], axis=1).astype(np.float32), device=device)
    )
    opacity = torch.sigmoid(torch.tensor(rows["opacity"].astype(np.float32), device=device))
    owners = [-1, *sorted(mapping)]
    views, counts = [], {label: 0 for label in mapping}
    for number, view in enumerate(request["views"]):
        matrix, intrinsic, distortion, width, height = pinhole(view, min(640, view["width"]))
        best = torch.zeros((height, width), device=device)
        winner = torch.full((height, width), -1, dtype=torch.int32, device=device)
        # Chunk categorical channels while retaining one global winner. Background
        # wins ties; every channel uses the SAME full-scene alpha compositing.
        with torch.no_grad():
            for start in range(0, len(owners), 31):
                chunk = owners[start : start + 31]
                colors = torch.tensor(np.stack([labels == owner for owner in chunk], axis=1), device=device).float()
                rendered, _, _ = rasterization(
                    means,
                    quats,
                    scales,
                    opacity,
                    colors,
                    torch.tensor(matrix, device=device).float()[None],
                    torch.tensor(intrinsic, device=device).float()[None],
                    width,
                    height,
                    sh_degree=None,
                )
                weight, channel = rendered[0].max(dim=-1)
                better = weight > best
                winner[better] = torch.tensor(chunk, device=device, dtype=torch.int32)[channel[better]]
                best = torch.maximum(best, weight)
        mask = winner.cpu().numpy()
        image_path, mask_path = directory / f"{number:06d}.png", directory / f"{number:06d}.npy"
        image = undistorted_image(view, distortion, width, height)
        if not cv2.imwrite(str(image_path), image[..., ::-1]):
            raise ValueError("could not persist corrected calibrated RGB")
        np.save(mask_path, mask, allow_pickle=False)
        for label in mapping:
            counts[label] += int(np.any(mask == label))
        views.append(
            {
                "image_path": str(image_path.resolve()),
                "mask_path": str(mask_path.resolve()),
                "width": width,
                "height": height,
                "center": view["center"],
                "rotation_xyzw": view["rotation_xyzw"],
                "parameters": [
                    float(intrinsic[0, 0]),
                    float(intrinsic[1, 1]),
                    float(intrinsic[0, 2]),
                    float(intrinsic[1, 2]),
                ],
                "camera_model": "PINHOLE",
                "coordinate_frame": "world",
                "distance_unit": "m",
            }
        )
    if any(count == 0 for count in counts.values()):
        raise ValueError("corrected object has no visible observations")
    return {"views": len(views), "masks_per_object": counts, "objectgs_views": views}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    args.result.write_text(json.dumps(run(json.loads(args.request.read_text()))))
