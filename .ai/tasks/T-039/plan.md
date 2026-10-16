# T-039: Build image GPU thật, đẩy lên GHCR, chạy một job từ đầu tới cuối trên GPU thuê

## Goal
Có một image `ghcr.io/<owner>/real2sim-gpu:<git-sha>` đã build thật, đã chạy `doctor` PASS và một job thật trên GPU
thuê. Thuê GPU lần sau chỉ cần chọn image này.

## Context
- `Dockerfile.gpu` chưa từng build trọn (laptop thiếu ổ). Sau T-038 nó gọi `install.sh`.
- Entrypoint có chế độ `stack` (API + worker trên chính pod, SQLite trên `/data`), dùng để thử trọn luồng mà chưa cần
  Supabase/R2/Railway (đó là T-041).
- Chi phí thật và tài khoản: việc của chủ dự án. Agent chuẩn bị lệnh, chủ dự án duyệt và cấp quyền.

## Cần chủ dự án làm trước (agent hỏi, không tự làm)
1. Chọn nơi build: một máy thuê có Docker, **≥ 150 GB ổ**, GPU NVIDIA (để chạy thử ngay sau build). Vast.ai hoặc
   RunPod pod có Docker. Agent đề xuất cấu hình và giá/giờ, chủ dự án thuê.
2. Tạo GitHub token có quyền `write:packages` và `docker login ghcr.io` trên máy build. Token không ghi vào repo hay log.
3. Đưa gói COLMAP nhị phân (T-038 bước 2) lên GitHub Release nếu chưa, để `pins.env` có URL.
4. Duyệt ngân sách tối đa (ví dụ: 3 giờ GPU). Agent dừng khi gần chạm.

## Steps
1. **Build.** Trên máy build: `git clone` đúng commit đã accepted của T-038,
   `docker build -f Dockerfile.gpu -t ghcr.io/<owner>/real2sim-gpu:<git-sha> .` Ghi: thời gian build, kích thước image
   (`docker image inspect`), từng lớp lớn (`docker history`). Build lỗi: sửa trong phạm vi `install.d/*`/`Dockerfile.gpu`,
   commit riêng từng bản sửa, ghi nguyên nhân vào report.
2. **Kiểm trong container.** `docker run --rm --gpus all <image> preflight` phải PASS mọi mục bắt buộc; mục ObjectGS
   tuỳ chọn cũng phải PASS (image có ObjectGS). Ghi nguyên output vào report.
3. **Đẩy image.** `docker push`; ghi digest `sha256:...`. Đặt thêm tag `latest-accepted` **chỉ sau** bước 5 PASS.
4. **Thời gian khởi động thật.** Trên một pod Vast.ai **mới** (khác máy build) chọn image theo digest: đo thời gian từ lúc
   bấm tạo tới lúc `preflight` PASS (chủ yếu là thời gian tải image). Đây là số cho tài liệu deploy.
5. **Job thật ở chế độ `stack`.** `docker run --gpus all -p 8000:8000 -v <đĩa pod>:/data <image> stack` với
   `AUTH_REQUIRED=true` và một tài khoản Reviewer tạo bằng lệnh trong `deploy/studio/README.md`. Tải lên video
   `Aisle_CW_0_1091__left.mp4` (có trong `data/studio_local/samples`, chép lên pod), chạy tới: preview 3DGS, xác nhận tỉ
   lệ mét (dùng lệnh xác nhận tự động trong `RUNPOD_GUIDE.md` nếu không mở được WebGL), tách vật, Tạo mesh với ObjectGS.
   Ghi thời gian từng bước, VRAM đỉnh, và lỗi gặp. So thời gian với laptop trong `eval/results/` nếu có số cùng video.
6. **Tắt pod** ngay khi xong (chủ dự án xác nhận đã tắt). Ghi tổng giờ GPU và chi phí.
7. **Tài liệu.** `docs/RUNPOD_GUIDE.md` và `deploy/studio/OVERVIEW.md`: mục "Dùng image dựng sẵn" với digest, kích
   thước, thời gian khởi động đo được, và lệnh chạy. Xoá ghi chú "CHƯA build" trong `Dockerfile.gpu`. Commit.

## Acceptance criteria
1. Image build thành công từ commit sạch; digest ghi trong tài liệu.
2. `preflight` PASS trong container trên GPU thật, kể cả ObjectGS.
3. Một job video chạy tới object geometry ready bằng ObjectGS trên pod thuê; số thời gian/VRAM thật trong report.
4. Pod đã tắt; giờ GPU và chi phí ghi trong report.

## Tests required
Không có test tự động mới. Report ghi đủ output `preflight`, log job (đã lược secret), thời gian và kích thước image.
Nếu sửa script: `bash -n` + `pytest tests/test_gpu tests/test_packaging -q`.

## Commit
Mỗi bản sửa build một commit; một commit tài liệu; một commit report + status. Không Co-Authored-By. Không ghi token,
IP pod hay mật khẩu vào repo.
Cần T-038 accepted.
