# Review T-009

Verdict: CHANGES REQUESTED (một chỗ nhỏ ở chế độ auto; phần còn lại đạt)

Đã đọc `report.md` và diff `src` của các commit T-009 (`297f7ad1`, `42c973c4`, `c32ed6ba`, `3b109112`), không tính commit T-008/T-013
chạy song song. Chạy lại Tests required: 88 passed.

## Acceptance criteria
1. POST build trên Draft → 202, `mode == "geometry"`: **pass**.
2. Worker chạy build qua lease/admission, phase cập nhật từ `progress`, `result_revision` mới: **pass**.
3. Huỷ theo `operation_id` → `cancelled`, scene giữ Draft: **pass** (dùng chung `cancel_event` + `commit_guard` như mode `membership`).
4. Lỗi build → `failed`, `retryable` lấy từ `ObjectGeometryBuildError`: **pass**.
5. Ready → 422 (lớp lỗi riêng `ObjectGeometryAlreadyReadyError`, không so chuỗi); revision sai/đang bận → 409: **pass**.
6. Role matrix: **pass**.
7. Auto xếp build sau tách vật; required thì không: **pass**, nhưng xem Required change.

## Quyết định Engineer (chấp nhận)
- Auto vẫn tạo Draft trước (ép `geometry_review=required` cho lần chạy, giữ mọi knob khác) rồi mới xếp build: đúng, vì build cần Draft làm
  đầu vào và người dùng vẫn sửa được về sau.
- Tái dùng profile tài nguyên GPU sẵn có thay vì bịa số VRAM: đúng.
- `GeometryBuildRequest` riêng, không mở rộng body objectify cũ: đúng.
- Actor `system` cho việc tự xếp hàng; không xếp trùng nếu đã có build cùng base revision: đúng.

## Required change
1. `extract_scene` (`src/services/orchestration/scene/extraction.py`, khối `if auto_geometry and object_geometry_state(...)`): lời gọi
   `objectify_queue.request(...)` xảy ra **sau** `publish_initial`. Nếu nó raise (`ObjectifyRequestError`, `SceneError`,
   `ArtifactStoreError`), stage `OBJECT_EXTRACT` bị đánh dấu thất bại dù Draft đã publish; người dùng thấy "thất bại" sai.
   Sửa: bắt các lỗi đó, `logger.warning(...)` kèm job_id và lý do, rồi trả `StageArtifact` SUCCEEDED như bình thường. Draft vẫn còn và
   người dùng bấm "Tạo mesh" được.
   Test: monkeypatch `objectify_queue.request` raise `ObjectifyRequestError` → stage SUCCEEDED, scene Draft đã publish, có log cảnh báo.
2. Chạy lại `tests/test_orchestration/test_scene_extraction.py` + ruff. Thêm "Round 2" vào report, đặt `implemented`.

## Suggestions (không chặn)
- Đoạn gom `processing.scene` thành nhóm `scene/coacd/inpaint` giờ xuất hiện ở 3 nơi (`objectify_with_retry`, `build_object_geometry`,
  `extract_scene`). Tách thành một hàm dùng chung khi có dịp (đã ghi ở review T-007).
- Import `objectify_queue` trong hàm để tránh vòng import: chấp nhận tạm.

---

# Review T-009 — Round 2

Verdict: ACCEPTED

Đã đọc diff `afe537e1`: lời gọi `state()` + `request()` của auto enqueue được bọc `try/except (ObjectifyRequestError, SceneError,
ArtifactStoreError)`, ghi `logger.warning` kèm job_id và lý do, stage vẫn trả SUCCEEDED. Chạy lại `test_scene_extraction.py` +
`test_scene_objectify_queue.py`: 44 passed.

T-013 được phép làm bước 7 (presets).

---

# Review T-009 — Round 3 (hồi quy phát hiện sau khi accept)

Verdict: CHANGES REQUESTED

`tests/test_scene/test_objectify_draft.py` có 2 test hỏng từ commit `3b109112` (auto mode): `extract_scene` gọi
`load_job_config(job.job_id, job.config_checksum, …)` **trước** bước kiểm runtime nghiêm ngặt. Test 1 truyền `job=None`, test 2 dùng job
giả thiếu `config_checksum`. Job thật luôn có field này nên production không hỏng, nhưng thứ tự là sai: lỗi "thiếu runtime" phải được
báo trước khi đọc config. Architect cũng bỏ sót vì file test này không nằm trong Tests required của T-009.

## Required changes
1. `extract_scene`: chỉ đọc job config và tính `auto_geometry` **bên trong** nhánh sẽ chạy objectify, sau kiểm `strict_geometry_required`
   và runtime. Không đổi hành vi auto.
2. `test_extraction_publishes_draft_with_source_ownership`: thêm `config_checksum` cho job giả (hoặc monkeypatch `extraction.load_job_config`
   trả `None`), để test mô tả đúng job thật.
3. Chạy: `tests/test_scene/test_objectify_draft.py`, `tests/test_orchestration/test_scene_extraction.py`,
   `tests/test_orchestration/test_scene_objectify_queue.py` + ruff. Thêm "Round 3" vào report, đặt `implemented`.

---

# Review T-009 — Round 3

Verdict: CHANGES REQUESTED (còn một test cùng nguyên nhân)

Diff `62e6288a` đúng yêu cầu: đọc job config và tính `auto_geometry` sau bước kiểm runtime nghiêm ngặt. `test_objectify_draft.py` PASS.

Còn hỏng: `tests/test_scene/test_objectgs_required_stage.py::test_required_objectgs_failure_never_publishes_a_legacy_scene[True]`
(`SimpleNamespace` không có `job_id`). Architect đã kiểm bằng worktree: file này 6/6 PASS tại `3b109112~1`, 2 failed tại `3b109112`;
Round 3 sửa được một. Nhánh `[True]` (runtime có) giờ chạy tới `load_job_config`, mà job giả trong test thiếu field.

## Required changes
1. Sửa fixture job giả trong `test_objectgs_required_stage.py` để có `job_id` và `config_checksum` (hoặc monkeypatch
   `extraction.load_job_config` trả `None`), giữ nguyên assertion của test.
2. Chạy **đủ** nhóm này (mọi file test đụng `extract_scene`):
   ```
   .venv/bin/python -m pytest tests/test_scene/test_objectify_draft.py tests/test_scene/test_objectgs_required_stage.py \
     tests/test_orchestration/test_scene_extraction.py tests/test_orchestration/test_scene_objectify_queue.py \
     tests/test_scene/test_objectgs_objectify_flow.py tests/test_scene/test_objectify_config_override.py -q
   ```
   Kết quả phải 0 failed. Thêm "Round 4" vào report, đặt `implemented`.

---

# Review T-009 — Round 4

Verdict: ACCEPTED

Diff `e7d692bc` chỉ sửa fixture `test_objectgs_required_stage.py` (thêm `job_id`/`config_checksum`), assertion giữ nguyên.
Chạy đủ 6 file test gọi `extract_scene`: 97 passed, 0 failed. T-013 được làm bước 7.
