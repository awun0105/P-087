# Report T-040: Bỏ bước chép runtime manifest tay (Phần B)

## Trạng thái: IMPLEMENTED (chờ Summarizer)

Đã làm đủ 9 bước của "Phần B (đã duyệt)" trong `plan.md`, mỗi bước một commit có test. Chưa kiểm trên pod RunPod thật (xem "Việc còn dở").

**Cổng phụ thuộc:** plan ghi "Phần B cần T-036 accepted". Tại thời điểm làm, T-036 vẫn `changes-requested` (bước 4 trên máy chưa làm lại). Theo yêu cầu trực tiếp của bạn, tôi làm Phần B; phần T-036 mà Phần B dựa vào là tên biến `R2S_*` và thư mục đã commit ở `71eda154`, không đổi sau đó. Cổng này vẫn chưa được Architect đóng.

## Commit theo bước

| Bước | Commit | Nội dung | File chính |
|---|---|---|---|
| 1 | `418e1d2a` | `software_runtime_checksum` (bỏ `gpu_model`, `vram`, `nvidia_driver`); `ExecutionProfile` giữ cả hai checksum; worker nhận job theo checksum phần mềm **hoặc** checksum đầy đủ (job cũ) | `jobs/profile.py`, `jobs/dispatch.py`, `jobs/runner.py`, `projects/registry.py`, `tests/test_orchestration/test_software_runtime_identity.py` |
| 2 | `28487653` | Migration **22** `r2s_worker_runtimes`; worker công bố runtime lúc khởi động và mỗi nhịp heartbeat (300 s); chọn runtime sống theo TTL 15 phút | `jobs/database.py`, `jobs/worker_runtimes.py` (mới), `jobs/worker_cli.py`, `jobs/profile.py`, `tests/test_orchestration/test_worker_runtimes.py`, `test_runtime_migrations.py` |
| 3 | `c9126e77` | Chế độ `PRODUCT_RUNTIME_FROM_WORKERS=true`: API chọn runtime cho job mới từ worker; không có worker sống vẫn tạo job; cấu hình cho phép thiếu manifest ở API | `src/config.py`, `projects/registry.py` (`job_profile()`), `api/studio/scenes.py`, `api/studio/assemblies.py`, `api/studio/deps.py`, `tests/test_orchestration/test_worker_runtime_selection.py` |
| 4 | `24dc976a` | `waiting_for="runtime"` ("Đang chờ GPU") khi không có worker sống chạy được runtime của job | `jobs/progress.py`, `jobs/worker_runtimes.py` (`has_live_runtime`), `api/studio/scenes.py`, `frontend/.../lib/contracts/studio.ts`, `sceneStatus.ts`, `ProgressTab.tsx`, `frontend/tests/runtime-waiting.test.tsx`, `tests/test_orchestration/test_runtime_waiting.py` |
| 5 | `a4e32e0c` | Rebind job QUEUED chưa có stage sang runtime của worker đang sống; finalize chỉ chạy trên worker đúng runtime | `jobs/models.py` (`RuntimeRebound`), `projects/persistence.py` (`runtime_rebind`), `projects/registry.py` (`rebind_job_runtime`), `jobs/worker_cli.py`, `tests/test_orchestration/test_runtime_rebind.py` |
| 6 | `b8d4c53f` | Migration **23** `r2s_job_leases`; lease theo attempt (TTL 10 phút, gia hạn 60 s), fencing trong cùng transaction với ghi revision; lease hết hạn → FAILED retryable ở bất kỳ máy nào | `jobs/database.py`, `jobs/lease.py` (mới), `projects/persistence.py` (`fence`), `jobs/runner.py` (dừng tiến trình con khi mất lease), `jobs/worker_cli.py`, `tests/test_orchestration/test_job_lease.py`, `test_runtime_migrations.py` |
| 7 | `c5086dc1` | Số đo ghi runtime phần mềm của **máy đã chạy** (`machine_runtime_checksum`), thay checksum của job; áp dụng ở runner và tách vật | `jobs/profile.py`, `jobs/runner.py`, `scene/objectify_queue.py`, `tests/test_orchestration/test_machine_runtime_provenance.py` |
| 8 | `47d15732` | Autoscaler chỉ đếm việc GPU mới chạy được: job có runtime đang sống, hoặc job chưa có stage (sẽ được gắn lại); job có stage trên runtime đã mất không đếm | `scripts/cloud/gpu_autoscaler.py` (`runnable_waiting`), `jobs/worker_runtimes.py` (`live_runtime_checksums`), `tests/test_gpu/test_gpu_autoscaler_runtime.py` |
| 9 | `30889790` | API bật `PRODUCT_RUNTIME_FROM_WORKERS=true` trong file mẫu, OVERVIEW bỏ bước chép manifest; checker không đòi manifest ở API khi bật chế độ worker | `deploy/studio/OVERVIEW.md`, `deploy/studio/README.md`, `deploy/studio/production.env.example`, `deploy/studio/api.env.example` (sinh lại), `scripts/studio/deploy_env.py`, `tests/test_packaging/test_deploy_env.py` |

