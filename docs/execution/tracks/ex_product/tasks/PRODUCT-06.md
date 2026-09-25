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

Load SceneIR và render real 3DGS từ `VisualArtifact` của Primary RGB Scene cùng
các view Geometry mesh, Point Cloud, Collider/SceneObject transforms trong browser.
Cho phép click chuyển view/bật lớp trên cùng revision, orbit/pan/zoom, select,
hide/show và transform-edit command flow.

## 3. Why This Task Exists

Web Studio cần inspection/editing trực tiếp mà không cần Blender hoặc Isaac GUI.
3DGS Visual là view P0 phải dùng output EX-REC thật; mesh, point cloud và
collider là view kỹ thuật ngang hàng, không phải fallback hoặc bằng chứng 3DGS.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-05 Web shell.
- SceneIR fixture and PRODUCT-04 artifact resolver.
- Real-browser AC-11 proof cần REC-04 publish real Brush `VisualArtifact`; fixture vẫn cho phép phát triển độc lập trước khi EX-REC hoàn tất.

## 5. Input Contract

- SceneIR, real EX-REC `VisualArtifact` (format/producer/version/checksum/coordinate metadata), resolved geometry/collider refs and edit API.
- SceneIR geometry/point-cloud/collider refs và checksums.
- Browser WebGL/WebGL2 capability; WebGPU không phải P0 requirement.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- 3D viewer state derived from SceneIR, có mode chuyển 3DGS Visual/Geometry mesh/Point Cloud/Collider.
- P0 real Gaussian rendering và PlayCanvas Engine technical views (Mesh, Collider) bind đúng artifact checksums/canonical transform trên cùng một Scene Graph.
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

**Primary Web 3D Core (`@playcanvas/supersplat-viewer` v1.35.2 + `playcanvas/engine` v2.22.4):**
- Tái sử dụng trọn vẹn package NPM `@playcanvas/supersplat-viewer` (xem chi tiết tại [`docs/execution/audits/09_supersplat_viewer.md`](../../../audits/09_supersplat_viewer.md)).
- Nhúng trực tiếp vào Next.js component với cấu hình không UI: `createViewer({ container, contentUrl, ui: false })`.
- Tự động hỗ trợ WebGPU khi khả dụng và tự động fallback sang WebGL2, đảm bảo 100% yêu cầu P0.
- Nạp trực tiếp file `.sog` / Streamed SOG LOD (từ `splat-transform`), `.ply` và `collision = .glb`.
- **Single Scene Graph Architecture (Audit #8):**
  - Mọi lớp (Visual SOG, Mesh GLB, Collider GLB) đều được gắn trên cùng một `pc.Entity` trong PlayCanvas Engine.
  - Cùng chia sẻ GPU Render Pass và Depth Buffer (không bị z-fighting).
  - Cùng chia sẻ Transform `position/rotation/scale`, đồng bộ trực tiếp với `SceneObject` trong `SceneIR`.
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **SceneIR là Source of Truth**: Viewer chỉ là viewport hiển thị; mọi transform/edit phải gửi command về backend FastAPI để cập nhật `SceneIR` revision. Local state không bao giờ là canonical scene.
  - ❌ **SSR Bypass**: Component viewer trong Next.js bắt buộc dùng `next/dynamic(..., { ssr: false })` để tránh lỗi truy cập `window`/WebGL trên Node server.
  - ❌ **GPU Lifecycle**: Bắt buộc gọi `viewer.destroy()` khi unmount component để giải phóng WebGL/WebGPU context, tránh tràn VRAM trình duyệt.

## 9. Implementation Plan

1. Tạo React component wrapper cho `@playcanvas/supersplat-viewer` với `ui: false` và `ssr: false`.
2. Tích hợp Single Scene Graph PlayCanvas: nạp Visual SOG (từ `REC-04`) và `collision.glb` (từ `REC-05`/`SIM-02`) trên cùng Entity.
3. Kích hoạt camera modes (Orbit, Fly, Walk) và surface picking từ viewer API.
4. Kết nối Transform Gizmo và gửi event cập nhật vị trí về backend SceneIR API.
2. Xây dựng `Real2SimEditorBridge` (typed postMessage) liên kết Next.js shell với SuperSplat-derived editor.
3. Tích hợp các view Geometry mesh và Collider wireframes trên PlayCanvas/Three.js.
4. Tận dụng `splat-transform` cho khâu tối ưu hóa, sinh LOD và SOG streaming.
5. Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- SceneIR loader/mapping unit tests.
- Renderer qualification test với real Brush output: format/producer/checksum, coordinate alignment, browser capability và lỗi format không tương thích.
- Geometry/point-cloud/collider loader, checksum binding và coordinate-composition tests.
- Missing/unresolved Visual/layer, wrong checksum, unsupported format và rejected-edit negative tests.
- Browser smoke: load fixture để phát triển, orbit/pan/zoom, click chuyển 3DGS/Geometry mesh/Point Cloud/Collider, edit và reload; real-browser test riêng với Brush artifact cho AC-11.
- WebGL/WebGL2 capability/error/degraded-state và renderer/GPU-resource cleanup tests; WebGPU checks chỉ nếu backend được chọn dùng WebGPU.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Viewer render real Brush 3DGS Visual trên Primary RGB Scene và chuyển được sang Geometry mesh/Point Cloud/Collider; fixture proof tách khỏi AC-11 real-browser proof.
- [ ] Visual/Geometry/Point Cloud/Collider refs bind đúng checksums; missing/incompatible Visual báo lỗi và không pass AC-11.
- [ ] Three.js layers dùng canonical coordinate/transform metadata.
- [ ] Transform edits persist through backend revision then re-render.
- [ ] Renderer capability/error state và cleanup rõ; synthetic visual hoặc mesh/point-cloud không bị báo cáo là Brush compatibility proof.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Interaction recording/screenshots.
- Real Brush `VisualArtifact` format/producer/version/checksum, các view artifact checksums, renderer/Three.js/WebGL runtime version và browser environment.
- Save/reload revision/checksum.
- Render performance and error state.
