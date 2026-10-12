TASK: CFG-03-COLMAP-MATCHING-MODES

## Ý TƯỞNG & ĐỘNG LỰC THỰC HIỆN (WHY & WHAT)
- **Tại sao cần task này (Why):** Hiện tại `colmap_runtime.py` đang bị ép cứng (hardcode) chỉ chạy lệnh `sequential_matcher` với cờ `--SequentialMatching.loop_detection 0`. Điều này khiến pipeline chỉ chạy được duy nhất một trường hợp video đi thẳng. Khi gặp video quay vòng 360° thì bị đứt gãy mô hình (vì thiếu vocab tree loop detection), còn khi người dùng tải lên một tập ảnh tĩnh rời rạc (như chụp từ máy ảnh DSLR) thì `sequential_matcher` hoàn toàn thất bại vì ảnh không có thứ tự thời gian.
- **Yêu cầu cốt lõi (What):** Mở rộng `ColmapConfig` và hàm sinh câu lệnh `_matching_command` trong `colmap_runtime.py` để hỗ trợ 3 chế độ so khớp rõ ràng:
  1. `sequential`: Chuỗi lân cận siêu nhanh (1–2 phút) cho video đi bộ một chiều.
  2. `sequential_vocab_tree`: Chuỗi lân cận + Loop detection tự động khâu vòng lặp qua file từ điển `vocab_tree.bin`.
  3. `exhaustive`: So khớp $O(N^2)$ mọi cặp ảnh cho tập ảnh tĩnh rời rạc.

GOAL:
Mở rộng cấu hình và adapter COLMAP (`ColmapConfig`, `colmap_runtime.py`) để hỗ trợ 3 chế độ so khớp đặc trưng:
1. `sequential`: So khớp theo chuỗi khung hình liên tiếp (cho video thông thường, siêu nhanh).
2. `sequential_vocab_tree`: So khớp theo chuỗi kết hợp phát hiện vòng lặp qua Vocabulary Tree (cho video quay vòng 360° hoặc nhảy góc).
3. `exhaustive`: So khớp toàn bộ các cặp ảnh chéo (cho tập ảnh tĩnh rời rạc ít ảnh).

INPUT CONTRACT:
- `ColmapConfig` trong `src/services/reconstruction/rgb/pose/camera_pose.py`.
- Module `src/services/reconstruction/adapters/vocab_tree.py` (từ CFG-02).
- Danh mục tham số trong `docs/execution/CONFIG_CATALOG.md` (Chặng 3).

OUTPUT CONTRACT:
- Thuộc tính mới trong `ColmapConfig`:
  - `matching_mode: Literal["sequential", "sequential_vocab_tree", "exhaustive"] = "sequential"`
  - `loop_detection_period: int = 10`
  - `loop_detection_num_images: int = 50`
  - `loop_detection_min_index_distance: int = 50`
- Hàm `_matching_command(config: ColmapConfig, match: str) -> list[str]` sinh câu lệnh CLI tương ứng:
  - `sequential`: `["sequential_matcher", "--database_path", "database.db", f"--{match}.use_gpu", str(int(config.use_gpu)), f"--{match}.num_threads", str(config.num_threads), "--SequentialMatching.overlap", str(config.sequential_overlap), "--SequentialMatching.loop_detection", "0"]`
  - `sequential_vocab_tree`: thêm `--SequentialMatching.loop_detection 1`, `--SequentialMatching.vocab_tree_path vocab_tree.bin`, `--SequentialMatching.loop_detection_period ...`
  - `exhaustive`: `["exhaustive_matcher", "--database_path", "database.db", f"--{match}.use_gpu", str(int(config.use_gpu)), f"--{match}.num_threads", str(config.num_threads)]`
- Kiểm tra tính hợp lệ: nếu chọn `sequential_vocab_tree` mà file từ điển không tồn tại thì raise `ColmapError("VOCAB_TREE_MISSING", ...)` có remediation message.

OWNED FILES:
- `src/services/reconstruction/rgb/pose/camera_pose.py`
- `src/services/reconstruction/adapters/colmap_runtime.py`
- `tests/test_reconstruction/test_colmap_matching_modes.py`

FILES YOU MAY MODIFY:
- `src/services/reconstruction/rgb/pose/camera_pose.py`
- `src/services/reconstruction/adapters/colmap_runtime.py`
- `src/services/reconstruction/adapters/colmap.py`
- `tests/test_reconstruction/`

FILES YOU MUST NOT MODIFY:
- `src/models/contracts/`
- `frontend/`

PRIMARY TOOL:
- Python 3.12, Pydantic v2, Pytest.

IMPLEMENT:
1. Cập nhật `ColmapConfig` trong `camera_pose.py`:
   - Thêm `matching_mode: Literal["sequential", "sequential_vocab_tree", "exhaustive"] = "sequential"`.
   - Thêm các tham số loop detection với giá trị mặc định chuẩn từ CONFIG_CATALOG.
   - Giữ nguyên `schema_version = "1.0"`.
2. Sửa `reconstruction_commands` và `_matching_command` trong `colmap_runtime.py`:
   - Rẽ nhánh command theo `config.matching_mode`.
   - Đối với `exhaustive_matcher`, thêm các cờ GPU/thread chuẩn của COLMAP.
   - Thêm probe capability cho `exhaustive_matcher` nếu cần trong `capabilities()`.
3. Viết unit test trong `tests/test_reconstruction/test_colmap_matching_modes.py`:
   - Test command sinh ra cho cả 3 chế độ.
   - Test fallback / validation lỗi khi thiếu file vocab tree.

TEST:
- `.venv/bin/pytest tests/test_reconstruction/test_colmap_matching_modes.py -v`
- `.venv/bin/pytest tests/test_reconstruction/test_rec03_colmap.py -v` (36 bài test gốc phải pass 100%)
- `ruff check src/services/reconstruction/`
- `ruff format --check src/services/reconstruction/`

DONE WHEN:
- Toàn bộ unit tests của COLMAP Matching Modes pass 100%.
- Không phá vỡ các bài test COLMAP cũ (`test_rec03_colmap.py` pass 36/36).

EVIDENCE:
- File `src/services/reconstruction/rgb/pose/camera_pose.py`
- File `src/services/reconstruction/adapters/colmap_runtime.py`
- Test log `.venv/bin/pytest tests/test_reconstruction/test_colmap_matching_modes.py`
