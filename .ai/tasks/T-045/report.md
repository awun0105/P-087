# T-045 report — chạy 9 scene qua pipeline (vận hành)

Cập nhật: 2026-10-18. Trạng thái: **đang chạy**. Theo chỉ dẫn rõ ràng của chủ dự án, Room có một job mới với processing config riêng và bản sửa admission được ghi bên dưới. Preset chung và `scripts/gpu/studio.env` không đổi.

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
| 6 | room | job-16725c90da50 (project-beb8422fb1e3), sau đó job-bfc7d73f0dbf (project-8f8407859c17) | 311 / 311 mỗi job | đang xử lý | chưa có; đợi đề xuất MoGe | — | — | — | **dừng job đầu: PREVIEW_RUNNER_FAILED, retryable=false; job mới RUNNING sau sửa admission** |
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

## Điều kiện chặn trước khi chạy Room (2026-10-18)

- Đã chọn scene `room` theo yêu cầu tiếp tục T-045; thư mục ảnh `/media/usb/AI20K/gaussian_training_datasets/mipnerf360/room/images_2` có 311 ảnh.
- Đĩa `/` còn 12 GB, trên ngưỡng dừng 6 GB; GPU Quadro T2000 đang dùng 8 MiB VRAM, nhiệt độ 58°C. Không có job nặng đang chạy.
- Chưa tạo project/job: `R2S_REVIEWER_EMAIL` và `R2S_REVIEWER_PASSWORD` không có trong shell hiện tại hoặc môi trường API/worker. Script nạp scene cần hai biến này để đăng nhập Reviewer.
- Điều kiện thermal guard chưa đạt: stack API/worker thuộc cgroup `app-gnome-dev.warp.Warp-868160.scope`; không có user unit `r2s-stack` hoặc `r2s-thermal`. `thermal_guard.sh r2s-stack` hiện không thể đóng băng scope đang chạy. Không chạy xử lý nặng khi chưa có cơ chế bảo vệ nhiệt phù hợp; không khởi động lại stack theo task.
- Đã nạp Room bằng `.venv/bin/python scripts/datasets/import_image_scene.py`; tạo project `project-beb8422fb1e3`, job `job-16725c90da50`, 311 ảnh và 311 khung video. Preset được script tự gán `photo_collection_indoor`. Không lưu thông tin đăng nhập vào report.
- Thermal guard `r2s-thermal` đang giám sát scope chứa API/worker. Journal đã ghi các lần CPU vượt 90°C; guard đóng băng scope và tự thả khi nhiệt độ xuống dưới ngưỡng nguội.
- Job hiện `QUEUED`, `waiting_for=resources`: dự toán cần 3.62 GiB VRAM, 2.38 GiB RAM và 11.93 GiB đĩa; hiện có 3.621 GiB VRAM, 8.75 GiB RAM và 11.701 GiB đĩa. Scheduler báo chờ `vram` và `disk`, cả hai do nguồn bên ngoài. Attempt 1 chưa bắt đầu; không đổi preset hay thử lại.
- Video làm việc tạm đã được xóa sau khi xác minh SHA-256 có hai bản sao giống hệt trong project (`display/scene.mp4`, `input/video/scene.mp4`). Cookie Reviewer tạm còn trong thư mục tạm riêng để theo dõi job; không ghi thông tin đăng nhập vào report. Đĩa `/` vẫn trên ngưỡng task 6 GB. Gói ảnh gốc và job artifacts giữ nguyên.
- Kiểm tra lúc `2026-10-18T06:14:31Z`: job vẫn `QUEUED`, `waiting_for=resources`; dự toán 3.62 GiB VRAM, 11.93 GiB đĩa so với 3.621 GiB VRAM, 11.717 GiB đĩa khả dụng. Scheduler vẫn báo chờ `vram` và `disk`; chưa có stage nào bắt đầu.
- Kiểm tra lại sau khi chủ dự án dọn tài nguyên, lúc `2026-10-18T06:44:26Z`: job vẫn `QUEUED`, attempt 1, `waiting_for=resources`; mọi stage vẫn `pending`. Worker đo 3.621 GiB VRAM, 7.97 GiB RAM, 12.657 GiB đĩa khả dụng so với nhu cầu 3.62/2.38/11.93 GiB; scheduler vẫn báo chờ `vram` và `disk` do tài nguyên ngoài pipeline. Không tạo attempt mới, không đổi preset/cấu hình, không bỏ qua gate. Thermal guard `r2s-thermal` vẫn active.
- Rà soát chỉ đọc lúc 13:44 giờ địa phương: `/` còn 13 GiB; `nvidia-smi` thấy GPU 0% bận, chỉ Xorg giữ 4 MiB và còn 3708 MiB VRAM. Các thư mục lớn có vẻ là cache nằm ngoài vùng task, gồm `~/.cache/google-chrome` 2.4 GiB, `~/.cache/torch` 1.1 GiB, `~/.cache/chrome-devtools-mcp` 923 MiB, `~/.cache/BraveSoftware` 773 MiB và `~/.cache/ms-playwright` 656 MiB; chưa xóa vì quy tắc task chỉ cho phép xóa file tạm do lượt chạy này tạo. `data/` khoảng 32 GiB gồm artifact/runtime của Studio nên giữ nguyên. Thư mục tạm riêng của lượt này chỉ còn cookie 205 byte.
- Kiểm kê checkpoint read-only lúc 13:52: không tìm thấy file Brush `ckpt_*.ply` nào trong `data/`. Có cache COLMAP 18 MiB ở `data/studio_local/workers/job-7c9820b4834f/resume/colmap-20ec4559a86f1c808e1a14e12b26f980`; job này hiện `SUCCEEDED`, nhưng cache vẫn là dữ liệu resume của job nên không xóa. Các file `visual.ply` cỡ 472 MB và thư mục artifact/geometry nhiều GB của các job cũ là output/scene artifact, không phải checkpoint. Không xóa artifact/runtime của job khác.
- Lúc 13:54 giờ địa phương, theo chỉ dẫn rõ ràng của chủ dự án, đã xóa đúng thư mục cache Brave `/home/lqaq/.cache/BraveSoftware` (773 MiB; Brave không chạy, đường dẫn thật không phải symlink). Đĩa `/` tăng từ 13 lên 14 GiB khả dụng theo `df -h` (hiển thị làm tròn); cache chung giảm từ 8.9 xuống 8.1 GiB. Worker đo lại Room: chỉ còn chờ `vram`; `disk` đã qua admission. Job vẫn `QUEUED`, attempt 1, chưa có stage bắt đầu.
- Chẩn đoán gate VRAM lúc `2026-10-18T06:54:47Z`: cấu hình resource model của preset có `danger_ratio=0.92`; admission yêu cầu `need < available * 0.92`. Với nhu cầu API làm tròn 3.62 GiB, cần trên khoảng 3.935 GiB VRAM khả dụng; worker chỉ đo 3.621 GiB. Quadro T2000 có 4 GiB tổng, chỉ 8 MiB đang dùng (4 MiB Xorg), nên không có tiến trình người dùng đáng kể để dừng. Job vẫn `QUEUED`, chờ VRAM bên ngoài; không đổi preset hoặc bỏ qua gate.
- Lúc `2026-10-18T07:24:57Z`, job `job-16725c90da50` kết thúc `FAILED` ở `ST-CAMERA-POSE`, mã `PREVIEW_RUNNER_FAILED`, `retryable=false`, chi tiết `KeyboardInterrupt`. Attempt 1 có 311 frame; resource log ghi outcome `interrupted`, exit code 130 và không có peak VRAM đo được. Không dùng API Retry. Project/job cũ sau đó bị xóa qua `DELETE /api/v1/scenes/project-beb8422fb1e3` (API trả 200); không khôi phục.
- Theo yêu cầu tiếp tục bằng ảnh downsampling 1/4 và cấu hình đã thống nhất, tạo project `project-8f8407859c17`, job `job-bfc7d73f0dbf` từ `/media/usb/AI20K/gaussian_training_datasets/mipnerf360/room/images_4`: 311 ảnh JPEG được giữ nguyên byte, 311 frame video xem trước. Processing config riêng đã lưu với `sampling.max_frames=320`, `colmap.max_image_size=800`, `brush.max_resolution=800`, `brush.max_splats=1200000`, `scene.sam_batch=8`; giữ `brush.total_train_iters=40000` và `scene.geometry_method=shell`. Checksum config `sha256:6474b9302e45dc3c0f4c812ad9a256209de3712c33b4a69b65f06ad88090e937`; preset chung không thay đổi.
- Job mới qua kiểm tra input, nhưng vẫn `QUEUED` tại `ST-INPUT-VALIDATE`: `r2s_resource_waits` ghi nhu cầu VRAM đo được 3.62 GiB, RAM 2.38 GiB, đĩa 6.43 GiB; khả dụng lần đo là 3.622 GiB VRAM, 15.65 GiB RAM và 13.019 GiB đĩa. Chỉ chờ `vram`, lý do `external`. Resource model `danger_ratio=0.92` đòi hơn khoảng 3.935 GiB VRAM khả dụng. Dù công thức ước lượng của config mới là 2.70/2.70/6.43 GiB, số đo VRAM cao hơn từ job hoàn tất có cấu hình trội hơn được dùng làm chặn trên; đổi ảnh/config này không đủ để qua gate trên GPU T2000 hiện tại.
- Sau khi phát hiện stack/thermal guard không còn chạy, đã khởi động `r2s-stack` và `r2s-thermal` bằng `systemd-run` theo runbook, không sửa `scripts/gpu/studio.env`; cả hai đang `active`. Tại lần kiểm tra cuối, GPU 61°C, 3709 MiB trống; `/` còn 14 GiB. Job mới giữ trong hàng đợi để tự được xét lại khi tài nguyên khả dụng thay đổi. Không bỏ qua admission hoặc chỉnh threshold.

