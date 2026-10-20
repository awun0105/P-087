# T-058 report
- Package mới `src/services/orchestration/pipeline/`; `next_action.py`: `NextActionKind` (16 loại), `SceneOperationFacts`, `PackageFacts`, `NextActionFacts`, `NextAction`, `next_action()`, `pending_candidates()`.
- Thứ tự quy tắc như chuông cũ: đang dựng > Draft (Tạo mesh lỗi trên revision hiện tại → retry_geometry, ngược lại review_objects kèm số vật chờ) > chọn cách tách vật > vật chờ xác nhận > (không đọc gói → scene_ready) > released > await_review > review_package > fix_preflight > create_package.
- Test: test_next_action (26: mỗi quy tắc + thứ tự + đếm vật chờ).
- Lệch plan: kiểu trạng thái/mode hàng đợi khai báo lại dạng Literal trong module (tránh import objectify_queue, giữ hàm thuần nhẹ); giá trị khớp `ObjectifyStatus`/`ObjectifyMode`.
