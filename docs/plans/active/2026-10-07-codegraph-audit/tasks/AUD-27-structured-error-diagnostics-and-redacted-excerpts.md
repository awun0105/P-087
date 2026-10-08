# AUD-27 — Chẩn đoán lỗi COLMAP, đoạn trích log đã che và hướng khắc phục trên UI

## Metadata và goal

- IN PROGRESS; P1; EX-REC adapters + EX-PRODUCT Studio API/UI.
- S1 and S2 implementation are committed; S2 owner visual signoff and S3 live worker-log evidence remain open.
- Canonical PRODUCT-02/08/09, REC-03/04.
- Goal: khi một stage lỗi, người dùng đọc được nguyên nhân và việc cần làm bằng tiếng
  Việt ngay tại stage đó; reviewer xem được đoạn cuối log đã che đường dẫn; lỗi COLMAP
  được phân loại theo kết quả thật thay vì một mã chung.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0027](../../../../decisions/0027-structured-error-diagnostics-and-redacted-excerpts.md).

## Baseline và scope

Điểm bắt đầu trong source (kiểm lại bằng CodeGraph trước khi sửa):

- `src/services/reconstruction/adapters/colmap_runtime.py`: `ColmapError` (dòng 26-50),
  `ColmapProcess.run` (dòng 61-87).
- `src/services/reconstruction/adapters/colmap.py`: `ColmapAdapter.execute` (dòng 73-94),
  `_execute` (dòng 96-125).
- `src/services/reconstruction/adapters/colmap_model.py:129-132`: `select_sparse_model`.
- `src/services/reconstruction/adapters/brush_runtime.py:38-46`: `FATAL_LOG_PATTERNS` (chỉ tham khảo).
- `src/models/contracts/retryability.py`: `_RETRYABLE_ERROR_CODES`.
- `src/models/contracts/manifests.py:185-192`: `ExecutionError` (`details: JsonObject | None`).
- `src/api/studio/scenes.py:279-280`: `GET /jobs/{job_id}/progress`, quyền `require_contributor`.
- `src/api/product/projects.py:64` và `:116`: route trả `JobManifest` và danh sách job.
- `frontend/src/features/studio/PipelineTimeline.tsx:16-24` (`StageView`), `:175-179` (khối lỗi).
- `frontend/src/features/studio/scene/ProgressTab.tsx:21-24`: nơi tạo `StageView`.

Hiện trạng đã kiểm trong source:

1. `ColmapProcess.run` gom stdout/stderr vào `workspace/process.log`. Khi mã thoát khác 0
   nó ném `ColmapError("COLMAP_PROCESS_FAILED", "COLMAP <lệnh> failed (exit N)")`.
   `details` chỉ có `action` (tiếng Anh) và `exception_type`.
2. Khi COLMAP không dựng được model nào, `select_sparse_model` ném `ValueError`, và
   `execute` biến nó thành `COLMAP_ARTIFACT_INVALID` với câu "inspect attempt artifacts".
   Đây là lỗi do video đầu vào nhưng người dùng nhận thông báo như lỗi hệ thống.
3. `COLMAP_REGISTRATION_LOW` đã tồn tại (`colmap.py:125`) nhưng thông báo không có con số.
4. Docstring của `ColmapError` và `VisualError` cấm đưa đường dẫn riêng và stderr thô ra UI.
5. UI hiện đúng một dòng `human_message (error_code)`. `details` và `retryable` có trong
   contract `frontend/src/lib/contracts/api.ts:166-172` nhưng `StageView.error` chỉ khai
   hai field nên không dùng được.
6. Không có test nào cho `PipelineTimeline` trong `frontend/tests/`.

### Chuỗi log thật của COLMAP đang pin (bằng chứng)

Lấy từ 29 file `process.log` dưới `data/`, tất cả là lượt chạy thành công:

