TASK: CFG-11-AUDIT-BACKEND-API

STATUS: PASS — Ready for Frontend Layer.

## Audit checkpoint (2026-10-13)

- Required six suites: 190 passed, no skips (`tasks/reports/CFG11-REQUIRED-SUITES.log`). HTTP matrix covers all 36 combinations, including the 12 input/environment/scope combinations under each capacity target.
- Initial complete orchestration/API run: 1268 passed, one failure. The role matrix had not classified the new stateless suggestion endpoint or three earlier upload/camera endpoints.
- Necessary additional file: `tests/test_api/test_role_matrix.py`. Classified `/processing/suggest` as public stateless calculation, temporary upload actions and camera edits as authenticated; actual router guards remain unchanged. All six role-matrix tests pass (`tasks/reports/CFG11-ROLE-MATRIX.log`).
- Necessary additional file: `tests/test_orchestration/test_processing_presets_schema.py`. Added real two-group legacy profile dispatch coverage and independent empty group defaults. Thirteen dispatch/schema cases pass (`tasks/reports/CFG11-DISPATCH-VERIFICATION.log`).
- Static checks: clean; 142 API/orchestration source files formatted (`tasks/reports/CFG11-STATIC-CHECKS.log`).
- Full suite rerun: 1269 passed, no skips, 15 HTTPX deprecation warnings in 102.11 seconds. The new legacy-file test was added after collection and passed separately in the 13-case dispatch suite. Report: `tasks/reports/AUDIT_02_BACKEND_API_REPORT.md`. All required audit items have executable evidence.


## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Sau khi hoàn thành loạt 3 task về Presets, Pydantic Schema và REST API (CFG-08, CFG-09, CFG-10), hệ thống backend đã bổ sung nhiều endpoint và thay đổi cách resolve cấu hình của Job.
  1. Nếu endpoint `POST /api/studio/processing/suggest` trả về sai kiểu dữ liệu hoặc thiếu trường `evaluation`, frontend sẽ crash ngay khi người dùng bấm vào bất kỳ ô wizard nào.
  2. Nếu `resolve_job_processing` trong `dispatch.py` gặp lỗi `KeyError` khi phân rã `config.geometry` hoặc `config.scene`, worker sẽ ném ngoại lệ làm chết job ngay lập tức lúc dispatch.
  3. Nếu không audit live API và schema trước khi chuyển sang code Frontend (TypeScript/React), lập trình viên frontend sẽ phải code mò mẫm dựa trên phỏng đoán, dẫn đến lệch contract và mất rất nhiều công sức debug.
- **Yêu cầu cốt lõi (What):** Đây là **Cổng kiểm soát chất lượng trung gian (Audit Gate 2)**. Agent thực hiện task này phải đóng vai trò kiểm toán viên backend: kiểm tra thực tế hoạt động của toàn bộ endpoint REST API qua `FastAPI TestClient`, gửi toàn bộ ma trận 12 kịch bản đầu vào để xác thực kết quả trả về, kiểm tra việc resolve job trong `dispatch.py`, và chạy toàn bộ các bài test hồi quy của tầng orchestration/api.

GOAL:
Thực hiện audit và tự kiểm tra chất lượng độc lập cho toàn bộ Presets Recommender, Pydantic Schemas, Job Dispatcher và REST API Endpoints (sau khi hoàn thành CFG-08 đến CFG-10), bảo đảm API hoạt động ổn định và sẵn sàng 100% cho Frontend tích hợp.

INPUT CONTRACT:
- Kết quả triển khai từ `CFG-08-SCENARIO-PRESETS-CATALOG` đến `CFG-10-API-OPTIONS-EVALUATION`.
- Các file mã nguồn:
  - `src/services/orchestration/processing/recommender.py`
  - `src/services/orchestration/processing/models.py`
  - `src/services/orchestration/processing/config.py`
  - `src/services/orchestration/jobs/dispatch.py`
  - `src/api/studio/processing.py`
  - `src/api/studio/scenes.py`
  - `configs/product/processing_presets_v1.json`

