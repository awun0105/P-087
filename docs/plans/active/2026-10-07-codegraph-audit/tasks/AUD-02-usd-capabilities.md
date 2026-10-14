# AUD-02 — USD export theo capability và fidelity thực tế

## Metadata và goal

- Status IMPLEMENTED; AUD-02.S1–S3 complete. DevTools visual acceptance is UNVERIFIED; real Isaac acceptance remains in AUD-05. P0; EX-SIM builder, EX-PRODUCT dispatch/errors.
- Canonical tasks SIM-03/04/05, PRODUCT-08. Strategy REUSE pxr/hybrid runner,
  SELF-CODE capability gate; không thêm USD implementation framework.
- Goal: candidate chỉ được publish khi exporter giữ đúng collider/physics đã yêu cầu.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0012](../../../../decisions/0012-editable-collision-and-usd-capabilities.md).

## Baseline và scope

CodeGraph: `build_simulation_package`, `_hybrid_layers`, `_generate_collider_usda`,
`enrich_scene_physics`, `build_candidate_package`, hybrid runner callers.
Current fallback chọn Mesh nhưng không points/topology/geometry_ref. Local repro:
convex scene + missing runtime → preflight PASS, ZIP với empty Mesh và thiếu mass.

Owned: src/services/simulation/{usd,preflight,enrichment}/,
src/services/orchestration/review/simulation_package.py,
src/api/studio/simulation.py, frontend ReviewPanel/API contracts khi expose blocker,
tests/test_simulation/, tests/test_orchestration/test_simulation_package.py.
Không thay collider policy/quality tự động, drop physics hoặc đổi saved config.

## Input / output / data contract

Input: current SceneIR, effective build config, available runtime capabilities,
resolved collider/asset refs. Output: valid CandidatePackage/SimulationPackage
hoặc typed blocker chưa có candidate, không publish physics_enrich revision
chỉ để phát hiện runtime thiếu sau đó.

S1 chốt internal ExportRequirements/ExportCapabilities tối thiểu: representation
types, static/dynamic physics, local offsets, hybrid visuals và external assets.
Đây là operational builder decision, không phải SceneIR mới. Requested mode và
effective mode/builder version phải hiện trong package provenance/config identity.
Không lấy filesystem presence một file Python làm runtime qualification proof.

| Requirement | Minimal supported behavior |
|---|---|
| AABB/OBB | Finite positive dimensions, local transform đúng, PhysicsCollisionAPI |
| Static mesh/hull | Actual points/topology hoặc resolved USD geometry; không empty Mesh |
| Dynamic convex decomposition | Convex pieces + RigidBody/Mass/material đúng; runtime hỗ trợ |
| ObjectPhysics | Mass/source/material được author đúng hoặc capability reject |
| Hybrid Gaussian | Layer/reference closure và object transform cùng physics |
| Local collider offset | Parent vào object, rotation/translation compose chính xác |

Preflight static và export capability là hai kết quả khác nhau. S1 chọn blocker
mapping vào DTO hiện có hoặc additive DTO; không đổi shared enum tùy tiện.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: USD requirements/capability và blocker thay false success.
Cần sửa đồng bộ: physics_enrich, package builder, OpenUSD fallback/hybrid, candidate inventory/API/ReviewPanel và validation worker.
Acceptance xuyên consumer: Unsupported capability không publish candidate/revision giả; supported export giữ mesh topology, local offsets/physics và exact refs.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập; S2 dùng requirements S1. Background geometry dùng AUD-01. S3 pxr
smoke cần runtime thật; Isaac smoke thuộc AUD-05.

## Sprint AUD-02.S1 — Capability matrix và guard trước publication

**Input:** box/static/dynamic/convex/hybrid fixtures; available/missing runtime.
**Output:** requirements classifier, capability result và regression của fallback.
**Contract:** unsupported requirement → blocker; candidate absent; current revision
và chosen config/checksum giữ nguyên.

Implement: inspect cả hybrid và legacy callers; derive requirements từ SceneIR,
không chỉ visual_master_ref. Kiểm capability trước physics_enrich publish và
package cache return; cache không được trả package không đáp ứng requested profile.
Giữ box-only path nếu có fidelity proof cho đúng subset.
Tests: missing runtime, bad refs, mesh-without-topology, dynamic mass thiếu,
cached package builder/version mismatch; API error projection không fake PASS.
**Exit:** [x] convex/hybrid không silently fallback; [x] supported boxes còn chạy.

## Sprint AUD-02.S2 — Export geometry/physics đúng cho supported paths

