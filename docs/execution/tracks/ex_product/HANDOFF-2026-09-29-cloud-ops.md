# Handoff — Cloud Studio: phần đưa lên cloud và vận hành

| | |
| --- | --- |
| **Ngày** | 2026-09-29 |
| **Trạng thái** | Tạm dừng theo quyết định owner; ưu tiên tiếp: hoàn thiện pipeline ứng dụng và UI/UX |
| **Nhánh đã merge** | `feat/cloud-studio` → `develop` |
| **Quyết định** | [ADR 0003](../../../decisions/0003-cloud-architecture-roles-and-browser-budget.md) (+ Amendment 1–3) |
| **Plan chi tiết** | [plan Cloud Studio](../../../plans/active/2026-09-29-cloud-studio.md) |

## 1. Đã xong (có test, chạy thật ở local với Postgres 16 + MinIO trong Docker)

| Phần | Code chính |
| --- | --- |
| PostgreSQL + migration có thứ tự v1→v3 (bootstrap một lần mỗi tiến trình) | `src/services/orchestration/jobs/database.py` |
| Kho file S3/R2 sau `ArtifactResolver`: cache cục bộ, đọc thiếu tự tải + verify, publish tự đẩy | `src/services/orchestration/artifacts/remote.py`, `storage.py` |
| Worker kéo input / đẩy output quanh mỗi REC CLI | `src/services/orchestration/jobs/runner.py` |
| Upload thẳng trình duyệt → kho file (phần 16 MiB, ký `Content-Length`, nối lại, server tự tính SHA-256, tự chạy lại bước kiểm tra kẹt) | `uploads/direct.py`, `src/api/studio/uploads.py`, `frontend/src/lib/api/directUpload.ts` |
| Tải artifact thẳng từ kho file (307 tới link có hạn sau khi kiểm allow-list) | `projects/registry.py`, `src/api/routes_product.py` |
| Đăng nhập 2 role, mã mời một lần, phiên httpOnly, nhật ký, hạn mức lượt GPU/24 giờ (Reviewer không giới hạn), giới hạn đăng nhập theo email + client | `orchestration/auth/`, `src/api/auth.py`, trang `/login`, `/register`, `/team` |
| `/health` kiểm DB (503 khi lỗi) | `src/main.py` |
| Benchmark `pipeline_runtime` + script tổng hợp | `orchestration/benchmark.py`, `scripts/benchmark/collect.py`, `eval/protocols/BENCHMARKS.md` |
| Script cấu hình bucket (CORS, hủy multipart bỏ dở) | `scripts/cloud/configure_bucket.py` |

Evidence: pytest 950 passed / 22 skipped (Postgres + MinIO thật), vitest 112/112, eslint, typecheck,
`next build`; QA hai "máy" tách cache (API không chứa video; GPU kéo video, đẩy 65 artifact);
upload 40 MiB qua trình duyệt thẳng MinIO; 307 → MinIO khớp checksum, khách 401.

## 2. Còn lại — 21 việc

✅ = làm được không cần tài khoản · 🔑 = cần tài khoản dịch vụ

### A. Máy GPU (worker)
1. ✅ Docker image GPU: COLMAP cài native (instance là container, không chạy Docker lồng), Brush 0.3.0,
   Node + splat-transform 3.6.6, Python; ghim version; Vulkan ICD NVIDIA.
2. ✅ **API cho worker + token riêng**: claim job, báo tiến trình, nộp kết quả, xin presigned URL.
   Máy thuê **không** giữ mật khẩu DB hay key R2 (hiện worker nối thẳng DB — rủi ro trên host lạ).
3. 🔑 Phase 1: thử image trên Vast.ai (chính) và RunPod (dự phòng) — Vulkan, COLMAP, thời gian khởi
   động, giá một job. Vast không đạt → RunPod thành chính (ghi amendment ADR 0003).
4. 🔑 Tự bật/tắt GPU: adapter nhà cung cấp (tạo/hủy/trạng thái; lọc độ tin cậy ≥ 98%, VRAM, đĩa,
   trần giá/giờ); bộ điều khiển trong API 30 s/lần: có job + không worker sống → tạo 1 máy; rảnh
   > 10 phút → hủy; mất heartbeat > 15 phút → hủy; bảng `r2s_gpu_instances`; giới hạn chi tiêu/ngày.

### B. Server API + database
5. ✅ Docker image API + Docker Compose nhiều service (API, worker, frontend, Postgres, MinIO).
6. ✅ Tác vụ nền: chạm DB hằng ngày (giữ Supabase Free thức), `pg_dump` hằng đêm lên kho file (giữ 7
   bản), dọn frame/file trung gian quá N ngày.
