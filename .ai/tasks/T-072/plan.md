# T-072: Ba worker chạy song song thật — chia sẻ GPU theo cận trên đo được, chỉ giữ GPU khi bước GPU chạy

Yêu cầu của chủ dự án (2026-10-20): máy thuê A5000 (24 GB VRAM, ≥32 GB RAM, 7 nhân CPU, `STUDIO_WORKERS=3`) phải
chạy tối đa và song song, chỉ cần không tràn VRAM. Hiện ba job bộ ảnh (cup, chinsu, flower) xếp hàng dù GPU còn trống
18,8 GB. Task này là các việc nhanh (≈1,5 ngày + một lần build/chứng nhận image GPU); hàng đợi theo từng bước là T-073.

Kết quả rà soát làm căn cứ (không sửa code trong phiên rà soát):

- `ResourceAdmission._demand` (`src/services/orchestration/jobs/admission.py:343`) lọc số đo bằng
  `usage.params == observation_params` trước khi gọi `observed_budget`, trong khi `observed_budget`
  (`processing/observed.py:126`) đã hỗ trợ `dominates()` (lượt chạy nặng hơn ở mọi thông số = cận trên). Vì bị lọc
  trước, mọi cấu hình chưa có số đo **trùng khớp** đều `measured=False` → `_assess` đặt `exclusive=True` → VRAM khả
  dụng của worker khác bị coi là 0 (`admission.py:716`). Chỉ cần đổi một ô thông số là thành cấu hình mới.
- Worker giữ chỗ cho cả "lượt": `_dispatch` (`jobs/worker_cli.py:305`) gọi `admission(job)` trước `run_video_job`,
  và `run_video_job` (`jobs/runner.py:1660`) chạy `prepare` (CPU: kiểm tra video, tách khung, che mặt) → LiDAR →
  `preview` (GPU: COLMAP + Brush + đề xuất tỉ lệ) trong một lần giữ chỗ; `admission.release()` chỉ gọi khi không còn
  việc (`worker_cli.py:682`). GPU bị coi là bận suốt bước CPU.
- `Reservation.gpu_required` và `Demand.gpu_required` đã có (dùng cho thao tác chỉ CPU), `_assess` đã bỏ qua VRAM khi
  `gpu_required=False`. Nền để tách giữ chỗ CPU/GPU đã sẵn.
- COLMAP được cấp `num_threads = min(colmap_max_threads=16, cpu_count)` khi tạo job (`processing/config.py:
  build_job_config`), tức 7 luồng trên máy 7 nhân; ba job cùng COLMAP = 21 luồng trên 7 nhân.
- Bước kiểm tra video mất 21 phút cho video 5 phút đã được vá ở commit `ae7e3aca` (bốn lượt giải mã chạy cùng lúc)
  nhưng image GPU production hiện tại (catalog v4, build từ `1b86b5f3`) chưa có bản vá này.
- `expected_duration` / hạn tự tính không thay đổi trong task này.

## Thiết kế

### A. Chạy chung GPU khi chưa có số đo trùng khớp

