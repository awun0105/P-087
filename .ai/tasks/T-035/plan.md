# T-035: Regression + hướng dẫn đo

## Goal
Chạy toàn bộ test sau Sprint 6, cập nhật hướng dẫn đo cho team.

## Steps
1. `.venv/bin/python -m pytest tests -q`; ruff check/format; `scripts/check_contract_mirror.py`; frontend vitest, typecheck, lint.
   Ghi số thật. Lỗi: sửa trong phạm vi task gây ra (commit riêng) hoặc báo Architect.
2. Viết `docs/plans/active/2026-10-16-value-metrics/HANDOFF.md`: mỗi metric lấy từ đâu, cách nhập ground truth, cách xuất bảng,
   giới hạn (L4 là khai báo; phút công người chỉ đo trong trang scene). Mục "Giới hạn đã biết" phải ghi đủ:
   - Nhánh PostgreSQL của ground truth (T-030) mới có test SQLite, chưa chạy trên PostgreSQL thật.
   - Đồng hồ máy khách lệch quá 60 s so với máy chủ thì mọi lô thời gian thao tác bị 422 và bỏ im lặng → phút công "chưa đo được".
   - Link tải CSV/Markdown dùng `<a download>`: phiên hết hạn thì file tải về là JSON lỗi; đăng nhập lại rồi tải lại.
   - "Mở Benchmark" ở thẻ Giá trị chỉ mở tab Studio; người dùng bấm nút "Benchmark" ở góc viewer.
3. Dọn nhỏ còn lại từ review T-033 (commit riêng, có test): tắt lớp phủ collider/vỏ/box trong lúc chọn điểm Benchmark để cú bấm
   trúng splat; nút "Bỏ chọn {id}" của vật cản chính đã bị xoá khỏi scene ghi "vật đã xoá ({id})" thay vì id thô.
4. Ghi lại mục "Sản phẩm cần thêm gì" của Playbook thành "đã có" (Architect cập nhật trang; engineer ghi danh sách vào handoff).

## Acceptance criteria
1. Mọi lệnh ở bước 1 PASS hoặc lỗi đã giải thích kèm task theo dõi.
2. Handoff đủ các mục ở bước 2.

## Commit
Một commit cho handoff, một commit cho bước 3. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
