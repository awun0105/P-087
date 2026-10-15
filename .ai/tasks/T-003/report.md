# Report T-003

## Done

Mỗi bước là một commit, theo TDD: viết test trước, chạy thấy đỏ, rồi mới sửa code.

- **Bước 1** (`f62c9dc9`): `ObjectShellManifest` trong `object_geometry.py`. Validator: `shell_mesh_ref` là `ObjectShellMesh`; `object_id` thuộc `source_membership`; `quality.passed is True`; `shell_mesh_ref.job_id == labels_ref.job_id`.
- **Bước 2** (`b0cebd69`): `SceneObject.surface_mesh_ref` nhận `ObjectShellMesh`. Vẫn từ chối `ObjectCollider` và ref khác job.
- **Bước 3, một phần** (`767ff587`): `object_geometry_state(scene)` trong `src/services/scene/geometry_state.py`. Thiếu khóa → `ready`; `awaiting_review` và `ready` trả nguyên; giá trị khác (kể cả `None`) → `ValueError`. **Chưa làm** `require_geometry_ready`, xem câu hỏi 2.
- **Bước 4a** (`d4013681`): `SceneObjectifyConfig.geometry_method` nhận `shell`. Thêm `geometry_review: Literal["legacy","required","auto"] = "legacy"`. Lift runner loại `geometry_review` khỏi config.
- **Bước 4b** (`c95dacd4`): `job_requires_strict_geometry` trả True khi `geometry_method` là `shell` hoặc `objectgs`. Giữ alias `job_requires_objectgs`. `extraction.py` gọi tên mới.
- **Bước 6**: `scripts/check_contract_mirror.py` PASS. Không sửa `api.ts`, vì script không kiểm `ObjectShellManifest`.
- **Chưa làm**: `require_geometry_ready` (bước 3) và đổi preset (bước 5). Cả hai bị chặn bởi câu hỏi cần Architect ở cuối file.

Các thay đổi trên không đổi hành vi job hiện có, vì preset vẫn là `objectgs`. Hiện không có đường nào đưa `shell` vào job ngoài preset: `ObjectifyRequest` của API chỉ có `expected_scene_revision` và `mode`, còn CLI `scripts/scene/reobjectify.py` chỉ nhận `legacy|objectgs`.

## Files changed

- `src/models/contracts/object_geometry.py`: thêm `ObjectShellManifest`, import thêm `FiniteFloat`.
- `src/models/contracts/scene.py`: `surface_mesh_ref` chấp nhận `ObjectShellMesh`.
- `src/services/scene/geometry_state.py` (mới): `ObjectGeometryState`, `object_geometry_state`.
- `src/services/orchestration/scene/objectify.py`: `geometry_method` thêm `shell`; thêm `geometry_review`; loại `geometry_review` khỏi lift config; `job_requires_strict_geometry` và alias.
- `src/services/orchestration/scene/extraction.py`: import và lời gọi đổi sang `job_requires_strict_geometry`.
- `tests/test_contracts/test_object_geometry.py`: test `ObjectShellManifest` và `SceneObject` với shell.
- `tests/test_scene/test_geometry_state.py` (mới): 5 test.
- `tests/test_scene/test_objectify_config_override.py`: default có `geometry_review`; lift không nhận `geometry_review`; `shell` hợp lệ; giá trị lạ bị từ chối; `job_requires_strict_geometry` (4 trường hợp).
- `tests/test_scene/test_objectgs_required_stage.py`: đổi tên monkeypatch sang `job_requires_strict_geometry` (xem Deviations).
- `.ai/tasks/T-003/report.md`, `.ai/status.md` (chỉ dòng T-003).

## Tests

- `.venv/bin/python -m pytest tests/test_contracts tests/test_scene/test_geometry_state.py tests/test_scene/test_objectify_config_override.py tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_processing_presets_schema.py tests/test_orchestration/test_scene_objectify_queue.py -q`: **343 passed** (lần chạy cuối, sau bước 4b).
- `.venv/bin/python scripts/check_contract_mirror.py`: **PASS**, exit 0.
- `ruff check` và `ruff format --check` trên 9 file đã sửa hoặc tạo: **passed**.
- Đỏ trước khi xanh, đúng như dự kiến: bước 1 ImportError; bước 2 một test fail; module state lỗi khi collect; bước 4a ba test fail; bước 4b bốn test fail.
- `graphify update .` đã chạy sau khi sửa code. `graphify-out/` nằm trong `.gitignore`.
- **Không chạy** `npm run typecheck`: không sửa TypeScript.
- **Không chạy** `tests/test_scene/test_objectgs_required_stage.py`: file không nằm trong danh sách Tests required. Đã đổi một dòng monkeypatch trong file này, nên **cần chạy ở T-019**.

