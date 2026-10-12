TASK: CFG-09-PRESETS-SCHEMA-BACKEND

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Trong `src/services/orchestration/processing/models.py`, các nhóm thông số đang bị chặn cứng bởi Pydantic validation:
  `group: Literal["sampling", "colmap", "brush"]`
  `key: pattern=r"^(sampling|colmap|brush)\.[a-z_]+$"`
  Và `PresetName` chỉ cho phép `"minimum_quality" | "maximum"`.
  Nếu không mở rộng schema backend, file cấu hình `processing_presets_v1.json` không thể khai báo các thông số của Lưới va chạm Voxel (`geometry`), Tách vật thể (`scene`), hay Vật lý OpenUSD (`simulation`), và hệ thống sẽ ném lỗi `ValidationError` ngay khi nạp file cấu hình có chứa các presets mới.
  Đặc biệt, trong `src/services/orchestration/jobs/dispatch.py`, `ResolvedProcessing` hiện chỉ chứa 5 trường (`colmap`, `brush`, `sample_fps`, `max_frames`, `anonymize`). Nếu không mở rộng `ResolvedProcessing` và hàm `resolve_job_processing()`, các cấu hình `geometry`, `scene`, `simulation` sẽ bị vứt bỏ trước khi worker thực thi job.
- **Yêu cầu cốt lõi (What):** Mở rộng schema backend trong `models.py`, `config.py` và `dispatch.py` để chấp nhận và chuyển giao đầy đủ các nhóm `geometry`, `scene`, `simulation`, đồng thời cập nhật file `configs/product/processing_presets_v1.json` khai báo toàn bộ các thông số mới và danh mục Presets theo kịch bản từ CFG-08.

GOAL:
Mở rộng backend Processing Presets (`models.py`, `config.py`, `dispatch.py`) và cập nhật file `configs/product/processing_presets_v1.json` để hỗ trợ đầy đủ các nhóm thông số mới (`geometry`, `scene`, `simulation`), các cờ CLI mới và danh mục Presets theo kịch bản.

INPUT CONTRACT:
- `src/services/orchestration/processing/models.py`.
- `src/services/orchestration/processing/config.py`.
- `src/services/orchestration/jobs/dispatch.py`.
- `configs/product/processing_presets_v1.json`.
- Danh mục Presets từ CFG-08 và `docs/execution/CONFIG_CATALOG.md`.

OUTPUT CONTRACT:
- `ParameterSpec.group`: mở rộng thành `Literal["sampling", "colmap", "brush", "geometry", "scene", "simulation"]`.
- `ParameterSpec.key`: regex `r"^(sampling|colmap|brush|geometry|scene|simulation)\.[a-z_]+$"`.
- `PresetName`: hỗ trợ chuỗi tên định danh preset linh hoạt (`str`).
- `JobProcessingConfig`: bổ sung các trường `geometry`, `scene`, `simulation` (dạng `dict[str, ParamValue] = Field(default_factory=dict)`).
- `build_job_config`: nhóm đúng các trường `geometry`, `scene`, `simulation` từ `params` vào `JobProcessingConfig`.
- `ResolvedProcessing` trong `dispatch.py`: bổ sung các trường `geometry: dict = field(default_factory=dict)`, `scene: dict = field(default_factory=dict)`, `simulation: dict = field(default_factory=dict)`.
- `resolve_job_processing()` trong `dispatch.py`: chuyển giao đúng các dict `geometry`, `scene`, `simulation` từ `JobProcessingConfig`.
- File `configs/product/processing_presets_v1.json` chứa đầy đủ các tham số mới và danh mục presets kịch bản, pass 100% validation của Pydantic.

OWNED FILES:
- `src/services/orchestration/processing/models.py`
- `src/services/orchestration/processing/config.py`
- `src/services/orchestration/jobs/dispatch.py`
- `configs/product/processing_presets_v1.json`
- `tests/test_orchestration/test_processing_presets_schema.py`

FILES YOU MAY MODIFY:
- `src/services/orchestration/processing/`
- `src/services/orchestration/jobs/`
- `configs/product/`
- `tests/test_orchestration/`

FILES YOU MUST NOT MODIFY:
- `frontend/`

PRIMARY TOOL:
- Python 3.12, Pydantic v2, Pytest.

IMPLEMENT:
1. Cập nhật `models.py` trong `src/services/orchestration/processing/`:
   - Mở rộng `group` và `key` regex trong `ParameterSpec`.
   - Cập nhật kiểu `PresetName = str`.
   - Thêm `geometry`, `scene`, `simulation` vào `JobProcessingConfig` với default factory dict.
2. Cập nhật `config.py` trong `src/services/orchestration/processing/`:
   - Khởi tạo nhóm trong `build_job_config`: `grouped = {"sampling": {}, "colmap": {}, "brush": {}, "geometry": {}, "scene": {}, "simulation": {}}`.
   - Ghép giá trị từ `params` vào đúng đối tượng `JobProcessingConfig`.
3. Cập nhật `dispatch.py` trong `src/services/orchestration/jobs/`:
   - Thêm `geometry`, `scene`, `simulation` vào dataclass `ResolvedProcessing`.
   - Cập nhật `resolve_job_processing()` để trích xuất `config.geometry`, `config.scene`, `config.simulation`.
   - Giữ nguyên fallback an toàn cho legacy profiles (chỉ có colmap + brush).
4. Cập nhật `configs/product/processing_presets_v1.json`:
   - Thêm các `parameters`:
     - `colmap.matching_mode` (kind: choice: sequential, sequential_vocab_tree, exhaustive).
     - `geometry.collision_mesh` (kind: choice: smooth, faces).
     - `geometry.external_fill_size_m` (kind: number, min: 0.0, max: 5.0, step: 0.1, unit: m).
     - `geometry.resolution_m` (kind: number, min: 0.02, max: 0.2, step: 0.01, unit: m).
     - `scene.max_objects` (kind: integer, min: 5, max: 100, step: 5, unit: vật).
   - Khai báo đầy đủ giá trị các thông số cho tất cả presets kịch bản.
5. Viết unit test trong `tests/test_orchestration/test_processing_presets_schema.py`:
   - Test nạp và xác thực `processing_presets_v1.json`.
   - Test sinh `JobProcessingConfig` với từng preset.
   - Test `resolve_job_processing()` sinh ra đúng `ResolvedProcessing` có đủ 6 nhóm.

TEST:
- `.venv/bin/pytest tests/test_orchestration/test_processing_presets_schema.py -v`
- `.venv/bin/pytest tests/test_orchestration/test_processing_config.py -v`
- `ruff check src/services/orchestration/`
- `ruff format --check src/services/orchestration/`

DONE WHEN:
- File `processing_presets_v1.json` nạp thành công không có lỗi validation.
- `JobProcessingConfig` và `ResolvedProcessing` chứa đầy đủ các phân nhóm cấu hình mới.

EVIDENCE:
- File `src/services/orchestration/processing/models.py`
- File `src/services/orchestration/jobs/dispatch.py`
- File `configs/product/processing_presets_v1.json`
- Test log `.venv/bin/pytest tests/test_orchestration/test_processing_presets_schema.py`
