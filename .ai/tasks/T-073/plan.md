# T-073: Hàng đợi theo từng bước — bước CPU và bước GPU của các job khác nhau chạy chồng lên nhau

Yêu cầu của chủ dự án (2026-10-20): "job này đang ở bước cần CPU thì cứ dùng CPU, job khác đang ở bước GPU thì dùng
GPU, không ai chiếm cả hai khi chỉ dùng một". Đây là mô hình chuẩn của hệ xử lý nặng (mỗi bước là một việc độc lập,
tự khai tài nguyên, một hàng đợi chung, nhiều làn nhận việc theo loại tài nguyên). Làm sau T-072 (Mức 1) khi số đo
cho thấy Mức 1 chưa đủ, hoặc khi cần thêm máy CPU rẻ / nhiều máy GPU. Ước 3–5 ngày kể cả kiểm thử.

Hiện trạng làm căn cứ:

- Đơn vị nhận việc hiện là **lượt**: `run_video_job` (prepare → LiDAR → preview), `run_reviewed_preview_job`,
  `run_prepared_job`, `run_finalize_job` (`jobs/runner.py`), được `_dispatch` (`jobs/worker_cli.py:305`) chọn theo
  `waiting_jobs` + `fair_order` (`jobs/queue.py`). Mỗi lượt giữ một lease (`_leased_call`) và một giữ chỗ tài nguyên.
- Mỗi bước đã là một tiến trình riêng qua `_run_tool` với tên tool: `prepare`, `lidar_ingest`, `lidar_odometry`,
  `preview` (COLMAP + Brush + `metric_proposal`), `finalize` (REC-06 canonical + REC-05 voxel/geometry),
  `scene_extract` (tách vật, ObjectGS), và các thao tác ngoài job (`reobjectify`, `import_package`,
  `isaac_validate`, `rgb_lidar_register`, LOD lúc rảnh). Mỗi bước ghi artifact + mốc bước (`r2s_step_marks`,
  `record_stage_progress`) và có resume cache (COLMAP sparse, checkpoint Brush).
- Số đo tài nguyên đã theo **tool** (`r2s_resource_usage.tool`), nên nhu cầu của từng bước đã có nguồn.
- Đã có làn CPU tùy chọn (`gpu/cpu_worker.py`, `GpuSettings.cpu_lane_*`) nhận registration/scene/import/demo trên máy
  API; chưa nhận bước nào của job pipeline.
- Bộ thuê máy (`gpu/workload.py::scan_scope`) đếm nhu cầu theo job đang chờ và thao tác; có sẵn `cpu_pending`.
- `StageId` (`models/contracts/manifests.py:142`) là trạng thái cho người dùng, không phải đơn vị xếp lịch.

## Thiết kế

### 1. Mô hình: job = chuỗi bước; bước = việc có loại tài nguyên

Bảng mới `r2s_job_steps` (migration v27): `job_id`, `step_id`, `kind: cpu|gpu`, `tool`, `state:
ready|claimed|running|done|failed|waiting_user|skipped`, `depends_on` (JSON list step_id), `required_gb` (JSON, điền
lúc ready từ admission `_demand` theo tool), `attempt`, `worker_id`, `lease_expires_at`, `job_manifest_checksum` (CAS),
`created_at`, `updated_at`. Khóa chính `(job_id, step_id)`.

Đồ thị bước cho job video (job dataset/bộ ảnh bỏ `prepare` khi frame set có sẵn):

| step_id | tool | kind | sau bước | ghi chú |
|---|---|---|---|---|
| prepare | prepare | cpu | — | kiểm tra video, tách khung, che mặt |
| anonymization_review | — | người dùng | prepare | chỉ khi có frame bị che; `waiting_user` |
| lidar_ingest | lidar_ingest | cpu | prepare/review | chỉ job có LiDAR |
| lidar_odometry | lidar_odometry | gpu | lidar_ingest | chỉ job có LiDAR |
| pose_visual | preview | gpu | prepare/review (+lidar) | COLMAP + Brush + metric_proposal, một tiến trình như nay |
| metric_confirm | — | người dùng | pose_visual | xác nhận tỉ lệ |
| canonical_geometry | finalize | cpu (gpu nếu `product_geometry_gpu_index`) | metric_confirm | REC-06 + REC-05 |
| scene_extract | scene_extract | gpu | canonical_geometry | tách vật; dừng `waiting_user` nếu `geometry_review=required` |
| object_review | — | người dùng | scene_extract | duyệt tách vật |
| collider_bundle | (phần cuối finalize hiện tại) | cpu | object_review / scene_extract | CoACD, USD |
| view_lod | lod | gpu, ưu tiên thấp | pose_visual, scene_extract | như `LodBuilder.tick` hiện nay |

