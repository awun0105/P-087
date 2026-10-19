# T-001: Tách hàm `occupancy_surface()` dùng chung

## Goal
Đưa phần "ô voxel → mesh mặt lộ ra" trong `build_background_collision` thành một hàm public để
T-002 (vỏ vật) dùng lại. **Không đổi hành vi** của collision môi trường.

## Context
`architecture.md` §6, §8.1. Code hiện tại: `src/services/scene/object_aware_geometry.py`, đoạn từ
comment `# Emit only exposed voxel faces` tới khi tạo `vertices`/`faces`.

## Files
- Sửa: `src/services/scene/object_aware_geometry.py`
- Sửa: `tests/test_scene/test_object_aware_geometry.py` (thêm test)

## Steps
1. Tạo hàm mới trong cùng file:
   ```python
   def occupancy_surface(cells: set[tuple[int, int, int]], voxel_m: float) -> tuple[np.ndarray, np.ndarray]:
       """Exposed voxel faces of an occupancy set, outward winding, metres. Raises ValueError if empty."""
   ```
   Chép nguyên vòng lặp hiện có (duyệt `sorted(cells)`, 6 hướng, đảo thứ tự góc khi `sign < 0`).
   Trả `(vertices float64 (N,3) đã nhân voxel_m, faces int64 (M,3))`.
2. Trong `build_background_collision`, thay vòng lặp bằng `vertices, faces = occupancy_surface(kept, voxel_m)`.
   Giữ nguyên tính `digest`, `statistics`.
3. Kiểm tra `max_grid_cells` vẫn chạy trước khi gọi hàm (như cũ).

## Interfaces
`occupancy_surface(cells, voxel_m) -> (vertices, faces)`; `cells` rỗng → `ValueError("occupancy is empty")`;
`voxel_m` không hữu hạn hoặc ≤ 0 → `ValueError`.

## Acceptance criteria
1. Mọi test cũ trong `tests/test_scene/test_object_aware_geometry.py`,
   `tests/test_scene/test_object_aware_composition.py` vẫn PASS.
2. Một ô đơn → 8 đỉnh, 12 tam giác, `trimesh.Trimesh(...).is_watertight` và `volume ≈ voxel_m**3`.
3. Hai ô kề mặt → 12 đỉnh, 20 tam giác, watertight, volume = 2·voxel³.
4. Checksum `occupancy_checksum` của `build_background_collision` không đổi so với trước refactor
   (test so với một giá trị chụp lại từ code cũ trước khi sửa).

## Tests required
Trong `tests/test_scene/test_object_aware_geometry.py`:
- `test_occupancy_surface_single_cell_is_closed_unit_cube`
- `test_occupancy_surface_adjacent_cells_share_internal_face`
- `test_occupancy_surface_rejects_empty_and_invalid_voxel`
- `test_background_collision_checksum_unchanged_after_refactor` (chụp checksum bằng code cũ trước, hardcode vào test)

Lệnh kiểm tra (KHÔNG chạy full suite):
```
.venv/bin/python -m pytest tests/test_scene/test_object_aware_geometry.py tests/test_scene/test_object_aware_composition.py -q
.venv/bin/ruff check src/services/scene/object_aware_geometry.py tests/test_scene/test_object_aware_geometry.py
.venv/bin/ruff format --check src/services/scene/object_aware_geometry.py tests/test_scene/test_object_aware_geometry.py
```

## Commit
Commit 1: thêm test chụp checksum (chạy trên code cũ, PASS). Commit 2: refactor + test mới.
Không thêm Co-Authored-By. Sau đó `graphify update .`, cập nhật `status.md` → `implemented`, viết `report.md`.

## Out of scope
Không thêm smoothing, không đổi thuật toán, không đụng objectify.
