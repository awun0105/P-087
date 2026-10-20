# T-069: Full regression, đo trước/sau, bàn giao

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Toàn bộ test xanh; có bảng số đo trước/sau cho mọi mục trong "Mốc đo hiện tại"; tài liệu bàn giao cho chủ dự án kiểm bằng mắt.

## Steps
1. `git status` sạch phần của Sprint 8 (thay đổi của phiên khác không động tới). Chạy:
   ```
   .venv/bin/python -m pytest -q
   cd frontend && ./node_modules/.bin/vitest run && npm run typecheck && npm run lint
   .venv/bin/ruff check . && .venv/bin/ruff format --check .
   ```
   Ghi số pass/fail/skip thật. Test đỏ: tìm commit gây lỗi (`git log` theo file); nếu là của phiên khác, báo trong report,
   không sửa test của họ.
2. Chạy lại các phép đo của T-051, T-052, T-053, T-054, T-059, T-060, T-066, T-067, T-068 trên cùng dữ liệu; bảng gộp
   trước/sau trong `docs/plans/active/2026-10-20-pipeline-stability/HANDOFF.md`.
3. Chạy migration trên bản sao DB local (`data/studio_local/runtime.db` → scratchpad) từ schema hiện tại tới mới nhất; mở
   `/scenes`, `/jobs/{id}/pipeline` cho bốn job thật (`job-a14981f78f85`, `job-f9f14e7fbfb1`, `job-7c9820b4834f`,
   `job-bfc7d73f0dbf`) in-process, kiểm không lỗi và dòng tiến trình hợp lý. Không ghi vào DB thật.
4. HANDOFF.md gồm: thay đổi theo đợt; số đo; việc chủ dự án cần kiểm bằng mắt (mở scene đang chạy, chờ mét, Draft, Ready,
   từng trang bước, bật Walk, đổi tab); lưu ý deploy (migration → API và worker cùng lúc; R2 metadata chỉ áp cho file mới;
   khuyến nghị nhiều tiến trình uvicorn; lệnh backfill bản nhẹ); backlog còn lại.
5. Cập nhật `docs/PIPELINE_HIEN_TAI_VA_LUONG_USER.md` mục 7 (cách đọc trạng thái): bước người dùng, `next_action`, mốc bước.
6. `graphify update .`, `report.md`, `status.md` → `implemented`; `roadmap.md` ghi kết quả Sprint 8.

## Acceptance criteria
1. Full suite xanh hoặc mọi test đỏ có giải thích và chủ sở hữu.
2. Bảng số đo đủ mọi mục.
3. HANDOFF đủ để người khác deploy và kiểm.

## Commit
`docs: hand off sprint 8 stability, progress model and viewer performance`. Đúng path.
