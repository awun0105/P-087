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

## Exporter capability contract (AUD-02.S1–S2 implementation evidence)

The implementation exposes an additive `export_capability` result beside static
Preflight. The two checks answer different questions: static Preflight validates
scene geometry and required artifacts; export capability proves that the selected
builder/runtime can preserve the SceneIR requirements. A package is publishable
only when both pass. The operational contract is `usd-export-capabilities-v2` and
is bound to SceneIR revision/checksum, effective mode, builder config, and runtime
USD version in the candidate build identity. This contract evidence does not by
itself mark this ADR Accepted; AUD-02.S3 and Isaac validation remain open.

The legacy path supports finite positive AABB/OBB boxes with exact dimensions and
local transforms. It rejects authored `ObjectPhysics`, external assets, and
unsupported collider types. The hybrid path is selected for Gaussian visuals,
authored physics, external assets, or collider types beyond the legacy subset. It
must pass an in-memory API probe in the configured USD interpreter before
publication. AABB/OBB geometry and `ColliderSpec.local_transform` are authored
directly. Convex decomposition emits validated triangle mesh parts and preserves
scene-node transforms; missing topology, invalid indices, non-finite coordinates,
degenerate faces, or absent geometry block instead of falling back to a box.

The writer authors `RigidBodyAPI` only for dynamic `ObjectPhysics`; supplied mass,
density, friction, restitution, mass source, and provenance are preserved. If
`ObjectPhysics` is absent, no mass/body/material defaults are authored. External
assets are limited to checksum-verified `.usd`, `.usda`, `.usdc`, and `.usdz`
artifacts. The exporter copies source bytes under a SHA-256 relative package path,
references them relatively, and checks the composed stage for unresolved or
out-of-package layer dependencies. Raw catalog URLs and non-USD formats remain
unsupported because they do not provide a checksum-bound package dependency.
Runtime build errors return a capability blocker before SceneIR revision or
candidate publication; cache reuse requires the exact config checksum and
matching requirements.

AUD-02.S2 ran the actual hybrid writer and opened the composed stage with `pxr`
from `data/scene_runtime/bin/python` (`usd-core 0.26.8`). Tests verified Gaussian
data, collider topology and dimensions, local/composed transforms, physics
attributes and metadata, relative asset composition, and missing-physics behavior.
This proves OpenUSD stage composition in the tested runtime. Isaac Sim execution
and physical behavior remain unverified and are assigned to AUD-05.

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
