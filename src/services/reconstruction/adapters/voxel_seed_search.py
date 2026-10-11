"""Tìm seed hợp lệ trong vùng không khí liên thông, thay vì quét vỏ cube.

ADR 0001 (owner amendment 2026-09-27) cho phép relocate seed có kiểm soát. Khác
với `findNearestFreeCell` của upstream 3.6.6 — quét vỏ cube, không connectivity,
có thể nhảy xuyên tường — module này BFS trên tập ô tự do nên ứng viên luôn nằm
trong cùng vùng không khí liên thông với seed đã yêu cầu.

Khoảng cách Euclidean tính từ seed gốc phải trong ngưỡng mét; đường BFS chỉ qua
raw free air; mọi quyết định giữ cả seed gốc lẫn seed được chấp nhận. Nếu tâm seed
nằm trong ô rắn thì không đoán phía nào của tường: từ chối và yêu cầu chọn lại.
"""

import math
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

from src.services.reconstruction.adapters.voxel_octree import Cell, CellBox, VoxelOctree
from src.services.reconstruction.adapters.voxel_output import VoxelMetadata
from src.services.reconstruction.rgb.geometry.voxel import (
    Vector3,
    VoxelConfig,
    native_from_world,
    world_from_native,
)

# Chỉ 6 lân cận cạnh: đi đường chéo là lọt qua kẽ của voxel rắn, vô nghĩa với
# đường đi của robot dù hình học có thể thông.
NEIGHBOURS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


@dataclass(frozen=True)
class SeedSearchPlan:
    """Mọi thứ đã resolve về lưới voxel, để các bước sau không phải quy đổi hệ toạ độ."""

    tree: VoxelOctree
    cell: Cell
    extents: Cell
    max_steps: int
    escape_hops: int
    requested_world: Vector3
    distance_limit_m: float

    @property
    def resolution(self) -> float:
        return self.tree.metadata.voxel_resolution

    def kernel(self, cell: Cell) -> CellBox:
        return CellBox(
            tuple(value - extent for value, extent in zip(cell, self.extents)),
            tuple(value + extent for value, extent in zip(cell, self.extents)),
        )

    def world(self, cell: Cell) -> Vector3:
        """Native Y-up sang canonical Z-up, giữ đơn vị mét."""
        bounds = self.tree.metadata.grid_bounds
        return world_from_native(
            tuple(bounds.min[axis] + (value + 0.5) * self.resolution for axis, value in enumerate(cell))
        )

    def steps_from_seed(self, cell: Cell) -> int:
        return sum(abs(value - start) for value, start in zip(cell, self.cell))

    def distance(self, cell: Cell) -> float:
        """Đo từ điểm yêu cầu thật, không từ tâm voxel đã làm tròn."""
        return math.dist(self.requested_world, self.world(cell))

    def fits_grid(self, cell: Cell) -> bool:
        """Kernel tràn ra ngoài grid thì không phải free space, mà là ngoài phạm vi."""
        box = self.kernel(cell)
        return all(lo >= 0 and hi < limit for lo, hi, limit in zip(box.low, box.high, self.tree.dimensions))


@dataclass(frozen=True)
class SeedSearchResult:
    """Ứng viên được chọn cùng thông số phải báo lại trong clearance evidence."""

    cell: Cell
    relocates: bool
    steps: int
    escape_hops: int
    reachable_cells: int


