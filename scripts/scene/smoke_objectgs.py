"""Opt-in real ObjectGS GPU smoke on calibrated synthetic cube/floor observations.

Runs upstream training and per-label export, never a mock. No Studio job or SceneIR is mutated.
A successful result is functional synthetic evidence, not Room/physics/mesh-quality acceptance.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services.scene.objectgs import ObjectGSRuntime, ObjectGSView, prepare_dataset, run_objectgs  # noqa: E402


def prepare_fixture(destination: Path) -> list[ObjectGSView]:
    """Write exact PINHOLE RGB and uint8 labels for a 1m cube above an observed floor."""
    destination.mkdir(parents=True, exist_ok=False)
    views = []
    size, focal = 96, 90.0
    yy, xx = np.mgrid[:size, :size]
    directions = np.stack(((xx + 0.5 - size / 2) / focal, (yy + 0.5 - size / 2) / focal, np.ones_like(xx)), axis=-1)
    low, high = np.array([-0.5, -0.5, 0.1]), np.array([0.5, 0.5, 1.1])
    for index, angle in enumerate(np.linspace(0, 2 * np.pi, 8, endpoint=False)):
        center = np.array([3 * np.cos(angle), 3 * np.sin(angle), 1.8])
        forward = np.array([0, 0, 0.6]) - center
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, [0, 0, 1])
        right /= np.linalg.norm(right)
        rotation = np.column_stack((right, np.cross(forward, right), forward))
        rays = directions @ rotation.T
        with np.errstate(divide="ignore", invalid="ignore"):
            a, b = (low - center) / rays, (high - center) / rays
            near, far = np.minimum(a, b).max(-1), np.maximum(a, b).min(-1)
            floor = -center[2] / rays[..., 2]
        hit = (near > 0) & (far >= near) & ((floor <= 0) | (near < floor))
        rgb = np.full((size, size, 3), [70, 90, 110], dtype=np.uint8)
        rgb[floor > 0] = [160, 165, 170]
        rgb[hit] = [210, 80, 40]
        image_path, mask_path = destination / f"rgb-{index}.png", destination / f"mask-{index}.png"
        Image.fromarray(rgb).save(image_path)
        Image.fromarray(hit.astype(np.uint8)).save(mask_path)
        views.append(
            ObjectGSView(
                image_path=image_path,
                mask_path=mask_path,
                width=size,
                height=size,
                parameters=(focal, focal, size / 2, size / 2),
                center=tuple(center),
                rotation_xyzw=tuple(Rotation.from_matrix(rotation).as_quat()),
            )
        )
    return views


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    runtime = ObjectGSRuntime.model_validate_json(args.runtime_config.read_bytes())
    root = args.workspace.resolve()
    root.mkdir(parents=True, exist_ok=False)
    views = prepare_fixture(root / "observations")
    grid = np.linspace(-0.5, 0.5, 12)
    points = []
    for axis in range(3):
        for edge in (-0.5, 0.5):
            for first in grid:
                for second in grid:
                    xyz = np.zeros(3)
                    xyz[axis] = edge
                    xyz[[a for a in range(3) if a != axis]] = [first, second]
                    xyz[2] += 0.6
                    points.append(xyz)
    object_count = len(points)
    points.extend([x, y, 0] for x in np.linspace(-2, 2, 20) for y in np.linspace(-2, 2, 20))
    rows = np.zeros(len(points), dtype=[(name, "<f4") for name in ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2"]])
    for axis, name in enumerate(["x", "y", "z"]):
        rows[name] = np.array(points)[:, axis]
    colors = np.full((len(points), 3), [160, 165, 170], dtype=float)
    colors[:object_count] = [210, 80, 40]
    for axis in range(3):
        rows[f"f_dc_{axis}"] = (colors[:, axis] / 255 - 0.5) / 0.28209479177387814
    labels = np.full(len(points), -1, dtype=np.int32)
    labels[:object_count] = 0
    prepare_dataset(rows, labels, {"0": "cube"}, views, root / "dataset")
    receipt = run_objectgs(runtime, root / "dataset", root / "runtime", progress=lambda stage: print(stage, flush=True))
    (root / "result.json").write_text(json.dumps(receipt, indent=2))
    print(root / "result.json")


if __name__ == "__main__":
    main()