## Deviations from plan

1. **Bước 3: không làm `require_geometry_ready`.** Plan viết `SceneEditRejectedError(code="OBJECT_GEOMETRY_NOT_READY", ...)` và bảo xem `errors.py` để biết cách gắn code. Nhưng `SceneEditRejectedError` không có tham số `code`, `errors.py` không có cơ chế gắn code nào, và API chỉ trả `detail = str(error)`. Không tự chọn cơ chế, xem câu hỏi 2.
2. **Bước 5: không đổi preset.** Chặn bởi câu hỏi 1.
3. **Sửa thêm `tests/test_scene/test_objectgs_required_stage.py`**, không có trong danh sách Files của plan. Test này monkeypatch `extraction.job_requires_objectgs`. Sau khi `extraction.py` gọi `job_requires_strict_geometry`, thuộc tính cũ không còn trong module và test sẽ lỗi. Đã đổi đúng một chuỗi tên.
4. **`src/models/contracts/__init__.py` không sửa.** File này không re-export contract `object_geometry`, kể cả `ObjectSurfaceManifest`, nên điều kiện "export nếu re-export" không áp dụng.
5. **`frontend/src/lib/contracts/api.ts` không sửa.** Script PASS mà không cần sửa; `ObjectSurfaceManifest` cũng không có trong mirror.
6. Thông báo lỗi của validator `surface_mesh_ref` đổi thành "must reference ObjectSurfaceMesh or ObjectShellMesh, not a collider". Thay đổi nhỏ, cùng ý.

## Known issues / TODO

- `objectify_with_retry` (objectify.py:1036) và `reobjectify` (objectify.py:1113) vẫn khai `geometry_method: Literal["legacy","objectgs"]`. Cần nới khi có nhánh shell (T-005/T-007).
- `extract_scene`: biến `objectgs_required` và thông báo "ObjectGS job requires ..." giờ cũng áp dụng cho job `shell`. Đổi chữ khi có nhánh shell. Chưa ảnh hưởng hành vi, vì preset chưa đổi.
- `objectify_queue.py:251`: `object_centric` chỉ nhận `provenance.geometry_method == "objectgs"`. Nhánh shell cần xử lý tương tự (T-005/T-009).
- Nhánh không-ObjectGS không ghi `geometry_method` vào provenance; key này chỉ được ghi ở objectify.py:1008. Xem câu hỏi 1.
- Không thuộc T-003 và không đụng tới: commit `f7d6d176` (T-001), dòng T-001 trong `status.md` đang nằm trong cây làm việc chưa commit, và các thay đổi `tasks/CFG-*`, `BRAINSTORM.md`, `MASTER_PITCH.md` trong cây làm việc.

## Câu hỏi cần Architect

Trạng thái T-003 là `changes-requested`, owner `architect`.

**1. Đổi preset sang `shell` + `geometry_review=required` (bước 5) có làm được trước khi có nhánh shell không?** Chặn bước 5.

Plan vừa đổi mọi preset sang `shell` (bước 5), vừa ghi "Chưa dùng `shell` trong luồng chạy". Hai điều này mâu thuẫn. Trên code hiện tại, job có `shell` rơi vào nhánh không-ObjectGS của `objectify()`:

- `objectgs_runtime = None` (objectify.py:338), nên không dựng vỏ.
- CoACD chạy trên Gaussian từng vật (objectify.py:641–651). Đây là đường hình học legacy.
- provenance không có `geometry_method` (objectify.py:914).
- `geometry_review` không được đọc ở đâu. Điểm dừng Draft là T-005.
- Scene không có khóa `object_geometry`, nên `object_geometry_state` đọc là `ready` theo quy tắc của plan.

Nếu đổi preset ngay, job mới mang cấu hình `shell` nhưng ra hình học legacy, bị đánh dấu `ready`, và không dừng để duyệt.

- **A (đề xuất):** giữ preset `objectgs` cho đến khi nhánh shell chạy được (T-007) và có điểm dừng Draft (T-005). Chuyển bước 5 sang đó. Hành vi job mới không đổi.
- **B:** đổi preset ngay, và để `objectify()` từ chối `shell` bằng `ObjectifyError(retryable=False)` cho tới T-007. Job mới lỗi có chủ đích.
- **C:** đổi ngay và chấp nhận hình học legacy cho job mới đến T-007. Không đề xuất.

