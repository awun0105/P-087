TASK: CFG-06-SIMULATION-PHYSICS-CONFIG

STATUS: COMPLETED — validated controls flow through package identity, carve and both USD exporters.

## Implementation and verification (2026-10-13)

- `CandidateBuildRequest` validates physical controls without discarding unrelated build metadata. Its legacy exporter receives `build_config`, authors the configured global material and honors `ground_plane=False`.
- The standalone hybrid runner validates the same controls with a stdlib-only helper. Its runtime has no Pydantic; importing app USD package modules would break the runner.
- Hybrid USD binds a global material with `weakerThanDescendants`; per-object material remains authoritative. Existing per-object mass/dynamic/provenance validation is unchanged.
- Carve helpers already accept `margin_m`. Consolidated the default constant and reject non-finite or negative margins.
- New tests validate request controls, custom triangle-selection margins, exported candidate bytes and both USD formats. Native `data/scene_runtime/bin/python` builds hybrid USD and reopens it with pxr to inspect material values, disabled ground plane and per-object material precedence.
- Initial test failures were fixture errors: an unconfigured confirmed floor object in the legacy export, and resolving the virtualenv Python symlink to system Python. Tests now use a scene without objects for global legacy controls and preserve the virtualenv executable path.
- Additional required files: `src/services/orchestration/review/simulation_package.py`, `src/services/simulation/usd/physics_config.py`, `src/services/simulation/usd/usda.py` and `tests/test_simulation/test_collision_edit_composition.py`. Recorded under the user clarification that may-modify paths are examples. The package service reads checksum-bound job simulation controls (legacy absent controls use defaults), forwards overrides to carve and hybrid USD, and binds values into cache/build identity. Builder version advances to v6 so older packages cannot satisfy the new export contract. Exact source-triangle ownership remains authoritative over approximate box carving.
- Verification: 108 passed in 31.62s, no skips. Log: `tasks/reports/CFG-06-VERIFICATION.log`. Real USD authoring is not Isaac/PhysX simulation acceptance.

Pre-flight (GUIDE.md Rule 13)
- codegraph: builder request/service, legacy exporter, hybrid material/build, carve helpers and orchestration callers inspected.
- impact: simulation package builder, collision ownership/selection and direct exporters; existing signatures retain defaults.
- understand: UNVERIFIED — understand-anything unavailable; package config → legacy/hybrid stage and carve consumers traced from current source.
- minimal-code: rung 3 — shared stdlib validation supports the independent runtime without adding dependencies.
- checks: ruff check and format check clean; focused suites recorded in verification log; TypeScript checks not applicable.
- DevTools: n/a — no UI change.

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
