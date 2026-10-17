# T-045 report — chạy 9 scene qua pipeline (vận hành)

Cập nhật: 2026-10-17. Trạng thái: **đang chạy**. Không sửa code, config, test hay `scripts/gpu/studio.env`.

## Môi trường lúc bắt đầu

- Stack đã chạy sẵn với code mới (API `127.0.0.1:8010`, web `127.0.0.1:3010`). Không khởi động lại.
- Hai job cũ `job-1c66b8f936bb` (drjohnson) và `job-7c9820b4834f` (playroom) bị bỏ qua, không đụng, không thử lại.
- `thermal_guard.sh r2s-stack` đang chạy (pid 952053).
- Đĩa `/` lúc bắt đầu: 13 GB trống. Ngưỡng dừng toàn bộ: dưới 6 GB.
- Lệnh nạp chạy với môi trường của stack (`source scripts/gpu/studio.env`, chỉ đọc). Tài khoản Reviewer lấy từ biến môi trường, không ghi vào file này.
- `--dataset-owner`: `Deep Blending` cho db, `Mip-NeRF 360` cho mipnerf360.

## Bảng theo scene

| # | Scene | Job | Ảnh / khung video | COLMAP đăng ký | Tỉ lệ mét MoGe (đề xuất → xác nhận) | Số vật | Lưới va chạm | Gói mẫu | Trạng thái |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | drjohnson | job-f9f14e7fbfb1 (project-27b54d5fda4b) | 263 / 263 | chưa đọc được số liệu đăng ký (COLMAP xong, không có số trong API) | MoGe đề xuất 0,836 m/đv SfM, khoảng cách 11,64 m; xem trước đạt; xác nhận đã ghi (cảnh báo độ cao camera -2,97…2,37 m) | 60 vật, duyệt 60/60 | lỗi ở bước Tạo mesh (xem dưới) | không có | **dừng: lỗi Tạo mesh, không retryable** |
| 2 | playroom | — | — | — | — | — | — | — | chưa chạy |
| 3 | bonsai | — | — | — | — | — | — | — | chưa chạy |
| 4 | counter | — | — | — | — | — | — | — | chưa chạy |
| 5 | kitchen | — | — | — | — | — | — | — | chưa chạy |
| 6 | room | — | — | — | — | — | — | — | chưa chạy |
| 7 | bicycle | — | — | — | — | — | — | — | chưa chạy |
| 8 | garden | — | — | — | — | — | — | — | chưa chạy |
| 9 | stump | — | — | — | — | — | — | — | chưa chạy |

Thời gian từng bước: sẽ điền khi có số liệu.

## Lỗi gặp

### drjohnson — bước Tạo mesh (scene/geometry/build)

- Mã/nội dung: `Vỏ của Vật thể 16 không dựng được: gaussian shell failed surface QA: open_or_nonpositive_component. Sửa vùng vật rồi thử lại.`
- `retryable: false`. Không thử lại. Không sửa vùng vật (plan cấm sửa hộp).
- Operation: `cc7f713077f24c69b402faecbda3e207`, phase `shell`, bắt đầu 11:00:04Z, kết thúc 11:00:17Z (UTC).
- Nguồn: `GET /api/v1/jobs/job-f9f14e7fbfb1/scene/objectify`. Trích `resource-usage.jsonl` tại `data/studio_local/workers/job-f9f14e7fbfb1/geometry-1be32dde32904ba99a1f6facb3cc2718/resource-usage.jsonl`. Không có file stderr riêng cho thao tác này.
- Đã dừng scene drjohnson, không xuất gói mẫu.
- Trước đó: Brush 40.000 bước hoàn tất, job ST-OBJECT-EXTRACT SUCCEEDED.

Ghi chú lần nạp đầu của drjohnson: lần nạp đầu lỗi đăng nhập vì thiếu cấu hình DB của stack, chưa tạo project nào. Nạp lại với môi trường của stack thì thành công. Lần nạp thứ hai bị chặn vì MP4 tạm từ lần đầu còn tồn tại; đã xóa file tạm của chính mình rồi nạp lại.

## Danh sách lỗi cần Architect

Chưa có.
