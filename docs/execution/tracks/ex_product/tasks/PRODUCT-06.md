# PRODUCT-06 — SceneIR 3D Viewer

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M1/M2` |

## 2. Goal

Load SceneIR và render Geometry/Point Cloud/Collider/SceneObject transforms trong
browser bằng Three.js/WebGL/WebGL2, cùng orbit/pan/zoom, select, layer toggles,
hide/show và transform-edit command flow.

## 3. Why This Task Exists

Web Studio cần inspection/editing trực tiếp mà không cần Blender hoặc Isaac GUI.
Direct browser Gaussian-splat rendering vẫn là stretch/non-blocking theo
Foundation decision; EX-REC `VisualArtifact` abstraction vẫn được giữ.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-05 Web shell.
- SceneIR fixture and PRODUCT-04 artifact resolver.

## 5. Input Contract

- SceneIR, resolved visual/geometry/collider refs and edit API.
- SceneIR geometry/point-cloud/collider refs và checksums.
- Browser WebGL/WebGL2 capability; WebGPU không phải P0 requirement.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- 3D viewer state derived from SceneIR.
- P0 Three.js rendering bind đúng artifact checksums.
- Backend edit commands and refreshed canonical revision.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `frontend/src/features/viewer/`
- shared viewer components trong `frontend/src/components/`
- typed API/contracts trong `frontend/src/lib/`
- `src/api/` scene endpoints
- browser/e2e tests

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` typed SceneIR composition trên Three.js/WebGL/WebGL2. Three.js render
Geometry, Point Cloud, SceneObject, Collider và transform controls. Direct
Gaussian renderer là follow-up stretch; không tự viết proprietary renderer hoặc
binary format. Nếu stretch được triển khai, phải audit license, real producer
format, capability và lifecycle cleanup riêng.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- SceneIR loader/mapping unit tests.
- Geometry/point-cloud/collider loader, checksum binding và coordinate-composition tests.
- Missing/unresolved layer and rejected-edit negative tests.
- Browser smoke: load fixture, orbit/pan/zoom, toggle Geometry/Point Cloud/Collider, edit và reload.
- WebGL/WebGL2 capability/error/degraded-state test.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Viewer renders fixture/real SceneIR layers and selection.
- [ ] Geometry/Point Cloud/Collider refs bind đúng checksums.
- [ ] Three.js layers dùng canonical coordinate/transform metadata.
- [ ] Transform edits persist through backend revision then re-render.
- [ ] Renderer capability/error state rõ; synthetic visual không bị báo cáo là Brush compatibility proof.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Interaction recording/screenshots.
- Artifact checksums, Three.js/WebGL runtime version và browser environment.
- Save/reload revision/checksum.
- Render performance and error state.
