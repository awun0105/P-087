TASK: CFG-05-SCENE-OBJECTIFY-CONFIG

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Trong `src/services/orchestration/scene/objectify.py`, số lượng vật thể tối đa bị gán chết `_MAX_OBJECTS = 60`. Khi quay video chỉ nhằm quét 1 vật thể duy nhất (như 1 chiếc ghế, 1 thùng hàng robot gắp), hệ thống vẫn cố gắng tìm và bóc tách tới 60 vật gây lãng phí lớn tài nguyên GPU và thời gian. Hơn thế nữa, khi gọi sang các runner độc lập:
  - `convex_runner.py` (CoACD) nhận một request json nhưng `objectify.py` không hề gửi kèm dict `"config"`, khiến các tham số CoACD quan trọng như `threshold` (độ lõm, chi tiết chân ghế), `max_convex_hull` (số khối lồi PhysX) luôn rơi về giá trị mặc định.
  - `inpaint_runner.py` (LaMa) cũng không được gửi dict `"config"`, khiến `max_new_gaussians` và khoảng cách lùi `behind_object_m` bị hardcoded ngầm.
- **Yêu cầu cốt lõi (What):** Cho phép `objectify.py` nhận tham số cấu hình linh hoạt (từ `job.config` hoặc dictionary), truyền `max_objects` vào hàm sinh seed, và nạp dict `"config"` chuẩn xác vào payload của `convex_request`, `inpaint_request` và `lift_request`.

GOAL:
Gỡ bỏ hardcode cho các tham số Tách vật thể (SAM2), Phân rã khối lồi CoACD và Vá nền LaMa trong `src/services/orchestration/scene/objectify.py`, truyền cấu hình động xuống các runner độc lập (`convex_runner.py`, `inpaint_runner.py`, `lift_runner.py`).

INPUT CONTRACT:
- `src/services/orchestration/scene/objectify.py`.
- `src/services/simulation/colliders/convex_runner.py`.
- `src/services/reconstruction/rgb/inpaint/inpaint_runner.py`.
- `src/services/scene/association/lift_runner.py`.
- Danh mục tham số trong `docs/execution/CONFIG_CATALOG.md` (Chặng 7).

OUTPUT CONTRACT:
- `objectify.py` nhận tham số cấu hình linh hoạt (từ job config hoặc dictionary):
  - Nhóm `scene`: `max_objects` (thay vì cố định `_MAX_OBJECTS = 60`), `min_score`, `max_area`, `box_margin_m`, `sam_batch`.
  - Nhóm `coacd`: `threshold` (mặc định 0.08), `max_convex_hull` (mặc định 8), `preprocess_resolution` (mặc định 30), `voxel_m` (mặc định 0.04).
  - Nhóm `inpaint`: `max_new_gaussians` (mặc định 400.000), `behind_object_m` (mặc định 0.05m).
- `convex_request` truyền kèm trường `"config"` chứa các thông số CoACD vào `convex_runner.py`.
- `inpaint_request` truyền kèm trường `"config"` chứa các thông số vá nền vào `inpaint_runner.py`.
- `lift_request` truyền kèm trường `"config"` chứa các thông số SAM2/nhấc vật vào `lift_runner.py`.
- Bảo toàn tương thích ngược: nếu không truyền override, các runner tự động dùng giá trị mặc định của hệ thống.

OWNED FILES:
- `src/services/orchestration/scene/objectify.py`
- `tests/test_scene/test_objectify_config_override.py`

FILES YOU MAY MODIFY:
- `src/services/orchestration/scene/objectify.py`
- `src/services/simulation/colliders/convex_runner.py`
- `tests/test_scene/`

FILES YOU MUST NOT MODIFY:
- `src/models/contracts/manifests.py`
- `frontend/`

PRIMARY TOOL:
- Python 3.12, Pytest.

IMPLEMENT:
1. Sửa hàm `_seeds()` trong `objectify.py`:
   - Nhận tham số `max_objects: int = 60`.
2. Sửa hàm `objectify()` trong `objectify.py`:
   - Trích xuất cấu hình từ `job.config` (nếu có trường `scene`, `coacd`, `inpaint`) hoặc nhận qua tham số `scene_config: dict | None = None`.
   - Nạp cấu hình vào `convex_request["config"] = {...}` trước khi gọi `CONVEX_RUNNER`.
   - Nạp cấu hình vào `inpaint_request["config"] = {...}` trước khi gọi `INPAINT_RUNNER`.
   - Nạp cấu hình vào `lift_request["config"] = {...}` trước khi gọi `LIFT_RUNNER`.
3. Viết unit test trong `tests/test_scene/test_objectify_config_override.py`:
   - Kiểm tra `convex_request` và `inpaint_request` được điền đúng dict `config` khi có override.
   - Kiểm tra hành vi fallback an toàn khi không có override.

TEST:
- `.venv/bin/pytest tests/test_scene/test_objectify_config_override.py -v`
- `.venv/bin/pytest tests/test_orchestration/test_scene_objectify_queue.py -v`
- `.venv/bin/pytest tests/test_scene/test_scene_rush_pipeline.py -v`
- `ruff check src/services/orchestration/scene/`
- `ruff format --check src/services/orchestration/scene/`

DONE WHEN:
- Các tham số CoACD, LaMa và SAM2 được truyền qua request dictionary chuẩn thay vì phụ thuộc hoàn toàn vào giá trị gán cứng.
- Unit tests pass 100%.

EVIDENCE:
- File `src/services/orchestration/scene/objectify.py`
- Test log `.venv/bin/pytest tests/test_scene/test_objectify_config_override.py`
