# T-057: Pha có kiểu và mốc bước cho hàng đợi tách vật

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Pha của hàng đợi tách vật (Tạo mesh, sửa vùng, chạy lại tách vật) là danh sách cố định, không còn chuỗi tự do; không hiện pha
cũ sau khi lỗi; mỗi pha và mỗi lượt có mốc bắt đầu / kết thúc giữ lại cả lịch sử (bảng hàng đợi chỉ giữ yêu cầu mới nhất).

## Context (đã kiểm trong code)
- `_Record.phase: str | None` (`scene/objectify_queue.py:209`), `ObjectifyState.phase` (dòng 128). Giá trị đang ghi:
  `"queued"` (`request()` dòng 388), `"done"` (dòng 916), từ `build_object_geometry`: `shell`, `objectgs`, `quality`,
  `collider`, `environment`, `publish` (`object_geometry_build.py:785-941`), từ `objectify.py`: `observations` (614),
  `collider_and_background` (793). Tìm hết bằng `grep -rn "progress(\"\|phase(\"\|report_progress(\"" src`.
- Lỗi / xếp lại / hủy (`_requeue_wait` 663-704, `_finish` 708-721, nhánh except 925-945) **không** xoá `phase` → giao diện
  hiện pha cũ.
- `r2s_scene_requests` khoá chính `job_id`: chỉ giữ yêu cầu mới nhất; lịch sử Tạo mesh mất khi có yêu cầu sửa vùng sau đó.
- Bảng `r2s_step_marks` và `record_marks` có từ T-056.

## Thiết kế
1. `ObjectifyPhase = Literal["queued", "observations", "collider_and_background", "shell", "objectgs", "quality",
   "collider", "environment", "publish", "done"]` (bổ sung mọi giá trị grep thấy). `_Record.phase` và
   `ObjectifyState.phase` đổi sang `ObjectifyPhase | None`, có `field_validator("phase", mode="before")`: giá trị không
   thuộc danh sách → `None`. Hàm `progress(phase)` trong `process_next` nhận `ObjectifyPhase`.
2. Xoá pha cũ: `_requeue_wait` đặt `phase="queued"`; khi kết thúc `failed`/`cancelled` (`_finish`, `recover_interrupted`)
   đặt `phase=None`; `done` giữ `"done"`.
3. Mốc: `run_kind="scene_operation"`, `run_id=f"{mode}:{operation_id}"`.
   - Lúc claim thành công: `start("queue", record.requested_at)`, `finish("queue", now, "succeeded")`,
     `start("operation", now)`.
   - Mỗi `progress(phase)`: `finish(<pha trước>, now, "succeeded")` nếu có, `start(phase, now)`.
   - `_finish`: `finish("operation", now, outcome)` với `done→succeeded`, `failed→failed`, `cancelled→cancelled`, rồi
     `close(now, outcome)`.
   - Yêu cầu bị hủy khi còn trong hàng: `finish("queue", now, "cancelled")`.
   Ghi qua `record_marks` (ngoài transaction của hàng đợi, lỗi chỉ log).
4. Frontend: kiểu `phase` trong `lib/contracts/studio.ts` thành union tương ứng; `geometryPhaseLabel`
   (`lib/scene/geometry-state.ts`) có nhãn tiếng Việt cho **mọi** giá trị; test nhãn.

## Steps
1. `tests/test_orchestration/test_scene_objectify_queue.py`: `test_legacy_phase_values_read` (dán JSON `_Record` thật với
   từng giá trị cũ, và `"something_else"` → `None`), `test_failed_operation_clears_phase`, `test_requeue_sets_phase_queued`.
   Cài thiết kế 1, 2. Commit `refactor(objectify): type queue phases and clear them when a run ends`.
2. `test_geometry_operation_records_phase_marks` (chạy `process_next` với build giả gọi `progress` qua 3 pha → mốc `queue`,
   `operation`, 3 pha, đủ hai đầu), `test_failed_operation_closes_open_marks`, `test_history_survives_later_request` (yêu
   cầu geometry rồi yêu cầu region → mốc của geometry còn). Cài thiết kế 3. Commit
   `feat(objectify): record phase marks for every scene operation`.
3. Frontend thiết kế 4 + test nhãn (`frontend/tests/geometry-review-row.test.tsx` hoặc test mới
   `geometry-phase-label.test.ts`). Commit.

## Acceptance criteria
1. Mọi bản ghi cũ đọc được; pha lạ thành `None`.
2. Sau lỗi / hủy không còn hiện pha cũ.
3. Mỗi lượt Tạo mesh / sửa vùng có mốc từng pha, giữ cả khi có yêu cầu sau.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_step_marks.py tests/test_scene/test_object_region.py -q
cd frontend && ./node_modules/.bin/vitest run <test nhãn pha> && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
