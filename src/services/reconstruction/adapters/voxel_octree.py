"""Reader format Laine–Karras 1.1; không viết lại voxelizer hay capsule carve.

ADAPT: supersplat-viewer/src/collision/voxel-collision.ts, isVoxelSolid /
checkLeafByIndex, revision c52f5258df424635323f26aaeebe51361dc0f8e6.
Copyright (c) 2011-2026 PlayCanvas Ltd. MIT, xem voxel_octree.LICENSE.
Thêm strict graph validation và box query để không quét toàn bộ dense grid.
"""

import math
import struct
from dataclasses import dataclass

from src.services.reconstruction.adapters.voxel_output import VoxelMetadata

Cell = tuple[int, int, int]
SOLID = 0xFF000000
OFFSET = 0xFFFFFF


@dataclass(frozen=True)
class CellBox:
    """Khoảng voxel đóng cả hai đầu, native Y-up."""

    low: Cell
    high: Cell

    def overlaps(self, origin: Cell, width: int) -> bool:
        """Bỏ qua nhánh octree nằm ngoài capsule kernel."""
        return all(lo < start + width and hi >= start for lo, hi, start in zip(self.low, self.high, origin))


class VoxelOctree:
    """Đọc little-endian bytes và kiểm mọi pointer trước khi nhận free space."""

    def __init__(self, metadata: VoxelMetadata, payload: bytes) -> None:
        self.metadata = metadata
        self.payload = payload
        self.dimensions = self._dimensions()
        if len(payload) != 4 * (metadata.node_count + metadata.leaf_data_count):
            raise ValueError("voxel binary length differs from metadata")
        self._validate_tree()

    def _dimensions(self) -> Cell:
        meta = self.metadata
        if meta.tree_depth > 17:
            raise ValueError("voxel tree exceeds pinned Morton depth limit")
        sizes = tuple((hi - lo) / meta.voxel_resolution for lo, hi in zip(meta.grid_bounds.min, meta.grid_bounds.max))
        if any(not math.isclose(size, round(size), rel_tol=0, abs_tol=1e-6) for size in sizes):
            raise ValueError("voxel grid extent is not integral")
        dimensions = tuple(round(size) for size in sizes)
        if any(size <= 0 or size % 4 or size > 4 * (1 << meta.tree_depth) for size in dimensions):
            raise ValueError("voxel grid extent disagrees with tree depth/leaf size")
        return dimensions

    def _word(self, index: int) -> int:
        return struct.unpack_from("<I", self.payload, index * 4)[0]

    def _children(self, index: int, level: int) -> range:
        node = self._word(index)
        count = (node >> 24).bit_count()
        base = node & OFFSET
        if level <= 0 or base <= index or base + count > self.metadata.node_count:
            raise ValueError("invalid voxel child pointer/depth")
        return range(base, base + count)

    def _validate_tree(self) -> None:
        pending = [(0, self.metadata.tree_depth)]
        seen: set[int] = set()
        leaves: set[int] = set()
        interiors = 0
        while pending:
            index, level = pending.pop()
            if index in seen:
                raise ValueError("voxel tree contains shared or cyclic nodes")
            seen.add(index)
            node = self._word(index)
            if node == SOLID:
                continue
            if node >> 24:
                interiors += 1
                pending.extend((child, level - 1) for child in self._children(index, level))
            else:
                if level != 0 or node in leaves or node >= self.metadata.num_mixed_leaves:
                    raise ValueError("invalid voxel mixed leaf pointer/depth")
                leaves.add(node)
        meta = self.metadata
        if (len(seen), interiors, len(leaves), meta.leaf_data_count) != (
            meta.node_count,
            meta.num_interior_nodes,
            meta.num_mixed_leaves,
            2 * len(leaves),
        ):
            raise ValueError("voxel tree counts/unreachable payload disagree")

    def solid_mask(self, origin: Cell, size: Cell) -> bytearray:
        """Trích occupancy thành mảng dense trong khối [origin, origin+size).

        Cần cho seed search: BFS hàng nghìn ô không thể gọi `intersects` từng ô vì
        mỗi lần là một lần duyệt cây. Một lần duyệt cây cho cả vùng rẻ hơn nhiều.
        """
        if any(
            lo < 0 or extent <= 0 or lo + extent > limit for lo, extent, limit in zip(origin, size, self.dimensions)
        ):
            raise ValueError("solid mask region falls outside the occupancy grid")
        mask = bytearray(size[0] * size[1] * size[2])
        pending = [(0, (0, 0, 0), 4 * (1 << self.metadata.tree_depth))]
        while pending:
            index, node_origin, width = pending.pop()
            if not _overlaps(node_origin, width, origin, size):
                continue
            node = self._word(index)
            if node == SOLID:
                _fill(mask, node_origin, width, origin, size)
                continue
            if not node >> 24:
                self._stamp_leaf(mask, node, node_origin, origin, size)
                continue
            half = width // 2
            mask_bits, base = node >> 24, node & OFFSET
            for octant in range(8):
                if mask_bits & (1 << octant):
                    start = tuple(node_origin[axis] + ((octant >> axis) & 1) * half for axis in range(3))
                    pending.append((base + (mask_bits & ((1 << octant) - 1)).bit_count(), start, half))
        return mask

    def _stamp_leaf(self, mask: bytearray, leaf: int, node_origin: Cell, origin: Cell, size: Cell) -> None:
        offset = self.metadata.node_count + leaf * 2
        bits = self._word(offset) | (self._word(offset + 1) << 32)
        while bits:
            bit = (bits & -bits).bit_length() - 1
            point = tuple(node_origin[axis] + ((bit >> (axis * 2)) & 3) for axis in range(3))
            _set(mask, point, origin, size)
            bits &= bits - 1

    def intersects(self, box: CellBox) -> bool:
        """Query exact rounded dilation box; ngoài grid không được coi là free space."""
        if any(lo < 0 or hi < lo or hi >= size for lo, hi, size in zip(box.low, box.high, self.dimensions)):
            raise ValueError("seed capsule kernel is outside occupancy bounds; select another seed")
        pending = [(0, (0, 0, 0), 4 * (1 << self.metadata.tree_depth))]
        while pending:
            index, origin, width = pending.pop()
            if not box.overlaps(origin, width):
                continue
            node = self._word(index)
            if node == SOLID:
                return True
            if not node >> 24:
                if self._leaf_intersects(node, origin, box):
                    return True
                continue
            half = width // 2
            mask, base = node >> 24, node & OFFSET
            for octant in range(8):
                if mask & (1 << octant):
                    child = base + (mask & ((1 << octant) - 1)).bit_count()
                    start = tuple(origin[axis] + ((octant >> axis) & 1) * half for axis in range(3))
                    pending.append((child, start, half))
        return False

    def _leaf_intersects(self, leaf: int, origin: Cell, box: CellBox) -> bool:
        offset = self.metadata.node_count + leaf * 2
        bits = self._word(offset) | (self._word(offset + 1) << 32)
        while bits:
            bit = (bits & -bits).bit_length() - 1
            point = tuple(origin[axis] + ((bit >> (axis * 2)) & 3) for axis in range(3))
            if box.overlaps(point, 1):
                return True
            bits &= bits - 1
        return False