Việc tách `finalize` thành `canonical_geometry` và `collider_bundle` cần tách `finalize_cli` thành hai lệnh có artifact
ranh giới rõ (REC-05 geometry ref); nếu quá tốn, giai đoạn 1 giữ `finalize` là một bước `cpu` (khi không có
`product_geometry_gpu_index`) và tách sau.

### 2. Sinh bước và chuyển trạng thái

- `StepPlanner.plan(job)`: từ `JobManifest` (loại input, có LiDAR, `scene.geometry_review`, cờ che mặt) sinh danh sách
  bước **tất định**. Chỉ tạo hàng khi job vào QUEUED lần đầu hoặc khi retry; CAS theo `job_manifest_checksum`.
- Bước `ready` khi mọi `depends_on` `done` (hoặc `skipped`). Bước người dùng chuyển `done` khi API ghi quyết định
  (xác nhận tỉ lệ, chấp nhận bản che, duyệt tách vật) — các API này đã có, chỉ thêm một dòng cập nhật bước.
- Hủy job / đổi revision: mọi bước chưa `done` của revision cũ → `skipped`; worker đang chạy bước phát hiện revision
  đổi như `_run_tool` hiện nay.
- Thất bại: bước `failed` + job FAILED ở `StageId` tương ứng (ánh xạ step → StageId cố định); retry của người dùng tạo
  lại bước đó với `attempt+1`, các bước trước giữ `done`.
- Hết bộ nhớ (`exhausted`): bước về `ready` với cờ "chạy một mình" (dùng lại `exhausted_before`).

### 3. Nhận việc theo làn

- `worker_cli` nhận tham số `--lanes gpu,cpu` (mặc định `gpu,cpu` trên pod; `cpu` trên máy API nếu bật làn CPU).
  Mỗi worker-process vẫn một việc một lúc (giữ cách cách ly tiến trình hiện có); số worker-process GPU trên pod =
  `STUDIO_WORKERS`, số worker-process CPU = `STUDIO_CPU_WORKERS` (mặc định `cpu_count // 2`, tối thiểu 1).
- `StepQueue.next(lanes, worker)`: chọn bước `ready` có `kind` trong `lanes`, xoay vòng theo chủ job (dùng lại
  `fair_order`), ưu tiên: bước người dùng đang chờ → bước nối tiếp của job đã bắt đầu → job mới → `view_lod`.
  Claim bằng CAS `state ready→claimed` + lease, như `_leased_call`.
- Admission theo bước: `ResourceAdmission.admit_step(step)` dùng `_demand` với `tools=(step.tool,)` (mở rộng
  `PHASE_TOOLS` thành theo tool), `gpu_required = kind == "gpu"`. Giữ nguyên quy tắc cận trên / 50% của T-072, giữ chỗ
  chỉ trong lúc bước chạy, `release()` ngay khi bước xong. Bước CPU giữ RAM/đĩa và **một slot CPU**: thêm tài nguyên
  `cpu` vào `RESOURCES` với `capacity = cpu_count`, mỗi bước CPU khai `required.cpu = luồng nó dùng` (prepare: 4;
  finalize: 2; collider: 2), bước GPU khai `cpu = cpu_count // STUDIO_WORKERS` (COLMAP) — thay cho C1 của T-072.
- Executor: bảng `STEP_EXECUTORS = {"prepare": _execute_prepare, "preview": _execute_preview, …}` bọc các hàm hiện có
  trong `runner.py`; mỗi executor nhận `_Attempt` dựng từ job + workspace riêng của bước
  (`<worker_root>/<job_id>/<step_id>-attempt-<n>`; `resume/` dùng chung như nay). Hàm `run_video_job` và họ hàng giữ lại
  làm đường chạy "một mạch" cho `--once` và test, nhưng không còn được `_dispatch` gọi.

### 4. Trạng thái cho người dùng và API

- `JobManifest.status/current_stage` vẫn là nguồn hiển thị; `record_stage_progress` gọi khi bước bắt đầu. Thêm vào
  `JobProgressView`: `steps: [{step_id, kind, state, waiting_on, started_at, finished_at}]` để `ProgressTab` hiện dòng
  "Đang chờ GPU trống" / "Đang chờ CPU" đúng bước, và thời gian từng bước.
