# T-040: Bỏ bước chép runtime manifest bằng tay giữa GPU worker và API

## Goal
Đổi pod, thuê GPU khác loại hay bật thêm worker **không cần đụng vào API**. Worker tự công bố runtime manifest của mình;
API gắn job vào runtime của worker đang sống. Job đang dở không bị kẹt vĩnh viễn khi pod cũ đã trả.

## Context (cơ chế hiện tại, đã đọc code)
- Runtime manifest (`scripts/gpu/make_runtime_manifest.py`) ghi phiên bản thật của công cụ, model GPU, driver; checksum
  canonical của nó là identity runtime.
- **API** đọc `PRODUCT_RUNTIME_MANIFEST` + `PRODUCT_PROCESSING_CONFIG` thành `ExecutionProfile`
  (`src/services/orchestration/jobs/profile.py`; dựng ở `get_project_registry`, `registry.py:1920`). Mỗi job mới mang
  `runtime_manifest_checksum` của profile đó (`_build_queued_job`, `registry.py:1696–1719`). Thiếu profile thì API từ
  chối tạo scene (`registry.py:1702`, `api/studio/scenes.py:185`, `api/studio/assemblies.py:440`). Settings bắt hai biến
  phải cùng có hoặc cùng thiếu (`src/config.py:186`).
- **Worker** chỉ nhận job có checksum trùng profile của nó (`require_profile`, `jobs/dispatch.py:73–83`;
  `worker_cli.py:270`). Đường chạy tiếp (finalize sau khi xác nhận tỉ lệ, preview sau khi duyệt bản che) kiểm ở
  `runner.py:1563`.
- Worker đã có nhịp ghi cấu hình máy vào DB mỗi 300 s (`_start_capability_heartbeat`, `worker_cli.py:299–331`,
  `record_capability`).
- Hệ quả hiện tại: đổi pod sang GPU/driver khác → checksum khác → mọi job mới và job đang chờ chạy tiếp bị worker từ
  chối im lặng, cho tới khi người vận hành chép manifest mới lên API và khởi động lại API (`deploy/studio/OVERVIEW.md`
  bước 4 và mục "Những chỗ dễ vấp").

## Phần A: khảo sát và thiết kế (làm trước, **dừng chờ Architect duyệt**)
Viết `.ai/tasks/T-040/design.md` trả lời bằng code đã đọc (file:dòng), không đoán:
1. Ngoài `JobManifest.runtime_manifest_checksum`, runtime identity còn được ghi ở đâu (artifact từng stage, attempt,
   evidence, benchmark snapshot `pipeline_runtime`, release seal, validation)? Cái nào được kiểm lại về sau và sẽ vỡ nếu
   một job có các stage chạy trên hai runtime khác nhau?
2. Một job đang ở từng trạng thái sau thì hiện nay đi đường nào khi worker có checksum khác: QUEUED chưa có stage nào;
   QUEUED do retry sau lỗi preview; RUNNING chờ xác nhận tỉ lệ rồi finalize; chờ duyệt bản che; yêu cầu tách vật/Tạo mesh
   (`objectify_queue`, có kiểm runtime không?); import scene; validation Isaac.
3. Đề xuất bảng DB (migration 22) và luồng như phác thảo dưới, sửa lại cho khớp với câu trả lời 1–2.

Phác thảo của Architect (engineer kiểm và đề xuất chỉnh):
- Bảng `r2s_worker_runtimes(runtime_manifest_checksum PK, manifest JSON, config_checksum, seed, gpu_name, first_seen_at,
  last_seen_at)`. Worker upsert lúc khởi động và trong mỗi nhịp heartbeat. Manifest phải qua kiểm canonical checksum như
  `ExecutionProfile.load`.
- API: nếu có `PRODUCT_RUNTIME_MANIFEST` thì giữ hành vi cũ (ghim tay, cho máy dev và cho ai muốn khoá). Nếu không có
  và bật `PRODUCT_RUNTIME_FROM_WORKERS=true`: job mới gắn vào runtime có `last_seen_at` mới nhất trong TTL (15 phút) và
  `config_checksum` trùng file config của API. Không có worker sống: vẫn tạo job, gắn runtime thấy gần nhất, UI báo
  "đang chờ GPU" (không từ chối).
- **Gắn lại runtime** (rebind) chỉ cho job **chưa có stage artifact nào** (QUEUED lần đầu): khi runtime của job không có
  worker sống quá TTL mà có runtime khác đang sống, API hoặc worker gắn lại, ghi job event `runtime_rebound {from, to,
  reason}`. Job đã có stage chạy trên runtime cũ thì **không tự gắn lại**; cách xử lý do design.md đề xuất dựa trên câu 1
  (ví dụ: nút "Chạy tiếp trên GPU hiện có" cho Reviewer, ghi rõ provenance hai runtime; hoặc chạy lại từ đầu).
