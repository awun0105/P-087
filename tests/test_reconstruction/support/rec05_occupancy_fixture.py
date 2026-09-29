"""Sparse occupancy fixture hợp lệ; không mô phỏng Gaussian GPU voxelization."""

import json
import struct
from pathlib import Path

from src.services.reconstruction.adapters.voxel_octree import SOLID

GRID_CELLS = 64
TREE_DEPTH = 4
RESOLUTION = 0.1
BOUNDS = 3.2


def occupancy_fixture(workspace: Path) -> dict:
    """Một voxel ở góc xa grid 64³, phần giữa trống cho orchestration fixture."""
    return write_occupancy(workspace, {(63, 63, 63)})


def write_occupancy(workspace: Path, solid: set[tuple[int, int, int]], name: str = "occupancy") -> dict:
    """Ghi occupancy octree hợp lệ từ tập ô rắn; tự build đúng pointer/mask/counts."""
    if any(not 0 <= value < GRID_CELLS for cell in solid for value in cell):
        raise ValueError("fixture cell outside the 64³ grid")
    nodes: list[int] = []
    leaves: list[int] = []
    _emit(_spec(solid, (0, 0, 0), GRID_CELLS, TREE_DEPTH), nodes, leaves)
    metadata = dict(
        version="1.1",
        asset={"generator": "splat-transform v3.6.6"},
        gridBounds={"min": [-BOUNDS] * 3, "max": [BOUNDS] * 3},
        sceneBounds={"min": [-BOUNDS] * 3, "max": [BOUNDS] * 3},
        voxelResolution=RESOLUTION,
        leafSize=4,
        treeDepth=TREE_DEPTH,
        numInteriorNodes=sum(1 for node in nodes if node != SOLID and node >> 24),
        numMixedLeaves=len(leaves),
        nodeCount=len(nodes),
        leafDataCount=2 * len(leaves),
    )
    payload = struct.pack(
        f"<{len(nodes) + 2 * len(leaves)}I", *nodes, *[w for bits in leaves for w in (bits & 0xFFFFFFFF, bits >> 32)]
    )
    (workspace / f"{name}.voxel.json").write_text(json.dumps(metadata))
    (workspace / f"{name}.voxel.bin").write_bytes(payload)
    return metadata


def _spec(solid: set, origin: tuple[int, int, int], span: int, level: int):
    """None = trống hoàn toàn, SOLID = đặc hoàn toàn, int = mixed leaf, dict = interior."""
    present = {
        (origin[0] + i, origin[1] + j, origin[2] + k)
        for i in range(span)
        for j in range(span)
        for k in range(span)
        if (origin[0] + i, origin[1] + j, origin[2] + k) in solid
    }
    if not present:
        return None
    if len(present) == span**3:
        return SOLID
    if level == 0:
        return sum(1 << ((x & 3) + 4 * (y & 3) + 16 * (z & 3)) for x, y, z in present)
    half = span // 2
    children = {}
    for octant in range(8):
        corner = tuple(origin[axis] + ((octant >> axis) & 1) * half for axis in range(3))
        child = _spec(solid, corner, half, level - 1)
        if child is not None:
            children[octant] = child
    return children


def _emit(root, nodes: list[int], leaves: list[int]) -> None:
    """Serialize BFS theo level, đúng `flattenDenseLevels` của writer 3.6.6.

    Writer gom node của một level trước, rồi append con của từng parent theo thứ tự
    octant tăng dần, liên tục ngay sau `nodeLen` hiện tại. Reader tính con là
    `base + popcount(mask thấp hơn)`, nên DFS sẽ phá vỡ liên kết này.
    """
    pending: list[tuple[int, dict]] = []
    nodes.append(0)
    if root is SOLID:
        nodes[0] = SOLID
    elif not isinstance(root, dict):
        leaves.append(root)
        nodes[0] = 0
    else:
        pending.append((0, root))
    while pending:
        wave, pending = pending, []
        for index, spec in wave:
            base = len(nodes)
            octants = sorted(spec)
            for slot, octant in enumerate(octants):
                child = spec[octant]
                nodes.append(0)
                if child is SOLID:
                    nodes[base + slot] = SOLID
                elif not isinstance(child, dict):
                    leaves.append(child)
                    nodes[base + slot] = len(leaves) - 1
                else:
                    pending.append((base + slot, child))
            nodes[index] = (sum(1 << octant for octant in octants) << 24) | base


def wall(axis: int, cells: range) -> set[tuple[int, int, int]]:
    """Bức chắn nguyên phẳng vuông góc trục, dùng để chứng minh không xuyên tường."""
    return {
        (i, j, k)
        for i in range(GRID_CELLS)
        for j in range(GRID_CELLS)
        for k in range(GRID_CELLS)
        if (i, j, k)[axis] in cells
    }


def shell(radius: int) -> set[tuple[int, int, int]]:
    """Khối rắn đặc có cạnh; dùng để kiểm seed bị vùi không còn ô tự do nào chạm tới."""
    centre = (GRID_CELLS // 2,) * 3
    return {
        (i, j, k)
        for i in range(GRID_CELLS)
        for j in range(GRID_CELLS)
        for k in range(GRID_CELLS)
        if max(abs(a - b) for a, b in zip((i, j, k), centre)) <= radius
    }
