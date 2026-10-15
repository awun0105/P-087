# T-019: Full regression + handoff

## Goal
Task **duy nhất** được chạy full suite. Xác nhận toàn bộ, build lại editor nếu cần, viết handoff và hướng dẫn chạy scene mới.

## Steps
0. Từ review T-018: thêm test `build_simulation_package` cho scene vỏ (Draft → build → Confirm → package → inventory có collider vỏ,
   không lỗi). Ghi vào handoff: collider vỏ xuất hiện ở cả `geometry` và `colliders` trong USD inventory (thừa, chưa sửa).
   Từ review T-008: chất lượng mask ObjectGS dựng lại từ nhãn hiện tại chỉ kiểm được trên GPU với scene thật.
1. Backend: `.venv/bin/python -m pytest tests -q` (chỉ thư mục `tests`, không quét `data/`). Ghi số pass/skip/fail.
2. `.venv/bin/ruff check src tests scripts` và `.venv/bin/ruff format --check src tests scripts`.
3. `.venv/bin/python scripts/check_contract_mirror.py`.
4. Frontend: `./node_modules/.bin/vitest run`, `npm run typecheck`, `npm run lint`.
5. Nếu có test fail: sửa trong phạm vi task gây lỗi (commit riêng, ghi rõ), hoặc báo lại cho Architect nếu là lỗi thiết kế.
   Test flaky đã biết: `object-review.test.tsx` "hủy selection … conflict 409" — chạy lại file riêng để xác nhận.
6. Viết `docs/plans/active/2026-10-16-geometry-review/HANDOFF.md`:
   - Đã làm gì (theo T-001..T-018), tái sử dụng gì.
   - Kết quả kiểm thử (con số thật).
   - Giới hạn chưa nghiệm thu: GPU (ObjectGS), browser (thao tác box thật), Isaac Sim; tham số vỏ (opacity 0.1, voxel 0.02/0.05)
     cần chỉnh trên scene thật.
   - Hướng dẫn chạy scene mới: tạo job với preset mặc định (`shell`, `required`, `multiview_v1`) → chờ tách vật → duyệt, chỉnh vùng →
     Tạo mesh → Confirm/Move → Walk → xuất USD → mở Isaac; cách thử huỷ và lỗi vỏ.
   - Gợi ý quay: đi vòng quanh vật chính ở 2 độ cao.
7. Cập nhật handoff cũ `docs/plans/active/2026-10-15-membership-correction/HANDOFF.md`: thêm mục "Superseded by geometry review".
8. Commit handoff. `graphify update .`. `status.md`.

## Acceptance criteria
1. Mọi lệnh ở bước 1–4 PASS (hoặc fail đã giải thích + có task theo dõi).
2. Handoff đủ các mục ở bước 6.

## Out of scope
Không chạy train scene mới, không push/merge/PR.
