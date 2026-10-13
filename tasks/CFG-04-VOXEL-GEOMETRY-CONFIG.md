TASK: CFG-04-VOXEL-GEOMETRY-CONFIG

STATUS: COMPLETED — dynamic mesh/fill configuration and padded-grid safety verified.

## Executable checkpoint (2026-10-13)

- Added dynamic `collision_mesh` and positive finite `floor_fill_size_m`. Both occupancy and collision commands receive configured fill flags.
- Default values are omitted from serialization. Tests pin checksums captured from the pre-change implementation for schemas 1.0, 1.1 and 1.2; non-default overrides change the checksum.
- `GeometryExecutionRequest.config` already accepts a caller-supplied `VoxelConfig`. The existing service passes it into `ProductVoxelRequest`; a fixture pipeline test verifies the override reaches the adapter and qualification receipt. No additional request override abstraction is needed.
- Verification: 75 tests passed across the new override tests, original voxel tests, product pipeline, adapter, clearance and audit regressions. The original voxel suite has 15 passing cases. Ruff check and format check passed for geometry and the new test; `git diff --check` passed.
- Additional required file: `src/services/reconstruction/adapters/voxel.py`, recorded under the user clarification that may-modify paths are examples. It qualifies floor-fill CLI support and applies padded-grid capacity checks to both fill modes. The larger radius bounds all axes conservatively; native floor fill pads only lateral axes. Regression tests reject an oversized floor-only grid. Log: `tasks/reports/CFG-04-VERIFICATION.log`.
- Runtime evidence covers installed CLI source and fixture execution. No new GPU scene run or production geometry acceptance is claimed.

Pre-flight (GUIDE.md Rule 13)
- codegraph: VoxelConfig, collision_command, occupancy_command, _fill_arguments, GeometryExecutionRequest and voxel runtime read.
- impact: voxel adapter, clearance/output/seed-search consumers, geometry service and finalize config builder; callers inspected.
- understand: UNVERIFIED — understand-anything tool unavailable; metric confirmation → request config → adapter → checksum-bound publication traced directly.
- minimal-code: rung 2 — reuse existing typed request and command helpers.
- checks: ruff clean; 75 pytest passed; TypeScript checks not applicable.
- DevTools: n/a — no UI change.

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Trong `src/services/reconstruction/rgb/geometry/voxel.py` dòng 164, cờ tạo mesh va chạm đang bị gán cứng tuyệt đối: `"--collision-mesh", "smooth"`.
  - Tùy chọn `"smooth"` dùng thuật toán Marching Cubes tạo lưới tam giác lượn sóng bo tròn, rất thích hợp cho robot hay nhân vật di chuyển không bị vấp cạnh.
  - Tuy nhiên, khi người dùng cần kiểm tra chiếm chỗ không gian (occupancy grid) dạng khối voxel rời rạc hoặc cần xuất mô hình hình học góc cạnh chính xác theo từng voxel (minecraft-like style / exact physics bounding), họ bắt buộc phải dùng cờ `"--collision-mesh", "faces"`.
  - Ngoài ra, cờ `--voxel-external-fill` (lấp đầy ngoài biên) chỉ phù hợp với cảnh trong nhà (indoor). Với cảnh ngoài trời (outdoor), việc bật external-fill sẽ làm hỏng thể tích biên; cảnh ngoài trời cần cờ `--voxel-floor-fill` (độn đặc từ đáy lên mặt đất).
- **Yêu cầu cốt lõi (What):** Bổ sung trường `collision_mesh: Literal["smooth", "faces"] = "smooth"` và `floor_fill_size_m: FiniteFloat | None = None` vào `VoxelConfig`. Sửa `collision_command` để truyền cờ động `--collision-mesh <smooth|faces>` và sửa `_fill_arguments` để hỗ trợ cả external fill và floor fill, đồng thời giữ nguyên tương thích ngược với serialization schema của `VoxelConfig`.

GOAL:
Gỡ bỏ hardcode cho cờ `--collision-mesh smooth` và kết nối cấu hình Lưới va chạm Voxel (`collision_mesh`, `external_fill_size_m`, `floor_fill_size_m`, `resolution_m`) trong `src/services/reconstruction/rgb/geometry/voxel.py` và `geometry_publication.py` để hỗ trợ cả bề mặt mượt (`smooth`) và bề mặt khối voxel (`faces`).

