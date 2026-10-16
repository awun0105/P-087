# T-035: Regression + hướng dẫn đo

## Goal
Chạy toàn bộ test sau Sprint 6, cập nhật hướng dẫn đo cho team.

## Steps
1. `.venv/bin/python -m pytest tests -q`; ruff check/format; `scripts/check_contract_mirror.py`; frontend vitest, typecheck, lint.
   Ghi số thật. Lỗi: sửa trong phạm vi task gây ra (commit riêng) hoặc báo Architect.
2. Viết `docs/plans/active/2026-10-16-value-metrics/HANDOFF.md`: mỗi metric lấy từ đâu, cách nhập ground truth, cách xuất bảng,
   giới hạn (L4 là khai báo; phút công người chỉ đo trong trang scene).
3. Ghi lại mục "Sản phẩm cần thêm gì" của Playbook thành "đã có" (Architect cập nhật trang; engineer ghi danh sách vào handoff).

## Acceptance criteria
1. Mọi lệnh ở bước 1 PASS hoặc lỗi đã giải thích kèm task theo dõi.
2. Handoff đủ các mục ở bước 2.

## Commit
Một commit cho handoff. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