@dataclass(frozen=True)
class _Region:
    """Khối dense đang xét; luôn bao trọn kernel của mọi ứng viên trong ngưỡng."""

    origin: Cell
    size: Cell

    def flat(self, cell: Cell) -> int:
        local = tuple(value - start for value, start in zip(cell, self.origin))
        return (local[2] * self.size[1] + local[1]) * self.size[0] + local[0]

    def cell_of(self, flat: int) -> Cell:
        size_x, size_y, _ = self.size
        return (
            self.origin[0] + flat % size_x,
            self.origin[1] + (flat // size_x) % size_y,
            self.origin[2] + flat // (size_x * size_y),
        )

    def unpack(self, flat: int) -> Cell:
        """Toạ độ cục bộ trong vùng, theo đúng thứ tự X nhanh nhất."""
        size_x, size_y, _ = self.size
        return flat % size_x, (flat // size_x) % size_y, flat // (size_x * size_y)

    def pack(self, x: int, y: int, z: int) -> int | None:
        """Chỉ số phẳng, hoặc None khi lân cận nằm ngoài vùng đang xét."""
        if not (0 <= x < self.size[0] and 0 <= y < self.size[1] and 0 <= z < self.size[2]):
            return None
        return (z * self.size[1] + y) * self.size[0] + x


def search_plan(tree: VoxelOctree, config: VoxelConfig) -> SeedSearchPlan:
    """Chốt ngưỡng dịch chuyển và số bước thoát từ kích thước capsule, không phải hằng số chui."""
    extents = kernel_extents(config)
    cell = seed_cell(config, tree.metadata)
    if any(value < 0 or value >= limit for value, limit in zip(cell, tree.dimensions)):
        raise ValueError("seed capsule kernel is outside occupancy bounds; select another seed")
    return SeedSearchPlan(
        tree=tree,
        cell=cell,
        extents=extents,
        max_steps=math.ceil(config.max_seed_relocation_m / tree.metadata.voxel_resolution),
        escape_hops=max(extents) + 1,
        requested_world=config.navigation_seed_world,
        distance_limit_m=config.max_seed_relocation_m,
    )


def kernel_extents(config: VoxelConfig) -> Cell:
    """Đúng `ceil` của carve 3.6.6: bán kính ở X/Z, nửa chiều cao ở Y."""
    radius = math.ceil(config.capsule_radius_m / config.resolution_m)
    return radius, math.ceil(config.capsule_height_m / (2 * config.resolution_m)), radius


def seed_cell(config: VoxelConfig, metadata: VoxelMetadata) -> Cell:
    """Ô chứa seed native, tức đúng `floor((seed - gridMin) / resolution)`."""
    seed = native_from_world(config.navigation_seed_world)
    return tuple(
        math.floor((value - low) / metadata.voxel_resolution) for value, low in zip(seed, metadata.grid_bounds.min)
    )


def find_connected_seed(plan: SeedSearchPlan) -> SeedSearchResult:
    """Ứng viên gần nhất trong vùng liên thông; raise khi vượt ngưỡng hoặc không có ứng viên."""
    if not plan.tree.intersects(plan.kernel(plan.cell)):
        return SeedSearchResult(plan.cell, False, 0, 0, 0)
    # Tâm seed trong vật rắn không xác định được phía tự do nào là đúng. Không
    # khởi tạo nhiều BFS ở hai bên tường để tạo ra connectivity giả.
    if plan.tree.intersects(CellBox(plan.cell, plan.cell)):
        raise ValueError("no unambiguous free air touching the requested seed; select another seed")
    region = _region(plan)
    solid = plan.tree.solid_mask(region.origin, region.size)
    air = bytearray(
        not hit and (flat == region.flat(plan.cell) or plan.distance(region.cell_of(flat)) <= plan.distance_limit_m)
        for flat, hit in enumerate(solid)
    )
    reached = _flood(region, air, [region.flat(plan.cell)])
    blocked = _box_any(solid, region.size, plan.extents)
    candidates = [flat for flat in reached if not blocked[flat] and plan.fits_grid(region.cell_of(flat))]
    best = _nearest(plan, region, candidates)
    if best is None:
        raise ValueError("no free capsule cell within the relocation bound; select another seed")
    return SeedSearchResult(best, True, plan.steps_from_seed(best), 0, len(reached))


def _region(plan: SeedSearchPlan) -> _Region:
    span = tuple(extent + plan.max_steps for extent in plan.extents)
    low = tuple(max(0, value - reach) for value, reach in zip(plan.cell, span))
    high = tuple(min(limit, value + reach + 1) for value, reach, limit in zip(plan.cell, span, plan.tree.dimensions))
    return _Region(low, tuple(hi - lo for lo, hi in zip(low, high)))


def _box_any(mask: bytearray, size: Cell, extents: Cell) -> bytearray:
    """Dilation box separable, cùng ngữ nghĩa `gpuDilate3` mà carve 3.6.6 dùng."""
    for axis, extent in enumerate(extents):
        mask = _window_any(mask, size, axis, extent)
    return mask


def _window_any(mask: bytearray, size: Cell, axis: int, extent: int) -> bytearray:
    """OR trong cửa sổ đối xứng theo một trục; ngoài mảng bị coi là không chặn."""
    out = bytearray(len(mask))
    stride, line_len = _axis_geometry(size, axis)
    for start in _line_starts(size, axis):
        values = [mask[start + i * stride] for i in range(line_len)]
        for i, hit in enumerate(_line_hits(values, extent)):
            out[start + i * stride] = hit
    return out


def _line_starts(size: Cell, axis: int) -> Iterator[int]:
    """Offset đầu mỗi đường song song `axis`, duyệt theo hai trục còn lại.

    Không suy ra từ `len(mask) // (line_len * stride)` vì khi một trục có extent 0
    thì số đường không còn chia hết, và phần chưa ghi sẽ bị đọc là trống.
    """
    others = [index for index in range(3) if index != axis]
    for outer in range(size[others[1]]):
        for inner in range(size[others[0]]):
            coord = [0, 0, 0]
            coord[others[0]], coord[others[1]] = inner, outer
            yield (coord[2] * size[1] + coord[1]) * size[0] + coord[0]


def _axis_geometry(size: Cell, axis: int) -> tuple[int, int]:
    """X là trục nhanh nhất nên stride của một trục là tích các trục thấp hơn nó."""
    stride = 1
    for lower in range(axis):
        stride *= size[lower]
    return stride, size[axis]


def _line_hits(values: list[int], extent: int) -> list[int]:
    """Cửa sổ trượt [i-extent, i+extent] bị cắt ở hai đầu; trả về 0/1 theo có vật cản hay không."""
    total = sum(values[: extent + 1])
    hits = []
    for index in range(len(values)):
        hits.append(1 if total else 0)
        added, dropped = index + extent + 1, index - extent
        if added < len(values):
            total += values[added]
        if dropped >= 0:
            total -= values[dropped]
    return hits


def _flood(region: _Region, free: bytearray, starts: list[int]) -> list[int]:
    """BFS 6 hướng trên ô tự do; đây là chỗ khác hẳn quét vỏ cube của upstream."""
    seen = bytearray(len(free))
    queue = deque(starts)
    reached = []
    for flat in starts:
        seen[flat] = 1
    while queue:
        flat = queue.popleft()
        reached.append(flat)
        x, y, z = region.unpack(flat)
        for dx, dy, dz in NEIGHBOURS:
            neighbour = region.pack(x + dx, y + dy, z + dz)
            if neighbour is None or seen[neighbour] or not free[neighbour]:
                continue
            seen[neighbour] = 1
            queue.append(neighbour)
    return reached


def _nearest(plan: SeedSearchPlan, region: _Region, reached: list[int]) -> Cell | None:
    """Ứng viên gần nhất trong ngưỡng; tie-break theo tọa độ để kết quả tất định."""
    cells = [region.cell_of(flat) for flat in reached]
    inside = [cell for cell in cells if plan.distance(cell) <= plan.distance_limit_m]
    if not inside:
        return None
    return min(inside, key=lambda cell: (plan.distance(cell), cell))
