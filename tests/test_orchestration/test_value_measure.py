"""Máy đo P2/P3 trên collision tổng hợp dựng tay: sai số, bề rộng khe, phân loại, nhất quán sau khi dời (§15.3)."""

import math
from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import ColliderSpec, ColliderType, SceneObject, SceneObjectOrigin, SceneObjectState
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects import ProjectRegistry
from src.services.orchestration.scene.errors import SceneError
from src.services.orchestration.value.ground_truth import GapCheck, MeasuredDistance, RobotProfile
from src.services.orchestration.value.measure import (
    CollisionWorld,
    collision_world,
    compose_collision_world,
    distance_error,
    gap_width,
)
from src.services.scene.representation_composition import resolve_representation, scene_representations

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
