# Review T-022

Verdict: ACCEPTED

Đọc diff source `22181667`; kiểm `inpaint_runner.py:272` (một đường trả về, luôn có `inpainted_gaussians`) nên kiểm kiểu mới
không làm build vốn đúng bị lỗi. Chạy lại 8 test mới: PASS.

## Acceptance criteria
1. Pass. Full build ghi count = số hàng vá; `representation_issues == []`; test e2e CoACD thật qua Confirm → package (`9e903dbe`).
2. Pass. Partial rebuild ghi đè count mỗi revision, có ca về 0.
3. Pass. Count sai cố ý vẫn `SOURCE_BACKGROUND_INVALID`; validator không đổi.
4. Pass. Test giữ head khi lỗi/huỷ vẫn PASS.

## Quyết định của engineer
- Cập nhật count trong correction `reassign` thay vì ghi đè: chấp nhận, giữ trường audit.
- Làm T-022 khi T-019 còn `changes-requested`: chấp nhận. Phụ thuộc trong roadmap là "sau review T-019", không phải "T-019 accepted".
