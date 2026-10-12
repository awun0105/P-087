TASK: CFG-07-AUDIT-CORE-RUNNERS

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Sau khi hoàn thành loạt 5 task can thiệp vào các core runners cấp thấp (CFG-02 đến CFG-06: Tải Vocab Tree, COLMAP matcher, Lưới Voxel, Tách vật thể CoACD, Vật lý OpenUSD), hệ thống có nguy cơ tiềm ẩn rất lớn:
  1. Một lỗi nhỏ trong câu lệnh sinh CLI (như sai tên cờ, sai dấu phẩy, thiếu khoảng trắng) có thể làm vỡ quy trình thực thi subprocess khi chạy thật.
  2. Việc thay đổi schema Pydantic (`ColmapConfig`, `VoxelConfig`) có thể âm thầm phá vỡ hàng chục bài test hồi quy (regression) vốn đang pass của hệ thống.
  3. Nếu agent vội vã chuyển sang viết Presets và API mà không dừng lại audit thực tế, lỗi sẽ tích tụ và rất khó truy vết nguồn gốc.
- **Yêu cầu cốt lõi (What):** Đây là **Cổng kiểm soát chất lượng trung gian (Audit Gate 1)**. Agent thực hiện task này phải đóng vai trò kiểm toán viên độc lập (Auditor): rà soát lại toàn bộ mã nguồn của 5 module vừa sửa, đối chiếu trực tiếp với hành vi thực tế của codebase, chạy lại 100% các bộ test hồi quy cũ và test mới, đảm bảo không có bất kỳ regression hay lỗi logic nào trước khi cho phép bước vào chặng Presets & API.

GOAL:
Thực hiện audit và tự kiểm tra chất lượng độc lập cho toàn bộ các Core Tool Runners & Adapters (sau khi hoàn thành CFG-02 đến CFG-06), xác minh tính đúng đắn của logic lệnh CLI, bảo đảm 100% các bài test hồi quy của hệ sinh thái backend tiếp tục pass và không có xung đột mã nguồn.

INPUT CONTRACT:
- Toàn bộ kết quả triển khai từ `CFG-02-VOCAB-TREE-ASSET` đến `CFG-06-SIMULATION-PHYSICS-CONFIG`.
- Các file mã nguồn:
  - `src/services/reconstruction/rgb/pose/camera_pose.py`
  - `src/services/reconstruction/adapters/colmap_runtime.py`
  - `src/services/reconstruction/adapters/vocab_tree.py`
  - `src/services/reconstruction/rgb/geometry/voxel.py`
  - `src/services/reconstruction/rgb/geometry/geometry_publication.py`
  - `src/services/orchestration/scene/objectify.py`
  - `src/services/simulation/usd/builder.py`
  - `src/services/simulation/usd/hybrid_runner.py`
  - `src/services/simulation/colliders/carve.py`

OUTPUT CONTRACT:
- Báo cáo kiểm toán Milestone 1 (`tasks/reports/AUDIT_01_CORE_RUNNERS_REPORT.md`):
  - Bảng đối chiếu câu lệnh CLI thực tế sinh ra cho từng công cụ (COLMAP, splat-transform, CoACD, LaMa, USD).
  - Kết quả chạy thực tế của toàn bộ các test suite hồi quy (Regression Test Pass Count).
  - Kết quả kiểm tra linter và type formatting.
  - Kết luận rõ ràng: `PASS - Ready for Presets & API Layer` hoặc `FAIL - Blocked with remedial actions`.

OWNED FILES:
- `tasks/reports/AUDIT_01_CORE_RUNNERS_REPORT.md`

FILES YOU MAY MODIFY:
- Các file thuộc phạm vi CFG-02 đến CFG-06 nếu phát hiện lỗi hoặc hồi quy cần sửa chữa khẩn cấp.
- `tasks/reports/`

FILES YOU MUST NOT MODIFY:
- `src/models/contracts/manifests.py`
- `frontend/`

PRIMARY TOOL:
- Python 3.12, Pytest, Ruff, CodeGraph.

AUDIT CHECKLIST & VERIFICATION:
1. **Kiểm tra câu lệnh CLI (Subprocess Command Invocations):**
   - COLMAP: Kiểm tra hàm `reconstruction_commands()` sinh đúng mảng string cho cả 3 chế độ (`sequential`, `sequential_vocab_tree`, `exhaustive`).
   - Voxel: Kiểm tra `collision_command()` sinh cờ `--collision-mesh faces` khi chọn faces và `--collision-mesh smooth` khi chọn smooth.
   - Voxel: Kiểm tra `_fill_arguments()` sinh `--voxel-floor-fill` khi có `floor_fill_size_m`.
   - CoACD & LaMa: Kiểm tra payload request json gửi sang `CONVEX_RUNNER` và `INPAINT_RUNNER` có chứa đúng cấu trúc dict `"config"`.
   - USD: Kiểm tra `UsdPhysics.MaterialAPI` nhận đúng giá trị friction và restitution từ `CandidateBuildRequest`.
2. **Chạy toàn bộ Regression Test Suites (Bắt buộc pass 100%):**
   - Test suite gốc COLMAP: `.venv/bin/pytest tests/test_reconstruction/test_rec03_colmap.py -v` (36 tests phải pass).
   - Test suite gốc Voxel: `.venv/bin/pytest tests/test_reconstruction/test_rec05_voxel.py -v` (15 tests phải pass).
   - Test suite gốc Scene: `.venv/bin/pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_scene/test_scene_rush_pipeline.py -v`.
   - Test suite gốc Simulation: `.venv/bin/pytest tests/test_contracts/test_collision_quality.py -v`.
3. **Chạy toàn bộ New Unit Test Suites (Bắt buộc pass 100%):**
   - `.venv/bin/pytest tests/test_reconstruction/test_vocab_tree_asset.py -v`
   - `.venv/bin/pytest tests/test_reconstruction/test_colmap_matching_modes.py -v`
   - `.venv/bin/pytest tests/test_reconstruction/test_geometry_config_override.py -v`
   - `.venv/bin/pytest tests/test_scene/test_objectify_config_override.py -v`
   - `.venv/bin/pytest tests/test_simulation/test_simulation_config_override.py -v`
4. **Kiểm tra Static Code Quality:**
   - `ruff check src/services/ scripts/`
   - `ruff format --check src/services/ scripts/`

DONE WHEN:
- Toàn bộ checklist kiểm tra trên đạt 100%.
- Không có bất kỳ hồi quy nào trên các test suite cũ.
- File báo cáo `tasks/reports/AUDIT_01_CORE_RUNNERS_REPORT.md` được ghi nhận với kết luận `PASS`.

EVIDENCE:
- File `tasks/reports/AUDIT_01_CORE_RUNNERS_REPORT.md`
- Terminal log thực thi của tất cả các lệnh test hồi quy.
