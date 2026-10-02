# Execution Plan: Worker tự quản lý tài nguyên (đo thật, dọn dần, tự hạ mức, tự học)

## Status

PLANNED — viết ngày 02/10/2026 trên `feat/pipeline-v2` tại commit `6c1889a`. Chưa có dòng code nào của plan này.
Người viết plan (agent phiên này) sẽ **audit** sau khi agent khác implement; xem mục "Audit checklist".

## Outcome

Worker không còn dựa vào hệ số viết tay để biết một job có chạy nổi không. Thay vào đó:

1. **Đo thật** mức dùng VRAM/RAM/đĩa cao nhất của từng bước và ghi thành bản ghi bất biến theo job.
2. **Dọn dần** đồ làm việc tạm sau khi kết quả đã publish, không đụng artifact.
3. **Đo trước mỗi bước** phần tài nguyên còn trống thật sự (không phải tổng của máy).
4. **Tự hạ mức** khi thiếu tài nguyên, có ghi lại. *(Chờ owner quyết — xem "Quyết định còn treo".)*
5. **Tự học**: bộ ước lượng lấy hệ số từ chính các bản ghi ở mục 1 trên chính máy đó.

Yêu cầu chung của owner: chạy đúng cả trên stack local (SQLite + filesystem) lẫn hướng deploy production
(ADR 0003: API trên Railway, PostgreSQL, kho file R2, GPU worker thuê). Không hardcode đường dẫn máy; cấu hình qua
`Settings`.

## Task Capsule

```text
Task / outcome:      5 cơ chế ở trên; pha A+B làm ngay, pha C–E theo thứ tự, pha D chờ quyết định.
Authority anchors:   ARCHITECTURE.md (placement, ownership orchestration = EX-PRODUCT, reconstruction = EX-REC);
                     docs/execution/TEAM_EXECUTION_CONTRACT.md (artifact bất biến, provenance/checksum);
                     docs/decisions/0003-*.md (deploy: API/worker tách máy, kho file R2);
                     eval/protocols/BENCHMARKS.md (quy ước mã benchmark, bản ghi theo job);
                     AGENTS.md §6, §8, §9.
Dependencies:        Không phụ thuộc task khác. Dùng runner, benchmark, capability, resources hiện có.
Inputs / outputs:    Vào: tiến trình con của từng bước, thư mục làm việc của worker. Ra: artifact
                     `jobs/<job>/benchmark/resource_usage/<attempt_id>.json`, thư mục tạm đã dọn, trường mới trong
                     bảng đánh giá nhóm "Hệ thống".
Owned paths:         src/services/orchestration/jobs/, src/services/orchestration/processing/,
                     src/services/orchestration/scene/objectify.py (chỉ chỗ gọi tiến trình con),
                     src/services/orchestration/benchmark.py, src/services/orchestration/evaluation/,
                     tests/test_orchestration/, eval/protocols/, docs của plan này.
Do-not-modify paths: src/models/contracts/** (không đổi shared contract), src/services/reconstruction/** (trừ khi
                     plan nêu rõ), JobManifest schema, bảng DB (không thêm migration ở pha A–C),
                     organizer scaffold, mọi thứ trong data/.
Proof required:      Mục "Validation" từng pha; positive + negative proof cho mọi invariant.
Unknowns / blockers: Mục "UNKNOWN cần kiểm khi implement" và "Quyết định còn treo".
```

## Hiện trạng đã kiểm (VERIFIED, commit `6c1889a`)

Đường dẫn tương đối từ gốc repo; số dòng có thể lệch vài dòng nếu file đổi.

**Cách các bước chạy**

- `src/services/orchestration/jobs/runner.py:120` `_run_tool(attempt, name, command, timeout, progress)` là **điểm duy
  nhất** chạy REC CLI cho ba bước: `prepare` (`_execute_prepare`, :288), `preview` = COLMAP + Brush trong **một** tiến
  trình (`_execute_preview`, :215), `finalize` (`run_finalize_job`, :404). Nó dùng `subprocess.Popen(...,
  start_new_session=True)` nên tiến trình con là trưởng nhóm tiến trình riêng (`os.killpg(process.pid, …)` ở `_stop`,
  :69). Vòng chờ poll mỗi 1 giây (`pause.wait(1)`), trong đó `progress.poll()` cập nhật `attempt.job.current_stage`
  theo file progress của REC.
