"""Máy đo P2/P3 trên collision tổng hợp dựng tay: sai số, bề rộng khe, phân loại, nhất quán sau khi dời (§15.3)."""

import math
from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import (
    ColliderSpec,
    ColliderType,
    SceneIR,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
)
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects import ProjectRegistry
from src.services.orchestration.scene.errors import SceneError
from src.services.orchestration.value import measure as measure_module
from src.services.orchestration.value.ground_truth import GapCheck, MeasuredDistance, RobotProfile
from src.services.orchestration.value.measure import (
    CollisionWorld,
    MoveResult,
    collision_world,
    compose_collision_world,
    distance_error,
    gap_width,
    move_consistency,
)
from src.services.scene.representation_composition import resolve_representation, scene_representations

_ROBOT = RobotProfile(width_m=0.6, safety_margin_m=0.05, height_min_m=0.05, height_max_m=1.2)


def _world(*boxes: tuple[str, tuple[float, float, float], tuple[float, float, float]]) -> CollisionWorld:
    """Mỗi hộp là (owner, tâm, kích thước). owner rỗng là môi trường (không kín theo nghĩa vật); owner khác rỗng là vật kín."""
    meshes, owners, parts = [], [], []
    for index, (owner, center, extents) in enumerate(boxes):
        box = trimesh.creation.box(extents=extents)
        box.apply_translation(center)
        meshes.append(box)
        owners.extend([owner] * len(box.faces))
        parts.extend([index if owner else -1] * len(box.faces))
    merged = trimesh.util.concatenate(meshes)
    return CollisionWorld(
        mesh=merged,
        face_owner=np.array(owners, dtype=object),
        solid_owners=frozenset(owner for owner, _, _ in boxes if owner),
        face_part=np.array(parts, dtype=np.int64),
        solid_parts=frozenset(index for index, (owner, _, _) in enumerate(boxes) if owner),
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


_JOB = "job-measure"


def _ref(name: str) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type="ArtifactContent",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB}/{name}.glb",
        artifact_checksum="sha256:" + "0" * 64,
        data_class="derived",
        producer_stage="ST-EDIT",
        job_id=_JOB,
    )


def _object(
    identifier: str,
    *,
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
    state: SceneObjectState = SceneObjectState.CONFIRMED,
    active: bool = True,
    review: str | None = None,
    origin: SceneObjectOrigin = SceneObjectOrigin.RECONSTRUCTED,
    collider_type: ColliderType = ColliderType.AABB,
    dimensions: tuple[float, float, float] | None = (0.2, 0.2, 0.2),
    collider_translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    collider_rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
    with_collider: bool = True,
) -> SceneObject:
    frame = f"{identifier}-local"
    collider = None
    if with_collider:
        collider = ColliderSpec(
            collider_id=f"{identifier}-collider",
            collider_type=collider_type,
            local_transform=Transform(
                parent_frame=frame,
                local_frame=f"{identifier}-collider-frame",
                translation_xyz=collider_translation,
                rotation_quaternion_xyzw=collider_rotation,
            ),
            dimensions_xyz_m=dimensions,
            parameters={},
            provenance={},
        )
    return SceneObject(
        id=identifier,
        name=identifier,
        state=state,
        origin=origin,
        active=active,
        local_frame=frame,
        transform=Transform(
            parent_frame="canonical",
            local_frame=frame,
            translation_xyz=translation,
            rotation_quaternion_xyzw=rotation,
        ),
        geometry_ref=_ref(identifier),
        collider=collider,
        provenance={} if review is None else {"review": review},
    )


_FLOOR_VERTICES = np.array([[-5.0, -5.0, 0.0], [5.0, -5.0, 0.0], [0.0, 5.0, 0.0]])
_FLOOR_FACES = np.array([[0, 1, 2]])


def _tetra(_: ColliderSpec) -> list[tuple[np.ndarray, np.ndarray]]:
    vertices = np.array([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.0, 0.1]])
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    return [(vertices, faces)]


def _open_triangle(_: ColliderSpec) -> list[tuple[np.ndarray, np.ndarray]]:
    return [(np.array([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.0, 0.1, 0.0]]), np.array([[0, 1, 2]]))]


