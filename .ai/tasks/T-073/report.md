# T-073: Báo cáo thực hiện (hàng đợi theo từng bước)

## Tóm tắt
Đã làm hàng đợi theo từng bước trên nhánh `develop`, chia thành 16 commit, chưa push. Không build image, không đụng production, `deploy/`, `.github/` hay Docker. Chủ dự án đã chốt: làn CPU trên máy API **không** nhận bước của pipeline; chỉ worker trên máy GPU chạy các bước.

Mục đích: job này đang ở bước cần CPU thì chỉ dùng CPU, job khác đang ở bước GPU thì dùng GPU; không job nào giữ cả hai khi chỉ dùng một.

## A. Bảng bước và cách sinh bước
- `src/services/orchestration/jobs/database.py`: migration v27 tạo bảng `r2s_job_steps`. Bảng có khóa chính `(job_id, step_id)` và các cột theo kế hoạch, thêm `started_at`, `finished_at`. Migration chỉ thêm bảng mới, dùng `IF NOT EXISTS`, nên chạy lại không lỗi và không đụng dữ liệu cũ.
- `src/services/orchestration/jobs/steps.py` (mới):
  - `plan_steps(job)` suy danh sách bước từ bản ghi job (JobManifest). Cùng một bản ghi thì luôn ra cùng một danh sách. Không đọc DB.
  - Các bước của job video: `prepare` (CPU) → `anonymization_review` (người dùng, chỉ khi có frame bị che) → `pose_visual` (GPU) → `metric_confirm` (người dùng) → `canonical_geometry` (CPU; GPU nếu máy đặt `product_geometry_gpu_index`) → `scene_extract` (GPU) → `view_lod` (GPU, ưu tiên thấp nhất, chạy sau khi job xong).
  - Job bộ ảnh đã có sẵn bộ frame thì không có bước `prepare`.
  - Trạng thái của bước: pending (chưa tới), ready (sẵn sàng, chờ máy), claimed (máy vừa nhận), running (đang chạy), done (xong), failed (lỗi), waiting_user (chờ bạn), skipped (bỏ qua).
- `src/services/orchestration/projects/persistence.py`: mỗi lần ghi một phiên bản mới của job (`save_job`), bảng bước được ghi lại trong **cùng một giao dịch DB**. Nhờ vậy bảng bước không bao giờ lệch khỏi bản ghi job.
  - Lỗi khi ghi bảng bước chỉ làm hỏng phần bảng bước (dùng savepoint), phần ghi job vẫn được lưu.
  - Mọi thao tác của người dùng đều tự cập nhật bảng bước qua đường này: hủy, thử lại, xác nhận tỉ lệ, chấp nhận bản đã che.
- Hủy job: mọi bước chưa xong thành `skipped`.
- Lỗi: bước đang chạy thành `failed`.
- Thử lại: chỉ bước lỗi được chạy lại (số lần chạy của bước tăng 1), các bước trước vẫn là `done`.
- Hết bộ nhớ: vẫn dùng cơ chế cũ (tự xếp lại một lần, chạy một mình trên GPU).

## B. Mỗi bước là một lượt chạy riêng
- Bước `prepare` (`run_prepare_step`): kiểm video, che mặt/biển số nếu bật, tách frame, rồi dừng. Job giữ trạng thái RUNNING ở bước tách frame, không máy nào giữ, chờ máy có GPU nhận bước dựng camera.
- Bước `pose_visual`: dùng lại `run_reviewed_preview_job` (mở rộng để nhận mọi job vừa chuẩn bị xong) và `run_prepared_job` (job đã có bộ frame).
- Bước `canonical_geometry` (`run_geometry_step`): chạy `finalize_cli` (REC-06, REC-05, bundle). Thành công thì ghi bundle bằng `record_geometry`; job giữ RUNNING ở `ST-RGB-GEOMETRY`, chờ bước tách vật. Lỗi thì job FAILED như cũ.
- Bước `scene_extract` (`run_scene_step`): tách vật từ bundle đã ghi, rồi kết thúc job (`record_scene_extract`). Tách vật lỗi vẫn không làm hỏng job, giống trước đây. Thử lại sau khi bước này bị ngắt thì chỉ chạy lại phần tách vật.
- Bước `view_lod` (`run_view_lod_step`): làm bản xem nhẹ cho các SOG lớn. Bước này được xếp sau khi job xong, chỉ máy có công cụ LOD mới nhận.
- `run_video_job` và `run_finalize_job` vẫn giữ để chạy tay và cho test, nhưng hàng đợi không gọi nữa.

## C. Xét tài nguyên theo bước
- `src/services/orchestration/jobs/admission.py`: thêm `admit_step` và `step_demand`.
  - Mỗi bước dùng số đo của **đúng công cụ của nó** (bảng `STEP_TOOLS` trong `processing/observed.py`).
  - Bước CPU giữ RAM, ổ đĩa và một số luồng CPU (`cpu_slots`), không giữ GPU.
  - Quy tắc của T-072 giữ nguyên cho bước GPU: dùng số đo của cấu hình nặng hơn làm cận trên; ước lượng nhỏ hơn 50% VRAM còn trống thì được chạy chung.
  - Chỗ giữ chỉ tồn tại trong lúc bước chạy, xong bước là trả.
