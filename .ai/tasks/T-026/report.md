# T-026: Danh sách scene hiểu Draft — báo cáo

Làm trực tiếp theo yêu cầu chủ dự án (không qua plan riêng). Không có review độc lập: Architect tự làm.

## Đã làm
- Backend (`4fee0110`): `objectify_queue.geometry_review()` cùng quy tắc với `geometryReviewStep` (running khi việc dựng
  geometry/region/membership đang chạy; Draft: failed khi build lỗi đúng revision, ngược lại waiting; Ready/scene cũ: None).
  `SceneSummary.geometry_review`; `scenes._geometry_review` cache trạng thái scene theo revision, đọc hàng đợi mỗi lần poll.
- Frontend (`eca3462f`): `sceneStatus` nhận `geometryReview`; một bảng nhãn `GEOMETRY_STATUS` dùng chung cho danh sách và
  đầu trang ("Chờ duyệt vật", "Đang tạo mesh", "Tạo mesh lỗi"). API cũ/Ready giữ "Đã dựng scene".

## Kiểm thử
- Backend: 13 ca `geometry_review` + 2 test route/cache, cùng nhóm object-choice: 20 PASS. Ruff, mirror PASS.
- Frontend: 7 file test trạng thái: 80–81 PASS; typecheck exit 0; eslint 0 lỗi (1 cảnh báo có sẵn ở dòng 11).
- Không chạy full suite.
