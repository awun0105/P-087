# 0019 Anonymized input copy và QA trước dispatch

Date: 2026-10-07

## Status

Proposed — scope mở rộng theo yêu cầu owner; không tự đổi self_attested hay
qa_verified authorization của implementation hiện có.

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

6. (Owner chốt 2026-10-09) Không có bước duyệt của reviewer: job chọn che chạy thẳng từ frame đã che sang dựng
   3D để giữ thời gian xử lý ngắn nhất. Vì không ai kiểm bản đã che, không có đường nào cấp
   `VERIFIED_ANONYMIZED`; job giữ trạng thái tự cam kết. Phần "manual correction/QA" ở mục 2 và 3 không được
   triển khai.

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
