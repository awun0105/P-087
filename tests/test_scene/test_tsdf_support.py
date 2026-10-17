"""Exact renderer/TSDF calibration and bounded support capture with CPU API fixtures."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from src.services.scene.tsdf_support import camera_calibration, depth_points, install_export_hooks


class Tensor:
    def __init__(self, data):
        self.data = np.asarray(data)

    @property
    def T(self):  # noqa: N802 - tensor transpose API
        return Tensor(self.data.T)

    def cpu(self):
        return self

    def numpy(self):
        return self.data


def camera(center=(0, 0, 0)):
    matrix = np.eye(4)
    matrix[:3, 3] = -np.asarray(center)
    return SimpleNamespace(
        fx=10.0,
        fy=12.0,
        cx=1.2,
        cy=0.4,
        image_width=4,
        image_height=3,
        world_view_transform=Tensor(matrix.T),
        alpha_mask=Tensor(np.ones((1, 3, 4))),
        image_name="fixture",
    )


def test_noncentered_principal_point_is_preserved_and_depth_stays_in_metres():
    view = camera((2, 3, 4))
    intrinsic, extrinsic = camera_calibration(view)
    assert intrinsic[0, 2] == 1.2 and intrinsic[1, 2] == 0.4
    depth = np.zeros((3, 4))
    depth[1, 2] = 2
    points = depth_points(depth, np.ones_like(depth), intrinsic, extrinsic, 8, 100)
    np.testing.assert_allclose(points, [[2 + 0.8 * 2 / 10, 3 + 0.6 * 2 / 12, 6]])
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
    transform = np.eye(4)
    transform[:3, :3] = rotation.T
    transform[:3, 3] = -rotation.T @ np.array([2, 3, 4])
    actual = depth_points(depth, np.ones_like(depth), intrinsic, transform, 8, 100)
    np.testing.assert_allclose(actual, (points - [2, 3, 4]) @ rotation.T + [2, 3, 4])


def test_depth_mask_invalid_values_and_truncation_cannot_create_support():
    view = camera()
    intrinsic, extrinsic = camera_calibration(view)
    depth = np.ones((3, 4))
    depth[0, :] = [0, -1, np.nan, 20]
    mask = np.ones((3, 4))
    mask[1, :] = 0
    points = depth_points(depth, mask, intrinsic, extrinsic, 8, 2)
    assert points.shape == (2, 3)
    bad = camera()
    bad.world_view_transform.data[:3, :3] *= 2
    with pytest.raises(ValueError, match="rigid"):
        camera_calibration(bad)


def test_hook_reuses_fusion_with_exact_camera_matrix_and_saves_same_depth_estimates(tmp_path, monkeypatch):
    observed = []
    module = SimpleNamespace()

    class Extractor:
        def extract_mesh_bounded(self, **kwargs):
            observed.append((module.to_cam_open3d(self.viewpoint_stack), kwargs))
            return "original mesh"

    module.GaussianExtractor = Extractor
    monkeypatch.setitem(sys.modules, "utils", SimpleNamespace(mesh_utils=module))
    monkeypatch.setitem(
        sys.modules,
        "open3d",
        SimpleNamespace(
            camera=SimpleNamespace(
                PinholeCameraParameters=lambda: SimpleNamespace(),
                PinholeCameraIntrinsic=lambda *args: args,
            )
        ),
    )
    path = tmp_path / "depth-support.npz"
    install_export_hooks(path)
    extractor = Extractor()
    extractor.viewpoint_stack = [camera(), camera((1, 0, 0))]
    extractor.depthmaps = [Tensor(np.full((1, 3, 4), 2.0))] * 2
    assert extractor.extract_mesh_bounded(voxel_size=0.01, depth_trunc=8) == "original mesh"
    assert observed[0][0][0].intrinsic == (4, 3, 10.0, 12.0, 1.2, 0.4)
    assert observed[0][1]["mask_backgrond"] is True
    with np.load(path, allow_pickle=False) as data:
        assert data["points"].shape == (24, 3)
        assert len(np.unique(data["view_ids"])) == 2
        assert "objectgs_rendered_depth_estimate" in str(data["metadata"])
    with pytest.raises(ValueError, match="categorical"):
        extractor.extract_mesh_bounded(mask_backgrond=False)