- Số luồng CPU mỗi bước khai:
  - `prepare`: 4;
  - hình học: 2;
  - LOD: 1;
  - bước GPU: số nhân CPU chia cho (số worker GPU + 1), để luôn chừa chỗ cho một bước CPU chạy song song.
  - Bước khai nhiều luồng hơn cả máy thì được tính bằng đúng số luồng của máy, nên không bao giờ phải chờ mãi.

## D. Worker nhận bước theo làn
- `src/services/orchestration/jobs/worker_cli.py`: mỗi lượt quét, worker nhận **một bước**. Cách nhận:
  - đánh dấu bước "đã nhận" trong bảng bước, chỉ khi bước vẫn "sẵn sàng" và job chưa có phiên bản mới hơn;
  - vẫn giữ quyền chạy job (lease) như trước, nên hai máy không thể cùng chạy một job.
- Tham số `--lanes`:
  - mặc định `gpu,cpu`: nhận cả hai loại, ưu tiên bước GPU;
  - `--lanes cpu`: chỉ nhận bước CPU.
- Thứ tự xét: theo làn của worker, rồi theo hạng ưu tiên (người dùng vừa thao tác xong → job đã bắt đầu → job mới → bản xem nhẹ), rồi xoay vòng theo người gửi.
- `scripts/gpu/run_workers.py`: khởi động thêm `STUDIO_CPU_WORKERS` worker chỉ làn CPU (mặc định 1, đặt 0 để tắt). Mỗi worker biết tổng số worker GPU qua biến `R2S_GPU_WORKERS`.
- Khi worker khởi động, nó không đánh FAILED một job đang có máy khác giữ quyền chạy. Thư mục làm việc `scene-*` của bước tách vật được nhận diện như mọi thư mục làm việc khác.

## E. Bộ thuê máy, API và giao diện
- `gpu/workload.py::scan_scope`: thuê máy theo bước sẵn sàng của từng job.
  - Bước CPU cũng là lý do thuê máy GPU (vì làn CPU trên máy API không nhận bước pipeline).
  - Job đang chờ người dùng không thuê máy.
  - Bước `view_lod` không thuê máy.
- `GET /api/v1/gpu/status`: thêm `pending_gpu_steps` và `pending_cpu_steps`.
- `GET /api/v1/jobs/{id}/progress`: thêm danh sách `steps`. Job dừng giữa hai bước vẫn có vị trí trong hàng đợi; vị trí tính theo đúng thứ tự worker sẽ nhận.
- Giao diện:
  - Tab Tiến trình hiện từng bước: loại (CPU / GPU / Bạn), trạng thái ("Đang chờ GPU trống", "Đang chờ CPU trống", "Đang chạy", "Xong"…) và thời gian bước đã chạy.
  - Job dừng giữa hai bước không còn bị báo "mất kết nối".
- Tài liệu: cập nhật `docs/PIPELINE.md`, `docs/ARCHITECTURE.md`, `scripts/gpu/studio.env.example`.

## F. Kiểm thử (kết quả chạy thật)
- Test mới:
  - `tests/test_orchestration/test_step_queue.py`: sinh bước cho job video, job bộ ảnh, job có frame bị che; bước người dùng; hủy; thử lại; nhận bước bằng so-và-ghi; nhận bước quá hạn; job cũ chưa có dòng bước; hai làn chạy song song; bản xem nhẹ; API tiến trình; chạy trên cả SQLite lẫn PostgreSQL.
  - `tests/test_orchestration/test_step_runners.py`: bước hình học và bước tách vật tách riêng; điểm dừng sau bước chuẩn bị.
  - `tests/test_gpu/test_step_workload.py`: thuê máy theo bước, trạng thái GPU.
  - Thêm vào test có sẵn: `test_resource_admission.py` (bước CPU, luồng CPU), `test_runtime_migrations.py` (DB v26 có job đang chạy), `test_gpu_plan.py` (worker làn CPU).
  - Frontend: `studio-processing-steps.test.tsx`.
- Toàn bộ test backend (`pytest -q tests`): `4370 passed, 41 skipped` (12 phút 49 giây). Lệnh `pytest -q` chạy ở gốc repo dừng ngay vì không nạp được 5 file test trong `data/objectgs_runtime/`, không liên quan task này.
- Các test chạy trên PostgreSQL thật (container local): 38 đạt, 4 bỏ qua.
- `ruff check src tests scripts`: đạt. `ruff format --check src tests scripts`: 874 file đúng định dạng. Lệnh chạy trên cả repo (`ruff check .`) vẫn báo lỗi ở các file script chưa đưa vào git trong `.ai/reports` (`ruff format --check .` báo 31 file, phần lớn trong `docs/` và `.harness-core/`); task này không sửa các file đó.
- `check_contract_mirror`: PASS.
- Frontend: lint 0 lỗi (7 cảnh báo có từ trước); typecheck đạt; vitest 126 file, 1125 test đạt.