7. 🔑 Deploy API lên Railway; biến môi trường; tạo Reviewer đầu tiên bằng
   `python -m src.services.orchestration.auth.cli create-user --role reviewer`.
8. 🔑 Supabase: nối qua pooler Supavisor (session mode), cùng vùng Railway; đo độ trễ; cân nhắc pool
   kết nối (hiện mỗi transaction mở một kết nối).

### C. Kho file
9. 🔑 Bucket R2 + API token; chạy `python -m scripts.cloud.configure_bucket --origin <domain UI>`;
   kiểm chữ ký `Content-Length` và lifecycle trên R2 thật (MinIO không hỗ trợ API CORS/lifecycle).
10. ✅ Hạn mức dung lượng upload theo tài khoản.

### D. Web UI
11. 🔑 Deploy frontend lên Vercel; proxy `/api/v1` → Railway (giữ cookie cùng domain); kiểm đăng nhập
    trên domain thật (cookie Secure).
12. ✅ Bản nhẹ (LOD) + tự chọn/hạ chất lượng theo thiết bị/FPS; ảnh bìa, video xoay làm dự phòng.

### E. Giám sát và chi phí
13. 🔑 Sentry (API, worker, frontend; tắt PII).
14. 🔑 UptimeRobot ping `/health` + trang chủ; trang trạng thái.
15. ✅ Cảnh báo worker mất heartbeat / job treo qua webhook Discord/Slack.
16. ✅ Log JSON có `job_id`, `stage`, `attempt`.

### F. Kiểm thử sau deploy
17. ✅ `scripts/gpu/smoke.sh`: video nhỏ đầu-cuối trên đúng image GPU, ghi benchmark.
18. ✅ Script E2E trên bản deploy: đăng nhập → upload → chờ job → tải bản nhẹ → kiểm checksum.

### G. Dữ liệu cá nhân (ADR 0003)
19. ✅ Nút xóa video/scene; tự xóa sau N ngày; điều khoản sử dụng ngắn khi upload.

### H. Chuẩn bị demo
20. ✅ Runbook deploy + vận hành cloud (hiện `scripts/gpu/README.md` chỉ mô tả chạy một máy).
21. 🔑 Video mẫu lên R2; tài khoản demo Editor/Reviewer; bật GPU trước buổi demo; kiểm fallback.

**Thứ tự đề xuất khi làm lại:** 1–2 → 5–6 → 15–16, 19 → 17–18, 20 → 12 → 10; có tài khoản thì
3 → 8–9 → 7, 11 → 4 → 13–14 → 21.

## 3. Tài khoản cần tạo (owner)

Vast.ai (nạp $5–10, tắt auto-recharge) · RunPod (dự phòng, spending limit) · Supabase · Cloudflare R2 ·
Railway (Hobby) · Vercel (Hobby) · Sentry · UptimeRobot. Key/token đặt trong `.env` (gitignored) hoặc
Variables của từng dịch vụ — **không dán vào chat**. SSH public key thêm vào Vast.ai/RunPod.

## 4. Cách chạy lại bằng chứng ở local

```bash
docker run -d --rm --name r2s-minio-test -p 127.0.0.1:19000:9000 \
  -e MINIO_ROOT_USER=r2stest -e MINIO_ROOT_PASSWORD=r2stest-secret minio/minio server /data
docker run -d --rm --name r2s-postgres-test -p 127.0.0.1:15432:5432 \
  -e POSTGRES_USER=r2s -e POSTGRES_PASSWORD=r2s-test postgres:16
R2S_TEST_POSTGRES_URL=postgresql://r2s:r2s-test@127.0.0.1:15432/postgres \
R2S_TEST_S3_ENDPOINT=http://127.0.0.1:19000 R2S_TEST_S3_KEY=r2stest R2S_TEST_S3_SECRET=r2stest-secret \
  pytest -q
docker rm -f r2s-minio-test r2s-postgres-test
```

## 5. Rủi ro / điểm cần nhớ

- Worker hiện nối thẳng DB + kho file bằng credential đầy đủ — không đưa lên máy thuê trước khi làm mục 2.
- `AUTH_REQUIRED` mặc định `false`; phải bật trên deployment cloud.
- CI GitHub Actions do ban tổ chức quản lý đang bị chặn billing — kiểm tra local trước mỗi merge.
- File `.aws` lạ ở root repo (không do code tạo) đã được gitignore; owner cần tự kiểm nguồn gốc.
