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

`SELF-CODE` typed SceneIR composition kết hợp với renderer/editor adapter đã kiểm chứng.

**Code Donor Reference (Audit #4):**
- Candidate Visual Editor Donor: [`playcanvas/supersplat`](https://github.com/playcanvas/supersplat) kết hợp [`playcanvas/splat-transform`](https://github.com/playcanvas/splat-transform) (xem chi tiết tại [`docs/execution/audits/04_supersplat.md`](../../../audits/04_supersplat.md)).
- Core components đáng adapt (**`ADAPT-HIGH`**):
  - WebGPU Gaussian splat renderer hỗ trợ Brush PLY metadata (`SplatRenderMode`).
  - Hệ thống Camera hoàn chỉnh (Orbit, Fly, Orthographic, axis alignment, reset).
  - Multi-layer Splats: ánh xạ 1:1 sang các `SceneObject` visual representations.
  - Transform gizmos (Move, Rotate), bounding-box selection, lasso, brush, eyedropper.
  - Tối ưu hóa scene lớn: LOD streaming, Morton ordering, định dạng SOG từ `splat-transform`.
- Three.js / R3F / Spark giữ vai trò technical view baseline cho Geometry mesh, Point Cloud và Collider wireframes.
- **Guardrails / Anti-patterns bắt buộc:**
  - ⚠️ **WebGPU Qualification Spike (`PRODUCT-06Q`)**: SuperSplat thuần WebGPU (không có WebGL fallback). Cần chạy spike kiểm chứng trên browser/GPU mục tiêu trước khi chuyển baseline.
  - ❌ **SceneIR là Source of Truth**: SuperSplat chỉ là editor frontend; mọi transform/edit phải emit event qua postMessage bridge về Next.js shell → FastAPI → cập nhật `SceneIR` revision. Cấm dùng `.ssproj` hay local state làm canonical scene.
  - ❌ **Không dùng Cloud Publish**: Bỏ hoàn toàn module upload lên PlayCanvas cloud (`publish.ts`).
  - ❌ **Geometry/Collider Extension**: SuperSplat không có sẵn viewer cho GLB mesh và collider specs; cần mở rộng bằng engine PlayCanvas hoặc giữ Three.js song song cho technical views.

## 9. Implementation Plan

1. **Qualification Spike (`PRODUCT-06Q`)**:
   - Thử nghiệm load file `VisualArtifact.ply` từ Brush qua HTTP URL vào SuperSplat.
   - Kiểm chứng WebGPU rendering, multi-layer loading (environment + 2 SceneObjects), move/rotate emit event và GPU resource cleanup.
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
