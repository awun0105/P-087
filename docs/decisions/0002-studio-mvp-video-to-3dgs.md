# 0002 Studio MVP: lát cắt video → 3DGS có editor, demo xử lý sẵn

Date: 2026-09-29

## Status

Proposed — owner EX-REC/Tech Lead (Quân) chốt hướng ngày 2026-09-29; cần Product
Owner (Cường) và QA/Validation Lead (Đạt) xác nhận để thành Accepted.

## Context

- Còn 4 ngày tới mốc MVP của owner; EX-SCENE và EX-SIM chưa có producer thật, nên
  P0 đầy đủ của PRD §4.1 (SceneObject, collider, OpenUSD, Isaac, review/release)
  chưa thể chạy xuyên suốt.
- Owner cần một luồng chạy được để demo: người dùng tải video → pipeline EX-REC →
  xem/chỉnh scene 3DGS trong browser; kèm kịch bản demo đã xử lý sẵn cho pitching.
- `docs/execution/tracks/ex_product/TRACK.md` §Authority Gates và Contract §3.3.1
  yêu cầu không bypass privacy gate cho demo; QA chấp nhận `VERIFIED_ANONYMIZED`.
- PRD §2.3/NFR-05 cho phép MVP dùng dữ liệu public hoặc tự quay không có PII và
  không bắt buộc hệ thống tự làm mờ khuôn mặt/biển số.

## Decision

1. Studio MVP là UI mới (route group `(studio)`); UI cũ giữ nguyên code, ẩn sau
   `LEGACY_UI=1` (`redirects()` trong `frontend/next.config.ts`).
2. Lát cắt MVP: upload video → `ST-INPUT-VALIDATE` → `ST-PRIVACY-GATE` →
   `ST-FRAME-EXTRACT` (stride) → `ST-CAMERA-POSE` → `ST-VISUAL-RECON` →
   `ReconstructionPreview` (metric `UNCONFIRMED`) → editor.
3. Chỉnh sửa ở mức Gaussian bằng SuperSplat 3.4.2 (MIT, vendor tại
   `frontend/vendor/supersplat`), export PLY/SOG về máy người dùng. Đây **không**
   phải SceneObject/collider của PRD FR-08/09.
4. Privacy trong MVP: deployment bật `PRODUCT_PRIVACY_MODE=self_attested`; người
   upload xác nhận quyền và việc không có khuôn mặt/biển số; report giữ
   `PRELIMINARY_SCREENED`, 0 frame được người kiểm tra; không phát
   `VERIFIED_ANONYMIZED`. Mặc định code vẫn là `qa_verified`.
5. Kịch bản demo dùng demo bundle export từ job thật chạy qua cùng pipeline trên GPU
   (`scripts/demo/export_demo_bundle.py`), phát lại tiến trình theo thời lượng thật.

## Alternatives Considered

1. Giữ P0 đầy đủ của PRD: không khả thi trong 4 ngày khi SCENE/SIM chưa có producer.
2. Demo bằng dữ liệu vẽ tay/giả lập tiến trình: bị loại vì AGENTS.md cấm báo kết quả
   không có evidence.
3. Tự viết lại công cụ chỉnh Gaussian: quá lâu; SuperSplat đã có selection/transform/
   measure/export với license MIT.

## Consequences

Positive:

- Có luồng người dùng thật chạy được end-to-end (đã chạy local 2026-09-29).
- Demo trung thực: số liệu và file 3DGS lấy từ job thật.

Tradeoffs:

- Editor SuperSplat cần WebGPU; trình duyệt không có WebGPU chỉ xem được (WebGL2).
- Privacy tự khai yếu hơn QA verified; cần đồng ý của Product Owner + QA Lead.
- Chỉnh sửa trong editor chưa lưu revision về backend; export chỉ là file tải về.

## Follow-Up

- Product Owner + QA Lead xác nhận hoặc từ chối mục 4 (privacy tự khai).
- Sau MVP: metric confirmation (ADR 0001) từ editor, lưu edited Gaussian revision
  vào backend, nối SceneIR/SIM; xóa người/vật thể trước train bằng mask (xem plan).