## Sửa admission theo yêu cầu chủ dự án (2026-10-18)

- Nguyên nhân: `_demand` dùng chặn trên đo từ cấu hình nặng hơn như số đo của cấu hình mới và cho phép chia sẻ GPU. Mức 3.62 GiB đó giữ config Room mới trong hàng đợi dù công thức ước lượng mới là 2.70 GiB. Đây chưa phải bằng chứng config mới cần GPU khác.
- Sửa tối thiểu tại `src/services/orchestration/jobs/admission.py`: chỉ nhận số đo có bộ observation params đúng cấu hình hiện tại cho admission. Cấu hình mới dùng cơ chế chạy riêng GPU hiện có để thu số đo. Giữ nguyên kiểm tra RAM/đĩa, threshold, GPU affinity, reservation/heartbeat và config checksum. Không sửa hàm chặn trên dùng cho đánh giá/recommender.
- Thêm regression tại `tests/test_orchestration/test_resource_admission.py` cho cả preview và finalize: số đo cấu hình nặng hơn không chặn lượt chạy riêng đầu tiên; worker thứ hai vẫn phải đợi GPU. Trước sửa: **2 failed**. Sau sửa: **99 passed** trong `test_resource_admission.py`, `test_observed_budget.py`, `test_processing_config.py`, `test_machine_runtime_provenance.py`.
- `ruff check` và `ruff format --check` trên hai file sửa: sạch; `git diff --check`: sạch. `graphify update .`: thành công, 27807 nodes/86875 edges. Không commit.
- Sau khi xác minh không có tác vụ nặng, lease hoặc reservation đang chạy, đã nạp code mới bằng restart `r2s-stack`; `r2s-thermal` vẫn active. Lúc `2026-10-18T07:52:29Z`, **job-bfc7d73f0dbf được nhận và RUNNING**, reservation `exclusive=true`, VRAM/RAM/disk 2.70/2.70/6.43 GiB. Checksum vẫn `sha256:6474b9302e45dc3c0f4c812ad9a256209de3712c33b4a69b65f06ad88090e937`; observation chờ VRAM đã được xóa. Chưa kết luận train/mesh toàn pipeline thành công.
- Lúc `2026-10-18T07:53:44Z`, job ở `ST-CAMERA-POSE`; input validation, privacy gate và frame extraction đều `SUCCEEDED`. COLMAP đang trích SIFT, log đã tới 278/311 ảnh 779×519; đây là số ảnh trích feature, chưa phải số camera đăng ký. Log: `data/studio_local/workers/job-bfc7d73f0dbf/attempt-25105e8cb45142d9827a54cccb0fc6ab/rec/colmap/process.log`.

Pre-flight (GUIDE.md Rule 13):
- codegraph: đọc `_demand`, `observed_budget`, `dominates`, `usage_vram`, `_assess` và các tests liên quan.
- impact: `_demand` dùng bởi admission job và `operation_profile_for_job`; operation chưa đo vẫn dùng strict headroom checks, job mới chạy riêng; số đo đúng cấu hình vẫn cho phép chia sẻ như trước.
- understand: flow queue → admission → reservation → worker; đối chiếu INTEGRATION_PLAYBOOK và plan quản lý tài nguyên. UNVERIFIED: công cụ understand-anything không có trong session.
- minimal-code: rung 2 — tái sử dụng nhánh exclusive-run đã có, chỉ lọc số đo trước lời gọi `observed_budget`.
- checks: 99 passed; Ruff lint/format sạch; diff check sạch. Frontend tsc/eslint/vitest n/a — không sửa frontend.
- DevTools: n/a — dịch vụ backend; có bằng chứng runtime job RUNNING và reservation exclusive, chưa có bằng chứng toàn pipeline hoàn tất.
