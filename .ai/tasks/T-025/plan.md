# T-025: Preview chỉnh vùng nhanh hơn và không giữ khoá lâu (GR-05, P2)

## Goal
Preview 2 triệu hàng (warm) về ≤ 1,5 s trên máy dev khi không có tải khác; `test_preview_three_hundred_thousand_rows_budget`
PASS ổn định. Không nới QA, không nới floor, không nâng timeout.

## Context
`.ai/tasks/T-019/review.md` §GR-05 và `evidence/preview-profile.txt`: warm 1,87 s = `_shell` 1,12 s + `_filter_gaussians`
0,96 s (kNN), `_resolve` 0,73 s; `_SOURCE_LOCK` giữ cả lúc đọc PLY/checksum/fit sàn (`membership_regeneration.py:78-89`);
cache 2 mục theo checksum labels nên Apply đổi labels là đọc lại PLY.

## Steps (đo profile sau mỗi bước, ghi số vào report)
1. Một phép đổi world → local cho mỗi preview (`region_box.resolve_region:98-101` và `object_region._resolve:96` đang làm hai lần).
2. Tách khoá: khoá chỉ bảo vệ bảng LRU; đọc/fit chạy ngoài khoá, chống tải trùng bằng future theo key.
3. Cache nguồn (positions, rows, floor) theo **identity của PLY nguồn** (`source_visual_ref.checksum` + profile sàn), không theo
   labels; labels đọc/kiểm checksum riêng mỗi lần (rẻ). Ngân sách byte (mặc định 1 GiB, cấu hình qua Settings), loại LRU.
4. Nếu còn vượt: đo lại rồi mới đụng `_filter_gaussians` (ví dụ giới hạn kNN trên mẫu 100k hàng đã chọn cho vỏ).

## Acceptance criteria
1. Benchmark script trong `scripts/scene/` (hoặc test đánh dấu `slow`): cold/warm, 1 và 16 box, 2M hàng PLY đủ SH; báo p50/p95,
   RSS. Warm p50 ≤ 1,5 s trên máy dev rảnh — ghi cấu hình máy.
2. Test budget 300k PASS 5/5 lần chạy riêng.
3. Kết quả preview (counts, checksum vỏ) giống hệt trước tối ưu trên các fixture hiện có.
4. Hai preview đồng thời trên hai job không chặn nhau trong lúc một job đang đọc PLY.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_region.py tests/test_scene/test_membership_regeneration.py -q
.venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts
```

## Commit
Mỗi bước một commit kèm số đo. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Đổi thuật toán vỏ, đổi `ShellParams`, preview trên GPU.