INPUT CONTRACT:
- `VoxelConfig` và `collision_command` trong `src/services/reconstruction/rgb/geometry/voxel.py`.
- `configs/product/geometry_indoor_v1.json`.
- Danh mục tham số trong `docs/execution/CONFIG_CATALOG.md` (Chặng 6).

OUTPUT CONTRACT:
- Mở rộng `VoxelConfig`:
  - `collision_mesh: Literal["smooth", "faces"] = "smooth"` (thay thế hardcode "smooth" hiện tại).
  - `floor_fill_size_m: FiniteFloat | None = Field(default=None, gt=0)` (hỗ trợ cờ `--voxel-floor-fill` cho địa hình ngoài trời).
  - Bảo toàn `_versioned_payload` để không làm thay đổi checksum receipt của schema cũ (1.0/1.1/1.2).
- Hàm `collision_command(config: VoxelConfig) -> tuple[str, ...]`:
  - Xuất `("--collision-mesh", config.collision_mesh)` thay vì hardcode `"smooth"`.
- Hàm `_fill_arguments(config: VoxelConfig) -> tuple[str, ...]`:
  - Bổ sung `("--voxel-floor-fill", str(config.floor_fill_size_m))` khi `config.floor_fill_size_m` được thiết lập.
- `geometry_publication.py`:
  - Hỗ trợ nạp cấu hình tùy biến từ request nếu có.

OWNED FILES:
- `src/services/reconstruction/rgb/geometry/voxel.py`
- `src/services/reconstruction/rgb/geometry/geometry_publication.py`
- `tests/test_reconstruction/test_geometry_config_override.py`

FILES YOU MAY MODIFY:
- `src/services/reconstruction/rgb/geometry/`
- `configs/product/geometry_indoor_v1.json`
- `tests/test_reconstruction/`

FILES YOU MUST NOT MODIFY:
- `src/models/contracts/manifests.py`
- `frontend/`

PRIMARY TOOL:
- Python 3.12, Pydantic v2, Pytest.

IMPLEMENT:
1. Sửa `VoxelConfig` trong `voxel.py`:
   - Thêm trường `collision_mesh: Literal["smooth", "faces"] = "smooth"`.
   - Thêm trường `floor_fill_size_m: FiniteFloat | None = Field(default=None, gt=0)`.
   - Cập nhật serialization và validation tương ứng, đảm bảo tương thích ngược.
2. Sửa `collision_command`:
   - Truyền `config.collision_mesh` vào sau cờ `--collision-mesh`.
3. Sửa `_fill_arguments`:
   - Nếu `config.floor_fill_size_m` tồn tại, thêm `--voxel-floor-fill`.
4. Cập nhật `geometry_publication.py`:
   - Cho phép nạp cấu hình `VoxelConfig` được ghi đè từ request nếu có.
5. Viết unit test trong `tests/test_reconstruction/test_geometry_config_override.py`:
   - Kiểm tra `collision_command` sinh đúng cờ khi `collision_mesh="faces"` và `collision_mesh="smooth"`.
   - Kiểm tra `_fill_arguments` sinh đúng `--voxel-external-fill` và `--voxel-floor-fill`.
   - Đảm bảo toàn bộ 15 test cases cũ trong `test_rec05_voxel.py` tiếp tục pass 100%.

TEST:
- `.venv/bin/pytest tests/test_reconstruction/test_geometry_config_override.py -v`
- `.venv/bin/pytest tests/test_reconstruction/test_rec05_voxel.py -v` (15 bài test gốc phải pass 100%)
- `ruff check src/services/reconstruction/rgb/geometry/`
- `ruff format --check src/services/reconstruction/rgb/geometry/`

DONE WHEN:
- Cờ `--collision-mesh faces` và `--collision-mesh smooth` hoạt động chính xác qua cấu hình.
- Unit tests kiểm tra `voxel.py` pass 100%, không hồi quy.

EVIDENCE:
- File `src/services/reconstruction/rgb/geometry/voxel.py`
- Test log `.venv/bin/pytest tests/test_geometry_config_override.py`
