# T-055 report
- `geometry_state.py`: `object_geometry_state` coi `None` như thiếu khoá; thêm `object_geometry_view` (hiển thị, không ném; lạ → awaiting_review + cảnh báo) và `has_geometry_review`.
- Xoá `objectify_queue.object_geometry_status`; `state()` và `/scenes` dùng `object_geometry_view`.
- `objectify_queue`: tách quy tắc thuần `review_state(record, object_geometry, revision)` + `latest_request(database, job_id)`; `geometry_review` dùng chúng.
- `stage_results`: bỏ câu SQL tự đọc `r2s_scene_requests`, dùng `latest_request` + `review_state` (nhập trong hàm để tránh vòng import).
- Test: 5 test mới ở test_geometry_state, `test_review_state_rule_is_shared`.
- Lệch plan: `stage_results` vẫn đọc khoá thô từ JSON SceneIR (không parse model) cho phần tóm tắt; giá trị lạ không hiện dòng kết quả — giữ như cũ.
