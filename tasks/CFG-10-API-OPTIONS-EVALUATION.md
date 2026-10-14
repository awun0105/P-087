TASK: CFG-10-API-OPTIONS-EVALUATION

STATUS: DONE — complete catalog and scenario suggestion API verified through HTTP and durable job artifacts.

## Implementation and verification (2026-10-13)

- `GET /api/v1/processing/options` now returns all 8 catalog presets plus `machine_maximum`, with parameters from all 6 groups.
- `POST /api/v1/processing/suggest` accepts the shared strict `ScenarioPreferences` model and returns typed `{preset_name, params, evaluation}`. It uses one capability snapshot, the existing recommender, the observed-resource budget and the same evaluation function as the existing evaluation endpoint. Inadequate worker capacity returns HTTP 409; invalid input returns 422; unknown capacity remains explicitly unknown.
- Route correction from current source: Studio's backend is mounted under `/api/v1`, with scene creation at `/scenes/from-upload`. The task's `/api/studio` and `POST /scenes` spellings were descriptive, not existing backend routes. No redundant aliases were introduced.
- Inspected `scenes.py` and `assemblies.py`: both already pass the complete `request.processing` dictionary to `build_job_config`, then seal/persist it. No production edit was necessary in these two files. HTTP tests now verify all new groups in both upload and assembly job artifacts, including assembly idempotency/replay and runtime revalidation.
- Additional test path: `tests/test_api/test_studio_routes.py`, required to extend the existing real assembly fixture rather than duplicate its setup.
- `.venv/bin/pytest tests/test_api/test_processing_options_api.py tests/test_api/test_scene_routes.py tests/test_api/test_studio_routes.py -v`: **131 passed**, no skips. Includes all 36 scenario combinations, unknown/inadequate workers, malformed choices, options catalog, upload persistence and assembly persistence. Log: `tasks/reports/CFG10-API-VERIFICATION.log`.
- `ruff check src/api/studio/ tests/test_api/test_processing_options_api.py tests/test_api/test_studio_routes.py`: clean. Corresponding `ruff format --check`: **18 files already formatted**. Log: `tasks/reports/CFG10-STATIC-CHECKS.log`.
- `git diff --check`: clean. `graphify update .`: AST graph refreshed.
- Scope: HTTP calls run through the application ASGI transport with temporary durable databases/artifacts. No production worker, GPU scene run or browser acceptance is claimed. CFG-11 remains the backend audit gate before frontend work.

### Pre-flight (GUIDE.md Rule 13)

- codegraph: read processing route/models, resource evaluation, create_scene_from_upload and run_input_assembly; checked ProcessingOptions/get_processing_options callers.
- impact: options consumers in Studio and landing, new suggestion endpoint, existing job creation contracts. Existing upload/assembly implementations reused.
- understand: UNVERIFIED — understand-anything unavailable; traced current route mounting, persistence and resource-budget paths directly.
- minimal-code: reused recommender, strict scenario schema, evaluation and existing HTTP/assembly fixtures. Added only the response model and route needed for suggestions.
- checks: Python results above; TypeScript/eslint/vitest n/a for this API task.
- DevTools: n/a — no rendered UI change; browser acceptance is CFG-14.


## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Hiện tại, endpoint `GET /api/studio/processing/options` chỉ trả về 2 preset tĩnh (`minimum_quality`, `maximum`) và chưa có endpoint nào phục vụ tính năng gợi ý thông minh từ xa cho frontend. Khi người dùng tick các ô lựa chọn cấp cao (indoor/outdoor, 360/walkthrough, object/room, min/max), giao diện Web Studio cần gọi một API endpoint chuyên trách `POST /api/studio/processing/suggest` để backend tính toán preset tối ưu nhất và trả về kèm bảng đánh giá rủi ro tài nguyên (RAM/VRAM/Disk) cho bộ máy hiện tại.
- **Yêu cầu cốt lõi (What):**
  1. Cập nhật `GET /api/studio/processing/options` để trả về danh mục đầy đủ các Presets kịch bản mới.
  2. Tạo endpoint mới `POST /api/studio/processing/suggest` nhận `ScenarioPreferences` và trả về `{ preset_name, params, evaluation }`.
  3. Cập nhật `POST /api/studio/scenes` trong `src/api/studio/scenes.py` để chấp nhận các bộ thông số mới khi người dùng bấm tạo scene.

GOAL:
Cập nhật và mở rộng API REST (`/api/studio/processing/options`, `/api/studio/processing/suggest`, `scenes.py`, `assemblies.py`) để cung cấp đầy đủ presets kịch bản và cung cấp endpoint gợi ý tự động cho Web Studio.

INPUT CONTRACT:
- `src/api/studio/processing.py`.
- `src/api/studio/scenes.py`.
- `src/services/orchestration/processing/recommender.py` (từ CFG-08).
- `src/services/orchestration/processing/models.py` (từ CFG-09).

OUTPUT CONTRACT:
- Endpoint `GET /api/studio/processing/options`:
  - Trả về danh sách parameters gồm cả các nhóm `geometry`, `scene`, `simulation`.
  - Trả về map `presets` chứa đầy đủ các presets kịch bản mới kèm `machine_maximum`.
- Endpoint mới `POST /api/studio/processing/suggest`:
  - Body: `ScenarioPreferences` (`input_type`, `environment`, `subject_scope`, `target_capacity`).
  - Response: `{ preset_name: str, params: dict[str, ParamValue], evaluation: Evaluation }`.
- Endpoint `POST /api/studio/scenes`:
  - Nhận và lưu trữ cấu hình xử lý chứa các trường mới của job.

OWNED FILES:
- `src/api/studio/processing.py`
- `src/api/studio/scenes.py`
- `src/api/studio/assemblies.py`
- `tests/test_api/test_processing_options_api.py`

FILES YOU MAY MODIFY:
- `src/api/studio/`
- `src/services/orchestration/processing/resources.py`
- `tests/test_api/`

FILES YOU MUST NOT MODIFY:
- `frontend/`

PRIMARY TOOL:
- Python 3.12, FastAPI TestClient / Httpx, Pytest.

IMPLEMENT:
1. Cập nhật `get_processing_options()` trong `src/api/studio/processing.py`:
   - Nạp toàn bộ presets kịch bản từ `presets.presets`.
   - Đưa vào payload trả về cho client.
2. Thêm endpoint `POST /api/studio/processing/suggest`:
   - Nhận payload `ScenarioPreferences`.
   - Gọi `recommend_preset` từ module `recommender.py`.
   - Gọi `evaluate` để chấm điểm tài nguyên tương ứng và trả về cho client.
3. Cập nhật `scenes.py` và `assemblies.py`:
   - Đảm bảo khi tạo job mới với `request.processing`, các trường mới được ghi nhận đầy đủ.
4. Viết unit/integration test trong `tests/test_api/test_processing_options_api.py`:
   - Test gọi `GET /api/studio/processing/options` và xác thực cấu trúc JSON trả về.
   - Test gọi `POST /api/studio/processing/suggest` với các lựa chọn tickbox khác nhau.

TEST:
- `.venv/bin/pytest tests/test_api/test_processing_options_api.py -v`
- `.venv/bin/pytest tests/test_api/test_scene_routes.py -v`
- `ruff check src/api/studio/`
- `ruff format --check src/api/studio/`

DONE WHEN:
- Toàn bộ danh mục Presets và endpoint gợi ý tự động `/processing/suggest` hoạt động ổn định.
- API tests pass 100%.

EVIDENCE:
- File `src/api/studio/processing.py`
- Test log `.venv/bin/pytest tests/test_api/test_processing_options_api.py`
