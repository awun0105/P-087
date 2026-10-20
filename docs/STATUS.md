# Trạng thái Real2Sim Studio

## 0. Phạm vi và cách đọc

| Thuộc tính | Nội dung |
| --- | --- |
| Ngày đối chiếu | 20/10/2026 |
| Snapshot source | `develop`, HEAD `4fb0f8f9`, có thay đổi chưa commit |
| Vai trò | Mỗi năng lực đang ở mức nào, bằng chứng nằm đâu, còn giới hạn gì, việc kế tiếp |
| Cập nhật | Sửa bảng khi có bằng chứng mới; mỗi ô kèm ngày và nguồn. Không nâng mức chỉ vì task chuyển sang `implemented` hay `accepted` |

Yêu cầu và tiêu chí nghiệm thu ở [PRD](PRD.md); cách đo ở [EVALUATION](EVALUATION.md). Tài liệu này chỉ ghi **đã chứng minh được đến đâu**.

### 0.1 Bốn mức bằng chứng

| Mức | Nghĩa | Không đủ để nói |
| --- | --- | --- |
| **Code** | Có implementation, có test trên dữ liệu giả hoặc fixture | Chạy được trên dữ liệu thật |
| **Local** | Đã chạy trên dữ liệu thật ở máy phát triển (Quadro T2000, SQLite) | Chạy được trên cloud, đạt chất lượng |
| **Production** | Đang chạy trên hệ thống cloud người dùng truy cập | Đạt tiêu chí nghiệm thu |
| **Nghiệm thu** | Đạt tiêu chí AC của PRD trên bộ dữ liệu đã khóa | — |

**Chưa năng lực nào ở mức Nghiệm thu.** Bộ dữ liệu nghiệm thu và ngưỡng chưa được khóa (EVALUATION mục 7).

## 1. Hệ thống đang chạy

| Phần | Trạng thái ngày 20/10/2026 | Nguồn |
| --- | --- | --- |
| Studio web | Chạy tại https://real2sim-studio.vercel.app; bản đang chạy có nút dùng thử Guest | Kiểm trực tiếp bundle trang đăng nhập, 20/10 |
| API | Chạy trên máy ảo Google Cloud ở Seoul, cùng vùng Supabase; `/health` và `/ready` trả 200, `/ready` báo có catalog GPU và 3 mẫu | Gọi trực tiếp 20/10; workflow `deploy-api.yml` chạy thành công trên repo `awun0105/P-087` |
| Database, artifact | PostgreSQL Supabase, Cloudflare R2 | Cấu hình production; xem [OPERATIONS mục 6](OPERATIONS.md) |
| Worker GPU | Controller RunPod đang bật thật, thuê A5000 khi có job; image GPU được chứng nhận trên A5000 ngày 20/10 (preflight đạt, kể cả COLMAP GPU) | Ghi chép vận hành của chủ dự án, lưu ngoài repo; plan T-071, T-072. Repo chưa có job id hay log của một job chạy hết trên pod |
| Theo dõi GPU | Workflow `gpu-watchdog.yml` chạy 15 phút một lần, thành công | Lịch chạy GitHub Actions trên `awun0105/P-087`, 20/10 |
| Trang giới thiệu | Cloudflare Pages, deploy thành công 20/10 04:14Z | Workflow `deploy-landing.yml` |
| CI | **Không chạy.** Repo tổ chức bị khóa thanh toán GitHub Actions; lần xanh cuối 17/09 | Lịch sử `ci.yml`; deploy chạy nhờ repo cá nhân |

Deploy Studio tự động bằng workflow đang lỗi vì `VERCEL_TOKEN` hết hạn; hiện deploy thủ công bằng `vercel deploy --prod`.

## 2. Năng lực theo luồng sản phẩm

