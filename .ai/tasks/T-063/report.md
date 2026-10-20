# T-063 report: một lần tải scene/gói/duyệt; dọn nhánh chết

## Đã làm
- `lib/api/studio.ts`: `getJobScene` dùng chung một request đang bay theo job và giữ bản đã parse kèm ETag; lần hỏi sau gửi
  `If-None-Match`, máy chủ trả 304 thì dùng lại đúng đối tượng cũ (không tải lại ~650 KB, không parse lại).
- `getSimulationPackage` và `getReviewState` dùng chung request đang bay (`shareInFlight`); xong là quên, nên không giữ bản cũ sau
  thao tác tạo gói / duyệt. `signal` của từng caller chỉ để thôi chờ, không hủy request chung.
- `ValidationRunsPanel` bỏ vòng `setTimeout` tự viết, dùng `usePolling` 5 s chỉ khi còn lượt đang chạy; tab ẩn thì nghỉ, quay lại
  hỏi ngay.

## Lệch so với plan (Ruling trong ledger)
- Không làm `SceneRecordProvider`: gom ở tầng API cho kết quả "một lần tải mỗi revision" mà không phải nối lại năm component và
  luồng xử lý 409. Mỗi component vẫn giữ luật so revision của mình.
- Không xoá: `GAUSSIAN_EDIT_ENABLED` (công tắc tạm của chủ dự án), `StageState` 4 giá trị, `NextAction.tsx`,
  `objectifyStageOverride`, `geometryReviewStep` (vẫn được dùng), nhánh dự phòng `sceneSummaryStatus` (API mới chưa lên).

## Kiểm thử
- `tests/scene-request-cache.test.ts` (5): chung request, 304 dùng lại đối tượng, lỗi không vào đệm, gói/duyệt chung request.
- `tests/validation-runs-polling.test.tsx`: tab ẩn không hỏi, quay lại hỏi ngay (RED trước khi đổi: 4 lần gọi thay vì 1).
- Các test review/package/results/validation: 13 file, 171 test xanh. Typecheck và eslint sạch.

## Đo
- Chuyển tab sau lần tải đầu: SceneIR chỉ còn request 304 (không thân), không parse lại.