- Vì mỗi bước nặng là tiến trình riêng, VRAM tự trả về khi tiến trình thoát. Không cần cơ chế "giải phóng VRAM" trong
  cùng tiến trình.
- Tách vật thể **không** đi qua `_run_tool`: `runner.py:376` `_extract_scene_stage` → `scene/extraction.py:123`
  `extract_scene` → `scene/objectify.py:78` `_run(python, script, request, workspace, name, timeout)` dùng
  `subprocess.run` (không tách nhóm tiến trình), gọi runtime Python riêng (`PRODUCT_SCENE_RUNTIME_PYTHON`).
  `objectify.py:324` `objectify_with_retry` thử lại tối đa `product_objectify_attempts` (mặc định 3) lần, mỗi lần một
  workspace `attempt-<n>`; docstring ghi lý do "lỗi GPU thường thoáng qua (hết VRAM do tiến trình khác, driver)".
- Hàng đợi dựng lại tập vật: `scene/objectify_queue.py:~207` dùng `product_worker_root/<job_id>/<mode>-<uuid>`.

**Thư mục làm việc**

- `runner.py:203`: `product_worker_root/<job_id>/attempt-<uuid>/` cho prepare+preview; `runner.py:433`:
  `…/<job_id>/finalize-<uuid>/`. Trong đó: `*.request.json`, `*.stdout.json`, `*.stderr.log`, `*.progress.jsonl`,
  thư mục `rec/` (workspace của REC CLI), và `scene/` (workspace tách vật thể, dưới thư mục finalize).
- `runner.py:~244`: `--resume-root <job_id>/resume` dùng chung cho mọi attempt của job. `src/services/reconstruction/
  resume.py` (docstring đầu file): giữ sparse model COLMAP đã hoàn tất + checkpoint Brush để attempt sau không dựng
  lại từ đầu; "là trạng thái vận hành, không phải artifact"; mất kho thì pipeline chạy lại từ đầu.
- **Không có code nào dọn** các thư mục này (`grep rmtree` trong `runner.py`, `objectify.py`, `objectify_queue.py`:
  không có). Ngày 02/10/2026 phải xoá tay 2,8 GB trong `data/studio_local/workers/`; sau khi xoá, 87/87 artifact của
  13 scene vẫn khớp checksum qua API và mọi màn xem bước vẫn đọc được → bằng chứng thực nghiệm rằng job **đã xong**
  không đọc lại thư mục làm việc.
- Màn xem bước và bảng đánh giá chỉ đọc artifact đã publish qua `runtime_resolver` (`jobs/stage_views.py`,
  `evaluation/scorecard.py`), không đọc `product_worker_root`.

**Đo máy và ước lượng**

- `processing/capability.py:51` `probe(worker_root)` đo **tổng** VRAM (`nvidia-smi --query-gpu=name,memory.total`),
  tổng RAM (`/proc/meminfo`), đĩa trống tại `worker_root`. Worker ghi mỗi 300 giây
  (`jobs/worker_cli.py` `CAPABILITY_INTERVAL_SECONDS`). Không đo VRAM/RAM **đang trống**.
