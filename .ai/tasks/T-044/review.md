# Review T-044

Verdict: CHANGES REQUESTED (1 sửa, kèm hướng dẫn)

Audit: 12 commit `d2c5d3cb` → `e3523b64`. Đọc trọn `src/services/orchestration/jobs/stage_results.py` (nguồn mọi dòng kết quả và
dữ kiện bundle), mô tả bước trong `frontend/src/features/studio/stages.ts`, quyết định về thời gian trong report. Chạy
`test_progress_notes.py` + `test_sample_export.py`: 51 PASS; `check_contract_mirror.py`: PASS.

Đã kiểm, đúng:
- Mô tả bước: tiếng Việt rõ, đúng các nhánh (che mặt và chờ duyệt, tỉ lệ đề xuất từ ảnh/LiDAR hoặc đo tay, lưới từ ảnh/LiDAR,
  ObjectGS hoặc cách cũ); không còn "CoACD"/"voxel" trong câu hiển thị (chữ "REC-" chỉ còn trong chú thích code).
- Dòng kết quả chỉ lấy từ biên nhận thật, kiểm checksum và job_id, nguồn đề xuất phải khớp phương pháp (`methods`), thiếu hoặc
  hỏng thì bỏ riêng dòng đó; không suy từ cấu hình. Đếm vật chỉ tính `origin == "reconstructed"`.
- Thời gian: không còn 0 giả; bước prepare gộp được ghi rõ; thời gian Tạo mesh chỉ lấy từ request `geometry` đúng revision.
- Bundle cũ vẫn đọc được (trường mới tuỳ chọn); không ghi vào `data/demo/library`.

## Required changes

### 1. Bộ đệm `_read` giữ nguyên tài liệu lớn trong RAM của API
`stage_results.py:29–38`: `@lru_cache(maxsize=128)` lưu **cả dict đã parse** của mọi file đọc qua `_read`, giới hạn mỗi file
4 MiB. `scene_results` (dòng 45–53) đọc **toàn bộ scene head** qua bộ đệm này. Đo trên máy: scene Room
(`job-a14981f78f85`, 60 vật) là 818 KB JSON, khi parse thành dict Python chiếm cỡ vài MB. Mỗi lần sửa scene sinh revision mới
→ một mục mới trong bộ đệm; UI poll `/progress` liên tục. Với nhiều scene cỡ Room, 128 mục có thể chiếm hàng trăm MB tới
khoảng 1 GB trên API Railway (RAM hạn chế), và không bao giờ nhả.

Sửa:
- Bỏ `@lru_cache` khỏi `_read` (đọc file nhỏ không tốn đáng kể; checksum vẫn kiểm mỗi lần).
- Đệm **kết quả đã rút gọn** thay vì tài liệu gốc: tách phần đọc scene trong `recorded_results` thành hàm
  `_scene_summary(resolver, uri, checksum) -> tuple` có `@lru_cache(maxsize=256)`, chỉ trả các giá trị nhỏ cần dùng:
  `candidate_count`, `object_extraction`, `collision_selection_ref` (uri, checksum), `collision_source_ref`,
  `object_geometry` state, danh sách `surface_selection.chosen`, `collider_count`, `scene_revision`. Tương tự đệm phần biên
  nhận tỉ lệ và bundle collision bằng tuple rút gọn (khoá theo checksum).
- `_redaction_summary` khoá theo `job.model_dump_json()` (chuỗi lớn làm khoá): đổi khoá sang
  `(job_id, sanitized_stage.artifact_checksum)` và đọc job qua registry bên trong nếu cần.
- Test (đỏ trên code cũ): gọi `stage_notes` cho 300 revision giả của một scene lớn (fixture vài trăm vật) rồi kiểm
  `_scene_summary.cache_info().currsize <= 256` và không còn hàm nào đệm dict scene đầy đủ (ví dụ kiểm `_read` không có
  `cache_info`). Giữ nguyên kết quả `stage_notes`/`result_facts` cho các ca hiện có (test cũ phải xanh).
- Đo lại thời gian `/progress` trên 3 job local như report, ghi vào Round 2.

## Suggestions (không bắt buộc)
- `stage_notes` dòng 218–231: nếu đã có bản chấp nhận **cũ** (checksum không khớp bản đã che hiện tại) mà job đang chờ duyệt lại,
  hiện không có dòng nào vì `elif` chỉ chạy khi chưa có bản chấp nhận. Nên hiện "Chờ bạn duyệt N vùng đã che" khi
  `awaiting_anonymization_review(job)` bất kể có bản chấp nhận cũ.
- Dòng ghi chú tỉ lệ "Bạn đo tay" có thể thêm ", bạn đã xác nhận" cho đồng giọng với các nhánh còn lại.
