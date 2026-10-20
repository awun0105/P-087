# T-062 report
- `features/studio/nextAction.ts` (mới): `nextActionView(action, ctx)` — một bảng câu chữ cho 16 loại việc (tiêu đề, mô tả, nút đích + nhãn nút, nhãn trạng thái); `operationLabel(mode)` ("Đang tạo mesh", "Đang dựng lại vùng"…); chờ máy khi GPU `off`/`starting` → "Đang khởi động máy GPU" kèm số phút còn lại.
- Chuông (`NextAction`): trong trang scene lấy câu từ `next_action`, **không còn tải SceneIR / gói / duyệt mỗi 10 s**; trạng thái thử lại và mất tín hiệu phía máy khách vẫn đứng trước. Ngoài trang scene giữ đường cũ.
- Nhãn đầu trang (`ScenePage`) và danh sách scene (`sceneSummaryStatus` theo `SceneSummary.next_action`, API cũ dùng đường cũ) dùng cùng bảng.
- `ObjectifyNotice` dùng `operationLabel` (hết "Đang áp vùng" / "Đang tái tạo sau hiệu chỉnh Gaussian").
- `ProgressTab`: `GpuStartupNotice` (component của phiên deploy) trong khung chờ máy khi `view.gpu` có.
- Test: next-action-view (5), bell-from-pipeline, scene-summary-next-action (2), gpu-notice-in-progress (2), objectify-notice-wording. Full frontend 1077/1077.
- Lệch plan: giữ `GeometryReviewBanner` (đã dùng đúng quy tắc vật chờ duyệt như backend); không đổi `GeometryBadge`/tiêu đề "Collision môi trường" (test của phiên khác khẳng định); hủy job khi chờ bản che đã được cho phép sẵn (chỉ chặn khi chờ xác nhận mét) nên không sửa. Chuông để trống khi máy chỉ đang chạy bình thường (giữ hành vi cũ).
