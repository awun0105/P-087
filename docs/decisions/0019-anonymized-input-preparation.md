# 0019 Anonymized input copy và QA trước dispatch

Date: 2026-10-07

## Status

Accepted (owner, 2026-10-09) với phạm vi ở mục 6–9: che tự động, người upload chấp nhận bản đã che,
`qa_verified` = bắt buộc che. Các phần "manual correction" và reviewer riêng ở mục 2–3 không triển khai.

## Context

Studio MVP có self-attestation, không phải auto detector chắc chắn tìm được
PII rồi reject. RGBPrivacyGate đã có inspection/QA acceptance contract. Có thể
thêm detection/tracking/redaction nhưng zero detections không chứng minh anonymous.

## Decision đề xuất

1. Opt-in input preparation tạo sanitized copy/selected frames trước training,
   thumbnails và public artifact publication. Original giữ access boundary hiện có.
2. Face/plate detector + temporal tracking + blur/mosaic/redaction có model/config
   identity và all-frame coverage; manual correction/QA cho missed/uncertain regions.
3. PrivacyInspectionEvidence/PrivacyQAAcceptance dùng lại để gate; automation
   không tự cấp QA acceptance hoặc VERIFIED_ANONYMIZED từ confidence score.
4. Derived sanitized input có source lineage, byte checksum, frame/time mapping;
   downstream chỉ consume approved copy đúng checksum khi mode này được chọn.
5. License code/model weights/data và detector quality envelope phải qualified
   trước runtime adoption. Không xem “YOLOv8-Face” là default miễn điều kiện.

6. (Owner chốt 2026-10-09, thay cho quyết định "không có bước duyệt" cùng ngày) Người upload tự xem và chấp
   nhận bản đã che trước khi dựng 3D. Sau bước che, job dừng ở `ST-FRAME-EXTRACT` với lý do chờ
   `anonymization_review`; worker không chạy COLMAP cho tới khi job có bản ghi `SanitizationAcceptance` gắn với
   đúng checksum của bộ frame đã xem. Không đồng ý thì người dùng hủy job. Không có vai trò reviewer riêng và
   không có sửa tay vùng che: phần "manual correction" ở mục 2 và 3 không được triển khai.
7. (Owner chốt 2026-10-09) `PRODUCT_PRIVACY_MODE=qa_verified` nghĩa là: mọi video upload qua Studio bị che tự
   động và, khi có frame bị che, phải được người upload chấp nhận trước khi dựng 3D. Worker tự áp việc che theo
   chế độ của project, không dựa vào cấu hình job do API ghi. Cổng dispatch cho video upload ở chế độ này đi
   qua với report `PRELIMINARY_SCREENED`; project không phải video upload vẫn cần `VERIFIED_ANONYMIZED`.
8. Job không có frame nào bị che thì chạy tiếp ngay, không dừng chờ: worker ghi một `SanitizationAcceptance` tự
   động (`accepted_by` rỗng, 0 frame bị che), phân biệt được với chấp nhận của người.
9. Privacy report của input không bị sửa thành `VERIFIED_ANONYMIZED`: bằng chứng của bước kiểm là bản ghi
   `SanitizationAcceptance` trên job. Bộ phát hiện có thể bỏ sót, nên lời khai của người upload vẫn bắt buộc ở
   cả hai chế độ.

## Data contract

AUD-18.S1 chốt SanitizationManifest refs/detections/redaction coverage/model
identity; map vào privacy evidence/report hiện có. Detection metadata giữ trong
restricted artifact boundary; logs không lưu crops/PII hoặc original download URLs.
Không silently replace user source hoặc override source-rights attestation.

## Alternatives Considered

1. Manual anonymization only: giữ là supported fallback, nhưng owner muốn plan auto tool.
2. Một model + zero detections → VERIFIED: không đủ inspection/QA proof.
3. Redact sau training: raw PII có thể đã vào thumbnails/3DGS; không chọn.

## Consequences

Positive: assisted anonymization reuse gate, downstream lineage rõ.
Tradeoffs: full-frame inference/tracking/QA, license/quality qualification và
restricted original/derived artifact handling.

## Follow-Up

- [AUD-18](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-18-privacy-anonymizer.md).
- [Technology/coverage note](../plans/active/2026-10-07-codegraph-audit/TECHNOLOGY_LIMITS.md).
