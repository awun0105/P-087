TASK: CFG-06-SIMULATION-PHYSICS-CONFIG

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Khi xuất scene sang định dạng OpenUSD cho NVIDIA Isaac Sim, các vật thể cần có thuộc tính vật liệu vật lý (`PhysicsMaterial`) như hệ số ma sát nghỉ (`static_friction`), ma sát trượt (`dynamic_friction`), độ đàn hồi nảy (`restitution`). Hiện tại trong `hybrid_runner.py` và `usda.py`, các giá trị này đang bị fix cứng (`0.5`, `0.4`, `0.0`). Tương tự, sàn phẳng vô hạn `GroundPlane` ($200\times 200\text{ m}$) luôn bị tự động bật (dù có những scene người dùng chỉ muốn dùng sàn mesh tự nhiên đã quét), và khoảng cách nới biên khoét mesh môi trường `COLLISION_CARVE_MARGIN_M = 0.05` trong `carve.py` cũng bị gán cứng.
- **Yêu cầu cốt lõi (What):** Mở rộng `CandidateBuildRequest.build_config` để hỗ trợ các tham số `ground_plane: bool`, `static_friction`, `dynamic_friction`, `restitution`, và `carve_margin_m`, truyền các giá trị này sang `hybrid_runner.py` và `carve.py`.

GOAL:
Chuẩn hóa và kết nối cấu hình vật lý mô phỏng OpenUSD / Isaac Sim (`ground_plane`, `static_friction`, `dynamic_friction`, `restitution`, `carve_margin_m`) trong `src/services/simulation/` để người dùng và preset có thể tùy biến thuộc tính vật liệu và điều kiện sàn mô phỏng.

INPUT CONTRACT:
- `src/services/simulation/usd/builder.py`.
- `src/services/simulation/usd/hybrid_runner.py`.
- `src/services/simulation/colliders/carve.py`.
- Danh mục tham số trong `docs/execution/CONFIG_CATALOG.md` (Chặng 8).

OUTPUT CONTRACT:
- `CandidateBuildRequest` hỗ trợ nhận các tham số qua `build_config`:
  - `ground_plane: bool = True` (bật/tắt sàn phẳng phân tích Analytic Ground Plane $200\times 200\text{ m}$).
  - `static_friction: float = 0.5` (hệ số ma sát nghỉ).
  - `dynamic_friction: float = 0.4` (hệ số ma sát trượt).
  - `restitution: float = 0.0` (hệ số đàn hồi).
  - `carve_margin_m: float = 0.05` (khoảng nới biên khoét mesh môi trường tại vị trí vật thể).
- `hybrid_runner.py` đọc các thông số này từ request và thiết lập vào stage OpenUSD qua `UsdPhysics.MaterialAPI`.
- `carve.py` nhận `margin_m` từ cấu hình thay vì cố định `COLLISION_CARVE_MARGIN_M = 0.05`.

OWNED FILES:
- `src/services/simulation/usd/builder.py`
- `src/services/simulation/usd/hybrid_runner.py`
- `src/services/simulation/colliders/carve.py`
- `tests/test_simulation/test_simulation_config_override.py`

FILES YOU MAY MODIFY:
- `src/services/simulation/usd/`
- `src/services/simulation/colliders/`
- `tests/test_simulation/`

FILES YOU MUST NOT MODIFY:
- `src/models/contracts/manifests.py`
- `frontend/`

PRIMARY TOOL:
- Python 3.12, Pytest.

IMPLEMENT:
1. Cập nhật `CandidateBuildRequest` trong `src/services/simulation/usd/builder.py`:
   - Trích xuất các tham số `ground_plane`, `static_friction`, `dynamic_friction`, `restitution`, `carve_margin_m` từ `build_config`.
2. Cập nhật `hybrid_runner.py`:
   - Ghi nhận `request.get("ground_plane", True)`.
   - Nếu vật thể chưa có vật liệu vật lý riêng, áp dụng `static_friction`, `dynamic_friction`, `restitution` từ cấu hình chung của gói.
3. Cập nhật `carve.py`:
   - Đảm bảo hàm `triangle_mask_in_box` và các caller truyền đúng `margin_m` từ cấu hình.
4. Viết unit test trong `tests/test_simulation/test_simulation_config_override.py`:
   - Kiểm tra việc truyền các thông số vật lý tùy chỉnh và kiểm tra tính hợp lệ của request payload sinh ra.

TEST:
- `.venv/bin/pytest tests/test_simulation/test_simulation_config_override.py -v`
- `.venv/bin/pytest tests/test_contracts/test_collision_quality.py -v`
- `ruff check src/services/simulation/`
- `ruff format --check src/services/simulation/`

DONE WHEN:
- Các thuộc tính vật lý của gói USD có thể cấu hình linh hoạt.
- Unit tests pass 100%.

EVIDENCE:
- File `src/services/simulation/usd/builder.py`
- Test log `.venv/bin/pytest tests/test_simulation/test_simulation_config_override.py`
