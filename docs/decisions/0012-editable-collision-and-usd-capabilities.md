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
itself mark this ADR Accepted; real Isaac validation remains open in AUD-05.

AUD-02.S3 projects the typed capability report into Studio separately from
static Preflight. When export is blocked, the user sees the blocker code, message,
affected objects, builder/runtime identity, and a retry action for the same
current scene requirements; the UI does not offer a package download. The
Studio router's existing `require_editor` dependency covers package read, build,
and download routes. API regression tests verify that each route rejects an
unauthenticated request when auth is enabled. This closes local API/UI wiring,
not browser acceptance: DevTools was unavailable because its Chrome profile was
locked, so visual browser evidence remains unverified.

The package endpoint currently invokes USD candidate authoring through its
configured OpenUSD subprocess; it does not load or run Isaac inside FastAPI.
Durable, isolated Isaac execution and its observed evidence remain AUD-05 work,
with operation admission in AUD-07. OpenUSD `pxr` stage composition does not
prove Isaac physics behavior.

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
out-of-package layer dependencies. Non-USD formats remain unsupported because
they do not provide a checksum-bound package dependency. A catalog `asset_url` is
provenance, not a dependency (see Audit amendments).
Runtime build errors return a capability blocker before SceneIR revision or
candidate publication; cache reuse requires the exact config checksum and
matching requirements.

AUD-02.S2 ran the actual hybrid writer and opened the composed stage with `pxr`
from `data/scene_runtime/bin/python` (`usd-core 0.26.8`). Tests verified Gaussian
data, collider topology and dimensions, local/composed transforms, physics
attributes and metadata, relative asset composition, and missing-physics behavior.
This proves OpenUSD stage composition in the tested runtime. Isaac Sim execution
and physical behavior remain unverified and are assigned to AUD-05.

## AUD-01.S3 legacy recovery evidence

The package builder can recover omitted legacy ownership only by following
`edited_from`/`previous_revision` through checksum-validated `SceneEditor.revision`
records. It requires the same scene ID, exact environment geometry ref,
reconstructed object ID, ownership object ID, and source geometry ref. Missing
history or a changed source ref stops recovery and blocks package creation before
publishing a candidate or new SceneIR revision. Successful recovery is recorded
in provenance on the newly published enriched revision; earlier SceneIR and
source-geometry bytes remain immutable. The existing API maps this ownership
failure to HTTP 422.

AUD-01.S3 verified the actual candidate ZIP and composed OpenUSD stage with USD
Core 0.26.8: the floor remained in the background, the object collider used its
current rotated pose, and a checksum-bound relative asset resolved. This proves
the local OpenUSD composition path, not Isaac Sim execution. Recovery preserves
historical OBB metadata as-is; it does not infer exact triangle membership or
upgrade OBB fidelity. Ambiguous OBB overlap was fail-closed here; the audit
amendments below replace that with keep-and-report.

## Audit amendments (2026-10-08)

A run of the exporter on a real 122-revision scene found three policies that
blocked a correct scene. They are changed as follows.

- **Overlap.** `triangle_indices` membership is authoritative over a
  `source_obb` approximation: an OBB never reclaims a triangle that another
  region owns exactly. Triangles still shared between a region being carved and
  a region that stays (an unconfirmed or inactive neighbour) are kept in the
  background and reported, not carved and not a blocker. The package records
  `retained_shared_triangles` and `retained_shared_object_ids`; the README and the
  Studio panel show them with the advice to confirm or delete the neighbours and
  rebuild. Dropping a neighbour's triangles silently would be a guess; refusing
  the export made a scene with adjacent candidates unexportable.
- **Catalog assets.** A user-added catalog object (`provenance.asset_url`, no
  `asset_ref`) exports as its box collider with the declared physics. The URL and
  family are written to prim `customData real2sim:catalog` by both writers and
  checked in the runner summary; the asset is not referenced, so the package stays
  hermetic. The capability report carries a non-blocking
  `CATALOG_ASSET_EXPORTED_AS_BOX` notice (`notices`, default empty so older
  stored reports still load) and the README names the objects. A sealed
  `asset_ref` USD artifact is unchanged and remains an external dependency.
- **Legacy ownership recovery.** Ownership is derived from the revision that
  extracted the object (root revision, or the first revision of a re-extraction
  with `objectify`/`use_boxes`), not from a later moved pose. Recovery follows
  `restored_from`, matches the earlier object by id and `geometry_ref`, and skips
  duplicates, which share a source with their original. `SceneEditor.revision`
  walks the committed lineage once per head and caches it, which took a 122-revision
  scene from 94 s to 3.2 s.

The hybrid ground plane now places its top face at z = 0 (translate before
scale); it was 9.8 mm above the floor. `reobjectify` binds source ownership so a
re-extracted object does not need legacy recovery. These changes keep the
`usd-export-capabilities-v2` identity: the capability schema only gained an
optional field and no stored candidate is invalidated.

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
