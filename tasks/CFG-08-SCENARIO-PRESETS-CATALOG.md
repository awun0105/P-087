TASK: CFG-08-SCENARIO-PRESETS-CATALOG

STATUS: COMPLETED — deterministic scenario catalog and resource recommendations verified.

## Implementation and verification (2026-10-13)

- Added strict `ScenarioPreferences` and six named scenario entries in the actual product catalog. Photos select indoor/outdoor photo presets first; video single-object scans select `video_single_object`; outdoor room captures use `video_outdoor_forward`; indoor room captures distinguish continuous and loop video. Tests cover all 36 preference combinations.
- `scale_for_machine` takes the catalog explicitly as a keyword argument so it uses authoritative limits and calibrated coefficients, rather than hidden defaults. It reuses `maximum_for_machine` to search SfM and training budgets separately, preserving scenario choices and other non-resource controls.
- Minimum quality caps the search at the existing minimum-quality values; balanced caps it at scenario values; machine maximum uses the maximum profile. Known idle VRAM/RAM/disk measurements bound the result below the warning threshold. An impossible floor, missing GPU, or incomplete idle measurement raises `RecommendationUnavailableError`.
- Unknown workers receive minimum-quality settings without claiming measured safety. A resource heuristic cannot guarantee that a future runtime never encounters OOM; live admission and actual runtime checks remain necessary. No unsupported worker is silently called safe.
- Additional required file: `configs/product/processing_presets_v1.json`. `PresetName` becomes `str` here because the real catalog cannot load six scenario names with the former two-name Literal. The rest of CFG-09 schema/group/worker work remains pending.
- New plus existing processing configuration suites: 78 passed, no skips. Log: `tasks/reports/CFG-08-VERIFICATION.log`. Cases include 4 GB versus 24 GB VRAM, independent RAM scaling, mutation isolation, busy-worker idle baseline and impossible budgets.
- Ruff check and format check clean for processing and new test; `git diff --check` clean. Processing API regressions: 2 passed, 55 unrelated tests deselected. Log: `tasks/reports/CFG-08-API-VERIFICATION.log`.
- Scenario catalog currently covers the existing parameter groups. New matching, geometry, objectify and simulation controls are added in CFG-09 before API/UI integration; no new pipeline run or UI acceptance is claimed here.

Pre-flight (GUIDE.md Rule 13)
- codegraph: processing models, resource estimate/search and their config/API callers inspected.
- impact: expanded catalog identifiers affect config loading and processing options; existing processing regressions pass.
- understand: n/a — new recommender uses the already traced resource model and queue idle-budget policy.
- minimal-code: rung 2 — reuse maximum_for_machine, estimate_gb and catalog validation.
- checks: 78 processing/recommender tests and 2 processing API tests passed; ruff clean.
- DevTools: n/a — UI-free service/config change.

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Người dùng thực tế (kỹ sư robotics, nhà nghiên cứu AI) không thể và không nên phải nhớ hàng chục con số kỹ thuật chi tiết (như SIFT features 8192, overlap 10, external fill 1.6m, CoACD concavity 0.08). Thay vào đó, họ chỉ biết loại dữ liệu mình vừa quay:
  1. Loại quay: Video đi bộ liên tục / Video quay vòng 360° / Tập ảnh rời.
  2. Không gian: Trong nhà (indoor) hay Ngoài trời (outdoor).
  3. Phạm vi đối tượng: Quét 1 đồ vật duy nhất (single object) hay Toàn bộ căn phòng/kho xưởng (full room).
  4. Mức độ tài nguyên mong muốn: Tối thiểu an toàn cho máy này (Minimum) / Khuyên dùng cân bằng (Balanced) / Tối đa tận dụng hết sức mạnh máy này (Maximum).
  Nếu thiếu một module suy luận cấu hình, người dùng sẽ phải chỉnh tay từng ô và rất dễ chọn sai làm gãy mô hình hoặc tràn bộ nhớ VRAM.
- **Yêu cầu cốt lõi (What):**
  1. Định nghĩa đầy đủ các bộ Preset kịch bản bao phủ mọi trường hợp video đầu vào.
  2. Viết module logic gợi ý cấu hình thông minh `src/services/orchestration/processing/recommender.py` có hàm `recommend_preset(preferences: ScenarioPreferences, capability: MachineCapability | None) -> tuple[str, dict[str, ParamValue]]`: tự động suy ra preset tối ưu và tự động điều chỉnh độ phân giải, số Gaussian phù hợp với VRAM/RAM thực tế của máy worker.

