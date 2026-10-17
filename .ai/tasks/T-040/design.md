# T-040 — Design (Phần A: khảo sát code)

Trạng thái khi viết: T-040 `planned`; T-038 vẫn `planned` (plan ghi "Cần T-038 accepted", xem mục 4.5).
Mọi khẳng định dưới đây kiểm được bằng file:dòng trong commit hiện tại. Không sửa code ở phần này.

## Tóm tắt

- Runtime identity hiện nằm ở **một trường chính**: `JobManifest.runtime_manifest_checksum`
  (`src/models/contracts/manifests.py:262`). Mọi nơi khác hoặc **sao chép** trường đó (usage, benchmark, sample export,
  budget), hoặc **kiểm chéo** với manifest của chính artifact (validation). Không có stage artifact nào mang runtime
  (`manifests.py:196-207`, `artifacts.py:66`).
- Việc chạy job bị kiểm runtime ở **hai chỗ** (claim thường và preview sau duyệt bản che). Hai đường **không** kiểm:
  **finalize** (`worker_cli.py:247-260`, `runner.py:1642-1665`) và **tách vật/Tạo mesh** (`objectify_queue.py:769-…`).
  Import và đăng ký cũng không kiểm.
- Job RUNNING của pod đã trả **kẹt vĩnh viễn**: `recover_interrupted_jobs` chỉ nhìn workspace trên máy của chính worker
  (`worker_cli.py:162-164`, `jobs/workspace.py:206-212`), nên pod mới bỏ qua job đó và không ai chuyển nó sang FAILED.
- Đề xuất cần Architect chọn ba điểm (mục 4): rebind job đã có stage, cơ chế thay recover-theo-workspace, và đơn vị identity
  (VRAM có nằm trong checksum hay không).

---

## 1. Runtime identity được ghi và kiểm lại ở đâu

Cột "kiểm lại sau" = có code đọc lại identity sau khi job đã claim. Cột "vỡ nếu hai runtime" = nếu một job có stage
chạy trên hai runtime, nơi đó sai hay lặng lẽ mất dữ liệu.

