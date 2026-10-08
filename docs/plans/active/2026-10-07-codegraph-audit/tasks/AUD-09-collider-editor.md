# AUD-09 — Chỉnh box collider với local offset có kiểm soát

## Metadata và goal

- IN PROGRESS — AUD-09.S1–S2 local implementation complete; S3 remains planned; P1; EX-SIM domain + EX-PRODUCT API/UI.
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

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Collider dimensions/local offset khác object pose.
Cần sửa đồng bộ: ColliderSpec/edit DTO, domain validation, API/TypeScript/UI, SceneIR CAS, legacy/hybrid exporter, candidate và validation.
Acceptance xuyên consumer: World collider transform = object × local collider; export khớp editor, edit invalidates approval và source carve vùng gốc giữ đúng.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

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
**Exit:** [x] command contract producer/consumer agree; [x] domain negative matrix pass.

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
**Exit:** [x] saved canonical collider matches preview; [x] failure rollback verified.
Browser visual acceptance remains **UNVERIFIED** because the available Chrome
session is at login without an authenticated Studio session.

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

tests/test_scene/test_collider_edit.py covers the pure edit command and validation.
Frontend tests/object-review.test.tsx,
tests/scene-overlay-gizmo.test.ts và gates theo guide. DONE cần command/UI/export
consumer proof; initial box-only scope được ghi rõ trong result.

## Result / Evidence

### AUD-09.S1 — Typed edit command và invariants

- **Base:** `75075b4` (`AUD-08.S4`).
- **Behavior before → after:** SceneIR had an existing collider model and
  enrichment could replace an object's collider from the explicit/generated map,
  but there was no revision-bound collider-edit command. `ColliderEditCommand`
  now accepts positive finite dimensions and finite local translation plus a
  normalized local quaternion. Empty input fails; a supplied value equal to the
  current value is accepted, matching the nearby `TransformEdit` policy.
- **Domain contract:** only existing AABB/OBB colliders with dimensions can be
  edited. Object/collider frame IDs, collider type and refs stay server-owned.
  The pure operation edits only collider dimensions/local pose, preserves the
  object transform, visual/geometry refs, primitive dimensions, collider params
  and physics, records manual-override provenance, refreshes the SceneIR checksum,
  and marks validation stale. It returns the same SceneIR revision; S2 owns
  publishing it through the shared revision CAS. Physics enrichment now preserves
  a manual override even when a generated or explicit collider is available.
- **Files:** `src/services/orchestration/scene/{models.py,objects.py,__init__.py}`,
  `src/services/scene/editing/commands.py`,
  `src/services/simulation/enrichment/service.py`,
  `frontend/src/lib/contracts/api.ts`, `tests/test_scene/test_collider_edit.py`,
  and this task/plan progress entry.
- **Verification:**
  - `.venv/bin/pytest tests/test_contracts/test_scene.py tests/test_simulation/test_colliders.py tests/test_simulation/test_enrichment.py tests/test_simulation/test_usd.py tests/test_simulation/test_hybrid_usd.py tests/test_simulation/test_usd_capabilities.py tests/test_api/test_scene_v2_routes.py tests/test_scene/test_collider_edit.py tests/test_orchestration/test_scene_editor.py tests/test_orchestration/test_simulation_package.py -q` — **176 passed**.
  - `.venv/bin/ruff check src/ tests/` — **passed**; `.venv/bin/ruff format --check src/ tests/` — **505 files already formatted**.
  - `.venv/bin/python scripts/check_contract_mirror.py` — **PASS**, 5 enum and 5 model projections.
  - In `frontend/`, `npm run typecheck`, `npx eslint src/lib/contracts/api.ts`, and `npx vitest run tests/layers.test.ts tests/object-review.test.tsx` — **46 tests passed**.
- **CodeGraph gate:** explored `ColliderSpec`, `TransformEdit`, object edit
  commands, enrichment and its `build_simulation_package` caller before editing;
  verified callers for the new command and pure edit operation after editing.
  `codegraph status`: 833 files, 16,219 nodes, 47,392 edges; index up to date,
  with an earlier-engine rebuild warning.
- **Limitations:** S1 defines the API command contract but does not expose an HTTP
  route or UI yet. It does not publish a new revision or produce browser/world-pose
  evidence. S2 adds the route/UI publication path; export and real Isaac contact
  remain S3/separate **UNVERIFIED** acceptance gates.

### AUD-09.S2 — Inspector, preview và canonical revision

- **Base:** `e3e9fc5` (`AUD-09.S1`).
- **Behavior before → after:** S1 defined and tested the domain command, but the
  Web app had no collider route or controls. `POST /api/v1/jobs/{job_id}/scene/collider`
  now accepts the revision-bound `ColliderEditCommand`, checks job ownership,
  applies the pure edit, and publishes it through `SceneEditor.publish_next`.
  The response is the canonical `SceneEditResponse` at the next SceneIR revision.
- **UI and data contract:** Inspector exposes dimensions, local translation in
  metres and local XYZ rotation angles in degrees for existing dimension-bearing
  AABB/OBB only. The UI converts local XYZ angles using `qZ × qY × qX` to the
  contract quaternion. Convex/mesh/no-collider cases state why editing is not
  available. The preview remains local state and composes
  `T_world_from_object × T_object_from_collider`; Gaussian/object transforms and
  visual/geometry refs remain canonical and unchanged. Box dimensions/local pose
  also feed browser physics preview. A pending write blocks concurrent mutations;
  cancel, API failure, or stale revision discards the preview. 409 reloads the
  latest canonical scene before further edits.
- **Files:** `src/api/product/scene.py`,
  `src/services/orchestration/scene/objects.py`,
  `frontend/src/lib/api/studio.ts`,
  `frontend/src/features/studio/ObjectReviewView.tsx`,
  `frontend/tests/object-review.test.tsx`,
  `tests/test_api/test_scene_v2_routes.py`,
  `tests/test_api/test_guest_ownership.py`, and plan progress entries.
- **Verification:**
  - `.venv/bin/pytest tests/test_api/test_scene_v2_routes.py tests/test_api/test_guest_ownership.py tests/test_scene/test_collider_edit.py tests/test_orchestration/test_scene_editor.py -q` — **108 passed**.
  - `.venv/bin/ruff check src/ tests/` — **passed**; `.venv/bin/ruff format --check src/ tests/` — **505 files already formatted**; `scripts/check_contract_mirror.py` — **PASS**.
  - In `frontend/`, `npm run typecheck`, changed-file ESLint, and Vitest for
    `object-review`, `layers`, and `stage-view-selection` — **56 tests passed**.
  - CodeGraph fully indexed 833 files, 16,258 nodes and 47,606 edges. The graph
    traces the route → domain edit → `publish_next` path and identifies the
    Inspector/overlay/frontend regression tests.
- **Acceptance boundary:** Chrome DevTools MCP reaches
  `http://localhost:3010/login?next=%2Foverview`; no authenticated session was
  available to inspect the actual PlayCanvas preview. Browser local/world-pose
  acceptance is therefore **UNVERIFIED**. USD/export consumer fidelity and real
  Isaac collision remain AUD-09.S3 gates; this sprint does not claim them.