| Chuỗi | Số lần xuất hiện trong lượt thành công |
|---|---|
| `=> Could not register, trying another image.` | 1.011 |
| `Linear solver failure. Failed to compute a step` | 157 |
| `=> No good initial image pair found.` | 29 |
| `Discarding reconstruction due to no initial pair` | 29 |
| `Discarding reconstruction due to insufficient size` | 20 |

Hệ quả bắt buộc: không được dùng các chuỗi này làm dấu hiệu "lỗi chết" để dừng tiến
trình, vì lượt chạy tốt cũng in ra chúng. Chúng chỉ được dùng để chọn lời giải thích
sau khi kết quả đã cho thấy thất bại. Chưa có file log COLMAP thất bại nào ở local.

### Owned

`src/services/reconstruction/adapters/colmap_runtime.py`,
`src/services/reconstruction/adapters/colmap.py`,
`src/services/reconstruction/adapters/log_excerpt.py` (mới),
`src/models/contracts/retryability.py`,
`src/api/studio/scenes.py` (`GET /scenes`, `POST /scenes/from-upload`, `GET /jobs/{job_id}/progress`),
`src/api/studio/assemblies.py` (`POST /input-assemblies/{assembly_id}/run`),
`src/api/product/projects.py` (hai route tạo và liệt kê job),
`src/api/product/jobs.py` (manifest, transition, retry và attempt routes),
`src/api/studio/error_view.py` (mới),
`frontend/src/features/studio/PipelineTimeline.tsx`,
`frontend/src/features/studio/errorGuidance.ts` (mới),
`src/services/orchestration/jobs/log_context.py` (mới), `src/services/orchestration/jobs/worker_cli.py`,
`src/services/orchestration/jobs/runner.py`, `tests/test_api/test_error_view.py`,
`tests/test_orchestration/test_job_log_context.py` (mới), `tests/test_reconstruction/test_rec03_colmap.py`,
`frontend/tests/pipeline-timeline.test.tsx` (mới).

S1/S2 không sửa `brush_runtime.py`, `frontend/src/features/studio/inspection/StageInspectionPage.tsx`,
`frontend/src/features/studio/scene/ProgressTab.tsx` hoặc `src/services/orchestration/jobs/progress.py`.
S3 được phép sửa `worker_cli.py` và `runner.py` theo phạm vi log context bên dưới.

## Input / output / data contract

- Schema `ExecutionError` không đổi. Thêm ba key tùy chọn trong `details`:
  - `log_excerpt`: danh sách chuỗi, tối đa 40 phần tử, tổng tối đa 4.096 byte.
  - `diagnostics`: object số nguyên, ví dụ `{"no_initial_pair": 3, "insufficient_size": 2}`.
  - `registered_frames`, `input_frames`, `min_registered_ratio`: chỉ với `COLMAP_REGISTRATION_LOW`.
- Mã lỗi mới: `COLMAP_NO_MODEL`, `COLMAP_OUT_OF_MEMORY`. Các mã cũ giữ nguyên tên.
- `human_message` và `details.action` phía backend giữ tiếng Anh như hiện tại. Tiếng Việt
  nằm ở frontend, tra theo `error_code`.
- API: `log_excerpt` chỉ có trong response khi người gọi là reviewer hoặc deployment tắt
  đăng nhập. Mọi vai trò khác nhận `details` không có key đó.

## Logic change và dependent updates

Phân loại lỗi COLMAP theo kết quả:

| Tình huống | Trước | Sau | Thử lại được |
|---|---|---|---|
| Không có model nào sau khi chạy xong | `COLMAP_ARTIFACT_INVALID` | `COLMAP_NO_MODEL` + `diagnostics` | không |
| Model tốt nhất dưới ngưỡng đăng ký | `COLMAP_REGISTRATION_LOW`, không có số | giữ mã, thêm ba con số vào `details` | không |
| Mã thoát -9 hoặc 137, hoặc đoạn trích có `std::bad_alloc` | `COLMAP_PROCESS_FAILED` | `COLMAP_OUT_OF_MEMORY` + `log_excerpt` | có |
| Mã thoát khác 0 còn lại | `COLMAP_PROCESS_FAILED` | giữ mã, thêm `log_excerpt` | không (giữ nguyên) |
| Quá thời gian | `COLMAP_TIMEOUT` | giữ mã, thêm `log_excerpt` | có (giữ nguyên) |