| # | Nơi | Ghi/kiểm | Kiểm lại sau? | Vỡ khi job có stage trên hai runtime? |
|---|---|---|---|---|
| 1 | `JobManifest.runtime_manifest_checksum` (`manifests.py:262`) | Ghi khi tạo job từ profile (`registry.py:1700-1719`) | Được đọc ở mọi chỗ bên dưới | Là nguồn sự thật; mọi bản ghi phụ tham chiếu nó |
| 2 | Claim thường: `require_profile` (`jobs/dispatch.py:74-83`, gọi tại `worker_cli.py:270`) và `_start_attempt` (`runner.py:411-413`) | So checksum job với profile worker, chỉ khi QUEUED | Chỉ tại thời điểm claim | Không. Lần claim sau luôn đối chiếu với worker mới |
| 3 | Preview sau duyệt bản che: `run_reviewed_preview_job` (`runner.py:1563-1564`) | So checksum job với profile worker | Chỉ tại claim | Không; ném `RuntimeStateConflictError`, dispatch bỏ qua (`worker_cli.py:286-287`) |
| 4 | Finalize: `run_finalize_job` (`runner.py:1642-1665`) và nhánh dispatch (`worker_cli.py:247-260`) | **Không đọc runtime** | Không | **Vỡ im lặng**: finalize chạy bằng cấu hình hình học của worker đang nhận (`runner.py:1659-1661`) |
| 5 | Tách vật/Tạo mesh: `objectify_queue.process_next` (`objectify_queue.py:769`, claim tại `:774`) | **Không đọc runtime của job**; chỉ dùng cho `ResourceContext` (`:748`) và `config_checksum` lúc yêu cầu (`:258`) | Không | **Vỡ im lặng**: chạy trên máy khác, nhưng bản ghi đo ghi runtime của job (`:748`) nên provenance sai |
| 6 | Usage (đo máy) `ResourceUsage.runtime_manifest_checksum` (`processing/telemetry.py:45`) | Ghi lúc đo, từ `attempt.job` (`runner.py:319`) và `objectify_queue.py:748` | Có, bởi budget và benchmark | Các lượt chạy trên runtime khác bị lọc **im lặng** khỏi budget (`observed.py:143`, `observed.py:189`) và khỏi thời gian công cụ (`benchmark.py:286`) |
| 7 | Benchmark snapshot `pipeline_runtime` (`benchmark.py:99`, ghi tại `:442`, lọc tại `:266-289`, `:370`) | Ghi checksum của job | Có, khi tổng hợp thời gian | Như dòng 6: thời gian của lượt khác runtime bị loại, không báo |
| 8 | Budget tài nguyên (`observed.py:127-143`, `:174-189`; dùng ở `jobs/admission.py:354-365`, `api/studio/deps.py:117-131`) | Lọc usage theo checksum và `gpu_name` | Có, khi nhận job | Không có số đo cho runtime mới → rơi về ước lượng (`admission.py:366-367`), không lỗi |
| 9 | Mẫu thư viện (`samples/export.py:291-298`) | Chép checksum của job vào provenance | Không | Bản mẫu xuất từ job đã rebind sẽ mang runtime cuối cùng, không mang lịch sử |
| 10 | Validation Isaac: `IsaacValidationRuntimeProfile.runtime_manifest_ref` (`validation_run.py:84-85`, `:129`); kiểm `validation_runs.py:340-352`, `:395-396`; worker `validation_worker.py:280-281`, `:303-307`, `:337-338`; `validation_gate.py:95-102` | Kiểm checksum manifest **của artifact** và phiên bản Isaac **quan sát được sau khi chạy** (`validation_worker.py:337-338`, `isaac/process.py:404-405`) | Có | **Không vỡ** do mixed runtime của job: profile gắn với config validation, không với checksum của job. Phát hiện sai lệch máy bằng quan sát sau chạy |
| 11 | Isaac tiền kiểm: `isaac/process.py:229-237` | Đọc manifest qua `profile.runtime_manifest_ref`, không đọc máy đang chạy | Không | Kiểm tính nhất quán của artifact, không kiểm máy thực. Ghi nhận rủi ro, không chặn T-040 |
| 12 | Release seal (`review/release_seals.py:37-50`) | Băm candidate, validation report, approval, release manifest; **không có runtime** | Không | Gián tiếp qua validation report (dòng 10). Không cần đổi |
| 13 | Capability LiDAR (`reconstruction.py:182-191`, `:283-297`; đối chiếu `projects/registry.py:1532-1575`, `persistence.py:455-466`) | Evidence registry R5/R6, khác với manifest | Có | Không liên quan checksum manifest; đổi registry là việc riêng |
| 14 | Stage artifact `StageArtifact` (`manifests.py:196-207`) và `ProductArtifactRef` (`artifacts.py:66`) | **Không có trường runtime** | — | Truy vết runtime của một stage chỉ qua lịch sử revision của job (bảng `r2s_job_events`, đọc event mới nhất tại `jobs/queue.py:145-149`) và `JobAttemptRecord.job_manifest_checksum` (`jobs/models.py:31`) |
| 15 | Cấu hình ghim của API: `ExecutionProfile.load` (`jobs/profile.py:22-29`), `get_project_registry` dựng một lần (`projects/registry.py:1920-1936`, `lru_cache`) | Băm canonical manifest và kiểm bằng checksum | Lúc khởi động | API đọc profile tĩnh; đổi manifest cần khởi động lại API (đúng như `deploy/studio/OVERVIEW.md:64-65`, `:73-75`) |

**Kết luận câu 1.** Runtime identity được *sao chép* vào nhiều bản ghi (1, 6, 7, 8, 9) và *kiểm chéo* ở validation
(10–12). Không có chỗ nào kiểm **job có stage trên hai runtime** và báo lỗi. Mixed runtime hôm nay **không bị phát hiện**;
chỉ có hai hậu quả im lặng: thiếu số đo (8) và thiếu thời gian công cụ (7). Nếu T-040 cho rebind, hai hậu quả này và
provenance sai (5) phải được xử lý cùng lúc.

---

## 2. Job đi đường nào khi worker có checksum khác

Quy ước: "Bỏ qua" = `dispatch_next` gặp `RuntimeStateConflictError` và chuyển sang job khác (`worker_cli.py:286-287`);
job không đổi trạng thái, không có event, không báo UI. Không có dòng nào trong bảng dưới ghi lỗi cho người dùng.

