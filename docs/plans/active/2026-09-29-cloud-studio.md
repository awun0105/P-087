# Execution Plan: Cloud Studio (Vercel + Railway + Supabase + R2 + Vast.ai/RunPod)

Date: 2026-09-29

## Status

Active — chưa bắt đầu code. Bắt đầu sau khi docs quyết định được merge vào `develop`.

## Outcome

Người dùng mở Web UI host riêng, đăng nhập theo role, upload video thẳng lên kho file;
GPU thuê tự bật xử lý rồi tự tắt; trình duyệt xem bản scene nhẹ vừa sức máy. Làm được
đến đâu dùng đến đó; fallback demo là stack một máy GPU hiện có.

## Context

- Quyết định: [ADR 0003](../../decisions/0003-cloud-architecture-roles-and-browser-budget.md)
  (kiến trúc, role, ngân sách trình duyệt, chi phí), [ADR 0002](../../decisions/0002-studio-mvp-video-to-3dgs.md)
  (Studio MVP), [ADR 0001](../../decisions/0001-metric-scale-strategy-and-roadmap.md) (metric scale).
- Nền hiện có: plan [MVP Studio](2026-09-29-mvp-studio-demo.md) Phase 0–8.
- Authority: PRD §3.4 (quyền), NFR-04/05; `ARCHITECTURE.md` §Deployment/Database;
  Contract (artifact URI + checksum, journal, CAS).
- EX-SCENE và EX-SIM chưa push code; Isaac Sim/SceneObject là hướng theo kế hoạch,
  chưa thuộc lát cắt này.

## Scope

In: phase 1–11 dưới đây. Out (sau, nhưng làm hết sức nếu còn thời gian): phase 12–14.
Không đổi schema shared contract khi chưa có producer/consumer review.

## Approach — phases

1. **Kiểm khả thi GPU thuê (làm đầu tiên).** Cùng một Docker image, thuê instance rẻ
   trên **Vast.ai (chính)** và **RunPod (dự phòng)**; kiểm Vulkan trong container (Brush
   `--version` + train ngắn, Dawn WebGPU cho SOG), COLMAP cài native (không Docker lồng);
   đo thời gian khởi động, thời gian + giá job mẫu. Vast không đạt → RunPod thành chính
   (ghi amendment ADR 0003).
2. **Kho file R2.** Backend S3 sau `ArtifactResolver` (URI `artifact://` giữ nguyên),
   presigned GET/PUT, multipart upload, CORS bucket, lifecycle xóa file trung gian.
3. **Postgres + migration.** Chuỗi migration theo `r2s_schema.version` (ADR 0003 §5),
   test trên SQLite và Postgres; deploy lên Supabase qua pooler Supavisor (session mode);
   `/health` truy vấn DB + tác vụ nền hằng ngày giữ Supabase không tạm dừng (Amendment 3).
4. **Upload thẳng.** API cấp link multipart; client upload, nối lại khi rớt mạng;
   bỏ route proxy upload của Next; `ffprobe` kiểm nhanh trước khi xếp hàng.
5. **Tách worker GPU.** Worker nhận job/báo tiến trình/commit qua server điều khiển,
   tải input và đẩy artifact qua R2; Docker image GPU ghim version; tự tắt khi rảnh;
   server tạo instance qua **adapter nhà cung cấp** (Vast.ai chính, RunPod dự phòng:
   tạo / hủy / trạng thái, lọc host theo độ tin cậy và trần giá) khi có job; instance
   dùng-xong-hủy vì dữ liệu nằm ở Postgres + R2.
6. **Đăng nhập + 2 role** (ADR 0003 §3): users/invites/audit_log, cookie phiên, kiểm
   quyền theo route, hạn mức; khách chỉ dùng video mẫu.
7. **Ngân sách trình duyệt:** LOD nhẹ/vừa/đầy đủ, client tự chọn và tự hạ theo FPS,
   ảnh bìa + video xoay render trên GPU.