Migration: `LATEST_SCHEMA_VERSION` 21 → **22** (bước 2, kiểm lại ngay trước commit) → **23** (bước 6). Test ghim số schema đã cập nhật đúng hai lần.

## Kiểm chứng

**Lệnh và kết quả thật:**

- Full backend, một lần: `.venv/bin/python -m pytest tests -q -p no:cacheprovider` → **3803 passed, 30 skipped, 1 failed**, 709.97 s.
  - Lỗi duy nhất: `tests/test_runtime_env_names.py::test_no_legacy_runtime_name_is_left_outside_the_rename_table`. Nguyên nhân: 14 dòng `REC*_` trong **`Makefile.studio` ở bản làm việc chưa commit** (đã `M` từ đầu phiên, không do T-040). HEAD của file này có 0 dòng `REC*`, và không commit T-040 nào đụng tới `Makefile.studio`. Tôi **không** sửa file này: đưa về HEAD là việc của T-036 (ghi trong `T-036/report.md`, mục "Bước 4 làm lại"). Lỗi này còn đó cho tới khi file được xử lý.
  - Lần chạy đầu không giới hạn đường dẫn (từ gốc repo) lỗi ở collection của `data/objectgs_runtime/` (bản clone có sẵn, không thuộc T-040). Đã chạy lại chỉ trên `tests/`.
- `tests/test_orchestration` (sau bước 7–8): **1164 passed**. Các bước trước đó đã chạy toàn bộ `tests/test_orchestration` và `tests/test_api` (422 passed sau bước 3).
- Test PostgreSQL: các tham số `[postgres]` của `runtime_database_url` **chạy thật** (không skip) nhờ `R2S_TEST_POSTGRES_URL` trong `.env`. Giá trị URL không ghi ở đây.
- `tests/test_gpu` (autoscaler): 19 passed.
- `tests/test_packaging`: 84 passed (gồm test đóng gói đã sửa).
- Frontend: `vitest run` trên `runtime-waiting` (4), `progress-objectify` (17) và `anonymization-review` (5) → 26 passed; `npm run typecheck` → exit 0.
- Ruff check + format-check trên 28 file Python đã đổi trong T-040: sạch.
- `graphify update .`: chạy xong, `graphify-out/` không nằm trong git nên không có thay đổi cần commit.

**Test mới đỏ trên code cũ:**

- Bước 1 đã kiểm thật: chạy test trong worktree tạm ở `HEAD` (trước bước 1) → lỗi `ImportError: software_runtime_checksum` (đỏ). Worktree đã xoá.
- Bước 5 đã kiểm: commit `a4e32e0c` chạy lại trong worktree tạm → 92 passed, 7 skipped (skip là tham số PostgreSQL vì worktree không có `.env`).
- Các bước còn lại: module hoặc hàm mới chưa tồn tại ở commit trước, nên test sẽ lỗi import/thiếu thuộc tính. Tôi **chưa chạy lại từng test trên commit trước** để xác nhận; ghi đây là khoảng trống.

**Đột biến (mutation) kiểm tra test có bắt lỗi thật không:**

- Bỏ kiểm runtime ở finalize (bước 5) → `test_finalize_runs_only_on_a_worker_with_the_job_runtime` đỏ.
- Bỏ điều kiện "chưa có stage" ở phía worker (bước 5) → test **không** đỏ, vì lớp persistence `_require_runtime_rebind` vẫn chặn. Đây là phòng thủ hai lớp, và `test_rebind_uses_revision_cas` / `test_job_with_stage_artifacts_is_never_rebound` đi qua lớp persistence.
- Bỏ fencing trong `save_job` (bước 6) → `test_worker_that_lost_its_lease_cannot_write_revisions` đỏ.
- Bỏ gia hạn lease (bước 6) → `test_renewal_keeps_a_running_attempt_alive_past_the_plain_ttl` đỏ.

Các đột biến được khôi phục ngay và đã xác nhận file trở về đúng nội dung.

**Frontend:** `eslint` không được cài trong `frontend/node_modules` (`npm run lint` sẽ lỗi). **Chưa lint frontend.**

## Quyết định lệch plan hoặc diễn giải