| Trạng thái hiện tại | Đường xử lý (file:dòng) | Worker khác checksum | Hệ quả |
|---|---|---|---|
| **QUEUED, chưa có stage** (lần đầu, hoặc video cần `prepare`) | `dispatch_next` → `_dispatch` → `require_profile` (`worker_cli.py:270`, `dispatch.py:80-83`) → `video_runner` → `_start_attempt` (`runner.py:413`) | Bỏ qua tại `:270` | Job QUEUED mãi cho tới khi có worker khớp. UI không thấy lý do (`progress.py:298-302` không có giá trị "runtime") |
| **QUEUED, retry sau lỗi PREVIEW** (có frame set) | `prepared_frame_reference` (`dispatch.py:36`) → `require_profile` (`worker_cli.py:270`) → `runner` → `_start_attempt` (`runner.py:413`) | Bỏ qua tại `:270` | Như trên. Đây là đường được kiểm đầy đủ |
| **QUEUED, chờ chấp nhận bản che** (`awaiting_anonymization_review`, `progress.py:140-149`) | `worker_cli.py:261-262` → `continue` | Không chạy (không liên quan runtime) | Chờ người dùng |
| **RUNNING, bản che đã chấp nhận, chờ dựng preview** (`awaiting_reviewed_preview`, `progress.py:152-159`) | `worker_cli.py:263-269` → `run_reviewed_preview_job` → kiểm `runner.py:1563-1564` | Ném `RuntimeStateConflictError` → bỏ qua (`worker_cli.py:286-287`) | Chờ worker khớp. Được bảo vệ, nhưng im lặng |
| **RUNNING/QUEUED, chờ xác nhận tỉ lệ rồi finalize** (`awaiting_finalize`, `progress.py:332-343`) | `worker_cli.py:247-260` → `finalize_runner` = `run_finalize_job` (`runner.py:1642`). Không có `require_profile`, không có so checksum trong `runner.py:1642-1665` | **Chạy trên worker không khớp** | Vỡ im lặng: `load_job_config` và `load_geometry_profile` (`runner.py:1658-1661`) lấy từ máy hiện tại. Đây là lỗ hổng cần sửa dù T-040 có làm hay không |
| **QUEUED, retry sau lỗi FINALIZE** (`awaiting_finalize`, QUEUED) | Cùng nhánh `:247-260` | Chạy trên worker không khớp | Như trên |
| **Yêu cầu tách vật / Tạo mesh** (hàng đợi `r2s_scene_requests`) | `worker_cli.py:380` → `process_next` (`objectify_queue.py:769`), claim `_claim` (`:774`, định nghĩa `:518`) | **Chạy trên worker không khớp**, không có kiểm (`objectify_queue.py` chỉ có hai tham chiếu runtime, `:258` và `:748`; không có `require_profile`/`execution_profile`) | Vỡ im lặng; bản ghi đo mang runtime của job (`:748`) dù máy khác chạy |
| **Import scene / đăng ký** (`worker_cli.py:378`, `:381`) | Không tham chiếu runtime (không có khớp trong `src/services/orchestration/imports/` và `jobs/registration_worker.py`) | Chạy bình thường | Không dùng runtime của job; không ảnh hưởng checksum |
| **Validation Isaac** (`worker_cli.py:379`, `validation_worker.process_next`) | Profile gắn với config validation (`validation_worker.py:276-283`); kiểm quan sát sau chạy (`:337-338`) | Chạy được; sai phiên bản Isaac bị phát hiện sau chạy | Không vỡ do checksum của job. Rủi ro: máy không có Isaac vẫn nhận việc nếu config cho phép |
| **RUNNING mồ côi** (worker cũ đã trả, job đang ở một stage, ví dụ `CAMERA_POSE`) | `recover_interrupted_jobs` (`worker_cli.py:121-197`): `job_root` theo máy hiện tại (`:162`, `jobs/workspace.py:206-212`); workspace không có → `continue` (`:163-164`) | Worker mới **không khôi phục** | **Kẹt vĩnh viễn, im lặng.** Job RUNNING không được dispatch (`require_profile` từ chối không-QUEUED, `dispatch.py:80-81`). Đây là đúng điều plan cấm |

