# T-039: Build image GPU thật, đẩy lên GHCR, chạy một job từ đầu tới cuối trên pod RunPod

## Goal
Có image `ghcr.io/<owner>/real2sim-gpu:<git-sha>` đã build thật, `preflight` PASS trên GPU thật, và một job video chạy
tới object geometry ready (ObjectGS) trên pod RunPod. Image này là đầu vào cho T-042 (RunPod Serverless) và T-041.

## Context
- `Dockerfile.gpu` chưa từng build trọn (laptop thiếu ổ). Sau T-038 nó gọi `install.sh`.
- Entrypoint có chế độ `stack` (API + worker trên chính pod, SQLite trên `/data`): thử trọn luồng mà chưa cần
  Supabase/R2/Railway.
- Nhà cung cấp GPU đã chọn: **RunPod** (Serverless ở T-042; task này dùng pod thường để build và thử).
- Chi phí và tài khoản là việc của chủ dự án; agent chuẩn bị lệnh, chủ dự án duyệt.

## Cần chủ dự án làm trước (agent hỏi, không tự làm)
1. Nơi build: Docker cần **≥ 150 GB ổ**. Pod RunPod thường không chạy được Docker daemon bên trong, nên chọn một trong:
   (a) máy có Docker của chủ dự án/teammate đủ ổ; (b) GitHub Actions runner lớn; (c) một VM có Docker (ví dụ RunPod CPU
   pod hỗ trợ Docker, hoặc nhà cung cấp VM khác). Agent đề xuất phương án rẻ nhất, chủ dự án chọn.
2. GitHub token có `write:packages`, `docker login ghcr.io` trên máy build. Không ghi token vào repo hay log. Nếu package
   GHCR để riêng tư thì cần thêm thông tin đăng nhập registry trong RunPod (Settings → Container Registry Auth).
3. Ngân sách tối đa (ví dụ 3 giờ GPU), tài khoản RunPod đã nạp tiền.

## Steps
1. **Build** từ commit sạch đã accepted của T-038:
   `docker build -f Dockerfile.gpu -t ghcr.io/<owner>/real2sim-gpu:<git-sha> .` Ghi thời gian build, kích thước image,
   lớp lớn (`docker history`). Build lỗi: sửa trong `install.d/*`/`Dockerfile.gpu`, mỗi bản sửa một commit, ghi nguyên
   nhân.
2. **Đẩy** `docker push`, ghi digest `sha256:...`.
3. **Pod RunPod** (GPU 24 GB, ví dụ RTX 4090, Community Cloud), image theo digest, ổ container ≥ 80 GB:
   - Đo thời gian từ lúc tạo pod tới lúc container chạy (chủ yếu là kéo image).
   - `preflight` (lệnh trong entrypoint) PASS mọi mục bắt buộc và mục ObjectGS. Ghi nguyên output.
4. **Job thật ở chế độ `stack`** trên pod đó (`AUTH_REQUIRED=true`, Reviewer tạo bằng lệnh trong
   `deploy/studio/README.md`; mở cổng HTTP của pod hoặc dùng SSH tunnel). Upload `Aisle_CW_0_1091__left.mp4`
   (`data/studio_local/samples`), chạy tới preview 3DGS → xác nhận tỉ lệ mét (lệnh tự động trong `RUNPOD_GUIDE.md` nếu
   không có WebGL) → tách vật → Tạo mesh bằng ObjectGS. Ghi thời gian từng bước, VRAM đỉnh, lỗi gặp; so với laptop nếu có
   số cùng video.
5. **Tắt và xoá pod** ngay khi xong (chủ dự án xác nhận). Ghi tổng giờ GPU, chi phí.
6. **Tài liệu:** mục "Dùng image dựng sẵn" trong `docs/RUNPOD_GUIDE.md` và `deploy/studio/OVERVIEW.md` (digest, kích
   thước, thời gian kéo image, lệnh chạy). Xoá ghi chú "CHƯA build" trong `Dockerfile.gpu`. Đặt tag `latest-accepted`
   sau khi bước 4 PASS. Commit.

## Acceptance criteria
1. Image build từ commit sạch; digest ghi trong tài liệu.
2. `preflight` PASS trên GPU thật, kể cả ObjectGS.
3. Một job video tới object geometry ready bằng ObjectGS trên pod RunPod; số thời gian/VRAM thật trong report.
4. Pod đã xoá; giờ GPU và chi phí ghi trong report.

## Tests required
Không có test tự động mới. Report ghi output `preflight`, log job (đã lược secret), thời gian, kích thước image.
Nếu sửa script: `bash -n` + `.venv/bin/python -m pytest tests/test_gpu tests/test_packaging -q`.

## Commit
Mỗi bản sửa build một commit; một commit tài liệu; một commit report + status. Không Co-Authored-By. Không ghi token,
IP pod hay mật khẩu vào repo.
Cần T-038 accepted.