def _overlaps(node_origin: Cell, width: int, origin: Cell, size: Cell) -> bool:
    """Prune nhánh octree không giao vùng trích xuất; trả về False để bỏ cả nhánh.

    Node trải [node_origin, node_origin + width - 1], vùng trải [origin, origin + size - 1],
    nên overlap khi `node_origin < origin + size` và `node_origin + width > origin`.
    """
    return all(
        start < low + extent and start + width > low
        for start, width, low, extent in zip(node_origin, (width,) * 3, origin, size)
    )


def _index(point: Cell, origin: Cell, size: Cell) -> int:
    """Chỉ số phẳng theo trục X ngoài cùng để BFS index hợp lệ."""
    local = tuple(value - start for value, start in zip(point, origin))
    if any(value < 0 or value >= extent for value, extent in zip(local, size)):
        return -1
    return (local[2] * size[1] + local[1]) * size[0] + local[0]


def _set(mask: bytearray, point: Cell, origin: Cell, size: Cell) -> None:
    flat = _index(point, origin, size)
    if flat >= 0:
        mask[flat] = 1


def _fill(mask: bytearray, node_origin: Cell, width: int, origin: Cell, size: Cell) -> None:
    """Solid node bao trọn khối con: đánh dấu mọi ô trong giao với vùng."""
    low = tuple(max(lo, start) for lo, start in zip(node_origin, origin))
    high = tuple(min(lo + width, start + extent) for lo, start, extent in zip(node_origin, origin, size))
    for z in range(low[2], high[2]):
        for y in range(low[1], high[1]):
            start = _index((low[0], y, z), origin, size)
            if start >= 0:
                mask[start : start + high[0] - low[0]] = b"\1" * (high[0] - low[0])
