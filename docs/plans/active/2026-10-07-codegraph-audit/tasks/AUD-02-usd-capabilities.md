# AUD-02 — USD export theo capability và fidelity thực tế

## Metadata và goal

- Status PLANNED; P0; EX-SIM builder, EX-PRODUCT dispatch/errors.
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
**Exit:** [ ] convex/hybrid không silently fallback; [ ] supported boxes còn chạy.

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
**Exit:** [ ] supported matrix có semantic stage proof; [ ] unsupported path block rõ.

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
**Exit:** [ ] user thấy capability cần thiết; [ ] no candidate on failed build;
[ ] pxr vs Isaac evidence được tách riêng.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_simulation/test_usd.py tests/test_simulation/test_hybrid_usd.py tests/test_simulation/test_preflight.py tests/test_simulation/test_enrichment.py tests/test_orchestration/test_simulation_package.py tests/test_contracts/test_candidate_manifest.py -q
```

Frontend focused: tests/review-panel.test.tsx và API client test trong frontend/.
Ruff/frontend gates theo AGENT_GUIDE. DONE khi capability matrix có negative
proof và emitted USD giữ đủ semantics; Isaac runtime acceptance vẫn ghi AUD-05.

## Result / Evidence

Pending — ghi builder/runtime versions, requirements, package refs và từng sprint exit.