8. **Benchmark / metric** (mục 9 bên dưới): ghi số đo mỗi job, script tổng hợp.
9. **Giám sát + chống đốt tiền** (mục 7 bên dưới).
10. **Kiểm thử GPU + E2E sau deploy** (mục 10 bên dưới).
11. **Deploy + chuẩn bị demo:** Vercel/Railway/Supabase/R2/Vast.ai (+ RunPod dự phòng); video mẫu lên R2; tài khoản
    Editor và Reviewer demo; bật GPU trước buổi demo; checklist fallback.
    DevOps theo sổ tay (`docs/guide/chapter-09.md` tiêu chí DevOps): Docker Compose nhiều
    service (API, worker, frontend, Postgres, MinIO cho local), Dockerfile riêng cho GPU
    worker, `/health`, Live URL trong README, Sentry + UptimeRobot (mục 7).
12. Hợp nhất UI P0 đầy đủ (sửa object, validation, review) vào Studio.
13. Chỉnh sửa gửi dạng lệnh về server (phụ thuộc khả năng lấy thao tác từ SuperSplat).
14. Tên miền riêng (Vercel đã có HTTPS).

## Notes theo từng vấn đề đã thảo luận (2026-09-29)

### Video lỗi và hướng dẫn quay (mục 5 — để sau, ghi chú)

- Tạm thời: hộp ghi chú trên trang upload — quay chậm, đủ sáng, camera đi dọc lối,
  tránh xoay tại chỗ, tránh bề mặt trơn/phản chiếu, 30–120 giây.
- Sau: thông báo lỗi theo stage bằng lời dễ hiểu (vd COLMAP đăng ký < N% ảnh →
  "video rung hoặc lướt nhanh"); tự thử lại một lần với cấu hình khác (tăng
  `sample_fps`, `sequential_overlap`) trước khi báo thất bại.

### Dữ liệu cá nhân (mục 6)

- Điều khoản sử dụng ngắn khi upload; nút xóa video/scene (xóa artifact + ghi audit);
  tự xóa dữ liệu sau N ngày (R2 lifecycle + job dọn DB).
- Sau: bước xóa/mask người và inpainting môi trường trong giai đoạn 3DGS, dùng
  Spirula Studio làm tham khảo code/thuật toán (kiểm license trước khi adapt).

### Giám sát và giới hạn chi phí (mục 7 — cách tiện nhất)

- Vast.ai: nạp trước số tiền nhỏ, tắt auto-recharge; RunPod: đặt spending limit. Worker
  tự yêu cầu hủy instance (qua server → adapter) khi hàng đợi rỗng 10 phút; server có
  job dọn dẹp hủy instance không còn heartbeat để tránh máy mồ côi tính tiền.
- Worker heartbeat: bảng `r2s_workers` đã có; server kiểm định kỳ, quá 15 phút không
  heartbeat mà còn job RUNNING → đánh dấu lỗi + gửi cảnh báo qua Discord/Slack webhook
  (một biến môi trường URL, không cần dịch vụ giám sát riêng).
- Postgres (Supabase Free): không dựa vào backup của gói Free; tác vụ nền trong API chạy
  `pg_dump` hằng đêm đẩy lên R2 (giữ 7 bản). Giữ thức: `/health` chạy `SELECT 1` (UptimeRobot
  5 phút/lần) + tác vụ nền chạm DB mỗi ngày; theo dõi email cảnh báo tạm dừng của Supabase.
- Giới hạn tần suất: hạn mức theo tài khoản trong DB (job/ngày, GB) là lớp chính;
  thêm giới hạn request theo IP ở middleware FastAPI cho route đăng nhập/upload.
- Log: stdout JSON có `job_id`, `stage`, `attempt` — Railway/Vast.ai/RunPod đều xem được.
- **Sentry** (gói Developer miễn phí: 5.000 lỗi/tháng, 1 user, lưu 30 ngày): `sentry-sdk`
  cho FastAPI + worker, `@sentry/nextjs` cho frontend; tắt gửi PII, không gửi nội dung
  video/artifact; DSN qua biến môi trường. Kiểm license trước khi thêm dependency.
- **UptimeRobot** (miễn phí: 50 monitor, 5 phút/lần, 1 trang trạng thái): ping `/health`
  của API và trang chủ Web UI; cảnh báo email khi sập. Railway/Vercel không ngủ nên chỉ
  dùng để cảnh báo + bằng chứng uptime; `/health` không được bật GPU.
