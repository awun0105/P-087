# 0028 Khoảng tham chiếu chất lượng, khuyến nghị theo quy tắc và số đo tài nguyên trong bảng đánh giá

Date: 2026-10-08

## Status

Accepted — owner duyệt ngày 2026-10-09. Phần code của AUD-28 đã triển khai; kiểm bằng mắt trên Studio còn mở. Kế hoạch triển khai: [AUD-28](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-28-benchmark-derived-verdicts-and-rule-based-insights.md).

## Context

Bảng đánh giá ([`scorecard.py`](../../src/services/orchestration/evaluation/scorecard.py))
đã có giá trị và lời giải thích tiếng Việt cho từng chỉ số. Còn bốn điểm thiếu:

1. **Ít chỉ số có kết luận.** Bốn chỉ số có `verdict`: `input.warnings`,
   `pose.registered_ratio`, `visual.nonfinite_values`, `metric.check_error`. Quy tắc ở
   `models.py:10` là chủ ý: chỉ gán verdict khi có ngưỡng đã được chấp nhận trong repo.
2. **PSNR/SSIM/LPIPS held-out có số nhưng không có điểm so sánh.** Job sản phẩm đã tự giữ
   lại một phần tám số ảnh để chấm (`eval_split_every = 8`). Người dùng thấy "26,4 dB" mà
   không biết đó là cao hay thấp.
3. **Không có kết luận tổng.** Người dùng phải tự đọc từng dòng để biết cần làm gì.
4. **Nhóm Hệ thống thiếu tài nguyên.** Peak RAM/VRAM đã được đo vào `r2s_resource_usage`
   nhưng không xuất hiện trong bảng đánh giá.

Dữ liệu held-out hiện có gồm sáu scene: PSNR 25,35 / 25,49 / 26,36 / 28,45 / 28,80 /
30,00 dB; SSIM từ 0,888 tới 0,939; LPIPS từ 0,268 tới 0,344 (năm scene). Không scene nào
trong số này được ghi nhận là hỏng.

## Quyết định đề xuất

1. **Không đặt ngưỡng Đạt/Không đạt cho PSNR, SSIM, LPIPS ở thời điểm này.** Sáu scene,
   không có mẫu xấu, không đủ để tách tốt khỏi xấu. Bất kỳ ngưỡng nào đặt bây giờ đều là
   con số tự chọn, trái với quy tắc ở `models.py:10`.
2. **Hiển thị khoảng tham chiếu thay cho verdict.** Mỗi chỉ số held-out có thêm một dòng
   dạng "Các scene đã chạy: 25,35–30,00 dB (6 scene)". Dữ liệu nằm trong
   `configs/product/evaluation_reference_v1.json`, mỗi giá trị kèm `job_id` và nguồn.
3. **Giữ nguyên verdict của `pose.registered_ratio`** theo `min_registered_ratio` trong cấu
   hình COLMAP của chính job. Không thêm ngưỡng thứ hai.
4. **Khuyến nghị sinh theo quy tắc từ các verdict đang có.** Một hàm thuần duyệt các chỉ
   số có `warn` hoặc `fail` và tra bảng `key → câu khuyến nghị`. Khi không có chỉ số nào
   dưới ngưỡng, câu trả về nêu rõ có bao nhiêu chỉ số có ngưỡng trên tổng số.
5. **Không có điểm gộp.** Không tạo "Sim-Ready Score" hay bất kỳ điểm tổng hợp có trọng
   số nào. Không sinh câu khẳng định scene sẵn sàng mô phỏng hay sẵn sàng duyệt, vì nhóm
   hình học và va chạm chưa có verdict.
6. **Thêm peak RAM, peak VRAM và cấu hình đã dùng vào nhóm Hệ thống**, lấy từ các bản ghi
   `completed` của đúng job. Ba chỉ số này không có verdict.
7. **UI:** khối khuyến nghị ở đầu bảng tổng hợp và dòng tham chiếu dưới chỉ số. Không vẽ
   thanh so ngưỡng, vì `Metric.threshold` là chuỗi mô tả và chỉ bốn chỉ số có verdict.

## Điều kiện để bật verdict cho PSNR/SSIM/LPIPS sau này

Đây là quyết định của owner, nằm ngoài AUD-28. Đề xuất: chỉ mở khi file tham chiếu có đủ
scene đã được reviewer duyệt và có cả scene bị reviewer từ chối vì chất lượng hình ảnh,
để ngưỡng được suy ra từ ranh giới giữa hai nhóm. Số scene tối thiểu do owner chọn.

## Hệ quả

- Schema bảng đánh giá lên 1.1: thêm `JobEvaluation.summary: list[str]` và
  `Metric.reference: str | None`. Consumer phải cập nhật cùng lúc: `report.py`,
  `frontend/src/lib/api/studio.ts`, `EvaluationCard.tsx`.
- `evaluate_job` nhận thêm đường dẫn file tham chiếu và danh sách bản ghi tài nguyên; cả
  hai đều tùy chọn, thiếu thì bảng đánh giá vẫn trả về.
- Thêm một setting `product_evaluation_reference` trong `src/config.py`.

## Giới hạn đã biết

- Khoảng tham chiếu của sáu scene chỉ mô tả những gì đã thấy; scene nằm ngoài khoảng
  chưa chắc là xấu. Câu hiển thị phải nói "các scene đã chạy", không nói "chuẩn".
- Job chạy trước khi có đo tài nguyên sẽ hiện "Chưa đo" ở ba chỉ số hệ thống mới.
