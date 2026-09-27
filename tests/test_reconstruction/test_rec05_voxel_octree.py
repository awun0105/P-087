"""Proof cho strict native octree reader: format, corruption và dense region extraction.

Hai bug đã sửa ở đây từng làm `solid_mask` sai âm thầm: `_overlaps` dùng `width` làm
upper bound thay vì `node_origin + width`, và `_window_any` bỏ sót ô khi một trục có
extent 0. Cả hai đều trả về "trống" giả nên im lặng chấp nhận seed sai, nên regression
test so với oracle chứ không chỉ so với kết quả đã lưu.
"""

import random
import struct
from pathlib import Path

import pytest

from src.services.reconstruction.adapters.voxel_octree import CellBox, VoxelOctree
from src.services.reconstruction.adapters.voxel_output import VoxelMetadata
from src.services.reconstruction.adapters.voxel_seed_search import _box_any
from tests.test_reconstruction.rec05_occupancy_fixture import GRID_CELLS, wall, write_occupancy

SOLID_WORD = 0xFF000000


def load(workspace: Path) -> VoxelOctree:
    meta = VoxelMetadata.model_validate_json((workspace / "occupancy.voxel.json").read_bytes())
    return VoxelOctree(meta, (workspace / "occupancy.voxel.bin").read_bytes())


def test_exact_mixed_leaf_bits_and_empty_branches(tmp_path: Path) -> None:
    """Octant XYZ và bit z*16+y*4+x; kiểm cả low/high words."""
    write_occupancy(tmp_path, {(63, 63, 63)})
    words = [0x80000001, 0x80000002, 0x80000003, 0x80000004, 0, 2, 0x80000000]
    (tmp_path / "occupancy.voxel.bin").write_bytes(struct.pack("<7I", *words))
    grid = load(tmp_path)
    for point, expected in [((63, 63, 63), True), ((61, 60, 60), True), ((60, 60, 60), False), ((32, 32, 32), False)]:
        assert grid.intersects(CellBox(point, point)) is expected


def test_solid_collapsed_node(tmp_path: Path) -> None:
    """Solid sentinel không bị đọc nhầm là child mask 255."""
    meta = write_occupancy(tmp_path, {(63, 63, 63)})
    meta.update(nodeCount=1, leafDataCount=0, numMixedLeaves=0, numInteriorNodes=0)
    grid = VoxelOctree(VoxelMetadata.model_validate(meta), struct.pack("<I", SOLID_WORD))
    assert grid.intersects(CellBox((1, 1, 1), (2, 2, 2)))


@pytest.mark.parametrize("mode", ["cycle", "pointer", "depth", "mixed", "count", "truncated", "extent", "overflow"])
def test_corrupt_tree_never_proves_free_space(tmp_path: Path, mode: str) -> None:
    """Reject malformed binary ngay lúc load, kể cả corruption ngoài queried box."""
    meta = write_occupancy(tmp_path, {(63, 63, 63)})
    words = [0x80000001, 0x80000002, 0x80000003, 0x80000004, 0, 0, 0x80000000]
    if mode == "cycle":
        words[1] = 0x80000001
    elif mode == "pointer":
        words[0] = 0x800000FF
    elif mode == "depth":
        words[4] = 0x80000005
    elif mode == "mixed":
        words[4] = 1
    elif mode == "count":
        meta["numInteriorNodes"] = 3
    elif mode == "extent":
        meta["gridBounds"]["max"][0] = 3.21
    elif mode == "overflow":
        meta["treeDepth"] = 18
    payload = struct.pack("<7I", *words)
    with pytest.raises(ValueError):
        VoxelOctree(VoxelMetadata.model_validate(meta), payload[:-1] if mode == "truncated" else payload)


def test_solid_collapsed_grid_keeps_full_mask(tmp_path: Path) -> None:
    """Grid đặc hoàn toàn serialize thành một node, không sinh 2^depth node rỗng."""
    everything = {(i, j, k) for i in range(GRID_CELLS) for j in range(GRID_CELLS) for k in range(GRID_CELLS)}
    meta = write_occupancy(tmp_path, everything)
    assert meta["nodeCount"] == 1
    grid = load(tmp_path)
    assert sum(grid.solid_mask((0, 0, 0), (4, 4, 4))) == 64