- **CI:** workflow đã có job Python + frontend, nhưng runner GitHub Actions do bot của ban
  tổ chức quản lý đang bị chặn billing (từ 26/09) — ngoài quyền của nhóm. Trước mỗi merge
  chạy cùng các bước ở local/checkout sạch và ghi kết quả vào PR.

### Database (mục 8)

Theo ADR 0003 §5: migration có thứ tự trong code, chạy trong transaction, test trên
SQLite + Postgres, không drop/reset; backup trước khi chạy migration production.
Production là Supabase (ADR 0003 Amendment 3): kết nối qua pooler, cùng vùng với Railway.

### Benchmark và số liệu cần đo (mục 9)

Mỗi job ghi một bản ghi benchmark (artifact JSON cạnh kết quả, kèm checksum) và script
tổng hợp theo mã loại benchmark (mục lục `eval/protocols/BENCHMARKS.md`): `eval/results/<mã>/<nhãn>.jsonl` + bảng trong `eval/results/report.md`.

| Nhóm | Số đo | Nguồn |
|---|---|---|
| Thời gian | Từng stage, tổng, thời gian chờ hàng đợi, thời gian bật GPU | Journal job |
| Chi phí | GPU giờ × đơn giá, dung lượng R2 dùng | Worker + giá cấu hình |
| Máy | GPU, VRAM, version tool, cấu hình (checksum) | Capability + runtime manifest |
| Input | Thời lượng, độ phân giải, số frame lấy / dùng | Prepare |
| COLMAP | % ảnh đăng ký, số điểm sparse, reprojection error | Model COLMAP |
| 3DGS | Số Gaussian, kích thước SOG từng LOD | Brush + splat-transform |
| Chất lượng ảnh | PSNR/SSIM (LPIPS nếu có) trên frame giữ lại | Split đánh giá, không dùng cho runtime |
| Metric scale | Sai số so với LiDAR/GT khi dataset có (ADR 0001) | Evaluation-only |
| Trình duyệt | Thời gian tải scene, FPS theo LOD/thiết bị | Client gửi lên (tùy chọn) |
| SM-06 | Thời gian thủ công vs dùng công cụ trên cùng scene | Đo tay, ghi vào report |

Data demo (Aisle_CW) chạy lại cùng cấu hình để so sánh giữa các lần; không dùng
dữ liệu evaluation-only trong đường runtime.

### Kiểm thử phần GPU (mục 10 — quyết định kỹ thuật)

1. **CI (GitHub, không GPU):** giữ unit/integration test với tool giả qua seam (đang có)
   + job frontend.
2. **Smoke GPU:** `scripts/gpu/smoke.sh` chạy trong đúng Docker image GPU: in version
   tool, chạy video fixture nhỏ (~30 frame, ~1k bước) đầu-cuối, kiểm artifact +
   checksum, ghi bản ghi benchmark. Chạy mỗi khi đổi image/pipeline; có thể kích
   hoạt tay bằng GitHub Actions `workflow_dispatch` gọi adapter nhà cung cấp GPU.
3. **E2E sau deploy:** script gọi API đã deploy: đăng nhập tài khoản test → upload video
   mẫu nhỏ → chờ job xong → tải LOD nhẹ → kiểm checksum. Chạy sau mỗi lần deploy.
4. Kết quả smoke/E2E lưu cùng định dạng benchmark để theo dõi hồi quy.

### Ngày demo (mục 11)

Bật GPU trước 15 phút; video mẫu đã lên R2; tài khoản Editor + Reviewer demo; mở sẵn
trang fallback (stack một máy) nếu cloud trục trặc.

## Risks And Recovery

- Vulkan/COLMAP trên Vast.ai không chạy → thử RunPod; cả hai không chạy → đổi image hoặc nhà cung cấp (phase 1 chặn).
- Host Vast.ai không ổn định → lọc theo độ tin cậy; job chạy lại trên instance khác.
- Không kịp → demo bằng stack một máy (`scripts/gpu/run_stack.sh`).
- LOD/`splat-transform` và lấy thao tác SuperSplat là UNKNOWN → kiểm trước khi cam kết.

