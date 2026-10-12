TASK: CFG-10-API-OPTIONS-EVALUATION

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
