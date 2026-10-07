# 0012 Background collision cho scene chỉnh sửa và capability của USD exporter

Date: 2026-10-07

## Status

Accepted for the AUD-01 source-ownership contract; implementation is in progress.
Exporter capability/publication changes are tracked by AUD-02. Existing invariants
for canonical transforms and exact candidates still apply.

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
6. Legacy và hybrid builder consume cùng một source-owned background. Identity
   là SHA-256 của algorithm, checksum mesh nguồn, face count, carve margin và packed
   removed-triangle mask; CandidateManifest bind identity qua build-config
   checksum. OBB claims có margin dùng chung và overlap mơ hồ bị reject.

## Data contract

`SceneObject.source_collision` is optional `SourceCollisionRegion` schema 1.0.
It stores `source_geometry_ref`, `extraction_revision`, `object_id`, immutable
`source_transform`, and either a `region_ref` to a typed triangle-membership
sidecar or positive source OBB dimensions. The sidecar repeats the source
geometry reference and binds sorted, unique triangle indices to that exact
geometry. Both artifact references use byte checksums; consumers verify bytes,
identity, bounds, and overlap before using membership.

SceneIR remains schema 1.0. When ownership is absent it is omitted from JSON so
legacy payloads retain their canonical checksum and remain readable. An editor
must not infer missing source ownership from the current transform. It may
recover only from the original extraction/artifact evidence; otherwise an edit
requiring a rebuilt background is blocked. Source pose is provenance, not a
second editable world transform.

Capability check phải xảy ra trước publish physics_enrich revision. Artifact
mesh cần finite vertices, topology hợp lệ, correct local transform và resolver
closure. USD stage phải dùng canonical units/axes; visual và physics cùng object ID.

## Exporter capability contract (AUD-02.S1 implemented)

The implementation exposes an additive `export_capability` result beside static
Preflight. The two checks answer different questions: static Preflight validates
scene geometry and required artifacts; export capability proves that the selected
builder/runtime can preserve the SceneIR requirements. A package is publishable
only when both pass. The internal contract is `usd-export-capabilities-v1` and is
bound to SceneIR revision/checksum, effective mode, builder config, and runtime USD
version in the candidate build identity.

The legacy path is limited to finite positive AABB/OBB boxes with local transforms;
it rejects authored ObjectPhysics, external assets, and unsupported collider types.
The hybrid path is selected for Gaussian visuals, authored physics, external assets,
or collider types beyond the legacy subset. It must pass an in-memory API probe in
the configured USD interpreter before publication. Current hybrid support blocks
non-identity collider offsets, unresolved/empty convex geometry, external asset
closure, and collider forms the adapter does not author yet. A cache hit requires
the exact builder config checksum and matching capability requirements.

The automated runtime-probe tests use a fake subprocess response. They establish
the contract and rejection behavior only; real `usd-core` stage acceptance and
Isaac Sim behavior remain unverified until AUD-02.S2/AUD-05.

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