| Năng lực | Mức | Bằng chứng | Giới hạn đã biết |
| --- | --- | --- | --- |
| Tải video, kiểm chất lượng, kiểm riêng tư | Local; Production cho API | Báo cáo quyền riêng tư có trong cả 4 job local (12–18/10) | Trình duyệt hạ video về 720p (tối đa 1080p), nên tùy chọn độ phân giải cao không có tác dụng (plan T-071) |
| Che mặt người, biển số (EgoBlur) | Production đã bật 20/10 | Cấu hình worker và API production, ghi chép vận hành | Chưa có job chứng minh trong repo |
| Pose camera bằng COLMAP | Local | Aisle_CW 65/65 frame (24–28/09); drjohnson 263, room 311 frame (T-045, 17–18/10) | Lỗi COLMAP không được thử lại; chế độ `video_loop_360` lỗi thiếu vocab tree trên image GPU (plan T-071) |
| Huấn luyện Gaussian bằng Brush, bản xem | Local | PSNR ảnh giữ lại 25–29 dB trên Aisle_CW (EVALUATION mục 6); drjohnson 40k bước (T-045) | GPU 4 GB giới hạn khoảng 600k splat |
| LOD cho cảnh lớn | Code | Dựng LOD cho 4 SOG trên T2000 (T-070, 20/10) | Chưa mở thử trên trình duyệt |
| Xác nhận tỉ lệ mét (đề xuất MoGe-2, đo hai điểm) | Local | drjohnson: đề xuất 0.836 m/đơn vị, đã xác nhận (T-045, 17/10); sai số đề xuất trên Aisle_CW dưới 0.3% (EVALUATION mục 6) | Chưa có ngưỡng khóa |
| LiDAR kèm video (R4–R6), odometry | Local, một lần cũ | `job-101e9b56344c`, 02/10, Aisle_CW + 100 scan (ADR 0009); odometry KISS-ICP trên nhiều traversal TorWIC | R2–R6 mở theo quyết định chủ dự án, chưa có bằng chứng trên dữ liệu giữ lại (ADR 0024); DB hiện tại không còn job LiDAR; gói LiDAR demo dùng quỹ đạo đáp án |
| Nhập Gaussian có sẵn | Local | 3 lần nhập `gaussian_ply` READY, 11–12/10 | Chưa chạy tiếp pipeline từ bản nhập |
| Tách vật: Draft → duyệt vùng → geometry Ready | Local, một phần | drjohnson: 60 vật đã duyệt, 22 có collider, geometry Ready ở rev-186 (`.ai/reports/2026-10-18-drjohnson-restore-ready.json`); Room và Playroom còn Draft | Mesh bề mặt ObjectGS trên cảnh thật bị QA loại vì hở; PR-05 **không đạt** cổng chất lượng vật lý (`docs/plans/active/2026-10-15-*/HANDOFF.md`) |
| Vá nền và collision môi trường | Local, chỉ artifact | `background.sog`, `environment_collision.usda` của job Room (13/10) và drjohnson | Chưa kiểm va chạm thật trên trình duyệt (PR-03 handoff) |
| Chỉnh scene, revision, Walk trên trình duyệt | Code; Local chỉ điều hướng | 1110 test vitest; mở trang scene drjohnson qua DevTools, không chỉnh (17/10) | Cảm giác Walk, Walk tải chậm, sửa lỗi kéo đơ còn chờ chủ dự án kiểm bằng mắt (handoff Sprint 8) |
| Gói mô phỏng OpenUSD, preflight | Local | Preflight PASS 6/6 (`job-123dfd4868d8`, khoảng 30/09); `scene.usda` của drjohnson (18/10) | Chưa thử với job có 60 vật trên production |
| Kiểm định Isaac, duyệt, phát hành | Code | Test process Isaac, cổng validation, niêm phong release | **Chưa từng chạy**: DB local có 0 lần validation, 0 release; image cloud không có Isaac Sim (cần chấp nhận giấy phép NVIDIA, +20–30 GB) |
| Thư viện mẫu, phiên demo | Production cho thư viện | 3 mẫu: drjohnson rev-198, room rev-062, playroom rev-003; `/api/v1/samples` trả 200 | Phiên demo dùng SQLite và thư mục cục bộ; chưa kiểm mở phiên demo trên production. Mẫu không được ghi là đã kiểm định Isaac |
| Tài khoản Guest/Editor/Reviewer, dùng thử | Production | Đăng nhập và nút dùng thử trên web thật, 20/10 | Test ma trận quyền đang đỏ vì route mẫu và phiên demo chưa được phân loại |
| Bảng giá trị `/benchmark` | Code | Audit trên SQLite local tìm 4 lỗi, đã sửa F1 và F3 (`.ai/reports/benchmark-*-20261018/`) | Chưa rõ F2 (giới hạn giờ GPU bỏ qua lần chạy lỗi) đã sửa; chi phí là giá khai báo × giờ, không phải hóa đơn |
| Đo so với dữ liệu đối chứng | Local, lịch sử | Kết quả trong `eval/results/`, chỉ TorWIC; dự án ngừng dùng TorWIC từ 20/10/2026 | Không có `EvaluationReport`, chưa có so đường đi Start–Goal (EVALUATION mục 7) |
| Controller GPU, hàng đợi, chia GPU | Production cho controller | Controller bật, giới hạn 0,55 USD/giờ, tổng 5 USD, trả máy sau 30 phút rảnh; pod A5000 chạy 3 worker | Chia GPU theo mức đo (T-072) và hàng đợi theo bước (T-073) mới là plan; RunPod hay hết A5000 trong mức giá, controller tạm dừng sau 3 lần và cần `resume` |

