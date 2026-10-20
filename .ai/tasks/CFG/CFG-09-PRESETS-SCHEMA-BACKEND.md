TASK: CFG-09-PRESETS-SCHEMA-BACKEND

STATUS: DONE — six-group catalog, sealed configuration dispatch and downstream consumers verified.

## Implementation and evidence (2026-10-13)

- Catalog: 8 presets, 35 declared parameters across sampling, colmap, brush, geometry, scene and simulation. Every preset validates and produces the six groups. COLMAP configuration validates against the real `ColmapConfig` contract.
- `PresetName = str` was completed in CFG-08. Added groups use independent dictionaries and omit empty defaults so legacy serialized job bytes are unchanged.
- Dispatch accepts the complete historical 11-key parameter set without changing its effective native defaults. Incomplete new parameter sets still use strict catalog validation. Artifact reads verify their job-bound checksum.
- Geometry: finalize now reads the sealed job controls, overlays the deployment profile, validates it, and carries mesh mode, resolution and both fill options into VoxelConfig. Zero fill means disabled. Nonzero external fill upgrades a legacy profile to schema 1.2. Added default fields remain absent from old serialized geometry profiles. Existing bundle publication records the effective profile snapshot and checksum.
- Objectify: initial extraction and reobjectify both use `objectify_with_retry`; it loads the sealed scene controls once and preserves provider groups across retries. Reobjectify queue identity now includes the job configuration checksum.
- Simulation: the catalog's enabled/disabled ground-plane choice is normalized to a boolean at the job boundary; the native physics contract remains strict. Existing friction, restitution and carve-margin consumers receive their values.
- Recommendation overlays preserve input mode, environment and single-object intent even when multiple scenarios share a preset name. Resource scaling changes only existing SFM/3DGS drivers.
- Catalog adjustment: `scene.max_objects` permits 1 with step 1 rather than the example minimum 5/step 5, so the single-object scenario can actually retain one object. Tests cover this for all input/environment/capacity combinations.

### Additional required source paths

The user clarified that may-modify lists are examples, not a source-path restriction. Inspection required these paths beyond the initial three schema files:

- `src/services/reconstruction/finalize.py`: geometry profile validation, overlays and native voxel forwarding.
- `src/services/orchestration/jobs/runner.py`: sealed configuration loading before finalize dispatch.
- `src/services/orchestration/scene/objectify.py`: shared initial/retry/reobjectify consumer.
- `src/services/orchestration/scene/objectify_queue.py`: bind queue identity to per-job controls.
- `src/services/orchestration/review/simulation_package.py`: ground-plane choice normalization.
- `src/services/orchestration/processing/recommender.py`: scenario-specific overlays for all six groups.
- `tests/test_reconstruction/test_rec05_finalize_quality.py`, `tests/test_orchestration/test_worker_cleanup.py`, `tests/test_orchestration/test_preset_recommender.py`, `tests/test_orchestration/test_processing_config.py`: native-boundary, request-capture and regression coverage.

### Verification

- `.venv/bin/pytest tests/test_orchestration/test_processing_presets_schema.py tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_preset_recommender.py -v`: **90 passed**, including all named schema tests and 36 scenario combinations. Log: `tasks/reports/CFG09-SCHEMA-VERIFICATION.log`.
- `.venv/bin/pytest tests/test_orchestration/test_processing_presets_schema.py tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_preset_recommender.py tests/integration/test_studio_processing_job.py tests/test_scene/test_objectify_config_override.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_simulation/test_simulation_config_override.py tests/test_orchestration/test_worker_cleanup.py tests/test_reconstruction/test_rec05_finalize_quality.py tests/test_reconstruction/test_gaussian_outlier_filter.py tests/test_reconstruction/test_quality_port.py -q`: **203 passed**, no skips. Log: `tasks/reports/CFG09-CONSUMER-VERIFICATION.log`.
- `ruff check src/services/orchestration/` plus changed reconstruction/tests: clean. Matching `ruff format --check`: **119 files already formatted**. Log: `tasks/reports/CFG09-STATIC-CHECKS.log`.
- `git diff --check`: clean. `graphify update .`: AST graph refreshed.
- These checks prove configuration and consumer plumbing with fixture/native USD coverage. They do not establish new GPU scene quality, Isaac simulation, browser UX or production acceptance. Those broader gates remain in later tasks.

### Pre-flight (GUIDE.md Rule 13)

- codegraph: explored schema/config/dispatch, GeometryProfile/build_voxel_config/load_geometry_profile, run_finalize_job, objectify_with_retry and simulation consumer paths.
- impact: Studio job creation and dispatch; finalize and geometry quality snapshots; extraction/reobjectify retries and queue identity; simulation package creation/cache.
- understand: UNVERIFIED — understand-anything is unavailable in this session; business flow traced through current callers, task contracts and existing tests.
- minimal-code: reused sealed artifact resolver, existing profile models, provider config validation, retry wrapper and physics normalization boundary; no new dependency.
- checks: Python checks and counts above; TypeScript/eslint/vitest n/a for this backend task.
- DevTools: n/a — no rendered UI change; UI contracts/wizard remain CFG-12/13 and browser gate CFG-14.

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
