"""Pinned export hooks: full camera intrinsics and bounded rendered-depth support, NumPy only."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def camera_calibration(camera: object) -> tuple[np.ndarray, np.ndarray]:
    intrinsic = np.array([[camera.fx, 0, camera.cx], [0, camera.fy, camera.cy], [0, 0, 1]], dtype=float)
    extrinsic = np.asarray(camera.world_view_transform.T.cpu().numpy(), dtype=float)
    if not np.isfinite(intrinsic).all() or intrinsic[0, 0] <= 0 or intrinsic[1, 1] <= 0:
        raise ValueError("TSDF requires finite positive focal lengths")
    if extrinsic.shape != (4, 4) or not np.isfinite(extrinsic).all():
        raise ValueError("TSDF requires a finite world-to-camera transform")
    if (
        not np.allclose(extrinsic[3], [0, 0, 0, 1])
        or not np.allclose(extrinsic[:3, :3] @ extrinsic[:3, :3].T, np.eye(3), atol=1e-6)
        or not np.isclose(np.linalg.det(extrinsic[:3, :3]), 1, atol=1e-6)
    ):
        raise ValueError("TSDF camera transform must be rigid; implicit scaling is forbidden")
    return intrinsic, extrinsic


def depth_points(
    depth: np.ndarray, mask: np.ndarray, intrinsic: np.ndarray, extrinsic: np.ndarray, depth_trunc_m: float, budget: int
) -> np.ndarray:
    depth, mask = np.asarray(depth).squeeze(), np.asarray(mask).squeeze()
    if depth.ndim != 2 or depth.shape != mask.shape:
        raise ValueError("rendered depth and object mask dimensions differ")
    pixels = np.argwhere(np.isfinite(depth) & (depth > 0) & (depth <= depth_trunc_m) & (mask >= 0.5))
    if len(pixels) > budget:
        pixels = pixels[np.linspace(0, len(pixels) - 1, budget, dtype=int)]
    v, u = pixels.T
    z = depth[v, u]
    camera = np.column_stack(
        [(u - intrinsic[0, 2]) * z / intrinsic[0, 0], (v - intrinsic[1, 2]) * z / intrinsic[1, 1], z]
    )
    return (camera - extrinsic[:3, 3]) @ extrinsic[:3, :3]


def save_support(extractor: object, path: Path, voxel_size_m: float, depth_trunc_m: float) -> None:
    views = extractor.viewpoint_stack
    chosen = np.unique(np.linspace(0, len(views) - 1, min(16, len(views)), dtype=int))
    points, owners, centers, calibration = [], [], [], []
    for number, index in enumerate(chosen):
        camera = views[index]
        intrinsic, extrinsic = camera_calibration(camera)
        sample = depth_points(
            extractor.depthmaps[index].cpu().numpy(),
            camera.alpha_mask.cpu().numpy(),
            intrinsic,
            extrinsic,
            depth_trunc_m,
            200_000 // len(chosen),
        )
        points.append(sample)
        owners.append(np.full(len(sample), number, dtype=np.int16))
        centers.append(-extrinsic[:3, :3].T @ extrinsic[:3, 3])
        calibration.append(dict(name=camera.image_name, intrinsic=intrinsic.tolist(), extrinsic=extrinsic.tolist()))
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        points=np.concatenate(points).astype(np.float32) if points else np.empty((0, 3)),
        view_ids=np.concatenate(owners) if owners else np.empty(0, dtype=np.int16),
        camera_centers=np.asarray(centers).reshape(-1, 3),
        metadata=json.dumps(
            dict(
                kind="objectgs_rendered_depth_estimate",
                coordinate_frame="world",
                distance_unit="m",
                voxel_size_m=voxel_size_m,
                depth_trunc_m=depth_trunc_m,
                camera_limit=16,
                point_limit=200_000,
                calibration=calibration,
            )
        ),
    )


def install_export_hooks(path: Path) -> None:
    """Reuse pinned fusion, replacing its FoV-only K with the renderer's exact K."""
    import open3d as o3d
    from utils import mesh_utils

    def cameras(views: list[object]) -> list[object]:
        output = []
        for camera in views:
            intrinsic, extrinsic = camera_calibration(camera)
            item = o3d.camera.PinholeCameraParameters()
            item.intrinsic = o3d.camera.PinholeCameraIntrinsic(
                camera.image_width,
                camera.image_height,
                intrinsic[0, 0],
                intrinsic[1, 1],
                intrinsic[0, 2],
                intrinsic[1, 2],
            )
            item.extrinsic = extrinsic
            output.append(item)
        return output

    original = mesh_utils.GaussianExtractor.extract_mesh_bounded

    def bounded(
        self: object,
        voxel_size: float = 0.004,
        sdf_trunc: float = 0.02,
        depth_trunc: float = 3,
        mask_backgrond: bool = True,
    ) -> object:
        if not mask_backgrond:
            raise ValueError("object surface fusion must use categorical object masks")
        mesh = original(self, voxel_size=voxel_size, sdf_trunc=sdf_trunc, depth_trunc=depth_trunc, mask_backgrond=True)
        save_support(self, path, voxel_size, depth_trunc)
        return mesh

    mesh_utils.to_cam_open3d = cameras
    mesh_utils.GaussianExtractor.extract_mesh_bounded = bounded