## 3. Chất lượng code

| Kiểm tra | Kết quả | Nguồn |
| --- | --- | --- |
| Toàn bộ pytest | 4254 đạt, 16 lỗi, 40 bỏ qua; một lỗi đã sửa sau đó | `.ai/tasks/T-069/report.md`, 20/10 |
| Toàn bộ vitest, typecheck | 1110 đạt; typecheck sạch | Như trên |
| Test đánh giá và bảng giá trị | 210 pytest, 39 vitest đạt | Chạy lại 20/10, EVALUATION mục 8 |
| Foundation | 5/5 đạt | Chạy lại 20/10 |
| Migration v26 | Đã chạy trên PostgreSQL 16 thật | T-069 |

Các test đang đỏ: ma trận quyền và 7 test route mẫu (route mới chưa phân loại); 2 test migration v11/v12 (còn kỳ vọng schema 23, code đã là 26); file env mẫu lệch với nguồn sinh; 4 test script cài GPU/ObjectGS (2 lỗi do tải giấy phép COLMAP trong sandbox).

## 4. Việc kế tiếp

Theo thứ tự ảnh hưởng tới nghiệm thu:

1. **Chạy một job GPU đầy đủ trên production** (thuê máy → xử lý → tự trả máy) và lưu job id, log vào repo.
2. **Chốt bộ dữ liệu nghiệm thu**: cảnh nào, split, robot, 5 cặp Start–Goal kèm nhãn (EVALUATION mục 7; PRD mục 10.1).
3. **Sửa mesh bề mặt hở** để vật trên cảnh thật qua QA collision (PR-05).
4. **Có runtime Isaac** (image riêng cho kiểm định) rồi chạy validation → duyệt → phát hành một lần thật.
5. **Kiểm bằng mắt trên trình duyệt**: Walk, chỉnh vật, LOD, va chạm (danh sách trong handoff Sprint 8).
6. **Làm xanh 15 test đỏ** và khôi phục CI (thanh toán GitHub của tổ chức, hoặc chạy CI ở repo cá nhân).
7. Thực hiện các plan T-071 (preset theo video thật, thử lại COLMAP, vocab tree), T-072, T-073.

## 5. Hồ sơ chưa cập nhật

`WORKLOG.md` và `JOURNAL.md` chỉ có nội dung tới 30/09; các ngày và tuần sau đó là khung trống. Không dùng hai file này làm bằng chứng cho giai đoạn từ 01/10. Bằng chứng giai đoạn này nằm trong `.ai/tasks/`, `.ai/reports/`, `docs/plans/active/*/HANDOFF.md` và lịch sử commit.
