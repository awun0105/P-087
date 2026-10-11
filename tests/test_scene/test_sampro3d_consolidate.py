"""SAMPro3D (ADR 0006) phần chạy trên CPU: chọn prompt, lọc mask, bỏ phiếu, gộp instance.

Proposal được dựng tay (như kết quả SAM2) để kiểm logic gộp mà không cần GPU/torch.
"""

from pathlib import Path

import numpy as np
import pytest

from src.models.contracts.floor_model import FloorModel
from src.services.scene.floor_model import above_floor_mask, fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.geometric import GeometricConfig
from src.services.scene.sampro3d.consolidate import (
    Proposal,
    Sampro3dConfig,
    farthest_point_sampling,
    segment,
    select_prompts,
)
from src.services.scene.sampro3d.pipeline import Sam2Runtime, Sampro3dInputError, candidates_from_instances, run_sam2
from src.services.scene.sampro3d.sam2_runner import project, visible_points


def _box(center: tuple[float, float, float], size: float, step: float = 0.05) -> np.ndarray:
    axis = np.arange(-size / 2, size / 2 + 1e-9, step)
    grid = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1).reshape(-1, 3)
    return grid + np.asarray(center)


def _scene() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sàn + hai hộp 0.5 m cách xa nhau; trả points, chỉ số hộp A, chỉ số hộp B."""
    floor = np.stack(np.meshgrid(np.arange(-2, 4, 0.1), np.arange(-2, 2, 0.1)), axis=-1).reshape(-1, 2)
    floor = np.column_stack([floor, np.zeros(len(floor))])
    box_a, box_b = _box((0, 0, 0.35), 0.5), _box((2.5, 0, 0.35), 0.5)
    points = np.vstack([floor, box_a, box_b])
    a = np.arange(len(floor), len(floor) + len(box_a))
    b = np.arange(a[-1] + 1, len(points))
    return points, a, b


def _floor_model(points: np.ndarray) -> FloorModel:
    return fit_canonical_floor_model(points, point_cloud_checksum(points))


def _proposal(records: list[tuple[int, int, float, np.ndarray]], views: int, points: np.ndarray) -> Proposal:
    return Proposal(
        view=np.array([r[0] for r in records]),
        prompt=np.array([r[1] for r in records]),
        iou=np.array([r[2] for r in records], dtype=np.float32),
        members=[r[3] for r in records],
        visible=[np.arange(len(points))] * views,
    )


def test_consistent_masks_across_views_become_instances() -> None:
    points, a, b = _scene()
    prompt_a, prompt_b, prompt_a2 = int(a[10]), int(b[10]), int(a[50])
    records = [(view, prompt, 0.9, members) for view in range(3) for prompt, members in ((prompt_a, a), (prompt_b, b))]
    # Prompt thứ hai trên cùng vật A → phải gộp với prompt_a, không thành vật riêng.
    records += [(view, prompt_a2, 0.85, a) for view in range(3)]
    instances = segment(_proposal(records, 3, points), points, _floor_model(points))
    assert len(instances) == 2
    assert {frozenset(instance.tolist()) for instance in instances} == {frozenset(a.tolist()), frozenset(b.tolist())}


def test_low_iou_or_single_view_masks_are_dropped() -> None:
    points, a, b = _scene()
    low_iou = [(view, int(a[0]), 0.3, a) for view in range(3)]
    single_view = [(0, int(b[0]), 0.95, b)]
    assert segment(_proposal(low_iou + single_view, 3, points), points, _floor_model(points)) == []


def test_floor_points_never_join_an_instance() -> None:
    points, a, _ = _scene()
    floor = np.nonzero(points[:, 2] == 0)[0][:200]
    with_floor = np.concatenate([a, floor])
    records = [(view, int(a[0]), 0.9, with_floor) for view in range(3)]
    floor_model = _floor_model(points)
    (instance,) = segment(_proposal(records, 3, points), points, floor_model)
    assert above_floor_mask(points[instance], floor_model).all()


def test_prompts_skip_floor_and_follow_voxel_count() -> None:
    points, a, b = _scene()
    floor_model = _floor_model(points)
    prompts = select_prompts(points, floor_model)
    assert len(prompts) and above_floor_mask(points[prompts], floor_model).all()
    assert set(prompts.tolist()) <= set(a.tolist()) | set(b.tolist())
    capped = select_prompts(points, floor_model, Sampro3dConfig(max_prompts=3))
    assert len(capped) == 3
    assert len(np.unique(farthest_point_sampling(points, 20))) == 20


@pytest.mark.parametrize("case", ["uncertain_floor", "empty_crop", "floor_only"])
def test_invalid_prompt_input_stops_before_sam2(case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    points, _, _ = _scene()
    model = _floor_model(points)
    if case == "uncertain_floor":
        model = FloorModel.model_validate(
            {
                **model.model_dump(),
                "status": "uncertain",
                "fallback_reason": "excessive_noise",
                "robust_noise_sigma_m": 0.0653,
            }
        )
        expected = "6.53 cm.*3.00 cm"
    elif case == "empty_crop":
        points = points[:0]
        expected = "vùng tách vật không có điểm"
    else:
        points = points[points[:, 2] == 0]
        expected = "phía trên dải bảo vệ sàn"

    def unexpected_runtime(*args: object, **kwargs: object) -> None:
        pytest.fail("SAM2 must not start for invalid scene input")

    monkeypatch.setattr("src.services.scene.sampro3d.pipeline.run_cancellable_process", unexpected_runtime)
    with pytest.raises(Sampro3dInputError, match=expected):
        run_sam2(
            points, [], Sam2Runtime(tmp_path / "python", tmp_path / "sam2.pt"), tmp_path / "work", floor_model=model
        )
    assert not (tmp_path / "work/request.json").exists()


def test_prompts_follow_tilted_floor_and_keep_low_object() -> None:
    floor_xy = np.stack(np.meshgrid(np.arange(-2, 4, 0.1), np.arange(-2, 2, 0.1), indexing="xy"), axis=-1).reshape(
        -1, 2
    )
    floor = np.column_stack([floor_xy, 0.12 * floor_xy[:, 0]])
    low_object = _box((2.5, 0.0, 0.43), 0.2)
    points = np.vstack([floor, low_object])
    floor_model = _floor_model(points)

    prompts = select_prompts(points, floor_model)

    assert prompts.size > 0
    assert (prompts >= len(floor)).all()


def test_boxes_keep_object_sized_instances_only() -> None:
    points, a, _ = _scene()
    wall = np.column_stack([np.linspace(0, 6, 200), np.zeros(200), np.linspace(0.1, 2, 200)])
    all_points = np.vstack([points, wall])
    wall_index = np.arange(len(points), len(all_points))
    (box,) = candidates_from_instances(all_points, [a, wall_index], GeometricConfig())
    assert np.allclose(box.center, (0, 0, 0.35), atol=0.05)
    assert all(0.45 <= d <= 0.6 for d in box.dimensions)


def test_projection_and_zbuffer_occlusion() -> None:
    # Camera tại gốc nhìn theo +Z (quaternion đơn vị); điểm trên trục quang học → điểm chính.
    view = {
        "center": [0, 0, 0],
        "rotation_xyzw": [0, 0, 0, 1],
        "model": "PINHOLE",
        "parameters": [100, 100, 50, 40],
        "width": 100,
        "height": 80,
    }
    u, v, depth = project(np.array([[0.0, 0.0, 2.0]]), view)
    assert (u[0], v[0], depth[0]) == (50, 40, 2)
    near, far, behind = [0.0, 0.0, 1.0], [0.0, 0.0, 3.0], [0.0, 0.0, -1.0]
    kept, _ = visible_points(np.array([near, far, behind]), view, cell=4, tolerance=0.1)
    assert kept.tolist() == [0]  # điểm xa bị che, điểm sau camera bị loại
