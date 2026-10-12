TASK: CFG-08-SCENARIO-PRESETS-CATALOG

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
