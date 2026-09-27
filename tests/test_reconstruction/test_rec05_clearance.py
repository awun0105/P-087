"""Seed clearance: native kernel, relocation có kiểm soát, và negative proof.

Proof cho octree reader/corruption nằm ở `test_rec05_voxel_octree.py`.
"""

import json
import struct
from pathlib import Path

import pytest

from src.services.reconstruction.adapters.voxel import SyntheticVoxelRequest
from src.services.reconstruction.adapters.voxel_clearance import validate_seed_clearance
from src.services.reconstruction.adapters.voxel_octree import CellBox, VoxelOctree
from src.services.reconstruction.adapters.voxel_output import VoxelMetadata
from src.services.reconstruction.adapters.voxel_runtime import GeometryError
from src.services.reconstruction.rgb.voxel import world_from_native
from tests.test_reconstruction.rec05_occupancy_fixture import wall, write_occupancy
from tests.test_reconstruction.test_rec05_adapter import adapter, request
from tests.test_reconstruction.test_rec05_voxel import config

# extents của config() là (ceil(0.1/0.1), ceil(0.4/0.2), 1) = (1, 2, 1), nên escape_hops = 3.
# nodeCount > 0 bắt buộc nên grid trống hoàn toàn không biểu diễn được; dùng voxel xa làm chỗ neo.
FAR = {(63, 63, 63)}
CUBE = {(i, j, k) for i in (32, 33) for j in (32, 33) for k in (32, 33)}


def tree(workspace: Path) -> VoxelOctree:
    """Load đúng serialized metadata/binary, không stub reader."""
    meta = VoxelMetadata.model_validate_json((workspace / "occupancy.voxel.json").read_bytes())
    return VoxelOctree(meta, (workspace / "occupancy.voxel.bin").read_bytes())


def world_of(cell: tuple[int, int, int]) -> tuple[float, float, float]:
    """Tâm ô native Y-up sang world canonical để test không dựng số tay."""
    return world_from_native(tuple(-3.2 + (value + 0.5) * 0.1 for value in cell))


def clearance(workspace: Path, solid: set, **overrides) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    write_occupancy(workspace, solid)
    settings = config(**overrides)
    return validate_seed_clearance(workspace, settings), settings


def test_corrupt_tree_never_yields_a_relocation(tmp_path: Path) -> None:
    """Search có BFS cũng không được tin cây hỏng để tìm ô trống."""
    meta = write_occupancy(tmp_path, FAR)
    words = [0x80000001, 0x80000002, 0x80000003, 0x80000004, 0, 0, 0x80000000]
    (tmp_path / "occupancy.voxel.bin").write_bytes(struct.pack("<7I", *words))
    assert json.loads((tmp_path / "occupancy.voxel.json").read_text()) == meta
    with pytest.raises(ValueError):
        validate_seed_clearance(tmp_path, config(navigation_seed_world=world_of((63, 63, 63))))
    assert not (tmp_path / "seed-clearance.json").exists()


def test_valid_seed_keeps_native_kernel_and_does_not_relocate(tmp_path: Path) -> None:
    """Native Y-up half-height, không ép height >= diameter; seed trống thì giữ nguyên."""
    receipt, settings = clearance(
        tmp_path, FAR, capsule_height_m=0.15, capsule_radius_m=0.21, navigation_seed_world=world_of((32, 32, 32))
    )
    assert tuple(hi - lo for lo, hi in zip(receipt["kernel_low"], receipt["kernel_high"])) == (6, 2, 6)
    assert receipt["relocates"] is False
    assert receipt["requested_seed_world"] == receipt["accepted_seed_world"] == list(settings.navigation_seed_world)
    assert receipt["relocation_steps_voxels"] == 0
    assert json.loads((tmp_path / "seed-clearance.json").read_text())["relocates"] is False


def test_blocked_seed_relocates_and_records_both_points(tmp_path: Path) -> None:
    """Seed bị vùi trong vật cản được tìm lại; receipt giữ cả điểm đã yêu cầu lẫn điểm nhận."""
    receipt, settings = clearance(tmp_path, CUBE, navigation_seed_world=world_of((32, 32, 32)))
    assert receipt["relocates"] is True
    assert receipt["requested_seed_world"] == list(settings.navigation_seed_world)
    assert receipt["accepted_seed_world"] != receipt["requested_seed_world"]
    assert receipt["relocation_steps_voxels"] >= 1
    assert receipt["relocation_distance_m"] <= settings.max_seed_relocation_m
    assert receipt["reachable_cells"] > 0
    assert tree(tmp_path).intersects(CellBox(receipt["kernel_low"], receipt["kernel_high"])) is False


