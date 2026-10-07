# AUD-09 — Chỉnh box collider với local offset có kiểm soát

## Metadata và goal

- PLANNED; P1; EX-SIM domain + EX-PRODUCT API/UI.
- Canonical SIM-02/03, SCENE-08, PRODUCT-06/07. SELF-CODE typed command,
  REUSE SceneEditor/gizmo/export adapters.
- Goal: sửa kích thước/local pose collider hiện có, giữ object visual/geometry
  transform và export đúng, tạo revision mới.
- [Agent guide](../AGENT_GUIDE.md), [AUD-02](AUD-02-usd-capabilities.md).

## Baseline và scope

CodeGraph: TransformEdit, ColliderSpec, ObjectReviewView, apply_object_action,
enrich_scene_physics, _hybrid_layers và USD collider generator.
Current object edit có translation/rotation; dimensions UI read-only. Hybrid
adapter phải truyền collider local offset khi feature này được thêm.

Owned: simulation/colliders/ domain, orchestration/scene/ commands/models,
src/api/schemas.py và active scene route, frontend ObjectReviewView/overlay typed
commands, simulation/USD adapters và tests thuộc các boundary này.
Không expose generic visual scale hoặc direct geometry editing; không biến
mesh/convex thành box tự động. Initial scope AABB/OBB dimensions + local pose;
collider type chuyển đổi/mesh regeneration là scope riêng, UI báo unsupported.

## Input / output / data contract

Proposed ColliderEditCommand: expected_scene_revision, object_id,
dimensions_xyz_m? (3 finite positive values), local_translation_xyz?,
local_rotation_quaternion_xyzw?. At least one change; nonzero unit quaternion
theo tolerance hiện có; client không đổi parent/local frame IDs hoặc refs tùy ý.
Output SceneEditResult với new SceneIR/ColliderSpec, byte/content checksums.

`T_world_from_collider = T_world_from_object * T_object_from_collider`.
Collider.local_transform.parent_frame = SceneObject.local_frame. Đổi box collider
không đổi SceneObject.transform, primitive_dimensions_xyz_m, visual/geometry refs.
Ghi manual override provenance để enrichment không âm thầm overwrite. New revision
invalidate old candidate/validation/approval. Bounds/preflight dùng edited collider.

MassSource.USER/mass đã chọn không đổi theo collider resize. Density-derived
mass chỉ đổi nếu existing explicit volume policy yêu cầu và ghi provenance;
không dùng collider override để giả object visual volume. Invalid legacy collider
data báo diagnostic; không rewrite artifact cũ khi thêm command validation.

## Dependencies

S1 có thể làm độc lập; publication S2 dùng AUD-10 CAS. Export S3 cần AUD-02 local
offset fidelity và AUD-01 background ownership không lấy edited dimensions làm
source carve region. Real collision validation ở AUD-05.

## Sprint AUD-09.S1 — Typed edit command và invariants

**Input:** current box ColliderSpec + revision-bound command.
**Output:** validated pure domain edit result và API/TypeScript contract fixtures.
**Contract:** finite positive sizes, frame binding, unchanged object transform/
visual/geometry, explicit manual override; unsupported collider rejected.

Implement: minimal DTO/service; validate after model_copy, không bypass Pydantic
validation. Keep parent-frame IDs server owned; define no-op policy theo nearby
scene command convention; inspect every enrichment caller for override behavior.
Tests: zero/negative/NaN/Inf dimensions, invalid quaternion, no-op/empty command,
missing object/collider, mesh edit reject, wrong frame, user mass preservation.
**Exit:** [ ] command contract producer/consumer agree; [ ] domain negative matrix pass.

## Sprint AUD-09.S2 — Inspector/gizmo và canonical revision

**Input:** selected object/current revision và user sizes/local pose.
**Output:** local collider preview, saved SceneEditResult hoặc rollback/error.
**Contract:** preview state tách API/domain state; save serialized; stale revision
409 reload; manual override persists across enrichment; visual transform unchanged.

Implement: numeric dimensions/local offsets và optional existing gizmo mode;
label collider-local axes/units rõ. Pending disable conflicting edits; rollback
failed save to canonical state. Publish revision qua shared CAS; type/mesh controls
chưa hỗ trợ phải explicit, không nhận command rồi bỏ qua.
Tests: typed API payload/roles, rapid saves/stale revision, cancel/failed save,
frontend component/gizmo/focus tests, browser local/world transform preview.
**Exit:** [ ] saved canonical collider matches preview; [ ] failure rollback verified.

## Sprint AUD-09.S3 — Export và simulation consumer

**Input:** edited box collider + new revision + supported builder.
**Output:** USD collider sizes/local transform đúng, preflight và candidate invalidation.
**Contract:** legacy/hybrid cùng compose local offset; unchanged object visual pose;
manual override không bị default enrichment thay thế.

Implement: adapter propagation/corrected preflight bounds; inspect USD stage
through pxr when available. Build twice with intervening collider edit và compare
candidate identity; old report không review new candidate.
Tests: rotated parent + rotated/translated collider; nonuniform sizes; out-of-bounds;
build/enrich preservation; exported collision witness vs visual witness; Isaac contact
smoke phối hợp AUD-05, không claim từ snapshot/text search.
**Exit:** [ ] exported collider semantically correct; [ ] revision/gate invalidation pass;
[ ] real contact evidence ghi riêng.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_contracts/test_scene.py tests/test_simulation/test_colliders.py tests/test_simulation/test_enrichment.py tests/test_simulation/test_usd.py tests/test_simulation/test_hybrid_usd.py tests/test_api/test_scene_v2_routes.py -q
```

Planned tests/test_scene/test_collider_edit.py. Frontend tests/object-review.test.tsx,
tests/scene-overlay-gizmo.test.ts và gates theo guide. DONE cần command/UI/export
consumer proof; initial box-only scope được ghi rõ trong result.

## Result / Evidence

Pending — before/after collider/scene/candidate checksums, manual-override proof,
local/world pose witnesses và browser/runtime limitations.