A1. **Cận trên từ số đo cấu hình nặng hơn.** Trong `_demand`, bỏ bộ lọc `usage.params == observation_params`; truyền
thẳng `usages` cho `observed_budget` để `dominates()` áp dụng. Ghi lại nguồn:
- `Demand` thêm `measured_scope: Literal["exact", "upper_bound", "estimate"]`; `measured = measured_scope != "estimate"`.
  `exact` khi có ít nhất một lượt `usage.params == observation_params` cho mọi tool của phase; `upper_bound` khi chỉ có
  lượt dominating. `ResourceWait.estimate_scope` thêm giá trị `"upper_bound"` (giao diện hiện "theo số đo của cấu hình
  nặng hơn").
- Giữ nguyên quy tắc: thiếu số đo của **bất kỳ** tool bắt buộc trong `PHASE_TOOLS[phase]` → không có budget.
- Sửa comment tại `admission.py:371` cho đúng lý do mới.

A2. **Biên an toàn cho cấu hình chưa có cận trên.** Hằng `UNMEASURED_SHARE_RATIO = 0.5` ở đầu `admission.py`.
Trong `_assess`, sau khi tính `available`, nếu `exclusive and isinstance(demand, Demand) and gpu_required and not
demand.exhausted and available["vram"] is not None and demand.required_gb["vram"] <= available["vram"] ×
UNMEASURED_SHARE_RATIO` thì `exclusive = False`. `Demand` thêm `exhausted: bool = False`, gán từ
`exhausted_before(usages, job.job_id)` trong `_demand` (job từng hết bộ nhớ vẫn chạy một mình như cũ).
- Thứ tự ưu tiên: có cận trên đo được (A1) thì không cần A2; A2 chỉ áp cho `measured_scope == "estimate"`.
- `available["vram"]` đã trừ phần worker khác giữ; peer đang `exclusive` vẫn làm `available = 0` → không chen vào job
  đang đo một mình.

A3. `shares_gpu()` (dùng cho sampler, `runner.py:438`) không đổi: job chạy chung thì số đo theo PID vẫn đúng; job chạy
chung mà không đo được theo PID thì `usage_vram` trả None và không thành số đo — giữ nguyên.

### B. Chỉ giữ GPU khi bước GPU chạy ("Mức 1")

B1. Thêm phase `"prepare"` vào `Phase` (`processing/observed.py:27`) với `PHASE_TOOLS["prepare"] = ("prepare",)`,
`PHASE_OPTIONAL_TOOLS["prepare"] = ()`. `_demand(job, "prepare", …)` trả `Demand(gpu_required=False)` với RAM/đĩa
theo số đo tool `prepare` nếu có (cận trên theo A1), không thì theo `estimate_gb` (RAM = `ram` ước lượng, VRAM bỏ qua).

B2. `ResourceAdmission` thêm hai hàm:
- `acquire_gpu(job, phase: Literal["preview","finalize"]) -> bool`: như `__call__` nhưng **nâng** giữ chỗ hiện có của
  worker này (cùng `worker_id`) từ `gpu_required=False` lên giữ chỗ GPU với demand của phase; dùng `_decide` với
  `others` đã loại bản ghi của chính mình. Không được nhận thì ghi `ResourceWait` như cũ (job đang RUNNING vẫn có
  `resource_wait`), giữ nguyên giữ chỗ CPU.
- `release_gpu(job)`: hạ giữ chỗ về `gpu_required=False`, `gpu_uuid=None`, `exclusive=False`, `required_gb` chỉ còn
  RAM/đĩa của phase CPU kế tiếp (hoặc giữ nguyên RAM/đĩa hiện có).

B3. Luồng trong worker:
- `_dispatch`: với job chưa có frame set → `admission(job, "prepare")` thay vì `admission(job)`; với job đã có frame
  set, `awaiting_reviewed_preview`, `awaiting_finalize` → giữ như cũ (phase GPU ngay từ đầu).
- `run_video_job`: sau `_execute_prepare` (và LiDAR ingest, vẫn CPU) và trước `_execute_preview`, gọi
  `gate.acquire_gpu(attempt.job, "preview")` trong vòng lặp: chưa được thì ghi sự kiện tiến trình
  `waiting_gpu` (xem B5), ngủ `product_queue_poll_seconds`, kiểm tra hủy job (`registry.get_job` đổi revision → thoát
  như `_run_tool` làm), làm mới lease (xác nhận `attempt_lease` làm mới trong thread nền; nếu không thì gọi làm mới
  trong vòng lặp). Hết `product_gpu_wait_timeout_seconds` (mới, mặc định 7200) → job về QUEUED với lý do chờ GPU, không
  FAILED.
- `VideoRunner` Protocol nhận thêm `gate: ResourceAdmission | None = None`; `dispatch_next` truyền `admission` vào
  `video_runner`. Runner cũ gọi không có `gate` (test) thì bỏ qua bước chờ.
- Sau `_execute_preview` xong (thành công hay lỗi) không cần `release_gpu` riêng: `_dispatch` trả về và `worker_cli`
  gọi `admission.release()` ở lượt kế tiếp như hiện nay. **Nhưng** phải `release()` ngay khi job chuyển sang chờ người
  dùng (xác nhận tỉ lệ, duyệt tách vật) — kiểm tra `worker_cli.py:682` đã làm điều này khi `handled=True` chưa; nếu
  `release()` chỉ gọi khi `not handled`, thêm `admission.release()` ngay sau mỗi `_leased_call` kết thúc.

B4. Phase `finalize` giữ nguyên là GPU (canonical + voxel + tách vật thể trong một lượt); tách CPU/GPU của finalize là
việc của T-073.

B5. Giao diện: `ProgressTab.tsx` đã đọc `resource_wait`; thêm trạng thái "Đang chờ GPU trống" khi job RUNNING ở bước
`ST-FRAME-EXTRACT`/`ST-LIDAR-*` có `resource_wait` với `waiting_on` chứa `vram`. Chữ: "Đã tách khung hình xong. Đang
chờ GPU trống để dựng camera và 3D (ước lượng cần {x} GB, đang trống {y} GB)". Không hiện đồng hồ đếm ngược.

### C. Chia luồng CPU theo số worker

C1. `scripts/gpu/run_workers.py` (sinh N worker) đặt biến môi trường `STUDIO_WORKER_COUNT=N` cho từng worker (nếu chưa
có). `resolve_job_processing` (`jobs/dispatch.py`) khi dựng `ColmapConfig` đặt
`num_threads = max(2, (os.cpu_count() or 4) // STUDIO_WORKER_COUNT)` thay cho giá trị trong config đã niêm phong.
Lý do: `num_threads` là tham số máy, không phải tham số chất lượng; cấu hình niêm phong của job (`config_checksum`)
không đổi.
C2. `ColmapConfig.checksum()` nằm trong khóa resume cache (`colmap.py:108`). Để số luồng không làm lệch khóa, loại
`num_threads` và `use_gpu` khỏi phần hash: thêm `exclude_from_checksum = ("num_threads",)` và hash
`canonical_json_bytes(self.model_copy(update={"num_threads": 0}))`. Ghi rõ trong docstring. (Giữ `use_gpu` trong hash
vì GPU/CPU SIFT cho kết quả khác.)
C3. Brush và tách khung hình: không đổi (Brush dùng GPU; ffmpeg giải mã đã đơn luồng mỗi lượt sau `ae7e3aca`).

### D. Đưa bản vá kiểm tra video vào image

`ae7e3aca` phải nằm trong commit dùng để build image GPU của task này. Chứng nhận ghi thời gian bước `prepare` cho
video 5 phút (kỳ vọng < 6 phút trên A5000).

## Kiểm thử

- `tests/test_orchestration/test_resource_admission.py`:
  - cấu hình mới trên GPU 24 GB với lượt đo của cấu hình nặng hơn → `measured_scope == "upper_bound"`, không
    `exclusive`, `required_gb` = số đo đó;
  - không có lượt nào dominating, ước lượng 2,67 GB, trống 23,5 GB → không `exclusive`; ước lượng 13 GB, trống 23,5 →
    `exclusive`;
  - job từng hết bộ nhớ → `exclusive` dù ước lượng nhỏ;
  - peer đang `exclusive` → vẫn chờ;
  - `admission(job, "prepare")` giữ chỗ `gpu_required=False`, không chặn worker khác dùng VRAM;
  - `acquire_gpu` nâng giữ chỗ cùng `worker_id`, ghi `ResourceWait` khi thiếu, `release_gpu` hạ về CPU;
  - test cũ `test_unmeasured_job_runs_alone_and_blocks_sharing` đổi thành máy 4 GB (ước lượng 2,67 > 50% của 3,8).
- `tests/test_orchestration/test_prepared_queue.py` / `test_job_queue.py`: `dispatch_next` truyền `gate`, job chờ GPU
  giữa chừng ghi sự kiện và tiếp tục khi GPU trống (giả lập bằng monkeypatch `_resource_snapshot`).
- `tests/test_reconstruction/test_rec03_colmap.py`: `ColmapConfig.checksum()` không đổi khi `num_threads` đổi.
- Frontend `scene-progress*.test.tsx`: trạng thái "Đang chờ GPU trống".
- Chạy thật trên A5000: ba job bộ ảnh cùng lúc; kỳ vọng: job 2 bắt đầu COLMAP trong khi job 1 đang Brush; log
  `r2s_resource_reservations` có hai bản ghi `gpu_required=True` không `exclusive`; không job nào OOM.

## Thứ tự làm và đưa lên

1. A1 → A2 → C → B (B lớn nhất, làm sau khi A và C xanh).
2. Build image GPU từ commit cuối (có `ae7e3aca`), chứng nhận A5000, catalog v5, worker.env thêm
   `PRODUCT_GPU_WAIT_TIMEOUT_SECONDS=7200` nếu muốn khác mặc định, cập nhật secret watchdog, push theo
   `prod-deploy-gcp-vm`.
3. Ghi `report.md`: số đo ba job chạy song song (thời gian từng bước, VRAM đỉnh), so với chạy lần lượt.

## Ngoài phạm vi
- Tách finalize thành CPU/GPU, hàng đợi theo từng bước, làn CPU trên máy API: T-073.
- Thay đổi preset/ước lượng: T-071.
