# Report T-001

## Done
- Bước 1: thêm `occupancy_surface(cells, voxel_m) -> (vertices, faces)` trong `src/services/scene/object_aware_geometry.py`. Vòng lặp mặt lộ ra được chép nguyên từ `build_background_collision`: duyệt `sorted(cells)`, 6 hướng, đảo thứ tự góc khi `sign < 0`. `cells` rỗng → `ValueError("occupancy is empty")`; `voxel_m` không hữu hạn hoặc ≤ 0 → `ValueError("voxel_m must be finite and positive")`.
- Bước 2: `build_background_collision` thay vòng lặp bằng `vertices, faces = occupancy_surface(kept, voxel_m)`. `digest` và `statistics` không đổi.
- Bước 3: kiểm tra `max_grid_cells` vẫn chạy trước lời gọi hàm.
- Commit 1 (`0ecd01e1`): thêm `test_background_collision_checksum_unchanged_after_refactor`, chụp giá trị trên code cũ, PASS, rồi hardcode vào test.
- Commit 2 (`f7d6d176`): refactor + 3 test `occupancy_surface` theo plan.

## Files changed
- `src/services/scene/object_aware_geometry.py`: thêm `occupancy_surface()`; `build_background_collision` gọi hàm này.
- `tests/test_scene/test_object_aware_geometry.py`: test pin checksum và digest mesh; 3 test `occupancy_surface`.
- `.ai/tasks/T-001/report.md`: báo cáo này.
- `.ai/status.md`: T-001 → `implemented | summarizer` (chỉ dòng T-001 được commit).

## Tests
Chạy từ root repo, không chạy full suite:
- `.venv/bin/python -m pytest tests/test_scene/test_object_aware_geometry.py tests/test_scene/test_object_aware_composition.py -q`
  - Trên code cũ (sau commit 1): 8 passed.
  - Sau refactor: **11 passed**. Cả 3 test mới và test pin đều PASSED.
- `.venv/bin/ruff check src/services/scene/object_aware_geometry.py tests/test_scene/test_object_aware_geometry.py`: All checks passed!
- `.venv/bin/ruff format --check src/services/scene/object_aware_geometry.py tests/test_scene/test_object_aware_geometry.py`: 2 files already formatted.

Giá trị chụp từ code cũ (fixture `fixture()` của test, `voxel_m=0.1`, `removed_labels={1}`):
- `occupancy_checksum = sha256:caea4ebef4569c056cc8a0b551e8ced62e95a5234ae5826cb4c0f255cf7ae1ab`
- SHA-256 của `vertices` (float64 little-endian) nối với `faces` (int64 little-endian) = `a2bedb2a16b128bf4658b2760f5f00f1c6f38298b46652acc97dc0141af9850d` (1676 đỉnh, 3348 tam giác).

## Deviations from plan
- Test pin có thêm SHA-256 của `vertices` và `faces`, không chỉ `occupancy_checksum`. Lý do: `occupancy_checksum` chỉ băm tập ô giữ lại và `voxel_m`, nên không phát hiện được thay đổi trong cách phát mặt. Không có digest mặt thì tiêu chí "không đổi hành vi" chưa được kiểm chứng.
- Plan không chỉ định input của test pin: dùng `fixture()` có sẵn (`voxel_m=0.1`, `removed_labels={1}`).
- Plan không chỉ định thông điệp lỗi cho `voxel_m`: chọn `"voxel_m must be finite and positive"`.
- Không có câu hỏi thiết kế nào mà plan không trả lời, nên không dừng giữa chừng.

## Known issues / TODO
- Chưa chạy `tests/test_simulation/test_surface_convex_runner.py`. File này cũng import `build_background_collision` nhưng nằm ngoài mục "Tests required" nên không chạy. Hàm đã được khóa bằng digest trên fixture; chưa kiểm chứng trên scene thật hay với CoACD.
- `graphify update .` đã chạy (24406 node). graphify báo số community đã đổi so với lúc gán nhãn; chưa chạy `graphify label` (bước LLM, không thuộc task).
- Cây làm việc còn thay đổi không thuộc T-001: xóa `tasks/CFG-*`, `tasks/reports/*`, file untracked `BRAINSTORM.md`, `MASTER_PITCH.md`, `tasks/CFG/`, và dòng T-003 trong `status.md` đã đổi sang `in-progress` bởi phiên khác. Các mục này không được stage và không bị đụng tới.