Consumer phải cập nhật cùng lúc: `retryability.py` (thêm một mã), hai nhóm route API
(che `log_excerpt`), `PipelineTimeline.tsx` và bảng `errorGuidance.ts`.

## Dependencies

- S1 độc lập. S2 cần S1 (cần các key `details` mới). S3 độc lập về code nhưng chỉ
  được bắt đầu khi `git status` không còn thay đổi chưa commit ở `runner.py`.
- Không phụ thuộc AUD-26 hay AUD-28.

---

## Sprint AUD-27.S1 — Phân loại lỗi COLMAP và đoạn trích log đã che

**Input:** `colmap_runtime.py`, `colmap.py`, `retryability.py`.
**Output:** hai mã lỗi mới, `details` có số liệu và đoạn trích, một module che log dùng chung.
**Contract:** không chuỗi nào trong `details` chứa đường dẫn tuyệt đối của máy worker.
Tiến trình COLMAP không bị dừng dựa trên nội dung log.

Implement:

1. Tạo `src/services/reconstruction/adapters/log_excerpt.py` với một hàm thuần:
   `redacted_excerpt(text: str, workspace: Path, *, max_lines: int = 40, max_bytes: int = 4096) -> list[str]`.
   Thứ tự xử lý:
   - Thay `str(workspace.resolve())` và `str(workspace)` bằng `<workspace>`.
   - Thay mọi đường dẫn tuyệt đối còn lại (chuỗi bắt đầu bằng `/` và có ít nhất hai
     đoạn, ví dụ `/home/a/b`, `/opt/x/colmap`) bằng `<path>`.
   - Bỏ dòng rỗng, lấy `max_lines` dòng cuối.
   - Nếu tổng vượt `max_bytes` thì bỏ dần dòng ở đầu cho tới khi vừa.
2. Mở rộng `ColmapError.__init__` thành `(code, message, *, details: dict | None = None)`.
   Trong `to_failed_stage`, gộp `details` này vào dict hiện có (giữ `action` và `exception_type`).
3. Sửa `ColmapProcess.run`:
   - Trước khi ghi dòng header của lệnh, ghi nhớ kích thước hiện tại của `process.log`
     (0 nếu chưa có file). File này được mở ở chế độ nối thêm cho nhiều lệnh liên tiếp,
     nên đoạn trích phải bắt đầu từ vị trí đó để chỉ chứa log của lệnh vừa lỗi.
   - Giữ nguyên `subprocess.run`. Không chuyển sang `Popen`, không đọc log khi đang chạy.
   - Khi mã thoát khác 0: đọc log từ vị trí đã nhớ, tạo `log_excerpt`. Nếu mã thoát là
     -9 hoặc 137, hoặc đoạn trích chứa `std::bad_alloc`, ném `COLMAP_OUT_OF_MEMORY`;
     ngược lại ném `COLMAP_PROCESS_FAILED` như cũ. Cả hai kèm `details={"log_excerpt": [...]}`.
   - Khi `TimeoutExpired`: giữ mã `COLMAP_TIMEOUT`, kèm `log_excerpt` theo cùng cách.
   - Khi `OSError` (không khởi động được): giữ nguyên, không kèm đoạn trích.
