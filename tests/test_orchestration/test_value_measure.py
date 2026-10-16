"""Máy đo P2/P3 trên collision tổng hợp dựng tay: sai số, bề rộng khe, phân loại, nhất quán sau khi dời (§15.3)."""

import numpy as np
import pytest
import trimesh

from src.services.orchestration.value.ground_truth import GapCheck, MeasuredDistance, RobotProfile
from src.services.orchestration.value.measure import CollisionWorld, distance_error, gap_width

_ROBOT = RobotProfile(width_m=0.6, safety_margin_m=0.05, height_min_m=0.05, height_max_m=1.2)


def _world(*boxes: tuple[str, tuple[float, float, float], tuple[float, float, float]]) -> CollisionWorld:
    """Mỗi hộp là (owner, tâm, kích thước). owner rỗng là môi trường (không kín theo nghĩa vật); owner khác rỗng là vật kín."""
    meshes, owners = [], []
    for owner, center, extents in boxes:
        box = trimesh.creation.box(extents=extents)
        box.apply_translation(center)
        meshes.append(box)
        owners.extend([owner] * len(box.faces))
    merged = trimesh.util.concatenate(meshes)
    return CollisionWorld(
        mesh=merged,
        face_owner=np.array(owners, dtype=object),
        solid_owners=frozenset(owner for owner, _, _ in boxes if owner),
    )


def _gap(identifier: str = "g", *, real_passable: bool, z: float = 0.5) -> GapCheck:
    return GapCheck(
        id=identifier,
        label="khe cửa",
        layout="A",
        a=(-0.5, 0.0, z),
        b=(0.5, 0.0, z),
        real_passable=real_passable,
    )


_LEFT_WALL = ("", (-0.9, 0.0, 0.5), (1.0, 2.0, 1.0))  # mặt phải tại x = −0,4
_RIGHT_WALL = ("", (0.9, 0.0, 0.5), (1.0, 2.0, 1.0))  # mặt trái tại x = +0,4


def _two_walls_both() -> CollisionWorld:
    return _world(_LEFT_WALL, _RIGHT_WALL)


def test_distance_error_is_the_simulated_span_minus_the_tape_measure() -> None:
    result = distance_error(MeasuredDistance(id="d1", label="bàn", a=(0, 0, 0), b=(1, 0, 0), real_m=0.98))

    assert result.sim_m == pytest.approx(1.0)
    assert result.error_m == pytest.approx(0.02)
    assert result.error_pct == pytest.approx(0.02 / 0.98 * 100)


def test_open_gap_between_two_walls_measures_its_true_width_within_a_centimetre() -> None:
    result = gap_width(_two_walls_both(), _gap(real_passable=True), _ROBOT)

    assert result.sim_width_m == pytest.approx(0.8, abs=0.01)
    assert result.sim_passable is True
    assert result.agree is True
    assert result.kind == "ok"


def test_passability_needs_robot_width_plus_both_safety_margins() -> None:
    # Ngưỡng 0,6 + 2·0,05 = 0,70; khe 0,80 qua được, robot rộng 0,80 thì không.
    wide = RobotProfile(width_m=0.8, safety_margin_m=0.05, height_min_m=0.05, height_max_m=1.2)

    assert gap_width(_two_walls_both(), _gap(real_passable=True), _ROBOT).sim_passable is True
    assert gap_width(_two_walls_both(), _gap(real_passable=False), wide).sim_passable is False


def test_obstacle_below_the_robot_height_band_does_not_block() -> None:
    low = ("", (0.0, 0.0, 0.015), (0.2, 0.2, 0.03))  # đỉnh 0,03 m < h_min 0,05 m
    world = _world(_LEFT_WALL, _RIGHT_WALL, low)

    result = gap_width(world, _gap(real_passable=True), _ROBOT)

    assert result.sim_width_m == pytest.approx(0.8, abs=0.01)


def test_obstacle_only_at_high_heights_inside_the_band_blocks_the_gap() -> None:
    high = ("", (0.0, 0.0, 0.9), (0.2, 0.2, 0.2))  # z 0,8–1,0 nằm trong dải robot
    world = _world(_LEFT_WALL, _RIGHT_WALL, high)

    result = gap_width(world, _gap(real_passable=True), _ROBOT)

    assert result.sim_width_m == pytest.approx(0.2, abs=0.01)
    assert result.sim_passable is False
    assert result.kind == "false_obstacle"


def test_midpoint_inside_a_closed_object_gives_zero_width() -> None:
    pillar = ("pillar", (0.0, 0.0, 0.5), (0.2, 0.2, 1.0))
    world = _world(_LEFT_WALL, _RIGHT_WALL, pillar)

    result = gap_width(world, _gap(real_passable=True), _ROBOT)

    assert result.sim_width_m == 0.0
    assert result.kind == "false_obstacle"


def test_missed_obstacle_is_a_gap_the_simulation_passes_but_reality_does_not() -> None:
    result = gap_width(_two_walls_both(), _gap(real_passable=False), _ROBOT)

    assert result.sim_passable is True
    assert result.agree is False
    assert result.kind == "missed_obstacle"


def test_checked_heights_follow_the_robot_band_in_five_centimetre_steps() -> None:
    result = gap_width(_two_walls_both(), _gap(real_passable=True), _ROBOT)

    assert result.heights_checked == 24  # 0,05 … 1,20 m, bước 0,05 m


def test_gap_width_is_deterministic_for_the_same_input() -> None:
    world = _two_walls_both()

    first = gap_width(world, _gap(real_passable=True), _ROBOT)
    second = gap_width(world, _gap(real_passable=True), _ROBOT)

    assert first == second


def test_vertical_gap_has_no_horizontal_direction_to_measure() -> None:
    vertical = GapCheck(id="v", label="cửa", layout="A", a=(0, 0, 0.1), b=(0, 0, 1.0), real_passable=True)

    with pytest.raises(ValueError, match="không có hướng ngang"):
        gap_width(_two_walls_both(), vertical, _ROBOT)
