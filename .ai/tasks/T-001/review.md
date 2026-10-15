# Review T-001

Verdict: ACCEPTED

Đã đọc `plan.md`, `report.md` và diff thật của `0ecd01e1`, `f7d6d176`. Bỏ qua bước Summarizer theo quyết định của chủ dự án.

## Acceptance criteria
1. Test cũ PASS: **pass**. Chạy lại `test_object_aware_geometry.py`, `test_object_aware_composition.py`, cộng thêm
   `tests/test_simulation/test_surface_convex_runner.py` (report nêu chưa chạy) và `test_objectgs_objectify_flow.py`: 29 passed.
2. Một ô → 8 đỉnh, 12 tam giác, watertight, volume = voxel³: **pass** (`test_occupancy_surface_single_cell_is_closed_unit_cube`).
3. Hai ô kề → 12 đỉnh, 20 tam giác, watertight, volume 2·voxel³: **pass**.
4. Checksum không đổi: **pass**. Kiểm độc lập bằng worktree tại `0ecd01e1` (code cũ): test chốt PASS, nên giá trị golden
   được chụp đúng từ code trước refactor. Agent chốt thêm digest đỉnh/mặt, chặt hơn plan (occupancy_checksum chỉ băm ô
   giữ lại, không bắt được thay đổi cách phát mặt). Lệch plan hợp lý.

## Correctness
- Vòng lặp chép nguyên, không đổi thứ tự duyệt, winding hay kiểu dữ liệu đầu ra.
- Kiểm `max_grid_cells` vẫn chạy trước lời gọi.
- Validate `voxel_m` (NaN, inf, ≤ 0) và tập ô rỗng có test.
- Commit đúng thứ tự: chốt hành vi trước, refactor sau. Không Co-Authored-By. Chỉ stage file của task.

## Required changes
Không có.

## Suggestions (không chặn)
- T-002 sẽ gọi hàm với tập ô lớn (hàng trăm nghìn ô). Vòng lặp Python dùng `set` vẫn đủ cho collision nền hiện tại;
  nếu T-002 đo thấy chậm, vector hoá trong T-002 nhưng **phải giữ** digest của test chốt.