**Input:** qualified mode S1 + enriched SceneIR.
**Output:** USD layers và inventory đầy đủ, build config identity đúng.
**Contract:** object.id ổn định; transforms/units/physics/material tương ứng SceneIR;
every external ref trong candidate closure có byte checksum.

Implement: sửa shared exporter một lần; author mesh thật khi path hỗ trợ, hoặc
delegate existing pxr runner. Propagate collider.local_transform qua hybrid
adapter; emit mass/material chỉ theo ObjectPhysics, không dùng default thay
user choice. Chuẩn hóa relative refs, reject unresolved asset dependencies.
Tests: geometry/topology, orientation/local offsets, convex pieces, dynamic/static
semantics, relative asset closure, corrupt mesh; parse USD bằng pxr khi có.
**Exit:** [x] supported matrix có semantic stage proof; [x] unsupported path block rõ.

## Sprint AUD-02.S3 — API/UI blocker và consumer acceptance

**Input:** supported/rejected build results + candidate artifacts.
**Output:** user-visible reason/retry routing, package metadata và consumer proof.
**Contract:** unavailable runtime không đổi scene/config; retry dùng cùng requirements;
candidate cache invalidation theo effective builder/version/config.

Implement: wire typed build blocker vào Studio; heavy route dùng worker boundary
hiện có, không chạy Isaac trong API. Kiểm ZIP inventory và stage load; phối hợp
AUD-05 cho real Isaac. Không coi text chứa def Mesh là geometry pass.
Tests: API blocker/permissions, Vitest ReviewPanel, USD open/reference checks,
actual Isaac loader nếu đã có runtime; browser feedback/rollback khi UI thay đổi.
**Exit:** [x] user thấy capability cần thiết; [x] no candidate on failed build;
[x] pxr vs Isaac evidence được tách riêng. DevTools browser feedback vẫn
UNVERIFIED do MCP không kết nối được Chrome session.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_simulation/test_usd.py tests/test_simulation/test_hybrid_usd.py tests/test_simulation/test_preflight.py tests/test_simulation/test_enrichment.py tests/test_simulation/test_usd_capabilities.py tests/test_simulation/test_collision_edit_composition.py tests/test_orchestration/test_simulation_package.py tests/test_orchestration/test_review_workflow.py tests/test_contracts/test_candidate_manifest.py tests/test_api/test_studio_routes.py -q
```

Frontend focused: tests/object-review.test.tsx, tests/review-panel.test.tsx,
tests/studio-results.test.tsx và tests/api-client.test.ts trong frontend/.
Ruff/frontend gates theo AGENT_GUIDE. DONE khi capability matrix có negative
proof và emitted USD giữ đủ semantics; Isaac runtime acceptance vẫn ghi AUD-05.

## Result / Evidence

### AUD-02.S1 — complete

- Commit base: `2634df9` (`AUD-01.S2`). Scope stayed within capability gating,
  candidate packaging, API projection, focused regressions, and this task/ADR.
- Before: hybrid selection depended on a configured Python file plus
  `visual_master_ref`; other scenes silently used a legacy writer that emitted a
  topology-free `Mesh` for non-box colliders. Candidate cache returned any record
  for the current revision without checking builder/profile identity.
- After: `ExportRequirements` selects `legacy_box` or `hybrid`; an additive
  `export_capability` DTO distinguishes capability from static Preflight. The
  legacy subset is finite positive AABB/OBB boxes without authored ObjectPhysics
  or external assets. Mesh colliders, physics, or Gaussian visuals require hybrid
  capability; the configured interpreter must pass an in-memory USD API probe.
  Unsupported references, empty mesh topology, dynamic mass gaps, uncomposed
  hybrid collider offsets, and unsealed external assets return blockers before
  `physics_enrich` publication. Candidate cache requires the exact builder config
  checksum, revision/checksum, effective mode, and requirements. `current_package`
  applies the same gate to API GET/download and workflow readers, not just POST
  rebuilds. Direct legacy generation now rejects fake Mesh prims, dropped
  ObjectPhysics, and omitted asset dependencies.
- Dependent updates: candidate builder validates the capability report against
  SceneIR; `SimulationPackage` and the existing API response project the blocker
  separately from static Preflight; the ZIP includes `export_capability.json`;
  both legacy and hybrid builder config identities carry the capability contract,
  effective mode, builder version, collision background identity, and hybrid USD
  runtime version. `_hybrid_layers` now excludes inactive objects consistently
  with the capability classifier.
- API/consumer proof: `test_simulation_api_projects_export_block_separately_from_preflight`
  verifies a static Preflight PASS can coexist with an explicit export blocker and
  no candidate/package reference. The package-level regression verifies missing
  hybrid runtime/convex geometry leaves the current SceneIR revision unchanged.
- Focused checks: `.venv/bin/ruff check src/ tests/` → All checks passed;
  `.venv/bin/ruff format --check src/ tests/` → 457 files already formatted;
  task-focused pytest command → 85 passed. The suite covers direct fallback
  rejection, box support, missing runtime, invalid/missing geometry references,
  topology-free meshes, dynamic mass, uncomposed hybrid offsets, external asset
  closure, cache builder-version mismatch, hybrid inventory binding, API response
  projection, stale GET/workflow cache rejection, and collision-background consumers.
- Runtime evidence at S1: the capability probe contract used controlled subprocess
  fixtures; real `usd-core` stage acceptance was added in S2. Isaac acceptance
  remains pending AUD-05.

### AUD-02.S2 — complete

- Commit base: `45b0258` (`AUD-02.S1`). Scope: exact supported collider and
  `ObjectPhysics` export, checked external USD assets, runtime stage validation,
  package summary verification, and dependent tests/docs.
- Before: the hybrid adapter discarded collider-local transforms and trusted
  primitive dimensions instead of `ColliderSpec`; convex export could fall back
  to an empty/box representation; GLB scene-node transforms were lost; physics
  metadata omitted density/provenance; asset references could leave the package.
- After: AABB/OBB export uses exact `dimensions_xyz_m` and local translation/
  quaternion. Convex decomposition emits every validated mesh part with node
  transforms baked in; missing/invalid geometry fails closed. Mesh vertices,
  triangles, indices, finite values, float range, duplicate indices and zero-area
  faces are checked by one shared loader used by the API capability gate and the
  low-dependency USD runtime. No convex-to-box fallback remains.
- `ObjectPhysics` is passed without synthesized defaults. The writer emits
  `RigidBodyAPI` only for dynamic objects; it writes supplied mass and density,
  friction, restitution, mass source and provenance, and leaves physics schemas
  off when `physics` is absent. Invalid numeric values or missing dynamic mass
  block the export.
- External `asset_ref` inputs are accepted only for `.usd`, `.usda`, `.usdc`, or
  `.usdz` artifact URIs whose
  resolved source bytes match the declared SHA-256. Bytes are copied under
  `assets/<sha256>.<ext>`, referenced relatively, then the composed root stage is
  checked for unresolved composition and dependencies outside the package. Raw
  catalog URLs, non-USD formats, missing refs, corrupt bytes and unsafe paths
  remain blocked. A runtime failure is converted to `USD_EXPORT_FAILED` before
  SceneIR revision/candidate publication.
- Dependent consumers: `_hybrid_layers` now passes exact collider data, physics
  and checksummed asset refs; validates runner summary against requested object
  IDs, collider types, local transforms, topology presence and asset checksums;
  includes the summary and dependency bytes in the ZIP. Runtime capability and
  cache/build identities use contract v2. Legacy box export keeps its existing
  exact box/local-transform path and does not receive default physics.
- Runtime evidence: `data/scene_runtime/bin/python` uses `usd-core 0.26.8`.
  The runner test creates USD layers, opens the composed `scene.usda` with `pxr`,
  and verifies Gaussian data, convex piece/node transforms, OBB dimensions,
  local and composed transforms, dynamic/static/no-physics cases, mass/density/
  material/provenance, and a relative USD asset reference. This proves OpenUSD
  stage composition in that runtime; Isaac Sim physics behavior remains pending
  AUD-05.
- Checks: the task-focused pytest command below → 94 passed; `.venv/bin/ruff check
  src/ tests/` → All checks passed; `.venv/bin/ruff format --check src/ tests/`
  → 458 files already formatted; `git diff --check` → clean. A first run exposed
  that a composition test bypassed production enrichment and its fake runner did
  not return the required summary; the test now uses enriched input and returns
  the runner contract. A malformed success summary is also verified to block.
  Final focused rerun passed.
- Remaining bounds: arbitrary USD resolver/plugin dependencies and nested external
  files are not accepted unless they resolve into the package closure; no blind
  repair of malformed meshes; no Isaac Sim, GPU or browser acceptance in this
  sprint. S3 remains responsible for end-user blocker/retry routing.
- Changed source files: `src/services/orchestration/review/simulation_package.py`,
  `src/services/simulation/mesh_geometry.py`, and
  `src/services/simulation/usd/{builder,capabilities,hybrid_runner}.py`.
  Changed tests: `tests/test_orchestration/test_simulation_package.py`,
  `tests/test_simulation/test_{collision_edit_composition,hybrid_usd,usd,usd_capabilities}.py`,
  and `tests/test_api/test_studio_routes.py`. Task, ADR 0012 and active plan
  progress record the same contract/evidence.
- Gate report: CodeGraph read capability/build/runtime symbols and callers;
  affected entry points are `build_simulation_package` (Studio API/workflow and
  package tests), `_hybrid_layers` (package and collision-edit tests), the USD
  capability gate and hybrid runner. `understand-anything` CLI/MCP was unavailable;
  the flow was manually traced through CodeGraph and focused integration tests.
  Minimal-code rung 2 reused `ArtifactResolver`, checksum utilities, `trimesh`,
  and the existing `pxr` runner; one shared topology validator closes the missing
  API/runtime contract. Browser DevTools is n/a because this is a UI-free service.

### AUD-02.S3 — implemented; capability-blocked browser state unavailable

- Commit base: `1aed466` (`AUD-01.S3`). No backend schema or persistence change.
- Before: the API response already contained `export_capability`, but
  `SimulationPackageView` dropped it. ReviewPanel therefore showed a generic
  Preflight failure message when static Preflight passed and USD export was
  blocked; users could not see the typed reason or distinguish OpenUSD builder
  qualification from Isaac execution.
- After: the frontend projection validates the typed capability fields and
  blocker records. A blocked capability cannot be paired with a package download
  reference at the client boundary. ReviewPanel shows status, effective mode,
  builder/runtime version, blocker code/message/object IDs, says no candidate was
  created, and offers a retry against the current scene requirements. Preflight
  failures retain their own remediation message.
- API/permission proof: the existing Studio router-level `require_editor`
  dependency covers simulation package GET, POST and download. Regression tests
  verify all three return 401 when auth is enabled without a session. The existing
  blocker projection test verifies Preflight PASS + export BLOCKED returns the
  typed report with `candidate` and `package_ref` null. Package tests also verify
  failed USD builds do not publish a candidate or scene revision.
- Consumer/runtime evidence: the focused AUD-02 suite → 98 passed. In those
  tests, `data/scene_runtime/bin/python` opens the emitted composed stage using
  OpenUSD `pxr` (`usd-core 0.26.8`) and verifies ZIP inventory and relative
  references. This is OpenUSD authoring/composition evidence only. No Isaac Sim
  runtime is installed in this checkout; real simulation/load acceptance stays
  with AUD-05. The API candidate builder uses its configured OpenUSD subprocess;
  this endpoint does not invoke Isaac in the FastAPI process.
- Frontend: `npm run test -- tests/object-review.test.tsx tests/studio-results.test.tsx`
  → 16 passed; `npm run test -- tests/review-panel.test.tsx tests/api-client.test.ts`
  → 15 passed; combined focused Vitest run → 31 passed. `npm run typecheck`,
  changed-file ESLint and `npm run build` passed.
  `.venv/bin/ruff check src/ tests/` and `.venv/bin/ruff format --check src/ tests/`
  passed; `git diff --check` was clean.
- Browser evidence (2026-10-09): Chrome DevTools MCP opened the existing job's
  Results tab in the authenticated Reviewer session. It rendered “Gói mô phỏng
  (candidate): CHƯA CÓ” and “Bản phát hành: CHƯA PHÁT HÀNH”. The API returned
  `null` for the selected job's simulation package; across the 10 visible latest
  jobs, four requests returned 200 with `null` and six returned 404. No current
  scene exposed an export-capability blocker with a candidate absent, so the
  specific typed-blocker/download state remains **UNVERIFIED**. No package was
  created and no project data was changed.
- Changed files: `frontend/src/lib/api/studio.ts`,
  `frontend/src/features/studio/SimulationPackagePanel.tsx`, frontend API/UI tests,
  `tests/test_api/test_studio_routes.py`, this task, ADR 0012 and the active plan.
- Pre-flight: CodeGraph read `SimulationPackageView`,
  `SimulationPackagePanel`, `create_simulation_package`, router dependencies and
  their consumers/tests. Affected callers include `ReviewTab`, `ResultsTab`,
  `NextAction`, the simulation API and `require_editor`; their relevant test paths
  ran. `understand-anything` CLI/MCP is unavailable; flow was traced through
  CodeGraph and the existing AUD-02 integration tests. Minimal-code rung 2 reused
  the existing JSON object/string helpers, API error boundary, router-level auth
  dependency and ReviewPanel. `ruff`, focused pytest, Vitest, typecheck, ESLint and
  production build passed. The DevTools MCP session works; the needed
  capability-blocked sample is unavailable in the current local data.