@pytest.mark.parametrize(
    "solid,origin,size",
    [
        ({(63, 63, 63)}, (0, 0, 0), (8, 8, 8)),
        ({(0, 0, 0)}, (0, 0, 0), (8, 8, 8)),
        (wall(0, range(30, 34)), (25, 25, 25), (15, 15, 15)),
        (wall(2, range(10, 14)), (0, 0, 0), (GRID_CELLS, GRID_CELLS, GRID_CELLS)),
    ],
)
def test_solid_mask_agrees_with_octree_queries(
    tmp_path: Path, solid: set, origin: tuple[int, int, int], size: tuple[int, int, int]
) -> None:
    """Mọi ô trong mask phải khớp đúng kết quả `intersects` từng ô.

    Đây là regression cho `_overlaps`: bug cũ prune nhánh sai nên mask rỗng trong khi
    cây thật sự có vật cản, và sai âm thầm thì seed sai vẫn bị coi là hợp lệ.
    """
    write_occupancy(tmp_path, solid)
    grid = load(tmp_path)
    mask = grid.solid_mask(origin, size)
    for z in range(size[2]):
        for y in range(size[1]):
            for x in range(size[0]):
                point = (origin[0] + x, origin[1] + y, origin[2] + z)
                expected = grid.intersects(CellBox(point, point))
                assert bool(mask[(z * size[1] + y) * size[0] + x]) is expected, point
    assert sum(mask) == sum(
        1
        for i in range(origin[0], origin[0] + size[0])
        for j in range(origin[1], origin[1] + size[1])
        for k in range(origin[2], origin[2] + size[2])
        if (i, j, k) in solid
    )


def test_solid_mask_rejects_region_outside_grid(tmp_path: Path) -> None:
    """Vùng tràn grid bị từ chối thay vì âm thầm coi phần ngoài là trống."""
    write_occupancy(tmp_path, {(63, 63, 63)})
    grid = load(tmp_path)
    with pytest.raises(ValueError, match="outside the occupancy grid"):
        grid.solid_mask((60, 0, 0), (8, 8, 8))
    with pytest.raises(ValueError, match="outside the occupancy grid"):
        grid.solid_mask((0, 0, 0), (0, 8, 8))


@pytest.mark.parametrize(
    "size,extents",
    [
        ((5, 6, 7), (1, 2, 1)),
        ((4, 4, 4), (1, 0, 1)),
        ((6, 5, 4), (2, 1, 0)),
        ((4, 1, 1), (1, 0, 0)),
        ((3, 3, 3), (0, 0, 0)),
        ((7, 5, 6), (2, 3, 1)),
    ],
)
def test_separable_box_any_matches_brute_force(size: tuple[int, int, int], extents: tuple[int, int, int]) -> None:
    """Dilation separable phải bằng box oracle, kể cả khi một trục có extent 0.

    Regression cho `_window_any`: trước đó số đường bị suy ra từ `len(mask) //
    (line_len * stride)`, nên khi extent 0 thì phần chưa ghi bị đọc là không chặn.
    """
    random.seed(20260927)
    source = bytearray(random.randint(0, 1) for _ in range(size[0] * size[1] * size[2]))
    got = _box_any(bytearray(source), size, extents)

    def solid(x: int, y: int, z: int) -> bool:
        return bool(source[(z * size[1] + y) * size[0] + x])

    for z in range(size[2]):
        for y in range(size[1]):
            for x in range(size[0]):
                want = any(
                    solid(x + dx, y + dy, z + dz)
                    for dz in range(-extents[2], extents[2] + 1)
                    for dy in range(-extents[1], extents[1] + 1)
                    for dx in range(-extents[0], extents[0] + 1)
                    if 0 <= x + dx < size[0] and 0 <= y + dy < size[1] and 0 <= z + dz < size[2]
                )
                assert bool(got[(z * size[1] + y) * size[0] + x]) is want, (x, y, z)
