# T-045: Chạy 9 scene Deep Blending và Mip-NeRF 360 qua pipeline, agent giám sát thay chủ dự án

## Goal
Agent tự chạy lần lượt 9 scene qua pipeline của Real2Sim (đầu vào là ảnh gốc của dataset), tự làm các bước cần người, tự theo
dõi, ghi lại kết quả. Chủ dự án không phải ngồi canh. **Đây là task vận hành: không sửa code.**

| Bộ | Scene | Thư mục ảnh | Preset |
| --- | --- | --- | --- |
| Deep Blending | drjohnson | `db/drjohnson/images` | `photo_collection_indoor` |
| Deep Blending | playroom | `db/playroom/images` | `photo_collection_indoor` |
| Mip-NeRF 360 | bonsai | `mipnerf360/bonsai/images_2` | `photo_collection_indoor` |
| Mip-NeRF 360 | counter | `mipnerf360/counter/images_2` | `photo_collection_indoor` |
| Mip-NeRF 360 | kitchen | `mipnerf360/kitchen/images_2` | `photo_collection_indoor` |
| Mip-NeRF 360 | room | `mipnerf360/room/images_2` | `photo_collection_indoor` |
| Mip-NeRF 360 | bicycle | `mipnerf360/bicycle/images_2` | `photo_collection_outdoor` |
| Mip-NeRF 360 | garden | `mipnerf360/garden/images_2` | `photo_collection_outdoor` |
| Mip-NeRF 360 | stump | `mipnerf360/stump/images_2` | `photo_collection_outdoor` |

Gốc: `/media/usb/AI20K/gaussian_training_datasets/`. Thứ tự chạy theo bảng. Preset do lệnh nạp tự gán, không chọn tay.

## Context (đã kiểm)
- Phần code đã xong và đã commit; **không làm lại**:
  - Pipeline nhận JPG/PNG (`d29a8e18`).
  - Lệnh nạp `scripts/datasets/import_image_scene.py`, video ghép chỉ để xem, ghép video 3 khung/giây (`cec33009`, `d146100d`,
    `834d7a46`, `84e56abe`).
  - Architect sửa 2026-10-17: ảnh dataset được chép thành khung hình thuộc job (`ae5bec67`, trước đó mọi scene lỗi ở bước đóng
    gói "bundle dependency belongs to another job"); preset bộ ảnh so mọi cặp ảnh (`70da9fd7`, trước đó drjohnson chỉ đăng ký
    76/263 ảnh vì preset kiểu video chỉ so mỗi ảnh với 10 ảnh liền kề, trong khi ảnh dataset chụp rời, không theo thứ tự).
- Stack đã khởi động lại với code trên (cổng API 8010, giao diện 3010). Không khởi động lại stack.
- Hai job cũ `job-1c66b8f936bb` (drjohnson) và `job-7c9820b4834f` (playroom) chạy trên code cũ: **bỏ qua, không đụng, không
  "Thử lại"**. Tạo job mới cho cả 9 scene.
- Máy local: Quadro T2000 4 GB, ổ còn khoảng 12 GB. Một việc nặng một lúc. COLMAP so mọi cặp ảnh chạy trên CPU, có thể mất
  1–3 giờ mỗi scene; đây là bình thường, không coi là treo khi log còn tăng.
- Tài khoản Reviewer local: lấy qua biến môi trường `R2S_REVIEWER_EMAIL`, `R2S_REVIEWER_PASSWORD` (chủ dự án cung cấp). Không in,
  không ghi mật khẩu vào file, report hay commit.

## Quy tắc
1. **Không sửa code, không sửa config, không sửa test, không sửa `scripts/gpu/studio.env`.** Chỉ được sửa
   `.ai/tasks/T-045/report.md` và `.ai/status.md`.
2. Gặp lỗi pipeline: ghi vào report (scene, bước, mã lỗi, trích log, đường dẫn log), **dừng scene đó, chuyển scene kế**. Không tự
   sửa, không tự đổi tham số, không chạy lại quá một lần. Chỉ bấm "Thử lại" một lần nếu lỗi có `retryable=true`.
3. Không ghi vào `data/demo/library`, không công khai mẫu, không xoá gì ngoài file tạm của mình.
4. Trước mỗi scene kiểm ổ trống (`df -h /`). Dưới 6 GB → dừng toàn bộ, ghi report, báo chủ dự án. Không tự dọn.
5. Chạy `scripts/gpu/thermal_guard.sh` suốt thời gian chạy (đọc README trong `scripts/gpu/` để biết cách dùng).

## Steps (lặp cho từng scene theo bảng)
1. Nạp: `.venv/bin/python scripts/datasets/import_image_scene.py --images <thư mục ảnh> --name <scene> --video <đường mp4 trong
   thư mục tạm của agent>`. Ghi `project_id`, `job_id`, số ảnh, số khung video.
2. Theo dõi job qua API (`GET /api/v1/jobs/{job_id}` và trang tiến trình) cho tới khi dừng chờ xác nhận tỉ lệ mét. Kiểm tra mỗi
   5–10 phút, không cần nhanh hơn.
3. **Xác nhận tỉ lệ mét bằng đề xuất MoGe**: `GET /api/v1/jobs/{job_id}/metric/proposal` → dùng đúng điểm và khoảng cách đề
   xuất cho `POST .../metric/preview` → `POST .../metric/confirm`. Không đo tay, không sửa số. Không có đề xuất → ghi report,
   dừng scene đó.
4. Theo dõi tới khi tách vật xong và scene chờ duyệt. **Duyệt vật**: chấp nhận đúng các vật hệ thống đề xuất, không sửa hộp. Bấm
   **Tạo mesh** (`POST /api/v1/jobs/{job_id}/scene/geometry/build` với `expected_scene_revision` hiện tại), phương pháp mặc
   định (vỏ Gaussian), không bật ObjectGS.
5. Khi Tạo mesh xong: xuất gói mẫu bằng `.venv/bin/python -m scripts.demo.export_demo_bundle job --job-id <job_id> --out` ra `/media/usb/AI20K/real2sim_samples/<scene>/`, mở trang phát lại
   kiểm gói đọc được.
6. Cập nhật report ngay sau mỗi scene, rồi sang scene kế.

## Report (`.ai/tasks/T-045/report.md`, viết lại từ đầu, bỏ nội dung Phần A cũ)
Bảng mỗi scene một dòng: job_id; thời gian từng bước; COLMAP đăng ký bao nhiêu ảnh / tổng; tỉ lệ mét MoGe đề xuất; số vật; trạng
thái lưới va chạm; lỗi gặp (mã, bước, trích log, đường dẫn log); đường dẫn gói mẫu. Cuối report: danh sách lỗi cần Architect.

## Acceptance criteria
1. Cả 9 scene đã được chạy, mỗi scene hoặc có gói mẫu trên USB, hoặc có lý do dừng ghi rõ kèm log.
2. Không có commit nào sửa code, config hay test.
3. Tỉ lệ mét của mọi scene đến từ đề xuất MoGe.

## Commit
Chỉ `.ai/tasks/T-045/report.md` và `.ai/status.md`, `git add` đúng path. Không push, không tạo branch, không Co-Authored-By.