def test_only_objects_that_the_usd_export_would_include_enter_the_collision_world() -> None:
    objects = [
        _object("a"),  # xác nhận, active → vật xuất
        _object("b", state=SceneObjectState.CANDIDATE, active=False),  # ứng viên: nguồn, không phải vật
        _object("c", active=False),  # xác nhận nhưng không active
        _object("d", active=False, review="DELETED"),
        _object("e", active=False, review="IGNORED"),
        _object("f", active=False, review="MERGED"),
    ]

    world = compose_collision_world(objects, _FLOOR_VERTICES, _FLOOR_FACES, _tetra)

    exported = {item.id for item in objects if resolve_representation(item).export_as_object}
    assert exported == {"a"}
    assert {owner for owner in world.face_owner if owner} == exported
    assert set(world.face_owner[: len(_FLOOR_FACES)]) == {""}


def test_collider_pose_is_object_transform_times_collider_local_offset() -> None:
    quarter_turn_z = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
    item = _object(
        "a",
        translation=(1.0, 2.0, 0.0),
        rotation=quarter_turn_z,
        dimensions=(0.4, 0.2, 0.2),
        collider_translation=(0.5, 0.0, 0.0),
    )

    world = compose_collision_world([item], _FLOOR_VERTICES, _FLOOR_FACES, _tetra)

    vertices = world.mesh.vertices[np.unique(world.mesh.faces[world.face_owner == "a"])]
    assert vertices.mean(axis=0) == pytest.approx([1.0, 2.5, 0.0], abs=1e-9)
    extent = vertices.max(axis=0) - vertices.min(axis=0)
    assert extent[0] == pytest.approx(0.2, abs=1e-9)  # bề rộng 0,2 bị xoay sang trục y
    assert extent[1] == pytest.approx(0.4, abs=1e-9)


def test_closed_collider_is_a_solid_and_an_open_part_is_not() -> None:
    closed = compose_collision_world([_object("box")], _FLOOR_VERTICES, _FLOOR_FACES, _tetra)
    open_part = compose_collision_world(
        [_object("open", collider_type=ColliderType.CONVEX_DECOMPOSITION, dimensions=None)],
        _FLOOR_VERTICES,
        _FLOOR_FACES,
        _open_triangle,
    )

    assert closed.solid_owners == frozenset({"box"})
    assert open_part.solid_owners == frozenset()


def test_exported_object_without_collider_is_refused_like_the_usd_export() -> None:
    with pytest.raises(ValueError, match="chưa có collider"):
        compose_collision_world([_object("a", with_collider=False)], _FLOOR_VERTICES, _FLOOR_FACES, _tetra)


@pytest.fixture
def fixture_registry(tmp_path: Path) -> ProjectRegistry:
    registry = ProjectRegistry(
        runtime_root=tmp_path / "artifacts", database=RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    )
    registry.seed_from_fixtures()
    return registry


def test_fixture_scene_selection_matches_the_usd_export_and_refuses_a_missing_collider(
    fixture_registry: ProjectRegistry,
) -> None:
    scene = fixture_registry.scene.current("job-fixture-001").scene
    exported_by_usd = {item.object_id for item in scene_representations(scene) if item.export_as_object}
    exported_by_measure = {item.id for item in scene.objects if resolve_representation(item).export_as_object}
    without_collider = {
        item.id for item in scene.objects if resolve_representation(item).export_as_object and item.collider is None
    }

    assert exported_by_measure == exported_by_usd
    assert without_collider  # cảnh báo fixture: vật xuất mà không có collider, USD cũng từ chối
    with pytest.raises(ValueError, match="chưa có collider"):
        compose_collision_world(scene.objects, _FLOOR_VERTICES, _FLOOR_FACES, _tetra)


def test_collision_world_refuses_a_revision_that_is_not_published_for_the_job(
    fixture_registry: ProjectRegistry,
) -> None:
    with pytest.raises(SceneError, match="không thuộc job"):
        collision_world(fixture_registry, "job-fixture-001", "rev-khong-co")