GOAL:
Xây dựng danh mục Presets kịch bản toàn diện cho mọi tình huống dữ liệu đầu vào và phát triển bộ máy logic gợi ý cấu hình tự động (`ScenarioPreferences` & `recommender.py`) dựa trên các lựa chọn cấp cao (high-level tickboxes) và năng lực máy worker.

INPUT CONTRACT:
- `docs/execution/CONFIG_CATALOG.md`.
- `MachineCapability` và `ResourceModel` trong `src/services/orchestration/processing/models.py`.

OUTPUT CONTRACT:
- Schema `ScenarioPreferences` trong `src/services/orchestration/processing/models.py`:
  - `input_type`: Literal["video_continuous", "video_loop_360", "photo_set"]
  - `environment`: Literal["indoor", "outdoor"]
  - `subject_scope`: Literal["single_object", "full_room"]
  - `target_capacity`: Literal["minimum_quality", "balanced", "machine_maximum"]
- Module mới `src/services/orchestration/processing/recommender.py`:
  - Hàm `recommend_preset(preferences: ScenarioPreferences, capability: MachineCapability | None, presets: ProcessingPresets) -> tuple[str, dict[str, ParamValue]]`
  - Tự động map lựa chọn cấp cao sang preset kịch bản chính xác nhất:
    - `video_continuous` + `indoor` + `full_room` $\rightarrow$ `video_indoor_walkthrough`
    - `video_loop_360` + `indoor` + `full_room` $\rightarrow$ `video_indoor_orbital_360`
    - `video_loop_360` + `indoor` + `single_object` $\rightarrow$ `video_single_object`
    - `video_continuous` + `outdoor` $\rightarrow$ `video_outdoor_forward`
    - `photo_set` + `indoor` $\rightarrow$ `photo_collection_indoor`
    - `photo_set` + `outdoor` $\rightarrow$ `photo_collection_outdoor`
  - Nếu `target_capacity == "machine_maximum"`: tự động scale tăng `max_resolution`, `max_splats`, `total_train_iters` lên mức trần an toàn theo VRAM của máy.
  - Nếu `target_capacity == "minimum_quality"`: tự động đưa về mức tối thiểu an toàn để không bao giờ bị OOM.

OWNED FILES:
- `src/services/orchestration/processing/recommender.py`
- `tests/test_orchestration/test_preset_recommender.py`

FILES YOU MAY MODIFY:
- `src/services/orchestration/processing/`
- `tests/test_orchestration/`

FILES YOU MUST NOT MODIFY:
- `frontend/`

PRIMARY TOOL:
- Python 3.12, Pydantic v2, Pytest.

IMPLEMENT:
1. Định nghĩa `ScenarioPreferences` trong `models.py` với 4 câu hỏi trắc nghiệm cấp cao.
2. Viết `src/services/orchestration/processing/recommender.py`:
   - Hàm `select_preset_name(preferences: ScenarioPreferences) -> str`.
   - Hàm `scale_for_machine(params: dict[str, ParamValue], capability: MachineCapability | None, target: str) -> dict[str, ParamValue]`.
   - Hàm chính `recommend_preset(...)` trả về `(preset_name, params)`.
3. Viết unit test trong `tests/test_orchestration/test_preset_recommender.py`:
   - Test tất cả các tổ hợp checkbox (indoor/outdoor, 360/walkthrough, object/room).
   - Test việc co giãn thông số khi máy có GPU 4GB VRAM vs GPU 24GB VRAM.

TEST:
- `.venv/bin/pytest tests/test_orchestration/test_preset_recommender.py -v`
- `ruff check src/services/orchestration/processing/`
- `ruff format --check src/services/orchestration/processing/`

DONE WHEN:
- Bộ máy gợi ý hoạt động độc lập, xác định (deterministic), hỗ trợ đầy đủ mọi kịch bản đầu vào và tính toán chính xác mức Tối thiểu / Tối đa cho máy.
- Unit tests pass 100%.

EVIDENCE:
- File `src/services/orchestration/processing/recommender.py`
- Test log `.venv/bin/pytest tests/test_orchestration/test_preset_recommender.py`