4. Sửa `ColmapAdapter._execute` trong `colmap.py`, ngay sau `models = self._models(...)`:
   - Nếu `models` rỗng: đọc `process.log`, đếm số lần xuất hiện của hai chuỗi
     `Discarding reconstruction due to no initial pair` và
     `Discarding reconstruction due to insufficient size`, rồi ném
     `ColmapError("COLMAP_NO_MODEL", "COLMAP produced no sparse model", details={"diagnostics": {"no_initial_pair": a, "insufficient_size": b}, "log_excerpt": [...]})`.
   - Tại chỗ ném `COLMAP_REGISTRATION_LOW`: thêm
     `details={"registered_frames": len(best.poses), "input_frames": len(images.frame_ids), "min_registered_ratio": request.config.min_registered_ratio}`.
5. `retryability.py`: thêm `"COLMAP_OUT_OF_MEMORY"` vào `_RETRYABLE_ERROR_CODES`.
   Không thêm `COLMAP_NO_MODEL` (lỗi do dữ liệu đầu vào, chạy lại cho cùng kết quả).

Không làm trong sprint này:

- Không tạo bảng `FATAL_LOG_PATTERNS` cho COLMAP.
- Không thêm các mã `COLMAP_REGISTRATION_FAILED`, `COLMAP_MATCHING_FAILED`,
  `COLMAP_DEGENERATE_TRAJECTORY`.
- Không viết thông báo tiếng Việt ở backend.
- Không sửa `brush_runtime.py`.

Test (thêm vào `tests/test_reconstruction/test_rec03_colmap.py`; theo mẫu
`test_real_process_boundary_errors` ở dòng 250, tức monkeypatch `subprocess.run`):

- `redacted_excerpt`: đường dẫn workspace thành `<workspace>`; đường dẫn khác thành `<path>`;
  không quá 40 dòng; không quá 4.096 byte; văn bản rỗng trả danh sách rỗng.
- Mã thoát 7 → `COLMAP_PROCESS_FAILED`, `details.log_excerpt` chỉ chứa log của lệnh thứ
  hai khi chạy hai lệnh liên tiếp trên cùng workspace.
- Mã thoát -9 và 137 → `COLMAP_OUT_OF_MEMORY`; `classify_retryability` trả đúng.
- Log có `std::bad_alloc` với mã thoát 1 → `COLMAP_OUT_OF_MEMORY`.
- `_models` trả rỗng → `COLMAP_NO_MODEL` với `diagnostics` đếm đúng; `retryable` là sai.
- Dưới ngưỡng đăng ký → `COLMAP_REGISTRATION_LOW` có đủ ba con số.
- Không `details` nào chứa `str(tmp_path)`.

Tests: `tests/test_reconstruction/test_rec03_colmap.py`, `tests/test_reconstruction/test_rec03_guided.py`,
`tests/test_contracts/` (file test của retryability nếu có).

**Exit:**
- [x] Bảy nhóm test trên pass; test COLMAP hiện có không đổi kỳ vọng ngoài hai mã mới.
- [x] Result ghi schema delta của `details` đúng như mục contract.

---

## Sprint AUD-27.S2 — Che `log_excerpt` ở API và hiển thị trên UI

**Input:** kết quả S1; các route trả lỗi của job; `PipelineTimeline.tsx`.
**Output:** người dùng thường không nhận `log_excerpt`; stage lỗi hiện nguyên nhân, cách
khắc phục, khả năng thử lại và phần chi tiết kỹ thuật.
**Contract:** việc che thực hiện ở server. UI không được là nơi duy nhất ẩn dữ liệu.

Backend:

1. Tạo `src/api/studio/error_view.py` với hàm
   `visible_error(error: ExecutionError | None, user: UserRecord | None) -> ExecutionError | None`:
   - `error` là `None` → trả `None`.
   - `user` là `None` → trả nguyên. `_require` trong `src/api/auth.py:59-70` chỉ trả `None`
     khi `auth_required` tắt, tức deployment không có đăng nhập.
   - `has_role(user, "reviewer")` → trả nguyên.
   - Còn lại → trả bản sao có `details` đã bỏ key `log_excerpt`.