- `scripts/cloud/gpu_autoscaler.py` và UI tiến trình: hiện "đang chờ GPU (runtime …)" thay vì im lặng.

## Phần B: làm theo design.md đã duyệt
Architect đã duyệt `design.md` (khảo sát đúng, file:dòng kiểm được). Quyết định và các bước ở mục **Phần B (đã duyệt)** cuối file.

## Acceptance criteria (cho cả task)
1. Deploy production không còn bước chép manifest tay; `OVERVIEW.md` bỏ bước 4.
2. Đổi pod sang GPU khác loại: job mới chạy được ngay, không khởi động lại API.
3. Job đang dở khi đổi pod có đường xử lý rõ ràng, có ghi provenance thật, không kẹt im lặng.
4. Máy dev ghim `PRODUCT_RUNTIME_MANIFEST` chạy như cũ.
5. Test cho: upsert manifest, chọn runtime cho job mới, rebind job chưa chạy, từ chối rebind job đã có stage, TTL.

## Tests required
Phần A: không có. Phần B: ghi trong phần bổ sung.

## Commit
Phần A: một commit `design.md`, đặt status `changes-requested` kèm ghi chú "cần Architect duyệt design". Không
Co-Authored-By.
Phần B cần **T-036 accepted** (tên biến ổn định). Không cần T-038, T-039.


## Phần B (đã duyệt, 2026-10-16)

### Quyết định của Architect (trả lời mục 4 của design.md)

**Q3 — Đơn vị identity: tách phần mềm khỏi phần cứng.** Production chạy RunPod Serverless, mỗi lượt có thể rơi vào loại GPU
khác; nếu checksum gồm `gpu_model`/`vram`/`nvidia_driver` (`make_runtime_manifest.py`) thì job gần như luôn lệch worker.
- **Runtime phần mềm** = checksum canonical của `RuntimeManifest` sau khi **bỏ** ba component `gpu_model`, `vram`,
  `nvidia_driver`. Đây là khoá ghép job ↔ worker. Mọi worker cùng image cùng một runtime phần mềm.
- **Phần cứng** chỉ để ghi nhận: manifest đầy đủ lưu trong `r2s_worker_runtimes`; mỗi lượt đo đã có `gpu_name`
  (`ResourceUsage`). Budget/benchmark lọc theo `gpu_name` như hiện tại.
- Job mới (cả chế độ ghim tay lẫn chế độ worker) lưu runtime phần mềm vào `JobManifest.runtime_manifest_checksum`. Viết hàm
  `software_runtime_checksum(manifest)` ở một chỗ (cạnh `ExecutionProfile`), `ExecutionProfile` giữ cả hai giá trị.
- **Tương thích job cũ:** worker nhận job nếu checksum của job bằng runtime phần mềm **hoặc** bằng checksum manifest đầy đủ của
  nó (job tạo trước task). Test cho cả hai.
- Bảng `r2s_worker_runtimes` khoá theo **runtime phần mềm**, có thêm cột `hardware` (JSON gpu/vram/driver gần nhất) và
  `worker_count_live` không cần — đếm từ `last_seen_at`.

**Q1 — Job đã có stage: (a) không rebind tự động.** Với identity phần mềm, lệch chỉ xảy ra khi **đổi phiên bản image**.
- Job chưa có stage (QUEUED, `stage_artifacts == []`): rebind tự động như design 3.4, ghi event `runtime_rebound`.
- Job đã có stage: chờ, UI hiện lý do mới `waiting_for = "runtime"` với câu "Phiên bản công cụ đã đổi; job này cần chạy lại
  từ đầu". Nếu repo đã có đường tạo lượt chạy mới cho cùng project (tìm trong API scene/project), thêm nút "Chạy lại từ đầu"
  cho người có quyền sửa job, job cũ giữ làm lịch sử. Không có đường sẵn thì chỉ hiện lý do, ghi vào report, Architect lập
  task riêng. Không làm (b) "chạy tiếp trên runtime khác".

**Q2 — RUNNING mồ côi: phương án A (lease theo job, có fencing).** Serverless sẽ giết worker ở `executionTimeout`; job RUNNING
mất workspace là chuyện thường.
- Khi claim attempt: ghi `lease_token`, `lease_expires_at` (TTL 10 phút) vào bảng lease mới hoặc cột của bảng job hiện có (chọn
  cách ít đụng contract, ghi lý do). Worker gia hạn mỗi 60 giây trong suốt attempt (luồng nền như heartbeat hiện có).