_FOOTPRINT = (0.0, 0.0, 0.5)  # tâm vật A; hộp 0,4 m nằm trong dải z 0,3–0,7 của robot
_MOVED = (1.0, 0.0, 0.5)  # bố trí B: dời sang phải 1 m


def _slab(carved: bool) -> tuple[np.ndarray, np.ndarray]:
    """Mặt phẳng môi trường tại z = 0,5 (trong dải robot). Khi khoét, bỏ dải giữa hai bên vết cũ của vật."""
    if not carved:
        vertices = np.array([[-5, -5, 0.5], [5, -5, 0.5], [5, 5, 0.5], [-5, 5, 0.5]], dtype=float)
        return vertices, np.array([[0, 1, 2], [0, 2, 3]])
    left = np.array([[-5, -5, 0.5], [-0.3, -5, 0.5], [-0.3, 5, 0.5], [-5, 5, 0.5]], dtype=float)
    right = np.array([[0.3, -5, 0.5], [5, -5, 0.5], [5, 5, 0.5], [0.3, 5, 0.5]], dtype=float)
    return np.vstack([left, right]), np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])


def _pose_scene(fixture_scene: SceneIR, objects: list[SceneObject]) -> SceneIR:
    return fixture_scene.model_copy(update={"objects": objects})


def _move_world(
    carved: bool, moved_object_present: bool = True, extra: list[SceneObject] | None = None
) -> CollisionWorld:
    vertices, faces = _slab(carved)
    objects = [_object("a", translation=_MOVED)] if moved_object_present else []
    return compose_collision_world([*objects, *(extra or [])], vertices, faces, _tetra)


@pytest.fixture
def move_scenes(fixture_registry: ProjectRegistry) -> tuple[SceneIR, SceneIR]:
    base = fixture_registry.scene.current("job-fixture-001").scene
    before = _pose_scene(base, [_object("a", translation=_FOOTPRINT)])
    after = _pose_scene(base, [_object("a", translation=_MOVED)])
    return before, after


def _world_a(carved: bool) -> CollisionWorld:
    vertices, faces = _slab(carved)
    return compose_collision_world([_object("a", translation=_FOOTPRINT)], vertices, faces, _tetra)


def test_triangle_box_overlap_is_exact_at_the_box_faces() -> None:
    lo, hi = np.array([-0.1, -0.1, 0.0]), np.array([0.1, 0.1, 0.2])
    inside = np.array([[[0.0, 0.0, 0.1], [0.05, 0.0, 0.1], [0.0, 0.05, 0.1]]])
    crossing = np.array([[[-1.0, 0.0, 0.1], [1.0, 0.0, 0.1], [0.0, 1.0, 0.1]]])
    beside = np.array([[[0.11, 0.0, 0.1], [0.5, 0.0, 0.1], [0.5, 0.5, 0.1]]])
    above = np.array([[[0.0, 0.0, 0.21], [0.05, 0.0, 0.21], [0.0, 0.05, 0.21]]])

    assert measure_module._triangles_touch_box(inside, lo, hi) is True
    assert measure_module._triangles_touch_box(crossing, lo, hi) is True
    assert measure_module._triangles_touch_box(beside, lo, hi) is False
    assert measure_module._triangles_touch_box(above, lo, hi) is False


def test_moved_object_whose_old_footprint_was_carved_passes(move_scenes: tuple[SceneIR, SceneIR]) -> None:
    before, after = move_scenes
    results = move_consistency(_world_a(carved=True), _move_world(carved=True), before, after, _ROBOT)

    assert results == [MoveResult(object_id="a", old_cleared=True, new_present=True, passed=True)]


def test_moved_object_whose_old_footprint_was_not_carved_fails(move_scenes: tuple[SceneIR, SceneIR]) -> None:
    before, after = move_scenes
    results = move_consistency(_world_a(carved=False), _move_world(carved=False), before, after, _ROBOT)

    assert results == [MoveResult(object_id="a", old_cleared=False, new_present=True, passed=False)]


