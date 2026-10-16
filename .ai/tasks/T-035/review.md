# Review T-035

Verdict: ACCEPTED

Audit: diff `03168b1d` (ẩn lớp phủ khi chọn điểm trong `MetricSceneView`, nhãn "vật đã xoá", dòng tổng hợp Markdown),
`e2d99ccb` (test schema), `0056c5dd` (HANDOFF.md).

- **Full backend do Architect chạy lại sau khi sửa test schema: 3.688 pass, 0 fail, 28 skip (8 phút 35 giây).**
  Agent chưa chạy lại; số này đóng mục đó.
- Test schema: đổi `LATEST_SCHEMA_VERSION == 19` thành `schema_version() >= 19`, ngay dưới vẫn kiểm `== LATEST_SCHEMA_VERSION`;
  `test_runtime_migrations.py` đã ghim 21. Không làm test lỏng đi.
- Ẩn lớp phủ: dùng `InspectionState.measuring` có sẵn, áp cho collision, collider, box, vỏ và marker mặt; tắt đo thì hiện lại.
  Cũng áp cho công cụ đo thường, hợp lý vì đo luôn trên splat.
- HANDOFF.md đủ nguồn 5 metric, cách nhập/xuất, đủ 4 mục giới hạn yêu cầu; định nghĩa bậc khớp §15.3.

Còn nhỏ, không chặn: dòng tổng hợp đầu `benchmark_markdown` vẫn ghi "bỏ sót: 0 · giả: 0" khi `gaps_total == 0`.

Architect đã cập nhật Playbook mục 3, 6, 9 theo danh sách trong handoff.