def test_relocation_is_deterministic(tmp_path: Path) -> None:
    """Cùng input phải cho cùng accepted seed; không có tie-break ngẫu nhiên."""
    first, _ = clearance(tmp_path / "a", CUBE, navigation_seed_world=world_of((32, 32, 32)))
    second, _ = clearance(tmp_path / "b", CUBE, navigation_seed_world=world_of((32, 32, 32)))
    assert first["accepted_seed_world"] == second["accepted_seed_world"]
    assert first["accepted_seed_cell"] == second["accepted_seed_cell"]


def test_relocation_beyond_bound_is_rejected(tmp_path: Path) -> None:
    """Ô trống có thật nhưng ngoài ngưỡng mét thì từ chối, không nới ngưỡng để lấy."""
    with pytest.raises(ValueError, match="within the relocation bound"):
        clearance(tmp_path, CUBE, navigation_seed_world=world_of((32, 32, 32)), max_seed_relocation_m=0.1)


def test_seed_buried_in_thick_wall_is_rejected(tmp_path: Path) -> None:
    """Không có ô tự do nào chạm seed trong số bước thoát thì reject, không đào xuyên bức tường dày."""
    thick = wall(0, range(30, 38))
    with pytest.raises(ValueError, match="touching the requested seed"):
        clearance(tmp_path, thick, navigation_seed_world=world_of((33, 32, 32)))
    with pytest.raises(ValueError, match="touching the requested seed"):
        clearance(
            tmp_path / "wide",
            thick,
            navigation_seed_world=world_of((33, 32, 32)),
            max_seed_relocation_m=100.0,
        )


def test_relocation_stays_in_connected_region_of_the_seed(tmp_path: Path) -> None:
    """Seed nằm trong bức tường; ứng viên phải thuộc phòng chứa nó, không sang phòng bên kia."""
    receipt, _ = clearance(tmp_path, wall(0, range(30, 32)), navigation_seed_world=world_of((30, 32, 32)))
    accepted = tuple(receipt["accepted_seed_cell"])
    assert accepted[0] <= 28, "relocation must not cross to the far side of the wall"
    assert receipt["escape_hops_voxels"] >= 1
    assert tree(tmp_path).intersects(CellBox(receipt["kernel_low"], receipt["kernel_high"])) is False


def test_seed_inside_solid_block_without_free_neighbour_is_rejected(tmp_path: Path) -> None:
    """Seed bị vùi kín, mọi ô lân cận đều rắn thì không có đường thoát hợp lệ."""
    block = {(i, j, k) for i in range(20, 45) for j in range(20, 45) for k in range(20, 45)}
    with pytest.raises(ValueError, match="touching the requested seed"):
        clearance(tmp_path, block, navigation_seed_world=world_of((32, 32, 32)))


@pytest.mark.parametrize("seed", [(100, 0, 0), (3.0, -3.0, 3.0), (-3.2, 0, 0)])
def test_out_of_bounds_seed_is_rejected(tmp_path: Path, seed: tuple[float, float, float]) -> None:
    """Ngoài grid không phải free space; kernel tràn biên phải raise trước khi search."""
    write_occupancy(tmp_path, FAR)
    with pytest.raises(ValueError, match="seed capsule kernel"):
        validate_seed_clearance(tmp_path, config(navigation_seed_world=seed))


def test_adapter_stops_before_carve_and_publishes_nothing(tmp_path: Path) -> None:
    """Seed không hợp lệ thì dừng trước collision process, không có log hay receipt."""
    source = tmp_path / "source.ply"
    source.write_bytes(b"fixture")
    values = request(source).model_dump()
    values["config"]["navigation_seed_world"] = (100, 0, 0)
    output = tmp_path / "attempt"
    with pytest.raises(GeometryError) as error:
        adapter().run_synthetic(SyntheticVoxelRequest.model_validate(values), output)
    assert "seed capsule" in str(error.value.__cause__)
    assert not (output / "collision.log").exists()
    assert not (output / "qualification.json").exists()
    assert not (output / "seed-clearance.json").exists()