def test_moved_object_missing_its_new_collider_fails(move_scenes: tuple[SceneIR, SceneIR]) -> None:
    before, after = move_scenes
    world_b = _move_world(carved=True, moved_object_present=False)

    results = move_consistency(_world_a(carved=True), world_b, before, after, _ROBOT)

    assert results == [MoveResult(object_id="a", old_cleared=True, new_present=False, passed=False)]


def test_unmoved_object_produces_no_result(move_scenes: tuple[SceneIR, SceneIR]) -> None:
    before, _ = move_scenes
    small_shift = _pose_scene(before, [_object("a", translation=(0.005, 0.0, 0.5))])

    assert move_consistency(_world_a(carved=True), _move_world(carved=True), before, small_shift, _ROBOT) == []


def test_rotation_beyond_one_degree_counts_as_a_move(move_scenes: tuple[SceneIR, SceneIR]) -> None:
    before, _ = move_scenes
    two_degrees = math.radians(2.0)
    turned = _pose_scene(
        before,
        [
            _object(
                "a", translation=_FOOTPRINT, rotation=(0.0, 0.0, math.sin(two_degrees / 2), math.cos(two_degrees / 2))
            )
        ],
    )

    results = move_consistency(_world_a(carved=True), _move_world(carved=True), before, turned, _ROBOT)

    assert [item.object_id for item in results] == ["a"]


def test_object_too_small_to_shrink_cannot_be_verified_and_fails(move_scenes: tuple[SceneIR, SceneIR]) -> None:
    tiny_before = _object("a", translation=_FOOTPRINT, dimensions=(0.03, 0.03, 0.03))
    before = _pose_scene(move_scenes[0], [tiny_before])
    after = _pose_scene(move_scenes[0], [_object("a", translation=_MOVED, dimensions=(0.03, 0.03, 0.03))])
    world_a = compose_collision_world([tiny_before], *_slab(carved=True), _tetra)

    results = move_consistency(world_a, _move_world(carved=True), before, after, _ROBOT)

    assert results[0].old_cleared is False


def test_midpoint_inside_the_overlap_of_two_convex_parts_of_one_object_gives_zero_width() -> None:
    """CoACD cho nhiều mảnh lồi chồng nhau; điểm trong vùng chồng cắt 2 + 2 mặt nên chẵn lẻ trên cả vật báo sai là ngoài."""
    first = ("table", (-0.05, 0.0, 0.5), (0.3, 0.3, 1.0))
    second = ("table", (0.05, 0.0, 0.5), (0.3, 0.3, 1.0))  # chồng với mảnh đầu ở x ∈ [−0,10; 0,10]
    world = _world(_LEFT_WALL, _RIGHT_WALL, first, second)

    result = gap_width(world, _gap(real_passable=False), _ROBOT)

    assert result.sim_width_m == 0.0
    assert result.kind == "ok"


def test_composed_parts_are_solid_one_by_one() -> None:
    def two_parts(_: ColliderSpec) -> list[tuple[np.ndarray, np.ndarray]]:
        closed = _tetra(_)[0]
        return [closed, _open_triangle(_)[0]]

    world = compose_collision_world(
        [_object("a", collider_type=ColliderType.CONVEX_DECOMPOSITION, dimensions=None)],
        _FLOOR_VERTICES,
        _FLOOR_FACES,
        two_parts,
    )

    assert world.solid_parts == frozenset({0})  # mảnh kín vẫn kiểm được "ở trong", mảnh hở thì không
    assert world.solid_owners == frozenset()  # vật không kín trọn vẹn


def test_another_object_occupying_the_old_footprint_is_not_a_leftover(move_scenes: tuple[SceneIR, SceneIR]) -> None:
    """Ghế để dưới chỗ cũ của bàn (hoặc vật khác được dời tới) là collider hợp lệ, không phải vết môi trường còn sót."""
    before, after = move_scenes
    chair = _object("chair", translation=_FOOTPRINT, dimensions=(0.1, 0.1, 0.1))  # nằm trong vết cũ
    world_b = _move_world(carved=True, extra=[chair])

    results = move_consistency(_world_a(carved=True), world_b, before, after, _ROBOT)

    assert results == [MoveResult(object_id="a", old_cleared=True, new_present=True, passed=True)]