**Các điểm cần Architect biết:**
- Có **bốn** đường xử lý khác nhau, trong đó finalize và tách vật không kiểm runtime. Muốn "không kẹt im lặng" thì phải thêm
  lý do chờ (`progress.py:70`, `:298-302`) và ghi event khi bỏ qua. Việc này nên làm trước rebind.
- `recover_interrupted_jobs` chỉ hoạt động khi job chạy trên cùng máy. Cơ chế cùng bài toán đã làm đúng cho tách vật:
  lease có TTL (`objectify_queue.py:57`, `_LEASE_TTL = 90 s`; `recover_interrupted` `:485-500`). Với job video, comment tại
  `worker_cli.py:3-4` ghi rõ "không reclaim RUNNING theo timeout vì trainer có thể vẫn còn sống trên host khác".

---

## 3. Đề xuất bảng DB (migration 22) và luồng, đã sửa theo câu 1–2

Migration số 22 còn trống: `LATEST_SCHEMA_VERSION = 21` (`jobs/database.py:405`, `:411`).

### 3.1 Bảng
Không tái dùng `r2s_workers` (`processing/capability.py:245-252`): bảng đó khoá theo `worker_id`, chỉ giữ bản đo mới nhất
(`ON CONFLICT ... DO UPDATE`), không giữ lịch sử theo checksum. Đề xuất bảng mới:

```
r2s_worker_runtimes(
  runtime_manifest_checksum TEXT PRIMARY KEY,   -- identity: checksum canonical của RuntimeManifest
  manifest TEXT NOT NULL,                        -- JSON đã qua ExecutionProfile.load (profile.py:22-29)
  config_checksum TEXT NOT NULL,                 -- file cấu hình xử lý của worker
  seed INTEGER,
  gpu_name TEXT,                                 -- từ components.gpu_model (make_runtime_manifest.py:62)
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL                     -- TTL 15 phút, cùng CAPABILITY_TTL (capability.py:27)
)
```
Không đổi `JobManifest` và không thêm trường runtime vào `StageArtifact`/`ProductArtifactRef`: identity của job vẫn là một
checksum (`manifests.py:262`), còn lịch sử rebind đi vào `r2s_job_events` (dòng 6–9 ở mục 1).

### 3.2 Worker
- Upsert lúc khởi động (trước vòng lặp, `worker_cli.py:361` là điểm gắn heartbeat) và trong mỗi nhịp (`worker_cli.py:313-320`,
  chu kỳ 300 s tại `:298`). Manifest đọc từ file local và đi qua `ExecutionProfile.load` để giữ kiểm canonical.
- Worker không khớp với file config của API (`config_checksum`) không được upsert, để API không chọn nhầm.

### 3.3 API
- `get_project_registry` (`projects/registry.py:1920-1936`) dựng profile **một lần**. Chế độ `PRODUCT_RUNTIME_FROM_WORKERS` cần
  thay việc đọc profile tĩnh bằng tra bảng khi tạo job: `_build_queued_job` (`registry.py:1700-1719`).
- Ba chỗ từ chối khi thiếu profile phải đổi thành "có worker sống trong TTL": `scenes.py:185-188`, `assemblies.py:440-442`,
  và `deps.py:117-131` (budget).
- Giữ nguyên chế độ ghim tay: `config.py:188-189` (cặp `PRODUCT_PROCESSING_CONFIG`/`PRODUCT_RUNTIME_MANIFEST`) và
  `get_project_registry` khi có manifest ghim.
- Không có worker sống: tạo job bình thường, gắn runtime gần nhất, và cần một giá trị mới trong `WaitingFor`
  (`progress.py:70`) và `waiting_for` (`progress.py:298-302`), ví dụ `"runtime"`, để UI báo "đang chờ GPU". Đây là
  thay đổi contract; cần đồng bộ `frontend/src/lib/contracts/studio.ts:233` và kiểm giá trị hợp lệ tại `studio.ts:525`.

### 3.4 Rebind (chỉ job chưa có stage artifact)
- Điều kiện: `job.stage_artifacts == []` (`manifests.py:267`; tạo lúc `registry.py:1724`), status QUEUED, và runtime hiện tại
  không có worker sống quá TTL trong khi có runtime khác đang sống.