**2. Gắn code `OBJECT_GEOMETRY_NOT_READY` vào lỗi thế nào?** Chặn `require_geometry_ready`. Không chặn bước nào khác.

`SceneEditRejectedError` không có `code`, và API chỉ trả `detail`. Lựa chọn:

- **A (đề xuất):** lớp con `ObjectGeometryNotReadyError(SceneEditRejectedError)` có thuộc tính `code = "OBJECT_GEOMETRY_NOT_READY"`. Không đổi API. T-010/T-013 sẽ đọc code khi nối API.
- **B:** thêm tham số keyword-only `code` vào `SceneEditRejectedError`. Đổi lớp dùng chung.
- **C:** đổi body lỗi sang `{detail, code}`. Đổi contract HTTP và cách frontend đọc `ApiError`. Vượt phạm vi T-003.

Khi có lựa chọn, tôi làm `require_geometry_ready` và test, khoảng 15 dòng.

## Round 2

Đọc `review.md` (CHANGES REQUESTED, một việc nhỏ). Hai câu hỏi đã được trả lời:

- **Câu 1 (preset):** chọn A. Bước 5 không còn thuộc T-003; chuyển sang T-013. Preset giữ `objectgs`. Round này không đổi preset.
- **Câu 2 (mã lỗi):** chọn A. Lớp con `ObjectGeometryNotReadyError(SceneEditRejectedError)` với `code = "OBJECT_GEOMETRY_NOT_READY"`. Envelope HTTP không đổi.

**Required change 1** (commit `9d4bd2a5`, một commit):

- `src/services/orchestration/scene/errors.py`: thêm `ObjectGeometryNotReadyError`, đặt cạnh `SceneEditRejectedError`.
- `src/services/scene/geometry_state.py`: thêm `require_geometry_ready(scene, action) -> None`. Khi state là `awaiting_review`, raise `ObjectGeometryNotReadyError(f"Cần tạo mesh trước khi {action}.")`. Scene `ready` hoặc thiếu khóa không raise.
- `tests/test_scene/test_geometry_state.py`: test raise đúng lớp và `code`, là `SceneEditRejectedError`, thông điệp đúng chuỗi trên. Test scene `ready` và scene thiếu khóa không raise.

**Required change 2:** báo cáo này và `status.md` → `implemented`, owner `summarizer`.

### Kiểm tra (Round 2)

- `.venv/bin/python -m pytest tests/test_scene/test_geometry_state.py -q`: **8 passed**. Trước khi sửa đã chạy đỏ: lỗi collect vì chưa có lớp lỗi.
- Bộ Tests required của plan (`tests/test_contracts tests/test_scene/test_geometry_state.py tests/test_scene/test_objectify_config_override.py tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_processing_presets_schema.py tests/test_orchestration/test_scene_objectify_queue.py`): **346 passed**. Chạy thêm vì `errors.py` được dùng chung bởi editor và các object action. Không có test nào liệt kê subclass của `SceneError`.
- `ruff check` và `ruff format --check` trên 3 file đã sửa: **passed**.
- `graphify update .` đã chạy.

### Files changed (Round 2)

- `src/services/orchestration/scene/errors.py`: thêm `ObjectGeometryNotReadyError`.
- `src/services/scene/geometry_state.py`: thêm `require_geometry_ready`.
- `tests/test_scene/test_geometry_state.py`: thêm 3 test cho `require_geometry_ready`.
- `.ai/tasks/T-003/report.md`, `.ai/status.md` (chỉ dòng T-003).

### Trạng thái các mục cũ

- Deviation 1 (`require_geometry_ready`): đã xong.
- Deviation 2 (bước 5, preset): theo quyết định câu 1, chuyển sang T-013. Không còn là việc của T-003.
- Deviation 3 (`test_objectgs_required_stage.py`): architect đã chạy và pass trong `review.md`, cùng `test_objectgs_objectify_flow.py` (357 passed).

### Ghi chú (không chặn)

- `src/services/orchestration/scene/__init__.py` re-export `SceneEditRejectedError` và các lỗi khác, nhưng chưa re-export `ObjectGeometryNotReadyError`. Thêm khi API dùng lớp này (T-010).
- Theo `review.md`, đổi tên `objectgs_required` và thông điệp "ObjectGS job requires…" làm ở T-005. Alias `job_requires_objectgs` không còn nơi dùng; xoá ở T-005.
