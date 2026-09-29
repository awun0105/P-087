# Execution Plan: Cloud Studio (Vercel + Railway + R2 + RunPod)

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

1. **Kiểm khả thi RunPod (làm đầu tiên).** Thuê pod rẻ; kiểm Vulkan trong container
   (Brush `--version` + train ngắn, Dawn WebGPU cho SOG), COLMAP cài native (không
   Docker lồng). Không đạt → tìm image/nhà cung cấp khác trước khi làm tiếp.
2. **Kho file R2.** Backend S3 sau `ArtifactResolver` (URI `artifact://` giữ nguyên),
   presigned GET/PUT, multipart upload, CORS bucket, lifecycle xóa file trung gian.
3. **Postgres + migration.** Chuỗi migration theo `r2s_schema.version` (ADR 0003 §5),
   test trên SQLite và Postgres.
4. **Upload thẳng.** API cấp link multipart; client upload, nối lại khi rớt mạng;
   bỏ route proxy upload của Next; `ffprobe` kiểm nhanh trước khi xếp hàng.
5. **Tách worker GPU.** Worker nhận job/báo tiến trình/commit qua server điều khiển,
   tải input và đẩy artifact qua R2; Docker image GPU ghim version; tự tắt khi rảnh;
   server tự bật pod qua RunPod API khi có job.
6. **Đăng nhập + 2 role** (ADR 0003 §3): users/invites/audit_log, cookie phiên, kiểm
   quyền theo route, hạn mức; khách chỉ dùng video mẫu.
7. **Ngân sách trình duyệt:** LOD nhẹ/vừa/đầy đủ, client tự chọn và tự hạ theo FPS,
   ảnh bìa + video xoay render trên GPU.
8. **Benchmark / metric** (mục 9 bên dưới): ghi số đo mỗi job, script tổng hợp.
9. **Giám sát + chống đốt tiền** (mục 7 bên dưới).
10. **Kiểm thử GPU + E2E sau deploy** (mục 10 bên dưới).
11. **Deploy + chuẩn bị demo:** Vercel/Railway/R2/RunPod; video mẫu lên R2; tài khoản
    Editor và Reviewer demo; bật GPU trước buổi demo; checklist fallback.
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

- RunPod: đặt spending limit/auto-recharge tắt trong tài khoản; worker tự
  `runpodctl stop pod` (hoặc RunPod API) khi hàng đợi rỗng 10 phút.
- Worker heartbeat: bảng `r2s_workers` đã có; server kiểm định kỳ, quá 15 phút không
  heartbeat mà còn job RUNNING → đánh dấu lỗi + gửi cảnh báo qua Discord/Slack webhook
  (một biến môi trường URL, không cần dịch vụ giám sát riêng).
- Postgres: dùng backup của Railway nếu gói có; không có thì cron `pg_dump` hằng đêm
  đẩy lên R2 (giữ 7 bản).
- Giới hạn tần suất: hạn mức theo tài khoản trong DB (job/ngày, GB) là lớp chính;
  thêm giới hạn request theo IP ở middleware FastAPI cho route đăng nhập/upload.
- Log: stdout JSON có `job_id`, `stage`, `attempt` — Railway/RunPod đều xem được.

### Database (mục 8)

Theo ADR 0003 §5: migration có thứ tự trong code, chạy trong transaction, test trên
SQLite + Postgres, không drop/reset; backup trước khi chạy migration production.

### Benchmark và số liệu cần đo (mục 9)

Mỗi job ghi một bản ghi benchmark (artifact JSON cạnh kết quả, kèm checksum) và script
tổng hợp sang `eval/results/benchmarks.jsonl` + bảng trong `eval/results/report.md`.

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
   hoạt tay bằng GitHub Actions `workflow_dispatch` gọi RunPod API.
3. **E2E sau deploy:** script gọi API đã deploy: đăng nhập tài khoản test → upload video
   mẫu nhỏ → chờ job xong → tải LOD nhẹ → kiểm checksum. Chạy sau mỗi lần deploy.
4. Kết quả smoke/E2E lưu cùng định dạng benchmark để theo dõi hồi quy.

### Ngày demo (mục 11)

Bật GPU trước 15 phút; video mẫu đã lên R2; tài khoản Editor + Reviewer demo; mở sẵn
trang fallback (stack một máy) nếu cloud trục trặc.

## Risks And Recovery

- Vulkan/COLMAP trên RunPod không chạy → đổi image hoặc nhà cung cấp (phase 1 chặn).
- Không kịp → demo bằng stack một máy (`scripts/gpu/run_stack.sh`).
- LOD/`splat-transform` và lấy thao tác SuperSplat là UNKNOWN → kiểm trước khi cam kết.

## Progress

- [x] Thảo luận và chốt quyết định; ADR 0003 + plan này (2026-09-29).
- [x] Merge docs vào `develop` (PR #9, merge commit `902bbc0`).
- [x] Đồng bộ `docs/` và `docs/execution/` theo ADR 0003 và hiện trạng (2026-09-29).
- [ ] Phase 1 … 14.

## Decisions

- ADR 0003 (Accepted bởi Tech Lead 2026-09-29).

## Validation

Mỗi phase: test focused + ruff/eslint/typecheck; phase có GPU chạy smoke trên pod;
sau deploy chạy E2E. Không claim cloud/GPU acceptance khi chỉ có test giả lập.

## Result

Chưa có.
