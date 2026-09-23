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
- P0 real Gaussian rendering và Three.js technical views bind đúng artifact checksums/canonical transform.
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
Geometry, Point Cloud, SceneObject, Collider và transform controls. Gaussian
renderer là P0, nhưng backend cụ thể chỉ được adopt sau qualification bằng
output Brush thực; không tự viết proprietary renderer hoặc binary format.

Tham khảo [Three.js docs/examples](https://threejs.org/docs/) cho OrbitControls,
TransformControls, Raycaster, PLYLoader và layers; không để Three.js scene state
thay canonical SceneIR transform. [React Three Fiber](https://github.com/pmndrs/react-three-fiber)
là library candidate để quản lý React/Three lifecycle, chỉ chọn sau khi kiểm
tra frontend scaffold/React compatibility. [Spark](https://github.com/sparkjsdev/spark)
là P0 renderer candidate cho Gaussian + mesh trong WebGL2;
[Spark + Next.js example](https://github.com/sparkjsdev/spark-react-nextjs) chỉ là
reference cho client-only setup/R3F integration, không clone thành product.
[Potree](https://github.com/potree/potree) chỉ là point-cloud LOD reference, không
phải P0 dependency. Chỉ adopt renderer sau khi chứng minh load đúng real Brush
`VisualArtifact`; PLYLoader/point cloud không phải Gaussian renderer.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

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