- `processing/resources.py:68` `estimate_gb(model, params)` ước lượng VRAM/RAM/đĩa **chỉ cho COLMAP + Brush** bằng hệ
  số trong `configs/product/processing_presets_v1.json` → `resource_model` (ghi chú trong file: "Ước lượng heuristic
  để cảnh báo trước khi chạy, không phải phép đo"). Không có số hạng nào cho hình học, tách vật thể, xuất USD.
- `processing/resources.py:110` `evaluate(...)` gắn trạng thái ok/warn/danger cho từng thông số;
  `processing/resources.py:188` `maximum_for_machine(presets, capability)` **đã tồn tại**: tìm nhị phân bộ thông số
  cao nhất giữa preset `minimum_quality` và `maximum` mà mọi tài nguyên dưới `warn_ratio`. API trả nó ở
  `src/api/studio/processing.py:52` (`machine_maximum`). Tức "trần theo máy" đã có, nhưng dựa trên mô hình heuristic
  và tổng tài nguyên, chỉ tính lúc tạo scene.
- Không có xử lý hết bộ nhớ ở prepare/preview/finalize: bước lỗi → job `FAILED` (`_record_runner_failure`, :157).

**Bản ghi hiện có**

- `src/services/orchestration/benchmark.py`: `PipelineRuntimeBenchmark` (thời gian từng stage, cấu hình, máy, kích
  thước input/SOG), publish ở `artifact://jobs/<job>/benchmark/pipeline_runtime/attempt-<n>.json` qua
  `publish_benchmark`. Gọi từ `runner.py:265` `_record_benchmark`, bọc `except Exception` + log: lỗi đo đạc không
  bao giờ làm hỏng job. **Chỉ gọi sau preview/prepare**, không gọi sau finalize.
- Bảng đánh giá: `src/services/orchestration/evaluation/scorecard.py` nhóm `system` (`_system_metrics`) hiện có thời
  gian xử lý, bước lâu nhất, số lượt chạy.

**Deploy**

- Worker trên máy GPU thuê khởi động với cache rỗng và gọi `runtime_resolver.sync_down(job_id)` (`runner.py:~211`),
  rồi `sync_up` sau mỗi bước. `ArtifactResolver.require/locate` tự tải từ kho file khi thiếu bản cục bộ
  (`artifacts/store.py`).
- `scripts/gpu/run_stack.sh:44` chạy `python -m src.services.orchestration.jobs.worker_cli`.

## UNKNOWN cần kiểm khi implement (không được đoán)

- U1. Nội dung và kích thước thật của `rec/` và `resume/` sau một lượt chạy (hiện không còn thư mục nào trên máy để
  xem). Phải chạy một job thật hoặc đọc `preview_cli`/`finalize_cli`/`resume.py` để liệt kê trước khi viết quy tắc dọn.
- U2. `nvidia-smi --query-compute-apps=pid,used_memory` có trả đúng PID của tiến trình con không khi worker chạy trong
  container (PID namespace khác). Nếu không, dùng `--query-gpu=memory.used` (toàn GPU) và ghi rõ đó là số của cả GPU.
- U3. Brush (wgpu/Vulkan) có hiện trong `--query-compute-apps` không, hay chỉ tiến trình CUDA mới hiện. Kiểm trên máy
  local (Quadro T2000) trước khi chọn nguồn số VRAM.
- U4. Có bước nào đọc file từ thư mục làm việc của attempt **trước** thay vì từ kho artifact không (đã thấy:
  `resume/` được đọc bởi attempt sau — cố ý). Tìm bằng `rg "attempts/|workspace" src/services/reconstruction`.
- U5. Mức VRAM thật của SAM2 / gsplat lifting / LaMa trên một scene thật — chưa từng đo.

## Thiết kế

### Pha A — Ghi mức dùng thật của từng bước (làm trước)

Module mới `src/services/orchestration/jobs/usage.py`:

- `ProcessTreeSampler`: nhận PID trưởng nhóm, mỗi lần `sample(stage_id)`:
  - RAM: cộng RSS của mọi tiến trình có `pgrp == pid` (đọc `/proc/<pid>/stat` trường 5 và `/proc/<pid>/statm`).
    Không có `/proc` → `None`, không ước lượng.
  - VRAM: gọi `nvidia-smi` thưa hơn RAM (vd mỗi 5 mẫu) vì mỗi lần gọi tốn ~50–100 ms; nguồn số theo kết quả U2/U3.
    Không có `nvidia-smi` → `None`.
  - Giữ **giá trị cao nhất theo `stage_id`** và số mẫu. `stage_id` lấy từ `attempt.job.current_stage` tại lúc lấy mẫu
    (preview chạy COLMAP rồi Brush trong một tiến trình, nên phải tách theo stage hiện hành).
- Model `StageUsage` (stage_id, seconds, peak_ram_gb | None, peak_vram_gb | None, vram_scope: "process" | "gpu",
  samples) và `ResourceUsageRecord` (schema_version, benchmark_kind = `resource_usage`, job_id, attempt_id, tool,
  recorded_at, machine (MachineCapability | None), inputs: số frame / số Gaussian / độ phân giải nếu đọc được từ
  artifact, stages: list[StageUsage], workspace_bytes_peak | None).
- Nối vào `runner._run_tool`: trong vòng chờ 1 giây gọi `sampler.sample(...)`; trả thêm dữ liệu usage cho nơi gọi
  (đổi kiểu trả về hoặc gắn vào `_Attempt`). Lỗi lấy mẫu **không được** làm hỏng job: bọc ở biên, log tên exception.
- Nối vào `scene/objectify.py:_run`: đổi `subprocess.run` thành `Popen` + vòng chờ có lấy mẫu **hoặc** lấy mẫu bằng
  thread nền quanh `subprocess.run`. Giữ nguyên hành vi timeout và thông báo lỗi hiện có (có test).
- Publish: `artifact://jobs/<job>/benchmark/resource_usage/<attempt_id>-<tool>.json`, cùng cách `publish_benchmark`
  (bất biến, `data_class=derived`, `producer_stage="benchmark"`). Gọi cả sau finalize (hiện benchmark không được ghi
  sau finalize).
- Giao thức: thêm `eval/protocols/resource_usage.md` và một dòng trong bảng `eval/protocols/BENCHMARKS.md`.
- Bảng đánh giá: `_system_metrics` thêm "VRAM cao nhất" và "RAM cao nhất" (kèm bước đạt đỉnh) đọc từ các bản ghi
  này; không có bản ghi → "Chưa đo" (D-05/D-16), không lấy số từ mô hình ước lượng.

Ranh giới: không đổi `JobManifest`, không đổi `PipelineRuntimeBenchmark` (giữ tương thích bản ghi cũ), không thêm bảng
DB.

### Pha B — Dọn đồ tạm (owner đã đồng ý hướng dè dặt)

Quy tắc owner chốt trong hội thoại 02/10/2026: **giữ đồ tạm tới khi cả giai đoạn xong; chỉ xoá sớm khi đĩa thiếu.**
Kết quả từng bước vẫn xem được vì chúng là artifact; dọn chỉ đụng thư mục làm việc.

- Module `src/services/orchestration/jobs/workspace.py`:
  - `cleanup_attempt(workspace, *, keep_logs=True) -> int` (số byte giải phóng): xoá thư mục con làm việc (`rec/`,
    `scene/`), **giữ** file nhỏ ở gốc (`*.request.json`, `*.stdout.json`, `*.stderr.log`, `*.progress.jsonl`) để
    còn chẩn đoán được. Chỉ xoá bên dưới `product_worker_root/<job_id>/`; từ chối đường dẫn thoát ra ngoài.
  - `cleanup_resume(job_root) -> int`: xoá `resume/` của job.
- Thời điểm:
  - Sau `record_preview` **thành công** (job sang `ST-METRIC-CANONICALIZE` chờ người dùng): dọn `rec/` của attempt.
    `resume/` **giữ** nếu job còn có thể retry preview; xoá khi preview đã thành công (kiểm U1/U4 trước: finalize có
    đọc gì từ `resume/` không).
  - Sau `record_finalize` thành công: dọn `rec/` và `scene/` của thư mục finalize.
  - Attempt **lỗi**: không dọn (cần log + resume để retry và chẩn đoán).
  - Hàng đợi `objectify_queue`: dọn workspace `<mode>-<uuid>` sau khi yêu cầu `done`; giữ khi `failed`.
- Thứ tự an toàn: chỉ dọn **sau** khi `runtime_resolver.sync_up(job_id)` đã chạy và bản ghi job đã commit. Lỗi khi
  dọn chỉ log, không đổi trạng thái job.
- Ghi số byte đã dọn vào `ResourceUsageRecord` (hoặc log có cấu trúc nếu bản ghi đã publish).
- Job đã vào Thùng rác: `projects/deletion.py` đã dời `product_worker_root/<job_id>` vào thùng rác (item kind
  `worker`); không cần xử lý thêm, nhưng test phải chứng minh hai cơ chế không giẫm nhau.

### Pha C — Đo trước mỗi bước

- `processing/capability.py`: thêm `probe_free(worker_root) -> FreeResources` (VRAM trống: `nvidia-smi
  --query-gpu=memory.used,memory.total`; RAM: `MemAvailable` trong `/proc/meminfo`; đĩa: `shutil.disk_usage`).
- Trước mỗi bước nặng (`_execute_preview`, `run_finalize_job`, `extract_scene`): đo, so với nhu cầu ước lượng của
  bước đó (pha E; trước khi có pha E dùng `estimate_gb` cho preview và **không chặn** các bước chưa có mô hình).
  - Đĩa thiếu → gọi dọn sớm (pha B, kể cả `resume/` của **job khác đã xong**) rồi đo lại.
  - Vẫn thiếu → hành vi theo quyết định ở pha D. Trước khi có quyết định: dừng bước với lỗi có `error_code` riêng
    (`INSUFFICIENT_RESOURCES`), `retryable=True`, `human_message` nêu thiếu gì và bao nhiêu — không chạy rồi sập.
- Ghi số đo "trống trước bước" vào `ResourceUsageRecord`.

### Pha D — Tự hạ mức (CHỜ OWNER QUYẾT)

Chưa implement cho tới khi owner trả lời câu 1 ở "Quyết định còn treo". Nếu được phép:

- Mỗi bước khai báo dãy nấc hạ được (vd Brush: `max_resolution`, `max_splats`; tách vật thể: số ảnh SAM2 mỗi lượt).
- Khi pha C thấy thiếu, hoặc tiến trình thoát với dấu hiệu hết bộ nhớ, chạy lại ở nấc thấp hơn (tối đa N lần).
- **Ràng buộc truy vết:** cấu hình job đang được khoá bằng `config_checksum` (`jobs/profile.py`,
  `persistence.save_job` từ chối revision đổi `config_checksum`). Hạ mức **không được** sửa cấu hình đã khoá; phải
  ghi thành dữ liệu riêng (đề xuất: trường `degradations` trong `ResourceUsageRecord` + `source_provenance` của
  artifact bước đó nếu REC cho phép). Cần EX-REC (owner) duyệt cách ghi vì chạm provenance của artifact REC.
- Bảng đánh giá hiện rõ scene đã bị hạ mức ở bước nào.

### Pha E — Tự học hệ số

- `processing/resources.py`: thêm đường ước lượng từ dữ liệu: đọc các `ResourceUsageRecord` của máy hiện tại (khoá
  theo `MachineCapability.gpu_name` + `vram_total_gb`), khớp tuyến tính đỉnh VRAM/RAM theo đặc trưng đầu vào (số
  frame, số Gaussian, megapixel). Ít hơn K bản ghi (đề xuất K = 3) → dùng mô hình heuristic hiện có và đánh dấu
  nguồn là `heuristic`; đủ → `learned`.
- Mở rộng ước lượng sang hình học và tách vật thể (hiện không có).
- `maximum_for_machine` và `evaluate` dùng ước lượng mới; API `/processing/options` trả thêm nguồn ước lượng để UI
  nói rõ con số là "đo từ N lượt chạy" hay "ước lượng".
- Nơi lưu bản ghi để học: đọc lại từ kho artifact theo danh sách job (không thêm bảng DB) **hoặc** thêm bảng
  `r2s_resource_usage` (migration v7). Chọn ở lúc implement dựa trên chi phí quét; nếu thêm migration thì theo quy
  tắc `jobs/database.py` (chỉ CREATE cộng thêm) và chạy được trên cả SQLite lẫn PostgreSQL.

## Thứ tự và phạm vi mỗi commit

Một pha = một hoặc vài commit nhỏ (`type(scope): mô tả`, không dòng attribution, không push). Thứ tự: A → B → C →
(D nếu được duyệt) → E. Mỗi pha tự đứng được và có thể dừng sau pha đó.

## Validation

Chung cho mọi pha (máy local: một việc nặng một lúc, bọc `systemd-run --user --scope -q -p CPUQuota=300%`):

```bash
.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/
.venv/bin/python -m pytest tests/test_orchestration -q -p no:cacheprovider
.venv/bin/python -m pytest tests/ -q -p no:cacheprovider      # baseline hiện tại: 1188 passed, 40 skipped
.venv/bin/python -m scripts.check_foundation && .venv/bin/python -m scripts.check_contract_mirror
```

Guard `tests/conftest.py::_no_writes_to_default_artifact_store` phải vẫn xanh (test không ghi vào `data/artifacts`).

**Pha A**

- Unit: sampler với tiến trình giả (script Python cấp phát N MB rồi ngủ) → `peak_ram_gb` nằm trong khoảng kỳ vọng;
  tiến trình con của con (cùng nhóm) được cộng; không có `/proc` hoặc `nvidia-smi` (monkeypatch) → `None`, không ném
  lỗi; đổi `current_stage` giữa chừng → đỉnh tách đúng theo stage.
- Negative: sampler ném lỗi → `_run_tool` vẫn trả kết quả của tool, job không `FAILED`.
- Integration: `tests/integration/test_upload_to_prepared_job.py` (đã có, chạy `prepare_cli` thật + FFmpeg) → sau lượt
  chạy có artifact `benchmark/resource_usage/…json` hợp lệ, checksum đúng.
- Runtime thật: chạy một job trên stack local, đọc bản ghi; đối chiếu đỉnh VRAM với `nvidia-smi` quan sát tay trong
  lúc train (chênh lệch chấp nhận ghi rõ trong báo cáo).

**Pha B**

- Positive: sau preview/finalize thành công, `rec/`, `scene/` không còn; file log ở gốc còn; artifact của job khớp
  checksum; `GET /jobs/{id}/stage-views`, `/evaluation`, `/artifacts` trả như trước khi dọn.
- Negative: attempt lỗi → không dọn gì; đường dẫn ngoài `product_worker_root/<job>` → từ chối; dọn lỗi (quyền ghi) →
  job vẫn `SUCCEEDED`.
- Retry: preview lỗi giữa chừng rồi retry vẫn dùng được `resume/` (test hiện có về resume phải xanh).
- Thùng rác: gỡ rồi khôi phục một scene đã dọn → `tests/test_orchestration/test_scene_deletion.py` xanh, thêm một ca
  cho job có thư mục worker đã dọn.

**Pha C**

- Unit với số đo giả: đủ → chạy; thiếu đĩa → dọn sớm rồi chạy; vẫn thiếu → lỗi `INSUFFICIENT_RESOURCES`, job không
  khởi chạy tool (kiểm tool không được gọi).
- Runtime: chiếm VRAM bằng một tiến trình khác rồi tạo job → thấy lỗi đúng mã thay vì sập giữa chừng.

**Pha E**

- Unit: với K bản ghi tổng hợp sinh từ hàm tuyến tính đã biết → hệ số khớp lại đúng trong sai số; dưới K → nguồn
  `heuristic`; bản ghi của máy khác không được dùng.
- Không đổi kết quả `maximum_for_machine` khi chưa có bản ghi (so với baseline hiện tại bằng test có sẵn trong
  `tests/test_orchestration/test_processing_config.py`).

## Quyết định còn treo (owner)

1. **Khi thiếu tài nguyên: tự hạ mức rồi ghi lại, hay dừng job và báo người dùng?** Quyết định mở khoá pha D.
2. **Giữ lại 1/8 ảnh không train để đo PSNR/SSIM/LPIPS cho mọi scene?** Không thuộc plan này (thuộc
   `docs/plans/active/2026-10-02-evaluation-system.md` pha 3) nhưng nếu bật sẽ đổi số frame train, tức đổi dữ liệu
   mà pha E học.
3. **Nhiều người dùng cùng lúc** (hiện một worker, tuần tự; Editor 10 lượt GPU/24 giờ): hiện vị trí hàng đợi, preset
   nhanh lúc đông, thêm worker, tự bật/tắt GPU — ngoài phạm vi plan này, cần plan riêng.

## Ngoài phạm vi

- Lấy mẫu frame theo chuyển động của video (thay `sampling.sample_fps` cố định): cần số đo từ lượt chạy GPU thuê.
- Chế độ hai camera cho COLMAP (`single_camera: false`) cho video ghép camera trái + phải.
- Tự bật/tắt máy GPU theo hàng đợi (ADR 0003 nêu, chưa có code).
- Đổi shared contract, đổi `JobManifest`.

## Risks And Recovery

- Lấy mẫu làm chậm vòng chờ: giữ chi phí mỗi vòng < 20 ms (đo trong test), `nvidia-smi` gọi thưa.
- Dọn nhầm thứ còn cần: chỉ dọn sau khi commit + sync_up; giữ log; mọi quy tắc dọn có negative test. Rollback: revert
  commit pha B — dữ liệu đã dọn là đồ tạm, artifact không mất.
- Số VRAM theo cả GPU bị lẫn tiến trình khác: ghi `vram_scope` trong bản ghi và hiện rõ trong bảng đánh giá.
- Hạ mức âm thầm làm scene kém đi: pha D bắt buộc ghi lại và hiện trên UI; không implement trước khi owner duyệt.

## Audit checklist (cho lượt kiểm sau khi implement)

- [ ] `git diff 6c1889a..HEAD --stat`: chỉ đụng "Owned paths"; không đụng `src/models/contracts/`, không sửa schema
      JobManifest, không thêm migration ở pha A–C.
- [ ] Mỗi mục U1–U5 có câu trả lời kèm bằng chứng (lệnh + output) trong phần Progress bên dưới, không phải suy đoán.
- [ ] Lỗi đo đạc/dọn dẹp không thể làm job `FAILED` (đọc code biên + có negative test).
- [ ] Sau khi dọn: màn xem từng bước, bảng đánh giá, tải artifact, khôi phục từ Thùng rác vẫn chạy (test + thử trên
      stack thật với ít nhất một scene).
- [ ] Bản ghi `resource_usage` bất biến, có checksum, publish qua `FilesystemArtifactStore`, được `sync_up` lên kho
      file; đọc lại được qua `runtime_resolver.require` trên máy không có bản cục bộ (test với `MemoryObjectStore`).
- [ ] Không có số ước lượng nào hiện như số đo; thiếu dữ liệu → "Chưa đo".
- [ ] Không hardcode đường dẫn máy, không đọc env ngoài `Settings`.
- [ ] `pytest tests/ -q` ≥ 1188 passed, không test nào bị xoá/nới để xanh; vitest và `next build` xanh nếu đụng UI.
- [ ] Pha D không được implement khi câu 1 chưa có trả lời của owner trong plan này.
- [ ] Comment/docstring tiếng Việt, giải thích why; type hints đủ; ruff sạch.

## Progress

- [x] 02/10/2026 — Khảo sát code, viết plan (agent phiên audit).
- [ ] Pha A
- [ ] Pha B
- [ ] Pha C
- [ ] Pha D (chờ quyết định 1)
- [ ] Pha E

## Decisions

- 02/10/2026 (owner, trong hội thoại): hệ số tài nguyên không được hardcode; worker phải tự đo, tự dọn, tự điều chỉnh.
- 02/10/2026 (owner): dọn đồ tạm theo hướng dè dặt — giữ tới khi giai đoạn xong, xoá sớm chỉ khi đĩa thiếu; kết quả
  từng bước phải vẫn xem được sau khi pipeline xong.
- 02/10/2026 (owner): code phải chạy đúng cả local lẫn hướng deploy production.

## Result

Chưa có.
