# T-061 report
- `stages.ts`: metadata `ST-ANONYMIZATION-REVIEW`, `ST-OBJECT-CONFIRM`, `ST-SCENE-DECOMPOSE`; `stageMeta` biết mọi bước backend gửi.
- `scene/stepActions.ts`: mọi nút của dòng tiến trình tính từ `next_action` (một nhánh mỗi loại) + "Hủy yêu cầu" khi việc hàng đợi tách vật đang chạy; "Dùng hộp ứng viên" chỉ khi `choose_object_method`; không handler → không nút.
- `scene/pipeline.ts`: `timelineFromSteps(view, now)` — thứ tự bước của backend, thời lượng cho bước hệ thống, "Chờ bạn x phút" / "Bạn xử lý trong x phút" cho bước người dùng, "Đang chờ máy xử lý" khi `queued`, nhãn pha.
- `ProgressTab`: trong trang scene (có `PipelineContext`) vẽ từ bước thật + `stepActions`; ngoài trang scene giữ đường cũ (dọn ở T-063).
- `usePolling`: đổi nhịp không còn khởi động lại vòng poll (trước đây làm thêm một request ngay lúc mở trang).
- `PipelineTimeline` bọc `memo`; hướng dẫn lỗi cho `OBJECTIFY_AWAITING_CHOICE`, `OBJECT_GEOMETRY_BUILD_FAILED`.
- Test: step-actions (9), use-pipeline (+1), use-polling-interval, error guidance (+2). Full frontend 1064/1064 trước bước memo/guidance.
- Lệch plan: không đổi tiêu đề "Collision môi trường" (3 test, một của phiên khác, khẳng định tên này; từ vựng gom ở T-062); chưa xoá hàng giả `UI-GEOMETRY-REVIEW` / demo replay vì đường cũ còn dùng ngoài trang scene (T-063). Test hướng dẫn lỗi viết cùng lúc với code (không thấy đỏ trước).
