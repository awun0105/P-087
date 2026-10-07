# 0012 Background collision cho scene chỉnh sửa và capability của USD exporter

Date: 2026-10-07

## Status

Proposed — khuyến nghị từ audit `develop@ef3a421`; chưa có owner acceptance hoặc
implementation mới. Invariants hiện có về canonical transform và exact candidate vẫn áp dụng.

## Context

`_carved_environment` khoét mesh gốc theo transform hiện tại và active state.
Move/delete vì vậy giữ lại hoặc phục hồi collision vật ở vị trí cũ. Hybrid path
cũng đọc canonical collision geometry gốc. Generator dự phòng tạo Mesh không
có topology cho các collider mesh, nhưng candidate có thể nhận preflight PASS.

## Decision đề xuất

1. Tách source geometry ownership khỏi editable transform. Ghi source region/
   source pose theo extraction revision và upstream geometry checksum.
2. Build background từ source ownership bất biến; compose object collider tại
   transform hiện tại. Delete hoặc canonical deactivate loại collider vật,
   không đưa geometry vật trở lại background. Ignore candidate giữ source
   geometry ở environment; client-only visibility không đổi physics.
3. Không khoét nền theo vị trí của user_added object. Vùng chồng lấn phải theo
   ownership, không trừ một hộp khiến mất sàn/tường không thuộc object.
4. Exporter khai báo capability theo scene/physics requirements. Nhánh box-only
   chỉ nhận representation đã xuất đúng; scene cần convex/hybrid/physics mà
   runtime không đáp ứng phải bị block hoặc được gửi worker phù hợp.
5. Candidate build identity ghi effective builder/config. Không silently
   downgrade thành box, empty Mesh hoặc bỏ mass/material để tạo package.

## Data contract

Giữ SceneIR/ColliderSpec/CandidatePackage hiện có. Source ownership metadata
hoặc sidecar phải bind source geometry checksum, extraction revision, object ID,
source transform và representation. S1 của AUD-01 chốt typed format/placement;
không serialize vùng/source pose dưới dạng world transform truth thứ hai.
Legacy revision thiếu metadata phải recover từ artifact gốc hoặc báo blocker.

Capability check phải xảy ra trước publish physics_enrich revision. Artifact
mesh cần finite vertices, topology hợp lệ, correct local transform và resolver
closure. USD stage phải dùng canonical units/axes; visual và physics cùng object ID.

## Alternatives Considered

1. Khoét bằng current transform: lỗi đã tái hiện khi move/delete.
2. Luôn dùng source OBB: phù hợp hotfix có provenance; không đủ khi OBB cắt nền
   hoặc vật chồng lấn. Dùng membership chính xác khi extraction đã cung cấp.
3. Cho fallback xuất mọi collider: không có fidelity proof; không chọn.
4. Bắt mọi box scene dùng Isaac/USD runtime: tăng dependency không cần thiết;
   box-only exporter hợp lệ vẫn có thể giữ.

## Consequences

Positive: collision phản ánh edit; export capability minh bạch; package không
được tạo từ geometry rỗng. Tradeoffs: legacy ownership cần migration/recovery;
scene v2 cần worker có runtime phù hợp.

## Follow-Up

- [AUD-01](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-01-collision-background.md).
- [AUD-02](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-02-usd-capabilities.md).
- Producer/consumer contract fixture; move/delete/ignore/overlap regressions;
  pxr stage checks và real Isaac smoke thuộc AUD-05.