- Lease hết hạn → chuyển FAILED `retryable=True` qua đúng đường `recover_interrupted_jobs` đang dùng (`worker_cli.py:182-188`),
  chạy ở mọi worker (không chỉ worker có workspace).
- **Fencing:** trước mỗi lần publish stage/transition, worker kiểm token còn của mình (CAS); mất lease thì dừng tiến trình con
  và không ghi. Trainer "còn sống trên host khác" (`worker_cli.py:3-4`) vì vậy không ghi đè được.
- Giữ `recover_interrupted_jobs` theo workspace cho máy local (nó vẫn đúng), lease là lớp thêm.

**Q4 — Finalize và tách vật khi không khớp.**
- **Finalize:** bỏ qua và chờ, giống claim thường (thêm kiểm runtime ở `worker_cli.py:247-260`), có `waiting_for = "runtime"`.
- **Tách vật/Tạo mesh (`objectify_queue`):** là thao tác sửa scene **sau** job, không phải stage của pipeline. **Không bắt
  khớp runtime**; sửa provenance: ghi **runtime phần mềm và GPU thật của máy đang chạy** vào `ResourceUsage` (thay
  `objectify_queue.py:748`), không ghi runtime của job. Tương tự `runner.py:319` ghi runtime thật của worker.

**Q5 — Phụ thuộc:** Phần B bắt đầu khi **T-036 accepted**; không cần T-038.

**Q6 — Autoscaler:** chỉ đếm việc mà worker hiện hành chạy được: job QUEUED/finalize có runtime phần mềm trùng runtime sống
mới nhất (hoặc rebind được), và mọi yêu cầu tách vật. Job chờ "Chạy lại từ đầu" không đếm. Đường dẫn thật:
`scripts/cloud/gpu_autoscaler.py:130-135`.

**Q7 — Migration:** dùng số kế tiếp `LATEST_SCHEMA_VERSION` lúc bắt đầu code (hiện 21 → 22); kiểm lại ngay trước khi commit,
vì agent khác có thể thêm migration.

### Steps Phần B
1. `software_runtime_checksum` + `ExecutionProfile` giữ cả hai checksum + nhận job cũ theo checksum đầy đủ. Test. Commit.
2. Migration `r2s_worker_runtimes` + worker upsert lúc khởi động và mỗi nhịp heartbeat (chỉ khi `config_checksum` khớp file
   config của worker). Test SQLite + tham số PostgreSQL theo fixture `runtime_database_url`. Commit.
3. API chế độ `PRODUCT_RUNTIME_FROM_WORKERS=true`: chọn runtime khi tạo job (`registry.py:1700-1719`), ba chỗ từ chối
   (`scenes.py:185-188`, `assemblies.py:440-442`, `deps.py:117-131`) đổi sang "có runtime đã biết"; không có worker sống vẫn
   tạo job. `config.py` cho phép thiếu `PRODUCT_RUNTIME_MANIFEST` khi bật chế độ này. Test. Commit.
4. `waiting_for = "runtime"` (backend `progress.py`, contract frontend `studio.ts`, câu hiển thị). Test hai phía. Commit.
5. Kiểm runtime ở nhánh finalize; rebind tự động job chưa có stage (đường riêng, CAS, event). Test: rebind đúng điều kiện; từ
   chối khi đã có stage; không rebind khi runtime cũ còn sống. Commit.
6. Lease + fencing cho attempt job (Q2). Test: lease hết hạn → FAILED retryable ở worker khác; worker mất lease không ghi
   được; gia hạn giữ job sống. Commit.
7. Provenance tách vật và attempt ghi runtime/GPU thật (Q4). Test budget/benchmark vẫn lọc đúng. Commit.
8. Autoscaler đếm theo Q6. Test với DB giả. Commit.
9. `deploy/studio/OVERVIEW.md`: bỏ bước 4 chép manifest, mô tả chế độ worker. Commit.

### Tests required Phần B
```
.venv/bin/python -m pytest tests/test_orchestration tests/test_api tests/test_gpu -q
R2S_TEST_POSTGRES_URL=<nếu có> .venv/bin/python -m pytest tests/test_orchestration -q -k postgres
cd frontend && ./node_modules/.bin/vitest run <test tiến trình đã sửa> && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```
Sau bước 9 chạy full backend một lần (task chạm worker, API, migration), ghi số thật.