2. Áp dụng tại `GET /jobs/{job_id}/progress` (`scenes.py:279`): cho lỗi cấp job và lỗi
   của từng stage trong response. Làm ở route, không sửa `progress.py`.
3. Áp dụng tại hai route trả job trong `src/api/product/projects.py` (dòng 64 và 116) cho
   mọi `stage_artifacts[*].error`.
4. Dùng CodeGraph tìm mọi `response_model` có chứa `ExecutionError`, `StageArtifact` hoặc
   `JobManifest`. Route nào tìm thấy thêm thì áp dụng cùng hàm và liệt kê trong Result.

Frontend:

5. Tạo `frontend/src/features/studio/errorGuidance.ts`: một bảng `error_code → { cause, fix }`
   và hàm `guidanceFor(error)`. Mã không có trong bảng thì trả `null`. Nội dung tối thiểu:

   | `error_code` | `cause` | `fix` |
   |---|---|---|
   | `COLMAP_NO_MODEL` | Không dựng được vị trí camera từ video này. | Nếu `diagnostics.no_initial_pair` > 0: "Các khung hình liên tiếp không có đủ điểm chung. Quay chậm hơn, giữ vật thể trong khung và tránh bề mặt trơn một màu." Ngược lại: "Cảnh bị tách thành nhiều đoạn rời. Quay một vòng liền mạch, không cắt ngang." |
   | `COLMAP_REGISTRATION_LOW` | Chỉ dựng được vị trí cho `registered_frames`/`input_frames` ảnh, dưới ngưỡng `min_registered_ratio`. | Quay chậm hơn và để các khung hình liên tiếp chồng lấn nhiều hơn. |
   | `COLMAP_OUT_OF_MEMORY` | Máy xử lý hết RAM khi dựng vị trí camera. | Giảm "Số khung hình tối đa" hoặc "Số điểm đặc trưng mỗi ảnh" rồi chạy lại. |
   | `COLMAP_TIMEOUT` | Bước dựng vị trí camera chạy quá thời gian cho phép. | Giảm "Số khung hình tối đa" hoặc thử lại khi máy xử lý rảnh. |
   | `VISUAL_OUT_OF_MEMORY` | GPU hết bộ nhớ khi dựng 3DGS. | Giảm "Số Gaussian tối đa" hoặc "Độ phân giải huấn luyện" rồi chạy lại. |
   | `VISUAL_GPU_DEADLOCK` | Driver GPU ngừng phản hồi khi dựng 3DGS. | Thử lại. Nếu lặp lại, báo quản trị viên kiểm tra driver GPU. |
   | `VISUAL_HANG_TIMEOUT` | Bước dựng 3DGS không có tiến triển trong thời gian dài. | Thử lại. Job tiếp tục từ checkpoint đã lưu. |
   | `VISUAL_TIMEOUT` | Bước dựng 3DGS chạy quá thời gian cho phép. | Giảm "Số bước huấn luyện 3DGS" hoặc thử lại. |

   Tên thông số trong ngoặc kép là `label` hiện có trong
   `configs/product/processing_presets_v1.json`; giữ đúng từng chữ để người dùng tìm thấy ô đó.
6. `PipelineTimeline.tsx`:
   - Đổi kiểu `StageView.error` thành `ExecutionError` từ `@/lib/contracts/api` (đã có
     `retryable` và `details`). Kiểm `parseJobProgress` trong `frontend/src/lib/api/studio.ts`
     có giữ `details` và `retryable` không; nếu nó bỏ thì sửa parser để giữ.
   - Thay khối lỗi ở dòng 175-179 bằng khối mới, hiển thị ngay khi stage `failed`, không
     cần bấm:
     - Dòng nguyên nhân: `guidance.cause`, hoặc `human_message` khi không có guidance.
     - Dòng cách khắc phục: `guidance.fix` (bỏ dòng này khi không có guidance).
     - Nhãn: "Có thể thử lại" khi `retryable` đúng, ngược lại "Cần sửa đầu vào trước khi chạy lại".
     - Mã lỗi dạng chữ đơn cách như hiện tại.
     - Phần tử `<details>` với `<summary>` "Chi tiết kỹ thuật", chỉ render khi
       `details.log_excerpt` là mảng không rỗng; bên trong là `<pre>` chứa các dòng.
   - Không sửa điều kiện bấm vào tên stage ở dòng 125 và khối `succeeded` ở dòng 181.
     Phần tử `<details>` gốc của trình duyệt đã đủ để mở chi tiết.