## Test cũ phải sửa và lý do
- `tests/integration/test_upload_to_prepared_job.py`, `tests/integration/test_studio_processing_job.py`: bước chuẩn bị và bước dựng camera giờ là hai lượt nhận riêng, nên test gọi `dispatch_next` hai lần.
- `test_runtime_migrations.py`: phiên bản schema mới nhất là 27.
- `test_unwatched_running_jobs.py`: trạng thái chờ có chủ ý cũ đổi tên `awaiting_reviewed_preview` → `awaiting_pose_step`, thêm `awaiting_scene_extract`.
- `test_job_queue.py`: vị trí hàng đợi theo thứ tự worker nhận bước.
- `test_capability.py`: test này đã lỗi khi chạy riêng ngay ở bản trước khi sửa, vì kết quả phụ thuộc thứ tự chạy test (phiên bản COLMAP được nhớ theo tiến trình). Đã thay hàm đó bằng bản giả trong test.

## Quyết định tự chọn hoặc chỗ kế hoạch mâu thuẫn
- Làn CPU trên máy API không nhận bước pipeline (chủ dự án chốt). Vì vậy bước CPU vẫn được tính là nhu cầu thuê máy GPU.
- Nhận gói LiDAR và odometry LiDAR vẫn nằm trong bước `pose_visual`, không tách thành bước riêng. Tách ra sẽ cần thêm một điểm dừng mới của job mà lợi ích nhỏ.
- Không tách `finalize` thành `canonical_geometry` + `collider_bundle` (kế hoạch cho phép): collider và USD nằm trong `finalize_cli`. Duyệt tách vật là hàng đợi scene có sẵn sau khi job xong.
- `STUDIO_CPU_WORKERS` mặc định là 1 thay vì một nửa số nhân CPU, để không có quá nhiều tiến trình cùng hỏi DB Supabase. Tăng lên khi số đo cho thấy bước CPU phải xếp hàng.
- Worker GPU ưu tiên bước GPU trước hạng ưu tiên, để GPU không phải ngồi chờ khi worker đang bận một bước CPU.
- Luồng CPU được ghi trong phần giữ chỗ (`cpu_slots`), không thêm "cpu" vào danh sách tài nguyên chính. Chờ luồng CPU không ghi bản chờ tài nguyên, nên định dạng dữ liệu cũ của giao diện không đổi; giao diện báo "Đang chờ CPU" từ trạng thái bước.
- Phát hiện lỗi có từ trước: sau bước chuẩn bị, job bị chuyển sang `ST-CAMERA-POSE`, nên bước chờ người dùng duyệt bản đã che (AUD-18) không bao giờ xảy ra trong pipeline thật. Đã sửa: job dừng ở `ST-FRAME-EXTRACT`.

## Chưa làm
- Chạy thật ba job bộ ảnh và một job video 5 phút trên A5000 để đo GPU rảnh và tổng thời gian: cần image mới và máy GPU.
- Nhiều máy GPU cùng lúc: ngoài phạm vi, giống kế hoạch.

## Job đang chạy dở lúc chuyển sang bản mới
- Không cần chạy bổ sung dữ liệu (backfill). Dòng bước của job cũ được tạo khi job có phiên bản mới, hoặc khi worker nhận bước. Màn tiến trình suy bước từ bản ghi job khi bảng chưa có dòng nào.
- Job đang chạy dở lúc đổi máy bị đánh FAILED (thử lại được) nhờ cơ chế hết hạn quyền chạy đã có. Bấm thử lại thì chỉ chạy lại từ bước đó.

## Việc phải làm khi deploy (đúng thứ tự)
1. Cho máy GPU chạy hết việc rồi tắt; không để máy chạy image cũ (v5) khởi động sau khi DB đã lên v27. Lý do: code cũ từ chối khởi động khi DB ở schema v27, và worker cũ đang chạy sẽ ngừng nhận việc vì không đọc được phần giữ chỗ mới.
2. Build image GPU từ `develop`, chứng nhận trên A5000, cập nhật danh sách image (release catalog) và secret của watchdog sang image mới.
3. Deploy API và Studio cùng lúc. Migration v27 tự chạy khi API kết nối DB lần đầu. Khởi động lại mọi tiến trình API, kể cả làn CPU và bộ điều khiển thuê máy.
4. Để bộ điều khiển thuê máy theo image mới. Nếu muốn, đặt `STUDIO_CPU_WORKERS` trong `worker.env` (mặc định 1, 0 là tắt).
5. Chạy ba job thử, ghi thời gian từng bước và thời gian GPU rảnh vào báo cáo này.

## Commit
a6960e3c, cf91f2d9, 9484b1b9, 65be17c5, 805dd82f, c283b726, 10f4cab7, abd31654, fc9d68d6, e071ecd5, 817e811d, 5988dfcb, 6a0a981d, 80679a78, 6df08446, 361af1e7.