## Task Capsule — đợt code 1 (2026-09-29, nhánh `feat/cloud-studio`)

```text
Task / outcome: phần không cần tài khoản cloud — kho file S3 (mirror), upload thẳng,
  Postgres + migration, đăng nhập 2 role, ghi benchmark.
Authority anchors: ADR 0003 (+ Amendment 1–3); Contract §3.1/§7.4 amendment; PRD §3.4,
  NFR-04; ARCHITECTURE §Database/§Deployment.
Dependencies and current state: artifact store filesystem (`artifacts/store.py`), resolver
  dùng trực tiếp ở ~40 chỗ trong REC/orchestration; RuntimeDatabase có nhánh Postgres
  nhưng psycopg chưa cài, chưa test; chưa có auth.
Inputs / outputs: env S3 (endpoint/bucket/key), DATABASE_URL; ra API upload/auth mới.
Owned paths: src/services/orchestration/**, src/api/**, src/config.py, frontend/**,
  tests/test_orchestration, tests/test_api, tests/integration, requirements*.in/lock.
Do-not-modify paths: src/services/reconstruction/** (REC giữ nguyên, đọc/ghi local cache),
  src/services/scene/**, src/services/simulation/**, shared contracts.
Proof required: unit test với object store giả; integration với MinIO + Postgres trong
  Docker tạm (container riêng, xóa sau khi test); ruff; pytest toàn bộ; frontend checks.
Unknowns / blockers: R2 hỗ trợ conditional PUT (If-None-Match) — fallback HEAD + checksum;
  Supavisor pooler với psycopg (kiểm khi có tài khoản).
```

Thiết kế kho file: filesystem vẫn là **cache cục bộ** trên mỗi máy; lớp **mirror** đồng
bộ với S3 ở ranh giới — worker kéo input trước job, đẩy namespace job sau mỗi stage;
API đọc artifact chưa có thì tải về (verify checksum). REC không cần sửa.

## Progress