Không làm trong sprint này: không thêm endpoint log, không thêm drawer/modal, không sửa
`StageInspectionPage.tsx` và `ProgressTab.tsx`, không dịch `details.action` ở backend.

Test:

- Backend (`tests/test_api/test_studio_routes.py` hoặc file test route progress hiện có):
  guest và editor không nhận `log_excerpt`; reviewer nhận; `auth_required` tắt thì nhận;
  các key khác của `details` còn nguyên.
- Frontend (`frontend/tests/pipeline-timeline.test.tsx`, mới): mã có guidance hiện `cause`
  và `fix`; mã lạ hiện `human_message`; nhãn thử lại đúng theo `retryable`; có `log_excerpt`
  thì có "Chi tiết kỹ thuật", không có thì không render; `COLMAP_NO_MODEL` chọn đúng một
  trong hai câu theo `diagnostics`.

**Exit:**
- [x] Test backend bốn vai trò pass; danh sách route đã áp dụng ghi trong Result.
- [x] Test frontend pass; `npm run lint`, `npm run typecheck`, `npm run build -- --webpack` pass.
- [ ] Kiểm bằng mắt trên Studio do owner thực hiện; agent không tự xác nhận phần này.

---

## Sprint AUD-27.S3 — `job_id` và `attempt_id` trong log worker

**Pre-flight bắt buộc:** chạy `git status --short src/services/orchestration/jobs/runner.py`.
Nếu file còn thay đổi chưa commit thì dừng và báo owner; không bắt đầu sprint.

**Input:** `src/services/orchestration/jobs/worker_cli.py`, `runner.py`.
**Output:** mọi dòng log của worker khi đang xử lý một job có `job_id` và `attempt_id`.
**Contract:** không đổi nội dung thông điệp log hiện có; dòng log ngoài phạm vi job không
có hai giá trị này và không lỗi định dạng.

Implement:

1. Tạo `src/services/orchestration/jobs/log_context.py`: hai `contextvars.ContextVar`
   (`job_id`, `attempt_id`, mặc định `"-"`), một `logging.Filter` gán hai giá trị vào
   record, và một context manager `job_log_context(job_id, attempt_id)`.
2. Tại `logging.basicConfig` của `worker_cli.py:306` và `runner.py:1062`: thêm filter và
   đặt format `%(asctime)s %(levelname)s job=%(job_id)s attempt=%(attempt_id)s %(name)s: %(message)s`.
3. Bọc đoạn xử lý một attempt trong `runner.py` (`_start_attempt` hoặc nơi tương đương)
   bằng `job_log_context`.

Test: `tests/test_orchestration/` thêm một test: trong context, record có đúng hai giá
trị; ngoài context là `"-"`; hai luồng với hai context khác nhau không lẫn giá trị.

**Exit:**
- [x] Test context pass; formatter smoke tạo được dòng log có đủ hai ID và dòng idle dùng `-`.
- [ ] Cần thêm log từ một attempt worker thật; formatter smoke bên dưới không được xem là bằng chứng chạy pipeline.

