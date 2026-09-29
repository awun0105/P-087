"""Synthetic GPU qualification REC-05; không chạy Aisle_CW hoặc cấp metric record.

Chạy bằng python -m tests.test_reconstruction.smoke.rec05_smoke --help.
Fixture room canonical 2 x 3 x 1.5m và một floater tách biệt; không phải robot thật.
"""

import argparse
import json
import math
import struct
from pathlib import Path

from src.services.reconstruction.adapters.voxel import SplatTransformVoxelAdapter, SyntheticVoxelRequest, file_checksum
from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess, VoxelRuntimeSettings
from src.services.reconstruction.rgb.geometry.voxel import VoxelConfig


def synthetic_room(path: Path) -> None:
    """Gaussian shell có ba kích thước khác nhau để bắt sai trục và loại floater."""
    points = set()
    for x in range(21):
        for y in range(31):
            for z in range(16):
                if x in (0, 20) or y in (0, 30) or z in (0, 15):
                    points.add((x / 10, y / 10, z / 10))
    points.add((6.0, 6.0, 3.0))
    fields = "x y z f_dc_0 f_dc_1 f_dc_2 opacity scale_0 scale_1 scale_2 rot_0 rot_1 rot_2 rot_3".split()
    header = f"ply\nformat binary_little_endian 1.0\nelement vertex {len(points)}\n"
    header += "".join(f"property float {field}\n" for field in fields) + "end_header\n"
    with path.open("xb") as stream:
        stream.write(header.encode())
        for point in sorted(points):
            values = (*point, 0.1, 0.2, 0.3, 4.0, *([math.log(0.07)] * 3), 1, 0, 0, 0)
            stream.write(struct.pack("<14f", *values))


def smoke_config(resolution: float) -> VoxelConfig:
    """Knobs/footprint chỉ áp cho fixture này, không chuyển thành product defaults."""
    return VoxelConfig(
        resolution_m=resolution,
        opacity=0.1,
        cluster_resolution_m=0.1,
        cluster_opacity=0.1,
        cluster_min_contribution=0.004,
        cluster_seed_world=(0, 1.5, 0.75),
        navigation_seed_world=(1, 1.5, 0.5),
        capsule_height_m=0.4,
        capsule_radius_m=0.1,
        gpu_index=0,
    )


def verify_synthetic(report: dict) -> None:
    """Asymmetric extents phát hiện flip/scale sai; topology đo trên output thật."""
    topology = report["topology"]
    if report["gaussian_counts"] != {"input": 2703, "cluster": 2702}:
        raise ValueError("synthetic disconnected floater not removed exactly once")
    if any(topology[key] for key in ("boundary_edges", "nonmanifold_edges", "degenerate_triangles")):
        raise ValueError("synthetic collision is not a closed manifold")
    bounds = report["canonical_bounds"]
    for index, size in enumerate((2.0, 3.0, 1.5)):
        low, high = bounds["min"][index], bounds["max"][index]
        if not (-0.5 < low < 0.5 and size - 0.5 < high < size + 0.5):
            raise ValueError("synthetic bounds violate known axes/scale or retain detached floater")


def main() -> None:
    """New workspace bắt buộc; runtime settings nhận từ environment đã provision."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolutions", type=float, nargs="+", default=[0.1, 0.05, 0.025])
    args = parser.parse_args()
    runner = SplatTransformVoxelAdapter(VoxelProcess(VoxelRuntimeSettings()))
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.output / "synthetic-room.ply"
    synthetic_room(source)
    for resolution in args.resolutions:
        task = SyntheticVoxelRequest(
            source=source, source_checksum=file_checksum(source), config=smoke_config(resolution)
        )
        report = runner.run_synthetic(task, args.output / f"voxel-{resolution}")
        verify_synthetic(report)
        print(json.dumps(dict(resolution_m=resolution, topology=report["topology"], bounds=report["canonical_bounds"])))


if __name__ == "__main__":
    main()
