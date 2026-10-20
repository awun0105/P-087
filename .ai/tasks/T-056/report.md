# T-056 report
- `StageId.ANONYMIZATION_REVIEW = "ST-ANONYMIZATION-REVIEW"` (backend + `STAGE_IDS` frontend, ngay sau ST-FRAME-EXTRACT).
- **Migration v26**: bảng `r2s_step_marks(job_id, run_kind, run_id, step_id, started_at, completed_at, outcome)`, khoá chính 4 cột. API và worker phải lên cùng lúc (code cũ từ chối DB schema mới hơn).
- `jobs/step_marks.py`: `StepMark`, `MarkWrite`, `marks_for_revision` (R1 bắt đầu stage, R2 artifact mới, R3 bắt đầu chờ bản che, R4 đóng mốc khi FAILED/CANCELLED), `apply_marks` (mốc bắt đầu sớm nhất và kết thúc đầu tiên thắng), `record_marks` (lỗi chỉ cảnh báo), `list_marks`.
- `save_job`: ghi mốc trong cùng transaction với revision job.
- Runner `_StageProgress`: dòng SUCCEEDED/FAILED/CANCELLED của worker → mốc kết thúc ngay (đọc số lượt chạy lười, lỗi chỉ cảnh báo).
- Xoá/khôi phục scene: `r2s_step_marks` nằm trong danh sách bảng của thùng rác (xoá và khôi phục cùng job).
- Test: test_step_marks (13), `test_stage_progress_poll_records_completion`, frontend `stage-ids-contract`.
- Sửa kèm lỗi do T-055: `test_sample_export` fixture thiếu `requested_at`; `stage_results` bỏ qua bản ghi hàng đợi hỏng như trước.
- Lệch plan: không viết test migration riêng cho v26 (các test "DB mới lên bản mới nhất" và "nâng từ v1" đã chạy qua v26); test xoá job dùng bộ test thùng rác hiện có (xanh).