## Verification và DoD

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/pytest tests/test_reconstruction/test_rec03_colmap.py tests/test_reconstruction/test_rec03_guided.py tests/test_api/test_studio_routes.py -q
cd frontend && npm run lint && npm run typecheck && npm test -- tests/pipeline-timeline.test.tsx && npm run build -- --webpack
```

Phân loại evidence: test S1 là unit với subprocess giả; test route là local integration;
frontend là unit (Vitest). Chưa có log COLMAP thất bại thật, nên nhánh `std::bad_alloc`
là UNVERIFIED trên runtime thật cho tới khi có một lượt lỗi thật; ghi rõ trong Result.

DONE khi S1 và S2 tick đủ Exit. S3 có thể hoàn tất sau.

## Result / Evidence
 
- **AUD-27.S1 (Hoàn thành):**
  - Files created/modified:
    - `src/services/reconstruction/adapters/log_excerpt.py`: Hàm `redacted_excerpt(text, workspace, max_lines=40, max_bytes=4096)`.
    - `src/services/reconstruction/adapters/colmap_runtime.py`: `ColmapError` nhận `details`, `ColmapProcess.run` ghi nhớ offset và phân loại exit code `-9`/`137`/`std::bad_alloc` thành `COLMAP_OUT_OF_MEMORY`.
    - `src/services/reconstruction/adapters/colmap.py`: Thêm kiểm tra `if not models` ném `COLMAP_NO_MODEL` kèm `diagnostics`, thêm `registered_frames`, `input_frames`, `min_registered_ratio` vào `COLMAP_REGISTRATION_LOW`.
    - `src/models/contracts/retryability.py`: Thêm `COLMAP_OUT_OF_MEMORY` vào `_RETRYABLE_ERROR_CODES`.
    - `tests/test_reconstruction/test_rec03_colmap.py`: Bổ sung 4 unit test kiểm tra redact path, sequential log slice, OOM, no model và registration low.
  - Verification: `.venv/bin/pytest tests/test_reconstruction/test_rec03_colmap.py tests/test_reconstruction/test_rec03_guided.py -v` (42/42 passed).
  - Schema delta of `ExecutionError.details`:
    - `details["log_excerpt"]`: `list[str]` (tối đa 40 dòng, tối đa 4.096 byte, đường dẫn đã che `<workspace>` và `<path>`).
    - `details["diagnostics"]`: `dict[str, int]` (`no_initial_pair`, `insufficient_size` cho `COLMAP_NO_MODEL`).
    - `details["registered_frames"]`, `details["input_frames"]`, `details["min_registered_ratio"]`: `int`, `int`, `float` (cho `COLMAP_REGISTRATION_LOW`).

- **AUD-27.S2 (Implementation hoàn thành; owner visual signoff còn mở):**
  - Files created/modified:
    - `src/api/studio/error_view.py`: `visible_error`, `filter_stage_artifact_errors`, `filter_manifest_errors`, `filter_stage_progress_errors`, `filter_job_progress_errors`, `filter_job_attempt_errors`.
    - `src/api/studio/scenes.py`: Lọc tại `GET /jobs/{job_id}/progress`, `GET /scenes` và nested job trong `POST /scenes/from-upload`.
    - `src/api/studio/assemblies.py`: Lọc nested job trong `POST /input-assemblies/{assembly_id}/run`.
    - `src/api/product/projects.py`: Lọc tại `POST /projects/{project_id}/jobs` và `GET /projects/{project_id}/jobs`.
    - `src/api/product/jobs.py`: Lọc tại `GET /jobs/{job_id}`, `POST /jobs/{job_id}/transitions`, `POST /jobs/{job_id}/retry`, `GET /jobs/{job_id}/attempts`.
    - `frontend/src/features/studio/errorGuidance.ts`: Bảng tra cứu và hàm `guidanceFor(error)` theo đúng nhãn của presets.
    - `frontend/src/features/studio/PipelineTimeline.tsx`: Khối lỗi hiển thị cause, fix, nhãn thử lại và collapsible `<details>` cho `details.log_excerpt`.
    - `frontend/src/lib/contracts/studio.ts`: Mở rộng `ExecutionErrorView.details`.
    - `tests/test_api/test_error_view.py`: Unit test 4 vai trò và integration test route progress/jobs/attempts.
    - `frontend/tests/pipeline-timeline.test.tsx`: Vitest tests kiểm tra cause/fix/retryable/log_excerpt collapsible.
  - Danh sách route áp dụng `visible_error`:
    - `GET /jobs/{job_id}/progress`
    - `GET /scenes`
    - `POST /projects/{project_id}/jobs`
    - `GET /projects/{project_id}/jobs`
    - `GET /jobs/{job_id}`
    - `POST /jobs/{job_id}/transitions`
    - `POST /jobs/{job_id}/retry`
    - `GET /jobs/{job_id}/attempts`
  - Verification:
    - `.venv/bin/pytest tests/test_api/test_error_view.py -q`: 3 passed.
    - `.venv/bin/pytest tests/test_api/test_error_view.py tests/test_api/test_guest_ownership.py -q`: 38 passed.
    - `cd frontend && npm run lint && npm run typecheck && npm test -- tests/pipeline-timeline.test.tsx && npm run build -- --webpack`: 0 lint errors, 0 typecheck errors, 7/7 vitest passed, next webpack build 17/17 pages succeeded.
    - Chrome DevTools: job lỗi thật `job-d1296a4dc969` hiển thị fallback message, error code và nhãn retry; console chỉ có thông báo React DevTools/HMR; progress request trả `200`.
    - Chưa có job nào chứa stage/báo cáo LiDAR calibration QA trong 10 scene hiện có. Checkbox owner visual signoff ở Exit vẫn để mở; snapshot do agent thu không thay cho signoff này.

- **AUD-27.S3 (Implementation xong; runtime acceptance còn mở):**
  - Files created/modified:
    - `src/services/orchestration/jobs/log_context.py`: Hai `ContextVar` mặc định `-`, `JobLogContextFilter`, `job_log_context()` có reset token và `configure_worker_logging()` idempotent trên root handlers.
    - `src/services/orchestration/jobs/runner.py`: Bọc prepared, upload-video và finalize attempts trong context; `attempt_id` là số `JobAttemptRecord.attempt` dạng chuỗi.
    - `src/services/orchestration/jobs/worker_cli.py`: Áp dụng cùng format/filter và giữ context quanh dispatch/error handling của từng job.
    - `tests/test_orchestration/test_job_log_context.py`: Kiểm tra mặc định, nested restore, thread isolation và dòng log đã format.
  - Verification:
    - `.venv/bin/pytest tests/test_orchestration/test_job_log_context.py tests/test_orchestration/test_worker_cleanup.py tests/test_orchestration/test_resource_telemetry.py tests/test_orchestration/test_job_progress.py tests/test_orchestration/test_observed_budget.py tests/test_orchestration/test_prepared_queue.py tests/test_orchestration/test_resource_admission.py tests/test_orchestration/test_finalize_flow.py tests/integration/test_upload_to_prepared_job.py -q -k 'not test_import_profile_scales_with_gaussian_count_and_marks_heuristic'`: 142 passed, 1 deselected.
    - Toàn bộ lệnh trên không lọc có 142 passed và một failure ở assertion cấu hình resource: test đòi `vram_base_gb=0.8`, `ram_base_gb=1.5`, trong khi file preset đang sửa trong worktree dùng số đo mới `1.25`/`0.9`. Không sửa hoặc stage cấu hình này.
    - `.venv/bin/ruff check src/ tests/`: pass; `.venv/bin/ruff format --check src/ tests/`: 533 files formatted.
    - Formatter smoke qua `configure_worker_logging()` và `job_log_context()` đã phát ra:

      ```text
      2026-10-09 00:27:18,000 INFO job=job-42 attempt=3 real2sim.worker: stage completed
      ```

    - Chưa dispatch attempt pipeline thật; dòng trên kiểm tra formatter/filter bằng context tổng hợp, không phải runtime worker evidence. Không có LiDAR QA stage trong dữ liệu browser hiện tại để kiểm tra màn hình QA mới.
