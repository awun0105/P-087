"""Tách 3DGS thành nền + vật (pipeline v2): lan nhãn, hệ cục bộ, PLY round-trip."""

import numpy as np
import pytest

from src.services.scene.decomposition.gaussian_split import (
    BACKGROUND,
    SplitConfig,
    label_gaussians,
    read_gaussian_ply,
    split,
    working_set,
    write_gaussian_ply,
)

_FIELDS = ["x", "y", "z", "rot_0", "rot_1", "rot_2", "rot_3", "scale_0", "scale_1", "scale_2", "opacity"]
_FIELDS += ["f_dc_0", "f_dc_1", "f_dc_2"]


def _rows(xyz: np.ndarray, opacity: float = 3.0, log_scale: float = np.log(0.02)) -> np.ndarray:
    rows = np.zeros(len(xyz), dtype=[(name, "<f4") for name in _FIELDS])
    rows["x"], rows["y"], rows["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    rows["rot_0"] = 1.0
    for name in ("scale_0", "scale_1", "scale_2"):
        rows[name] = log_scale
    rows["opacity"] = opacity
    return rows


def _scene() -> tuple[np.ndarray, np.ndarray]:
    """Một khối vật 0,4 m đặt trên sàn tại (2, 3) + sàn; trả (rows, chỉ số hạt giống của vật)."""
    rng = np.random.default_rng(0)
    cube = rng.uniform([1.8, 2.8, 0.05], [2.2, 3.2, 0.45], size=(600, 3))
    floor = np.column_stack([rng.uniform(0, 5, 800), rng.uniform(0, 5, 800), rng.uniform(0.0, 0.02, 800)])
    rows = _rows(np.vstack([cube, floor]))
    return rows, np.arange(0, 600, 3)  # chỉ 1/3 Gaussian của vật là hạt giống


def test_ply_round_trip_is_byte_identical() -> None:
    rows, _ = _scene()
    payload = write_gaussian_ply(rows)

    assert write_gaussian_ply(read_gaussian_ply(payload)) == payload


def test_non_gaussian_ply_is_rejected() -> None:
    payload = b"ply\nformat binary_little_endian 1.0\nelement vertex 0\nproperty float x\nend_header\n"

    with pytest.raises(ValueError, match="không phải 3DGS"):
        read_gaussian_ply(payload)


def test_labels_grow_from_seeds_to_neighbours_but_not_to_floor() -> None:
    rows, seeds = _scene()
    labels = label_gaussians(rows, [seeds])

    assert (labels[:600] == 0).mean() > 0.95  # gần hết khối vật được gán dù chỉ 1/3 là hạt giống
    assert (labels[600:] == BACKGROUND).all()  # sàn ngay dưới vật không bị kéo theo


def test_large_gaussians_stay_in_background() -> None:
    rows, seeds = _scene()
    rows["scale_0"][1] = np.log(2.0)  # một Gaussian cỡ 2 m nằm giữa vật, không phải hạt giống
    labels = label_gaussians(rows, [seeds])

    assert labels[1] == BACKGROUND


def test_split_writes_objects_in_axis_aligned_local_frame() -> None:
    rows, seeds = _scene()
    background, parts = split(rows, label_gaussians(rows, [seeds]))

    assert len(parts) == 1
    part = parts[0]
    assert part.center == pytest.approx((2.0, 3.0, 0.25), abs=0.03)
    assert part.dimensions == pytest.approx((0.4, 0.4, 0.4), abs=0.03)
    # Toạ độ cục bộ: quanh gốc; cộng tâm lại ra đúng vị trí world.
    assert abs(float(part.rows["x"].mean())) < 0.05
    assert float(part.rows["x"].max() + part.center[0]) == pytest.approx(2.2, abs=0.01)
    assert len(background) + len(part.rows) == len(rows)


def test_tiny_instances_return_to_background() -> None:
    rows, _ = _scene()
    background, parts = split(rows, label_gaussians(rows, [np.arange(5)], SplitConfig(grow_radius_m=0.0)))

    assert parts == [] and len(background) == len(rows)


def test_working_set_filters_by_opacity_and_crop() -> None:
    rows, _ = _scene()
    rows["opacity"][:10] = -5.0  # gần trong suốt
    chosen = working_set(rows, np.array([1.0, 2.0]), np.array([3.0, 4.0]), (-0.5, 4.0))

    assert not set(range(10)) & set(chosen.tolist())
    assert len(chosen) > 500
