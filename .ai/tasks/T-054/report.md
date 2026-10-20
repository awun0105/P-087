# T-054 report
- `observed.load_usages(database, job_ids=...)`: lọc theo `job_id IN (...)` (bảng đã có index theo job).
- `/scenes`: lấy job mới nhất của từng project trước, rồi chỉ đọc usage của các job đó; tính `processing_seconds` bằng đúng hàm cũ (kết quả khớp, có test so sánh).
- `stage_views`: đệm theo (registry, job, checksum manifest); route `/stage-views` có ETag theo checksum manifest + 304.
- Lệch plan:
  - Không viết lại quy tắc tính phí bằng SQL: lọc dòng theo job rồi dùng lại hàm Python để chắc chắn khớp.
  - Không làm `latest_jobs` một truy vấn và đệm `preview_ready`: sau T-053, `list_jobs`/`get_job` chỉ còn truy vấn DB + trúng đệm manifest; `preview_ready` dùng đường kiểm preview đã có đệm.
  - Không đổi `job_requesters` (đọc sự kiện theo lô một lần mỗi request, giữ nguyên).
- Rủi ro đã cân nhắc: stage-views được đệm theo manifest; worker đẩy artifact lên kho trước khi commit manifest, nên kết quả không bị đệm khi artifact chưa có.