OUTPUT CONTRACT:
- Báo cáo kiểm toán Milestone 2 (`tasks/reports/AUDIT_02_BACKEND_API_REPORT.md`):
  - Kết quả kiểm thử ma trận 12 kịch bản đầu vào của `POST /api/studio/processing/suggest`.
  - Kết quả kiểm tra payload `GET /api/studio/processing/options` (đủ 6 groups, đủ presets kịch bản).
  - Kết quả kiểm tra hàm `resolve_job_processing()` với job mới và job legacy.
  - Kết quả chạy thực tế của toàn bộ các test suite hồi quy (Regression Test Pass Count).
  - Kết luận rõ ràng: `PASS - Ready for Frontend Layer` hoặc `FAIL - Blocked with remedial actions`.

OWNED FILES:
- `tasks/reports/AUDIT_02_BACKEND_API_REPORT.md`

FILES YOU MAY MODIFY:
- Các file thuộc phạm vi CFG-08 đến CFG-10 nếu phát hiện lỗi hoặc bất cập cần sửa chữa.
- `tasks/reports/`

FILES YOU MUST NOT MODIFY:
- `frontend/`

PRIMARY TOOL:
- Python 3.12, FastAPI TestClient, Pytest, Ruff.

AUDIT CHECKLIST & VERIFICATION:
1. **Kiểm tra ma trận kịch bản (Scenario Matrix Testing):**
   - Viết kịch bản kiểm thử duyệt qua 12 tổ hợp (`input_type` x `environment` x `subject_scope` x `target_capacity`):
     - Gửi request đến `POST /api/studio/processing/suggest`.
     - Xác thực response HTTP 200 OK.
     - Xác thực payload trả về có đầy đủ `{ preset_name, params, evaluation }`.
     - Xác thực `evaluation.resources` và `evaluation.parameters` không rỗng và có cấu trúc hợp lệ.
2. **Kiểm tra Endpoint Options:**
   - Gửi `GET /api/studio/processing/options`.
   - Xác thực danh sách `parameters` bao phủ đầy đủ 6 nhóm: `sampling`, `colmap`, `brush`, `geometry`, `scene`, `simulation`.
   - Xác thực dictionary `presets` chứa đầy đủ các tên preset kịch bản.
3. **Kiểm tra Dispatch & Compatibility:**
   - Xác thực `resolve_job_processing` phân rã đúng các trường mới thành `ResolvedProcessing`.
   - Xác thực không làm hỏng cơ chế nạp legacy config profile (với các job cũ chỉ có `colmap` và `brush`).
4. **Chạy toàn bộ Regression Test Suites Backend:**
   - `.venv/bin/pytest tests/test_orchestration/test_processing_config.py -v`
   - `.venv/bin/pytest tests/test_api/test_scene_routes.py -v`
   - `.venv/bin/pytest tests/test_api/test_scene_v2_routes.py -v`
   - `.venv/bin/pytest tests/test_api/test_processing_options_api.py -v`
   - `.venv/bin/pytest tests/test_orchestration/test_preset_recommender.py -v`
   - `.venv/bin/pytest tests/test_orchestration/test_processing_presets_schema.py -v`
5. **Kiểm tra Static Code Quality:**
   - `ruff check src/api/ src/services/orchestration/`
   - `ruff format --check src/api/ src/services/orchestration/`

DONE WHEN:
- Toàn bộ checklist kiểm tra trên đạt 100%.
- Không có bất kỳ lỗi 422, 500 hay hồi quy nào trên backend API.
- File báo cáo `tasks/reports/AUDIT_02_BACKEND_API_REPORT.md` được ghi nhận với kết luận `PASS`.

EVIDENCE:
- File `tasks/reports/AUDIT_02_BACKEND_API_REPORT.md`
- Terminal log thực thi của tất cả các lệnh test API.
