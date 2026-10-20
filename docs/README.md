# Bản đồ tài liệu

Mỗi chủ đề có **một** tài liệu trình bày chính. Tài liệu khác chỉ dẫn liên kết tới đó, không chép lại. Khi hai nơi nói khác nhau, tin tài liệu chính; khi tài liệu chính khác code, tin code và sửa tài liệu.

## Tài liệu chính

| Tài liệu | Trả lời câu hỏi | Đọc khi |
| --- | --- | --- |
| [README](../README.md) | Dự án là gì, dùng thử ở đâu, chạy nhanh thế nào | Lần đầu gặp dự án |
| [BRAINSTORM](BRAINSTORM.md) | Vì sao chọn bài toán này, lập luận định vị | Cần hiểu gốc ý tưởng |
| [MASTER_PITCH](MASTER_PITCH.md) | Câu chuyện sản phẩm, người dùng, thông điệp, điều được phép nói | Chuẩn bị trình bày, viết nội dung giới thiệu |
| [PRD](PRD.md) | Sản phẩm phải làm gì, cho ai, nghiệm thu bằng tiêu chí nào | Quyết định phạm vi, viết tiêu chí hoàn thành |
| [ARCHITECTURE](../ARCHITECTURE.md) | Hệ thống gồm phần nào, mỗi phần giữ dữ liệu gì, nối với nhau ra sao | Thêm module, đổi nơi lưu, đổi cách triển khai |
| [PIPELINE](PIPELINE.md) | Dữ liệu đi qua những bước nào, nhánh nào, chờ người dùng ở đâu | Sửa một bước xử lý, chẩn đoán job |
| [CONTRACTS](CONTRACTS.md) | Quy tắc định danh, checksum, tọa độ, revision, bằng chứng giữa các phần | Đổi schema, thêm artifact, đổi luồng duyệt |
| [UX](UX.md) | Màn hình, thao tác, quyền và trạng thái hiển thị | Sửa giao diện, viết hướng dẫn người dùng |
| [OPERATIONS](OPERATIONS.md) | Cài, chạy, cấu hình, bàn giao, khôi phục, triển khai | Dựng máy mới, vận hành production |
| [EVALUATION](EVALUATION.md) | Đo chất lượng bằng dữ liệu nào, lệnh nào, kết luận đến đâu | Chạy đo, trích số liệu |
| [STATUS](STATUS.md) | Phần nào đã chạy thật, phần nào mới có code, còn thiếu gì | Báo cáo tiến độ, chọn việc tiếp theo |

[Sơ đồ kiến trúc](architecture_diagram.md) là bản tóm tắt bằng hình cho hồ sơ nộp bài; nội dung đầy đủ ở ARCHITECTURE.

## Hồ sơ và quy định được giữ riêng

Các nhóm dưới đây không phải mô tả hệ thống hiện hành. Chúng được giữ để làm việc hoặc truy vết, không sửa để khớp tài liệu chính.

| Nhóm | Vị trí | Vai trò |
| --- | --- | --- |
| Quy định cho agent | [AGENTS.md](../AGENTS.md), [GUIDE.md](../GUIDE.md), [plain-prose.md](../plain-prose.md), [WORKFLOW.md](WORKFLOW.md), [patterns/](patterns/) | Cách agent đọc, sửa, kiểm và bàn giao |
| Đóng góp, bảo mật, giấy phép | [CONTRIBUTING](../CONTRIBUTING.md), [SECURITY](../SECURITY.md), [CODE_OF_CONDUCT](../CODE_OF_CONDUCT.md), [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md), [LICENSE](../LICENSE) | Quy tắc cho người đóng góp |
| Sổ tay kỹ thuật | [guide/](guide/) | Technical Book của chương trình; sửa cần book-maintainers duyệt |
| Nhật ký dự án | [WORKLOG](../WORKLOG.md), [JOURNAL](../JOURNAL.md), [AI_LOG_SETUP](AI_LOG_SETUP.md), [mentor-duty-report/](mentor-duty-report/) | Hồ sơ nộp bài, tiến độ theo tuần |
| Đề bài gốc | [RAV01_MO_TA_DE_TAI](RAV01_MO_TA_DE_TAI.md) | Mô tả đề tài do chương trình giao |
| Quyết định kiến trúc | [decisions/](decisions/) | ADR; quyết định còn hiệu lực đã đưa vào tài liệu chính |
| Kế hoạch và task | [plans/](plans/), [execution/](execution/), `.ai/` | Phạm vi, báo cáo và bằng chứng của từng task; `scripts/check_foundation.py` kiểm bốn file trong `execution/` |
| Protocol và kết quả đo | [`eval/protocols/`](../eval/protocols/), [`eval/results/`](../eval/results/) | Bằng chứng gốc mà EVALUATION và STATUS dẫn tới |
| Tài liệu cũ | [archived/](archived/) | Bản đã được thay thế, còn giữ vì code hoặc hồ sơ trích dẫn |
| Mẫu | [templates/](templates/) | Mẫu task, ADR, kế hoạch |

## Khi cập nhật tài liệu

- Sửa đúng tài liệu chính của chủ đề; nơi khác chỉ sửa liên kết.
- Ghi rõ ngày đối chiếu và commit ở mục 0 của tài liệu kỹ thuật khi đối chiếu lại với code.
- Tách bốn loại phát biểu: yêu cầu sản phẩm, hành vi code hiện tại, kết quả đã chạy thật có ngày và nguồn, kế hoạch chưa làm.
- Không tạo tài liệu tổng quan, tóm tắt hay trạng thái mới cạnh tranh với bảng trên. Cần thêm chủ đề mới thì bổ sung một hàng vào bảng.