- Phải đi qua đường riêng, vì `persistence.py:309-317` **chặn** mọi thay đổi `runtime_manifest_checksum` giữa các revision.
  Đường riêng phải kiểm lại điều kiện bên trên dưới cùng CAS (`expected_checksum`) và ghi event `runtime_rebound {from, to, reason}`.
- Nơi thực hiện đề xuất: `dispatch_next` (`worker_cli.py:200-294`) của worker đang sống, để không cần API ghi.
- Job đã có stage (QUEUED retry sau lỗi preview/finalize, RUNNING): **không rebind tự động**. Đây là câu hỏi 4.1.

### 3.5 Sửa lỗ hổng đã thấy (không phụ thuộc rebind)
- Thêm kiểm runtime vào nhánh finalize (`worker_cli.py:247-260`) và vào `objectify_queue.process_next` trước `_claim`
  (`objectify_queue.py:774`). Không khớp thì bỏ qua và ghi lý do, không chạy.
- Ghi runtime thật của máy vào `ResourceUsage` (thay vì runtime của job tại `objectify_queue.py:748` và `runner.py:319`).
  Lúc đó budget và benchmark (dòng 6–7) lọc đúng theo máy đã chạy.

### 3.6 Job RUNNING của pod đã trả
- Phương án A: lease có TTL theo job, heartbeat từ worker đang chạy, tương tự `_LEASE_TTL` tại `objectify_queue.py:57`.
  Khi lease hết hạn, job chuyển FAILED với `retryable=True`, như `recover_interrupted_jobs` làm hôm nay (`worker_cli.py:182-188`).
- Phương án B: giữ kiểm workspace nhưng coi "không có workspace trên máy này và không có heartbeat quá TTL" là mồ côi.
- Rủi ro chung: trainer có thể vẫn chạy trên host khác (`worker_cli.py:3-4`). Phương án A tôn trọng điều này nhờ fencing
  bằng token, như lease gắn `lease_token` và `lease_expires_at` khi claim (`objectify_queue.py:542`, `:563`).

---

## 4. Câu hỏi cho Architect (cần duyệt trước khi làm Phần B)

1. **Rebind job đã có stage.** Chọn một:
   (a) không rebind; job RUNNING/đã có stage chờ đúng runtime cũ, và UI báo rõ;
   (b) "chạy tiếp trên GPU hiện có" cho Reviewer, ghi provenance hai runtime trong `r2s_job_events`;
   (c) chạy lại từ đầu trên runtime mới, giữ các stage cũ như lịch sử.
2. **RUNNING mồ côi.** Phương án A (lease theo job, FAILED retryable khi hết TTL) hay B (kiểm workspace + heartbeat)?
   Phương án A thay đổi hành vi của job video dài; cần duyệt.
3. **Đơn vị identity của runtime.** `make_runtime_manifest.py:62-64` đưa `vram` và `nvidia_driver` vào manifest, nên hai pod
   cùng model GPU nhưng khác VRAM hoặc driver sẽ có checksum khác và không chia job được. Có giữ nguyên (chặt) hay băm
   theo model + driver, bỏ VRAM (nới)?
4. **Finalize và tách vật khi không khớp:** bỏ qua và chờ worker khớp (đề xuất), hay ghi FAILED retryable?
5. **Phụ thuộc T-038.** Plan ghi "Cần T-038 accepted" và T-038 vẫn `planned`. Phần B không nên bắt đầu trước khi T-038 xong.
6. **Đường dẫn autoscaler.** Plan ghi `scripts/autoscaler`; thực tế là `scripts/cloud/gpu_autoscaler.py`. Script này đọc job
   qua `registry.get_job` (`gpu_autoscaler.py:130`) nhưng chỉ đếm trạng thái: QUEUED hoặc chờ finalize được tính là việc
   chờ GPU (`:134-135`), không xét runtime. Hệ quả: một job QUEUED cho runtime không còn worker vẫn làm autoscaler bật GPU.
   Chỉ cần sửa đường dẫn trong plan; việc đếm theo runtime là việc của Phần B nếu Architect chọn rebind.
7. **Migration 22.** Xác nhận không task nào khác đang giữ số 22 (T-037 đang `in-progress`).