- `GET /api/v1/gpu/status` thêm `pending_gpu_steps`, `pending_cpu_steps`.

### 5. Bộ thuê máy và máy CPU

- `scan_scope` đếm bước `ready|claimed` theo `kind`: `pending` (GPU) và `cpu_pending`. Thuê pod theo số bước GPU
  đang chờ và VRAM yêu cầu, không theo số job. Pod không còn bước GPU chờ/chạy mà còn bước CPU thì vẫn giữ pod tới
  `GPU_IDLE_SECONDS` như nay (bước CPU trên pod vẫn cần ổ scratch và artifact đã tải).
- **[QUYẾT ĐỊNH]** Làn CPU trên máy API (e2-standard-2, 2 vCPU, 8 GB sau nâng cấp): chỉ nên nhận `collider_bundle` và
  thao tác nhẹ; `prepare` (giải mã video) và `canonical_geometry` (voxel) nặng CPU, để trên pod. Nếu muốn
  `prepare` chạy trước khi thuê pod (tiết kiệm phút GPU), cần máy CPU riêng 4–8 nhân; đề xuất để sau khi có số đo.

### 6. Lộ trình làm (mỗi bước xanh test rồi mới sang bước sau)

1. Migration v27 + `StepPlanner` + `StepQueue` (không đổi hành vi: worker vẫn chạy theo lượt, chỉ sinh và cập nhật
   bước để quan sát). Deploy API + worker, so khớp bước với `StageId` trên vài job thật.
2. Worker nhận `prepare` và `preview` như hai bước riêng (bỏ T-072 B3 vì giữ chỗ giờ theo bước). Giữ `finalize` +
   `scene_extract` như một bước `gpu` tạm.
3. Tách `finalize` thành `canonical_geometry` (cpu) và `collider_bundle` (cpu), `scene_extract` (gpu) thành bước riêng.
4. Làn CPU nhận bước pipeline; `scan_scope` theo bước; giao diện `steps`.
5. Gỡ đường cũ trong `_dispatch` (giữ `run_*_job` cho test), cập nhật `docs/PIPELINE.md`, `ARCHITECTURE.md`.

### 7. Rủi ro và cách chặn

- **Hai worker cùng chạy một bước**: CAS + lease như job hiện nay; test `test_runner_claim_gap.py` mở rộng cho bước.
- **Artifact nửa chừng giữa hai bước** trên máy khác (sau này nhiều pod): mỗi bước `sync_up` artifact trước khi
  `done` (đã làm cho preview: `runtime_resolver.sync_up`), bước sau `sync_down`. Giai đoạn 1 chỉ một pod nên chưa
  gặp.
- **Số đo tài nguyên**: tool name không đổi nên số đo cũ vẫn dùng được; `PHASE_TOOLS` chuyển thành theo tool.
- **Thời gian**: 3–5 ngày; đụng lõi điều phối nên làm trên nhánh riêng, deploy sau khi chạy ba job thật trọn vẹn.

## Kiểm thử

- `tests/test_orchestration/test_step_queue.py` (mới): sinh bước cho ba loại job (video, video+LiDAR, dataset), chuyển
  trạng thái theo phụ thuộc, bước người dùng, hủy/skip, retry giữ bước đã xong, CAS claim.
- `test_resource_admission.py`: `admit_step` cho bước cpu/gpu, tài nguyên `cpu` slot, giữ chỗ chỉ trong lúc chạy.
- `test_prepared_queue.py` / `test_job_queue.py`: worker hai làn, bước GPU của job B chạy khi job A đang ở bước CPU
  (giả lập bằng executor stub ghi thứ tự).
- `tests/test_gpu/test_gpu_autoscaler*.py`: `scan_scope` theo bước.
- Frontend: `ProgressTab` hiện `steps`.
- Chạy thật: ba job bộ ảnh + một job video 5 phút trên một pod A5000; kỳ vọng GPU không rảnh quá 2 phút liên tục khi
  còn bước GPU chờ, và tổng thời gian bốn job ≤ 60% so với chạy lần lượt. Ghi `report.md`.

## Ngoài phạm vi
- Nhiều pod GPU cùng lúc (cần artifact sync giữa pod ở mọi bước; thiết kế đã chừa chỗ ở mục 7).
- Thay đổi thuật toán từng bước, preset (T-071), từ điển COLMAP (T-071 B).