1. **Cổng T-036**: nêu ở đầu report.
2. **Bước 2, "config_checksum khớp file config của worker"**: diễn giải là worker chỉ công bố khi băm lại file cấu hình vẫn bằng giá trị lúc khởi động (`publisher`); API chọn runtime theo config checksum của chính nó.
3. **Bước 2, khoá của bảng**: `software_runtime_checksum` là PRIMARY KEY (theo Q3). Hệ quả: hai worker cùng checksum phần mềm nhưng khác config hoặc seed ghi đè nhau trên một dòng. Chấp nhận, vì mọi máy trong một deployment dùng cùng config; ghi làm giới hạn.
4. **Bước 4, nội dung hiển thị**: `WaitingFor` không có trường runtime nên UI **không** hiện id runtime (plan ghi "(runtime …)"). Thêm trường vào contract là việc riêng.
5. **Bước 4, thứ tự ưu tiên**: `runtime` chỉ hiện khi job **không** có snapshot chờ tài nguyên (`resources is None`). Lý do: snapshot chỉ do worker đang sống ghi, nên đã có máy xét job. Một test cũ (`test_progress_api_reads_durable_wait_snapshot`) bắt được hồi quy này khi chạy full suite.
6. **Bước 5, tên trường event**: `from_checksum` / `to_checksum` thay vì `from` / `to` (`from` là từ khoá Python). Plan ghi `{from, to, reason}`.
7. **Bước 5, UI**: câu báo cho job đã có stage nói "Nếu phiên bản đã đổi, job này cần chạy lại từ đầu" (không khẳng định chắc chắn, vì worker có thể chỉ mất tạm thời quá TTL). Nút "Chạy lại từ đầu": **không làm** — không có đường sẵn để chạy lại job chưa thất bại (plan yêu cầu ghi lại và để Architect lập task).
8. **Bước 6, nơi lưu lease**: bảng riêng `r2s_job_leases` (migration 23), không thêm cột vào `r2s_jobs`/`JobManifest`, để không đổi contract. Lease giữ quanh mỗi lần gọi runner trong `_dispatch` (phủ cả bốn đường: prepared, video, reviewed-preview, finalize).
9. **Bước 6, mã lỗi**: dùng `INTERRUPTED_SHUTDOWN` (đã có chính sách retry) thay vì mã mới.
10. **Bước 6, dừng tiến trình con khi mất lease**: đi qua vòng theo dõi tool trong `_run_tool` (cờ `lease_lost`). Đường này **không có test riêng** (chỉ kiểm cờ và fencing).
11. **Bước 9, phạm vi mở rộng**: plan chỉ nói OVERVIEW.md. Tôi cũng sửa `deploy_env.py`, `production.env.example`, `api.env.example` (sinh lại bằng `render --examples`), `deploy/studio/README.md` và test đóng gói. Lý do: tiêu chí chấp nhận 1 ("deploy không còn chép manifest tay") không đạt nếu checker vẫn đòi `PRODUCT_RUNTIME_MANIFEST` trên API.
12. **Bước 7**: thêm `machine_runtime_checksum` vào `profile.py`; áp dụng ở `runner._resource_sampler` và `objectify_queue._scene_sampler`.

## Việc còn dở và rủi ro

1. **Job RUNNING có sẵn lúc deploy (tạo trước migration 23, không có lease)**: lease không tự đưa chúng về FAILED. `recover_interrupted_jobs` chỉ xử lý trên cùng máy. Cần một lần xử lý khi deploy (xem câu hỏi 1).
2. **Chưa kiểm trên pod RunPod thật**: tiêu chí 2 ("đổi pod khác GPU, job mới chạy ngay, không restart API") và tiêu chí 1 mới được kiểm bằng test và tài liệu. Việc này thuộc T-039 / T-042.
3. **`PRODUCT_INPUT_RUNTIME_REGISTRY` vẫn chép tay** lên volume của API: ngoài phạm vi T-040, cần task riêng để bỏ.
4. **`Makefile.studio` trong bản làm việc còn tên `REC*`**: làm test `test_no_legacy_runtime_name...` đỏ trên cây hiện tại. Thuộc T-036.
5. **Frontend chưa lint** (eslint chưa cài).
6. **Giới hạn khoá bảng** (mục 3 ở trên).
7. **Hai lớp kiểm rebind**: nếu ai sửa `_require_runtime_rebind` trong persistence, bảo vệ job đã có stage mất một lớp; test `test_rebind_uses_revision_cas` và `test_job_with_stage_artifacts_is_never_rebound` cần được giữ.

## Câu hỏi cho Architect

1. **Job RUNNING cũ lúc deploy**: có làm một lần khi deploy không (ví dụ đánh dấu FAILED retryable những job RUNNING không có dòng lease và có sự kiện cũ hơn TTL)? Nếu không, một số job có thể kẹt im lặng đúng ở lần nâng cấp đầu tiên.
2. **Nút "Chạy lại từ đầu"** cho job đã có stage mà runtime không còn máy nào: tạo task riêng?
3. **Cổng T-036**: có chấp nhận Phần B đã làm trước khi T-036 accepted, hay cần đóng T-036 (làm lại bước 4 và sửa `Makefile.studio`) trước khi T-040 được coi là accepted?
4. **Khoá bảng `r2s_worker_runtimes`**: có cần thêm config và seed vào khoá (một dòng cho mỗi cặp) thay cho việc ghi đè?
5. **`PRODUCT_INPUT_RUNTIME_REGISTRY`**: có tạo task để bỏ chép tay không?