- [x] Thảo luận và chốt quyết định; ADR 0003 + plan này (2026-09-29).
- [x] Merge docs vào `develop` (PR #9, merge commit `902bbc0`).
- [x] Đồng bộ `docs/` và `docs/execution/` theo ADR 0003 và hiện trạng (2026-09-29).
- [x] **Đợt code 1 (2026-09-29, nhánh `feat/cloud-studio`)** — không cần tài khoản cloud:
  - Kho file S3 (phase 2): `artifacts/remote.py` (`ObjectStore`, `S3ObjectStore`, `ArtifactRemote`)
    sau `ArtifactResolver`: đọc thiếu thì tải + verify checksum, publish thì đẩy lên, sync theo
    namespace; worker kéo input/đẩy output quanh mỗi REC CLI (`jobs/runner.py`). REC không sửa.
  - Upload thẳng (phase 4 phần 1): `uploads/direct.py` + `/api/v1/uploads/direct*`; trình duyệt PUT
    từng phần 16 MiB (4 luồng, thử lại, nối lại qua localStorage); server tự lấy danh sách phần,
    ghép và tự tính SHA-256 (không tin client); khai sai kích thước → FAILED + xóa object.
  - Postgres + migration (phase 3): `MIGRATIONS` v1→v3 theo `r2s_schema.version`; `/health` chạy
    `SELECT 1` (503 khi DB lỗi) — giữ Supabase thức theo Amendment 3.
  - Đăng nhập 2 role (phase 6): `orchestration/auth` (scrypt stdlib, phiên httpOnly lưu băm, mã
    mời một lần, nhật ký, hạn mức scene/ngày), `src/api/auth.py`, guard theo route (upload/scene/
    product = Editor; review/release = Reviewer; video mẫu + thông số = công khai), CLI tạo Reviewer
    đầu tiên; UI đăng nhập/đăng ký/Nhóm. `AUTH_REQUIRED` mặc định tắt (local/test).
  - Benchmark (phase 8 phần ghi): `orchestration/benchmark.py` — worker publish
    `jobs/<job>/benchmark/pipeline_runtime/attempt-N.json`; `scripts/benchmark/collect.py` →
    `eval/results/pipeline_runtime/<nhãn>.jsonl`; mục lục `eval/protocols/BENCHMARKS.md`.
  - Hạ tầng: `scripts/cloud/configure_bucket.py` (CORS + hủy multipart bỏ dở), env mẫu.
  - **Evidence:** pytest 940 passed / 22 skipped với Postgres 16 + MinIO thật trong Docker tạm;
    vitest 111/111, eslint, typecheck, `next build` pass. QA Chrome headless: upload 40 MiB qua
    `/new` đi thẳng MinIO (checksum khớp, không request video qua API); đăng nhập bật: khách chỉ
    thấy video mẫu, Reviewer tạo mã mời ở `/team`. **Hai "máy" tách cache** (API/GPU khác
    `ARTIFACT_ROOT`, chung DB + MinIO), job thật `job-a133f8c24292` (30 frame, 1k bước, T2000):
    cache API không có video, GPU kéo video + đẩy 65 artifact, API đọc preview 200; benchmark
    67 s, SOG 0.12 MB, ~$0.006 ở $0.34/giờ.
  - **Quyết định kỹ thuật:** giữ proxy `/api/v1` qua Next để cookie phiên cùng domain với UI
    (UI Vercel, API Railway khác domain); video vẫn đi thẳng R2 nên proxy chỉ mang JSON.
  - **Chưa kiểm chứng:** R2/Supabase/Railway/Vercel/Vast.ai thật (chưa có tài khoản);
    `configure_bucket` trên R2 (MinIO không hỗ trợ API CORS/lifecycle); Supavisor pooler.
  - **Giới hạn đo:** privacy/tách frame chạy chung CLI prepare nên không có số giây riêng.
- [x] **Rà soát đợt code 1 và sửa (2026-09-29):**
  - Hạn mức đổi thành **lượt xử lý GPU / 24 giờ** (scene mới + Thử lại, nhật ký `gpu.run`);
    Reviewer không giới hạn, chỉ Reviewer chỉnh hạn mức của Editor.
  - Link PUT từng phần ký kèm `Content-Length` → không PUT được phần to hơn khai báo (MinIO: 403).
  - Phiên upload kẹt VERIFYING khi API khởi động lại: gọi lại complete lên lịch kiểm tra lại;
    client nhắc mỗi ~1 phút, bỏ cuộc sau 30 phút.
  - Giới hạn đăng nhập theo email (10/5 phút) + client thật từ `X-Forwarded-For` (100/5 phút):
    một người nhập sai không khóa cả nhóm qua proxy chung.
  - Đăng ký bằng mã mời trong một transaction (trước: mã có thể kẹt "pending" khi lỗi giữa chừng).
  - Bootstrap migration chỉ chạy một lần mỗi tiến trình cho mỗi DB (trước: mỗi request).
  - Artifact tải thẳng từ kho file: `/jobs/{id}/artifacts/content` trả 307 tới link có hạn sau khi
    kiểm allow-list; object chưa lên kho thì API tự phục vụ (QA: 307 → MinIO, checksum khớp, khách 401).
  - Benchmark ghi cả khi job dừng ở bước chuẩn bị; route chat LLM cần Editor khi bật đăng nhập.
  - **Còn để sau (đã biết):** worker trên máy thuê giữ mật khẩu DB/key R2 → phase 5 dùng API worker +
    token riêng; chưa có hạn mức dung lượng upload; mỗi transaction mở một kết nối Postgres (cân
    nhắc pool khi đo độ trễ Supabase); xóa file SQLite khi API đang chạy cần khởi động lại API.
- [ ] Phase 1 (thử GPU thuê), 5 (tách worker + bật/tắt GPU), 7 (LOD), 9–11 (giám sát, kiểm thử GPU, deploy), 12–14.

## Decisions

- ADR 0003 (Accepted bởi Tech Lead 2026-09-29).

## Validation

Mỗi phase: test focused + ruff/eslint/typecheck; phase có GPU chạy smoke trên pod;
sau deploy chạy E2E. Không claim cloud/GPU acceptance khi chỉ có test giả lập.

## Result

Chưa có.
