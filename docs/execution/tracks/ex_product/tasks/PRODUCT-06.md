# PRODUCT-06 — SceneIR 3D Viewer

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
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
- Nhúng vào client-only Next.js component: `createViewer({ container, contentUrl, settings, ui: false })`.
- WebGPU khi khả dụng và WebGL2 fallback phải qualification trên browser mục tiêu;
  host hiển thị capability error nếu không khởi tạo được backend.
- Nạp trực tiếp file `.sog` / Streamed SOG LOD (từ `splat-transform`), `.ply` và `collision = .glb`.
- **Single Scene Graph Architecture (Audit #8):**
  - Mọi lớp (Visual SOG, Mesh GLB, Collider GLB) đều được gắn trên cùng một `pc.Entity` trong PlayCanvas Engine.
  - Cùng scene graph/depth pipeline; vẫn phải kiểm chứng occlusion và z-fighting thực tế.
  - Cùng chia sẻ Transform `position/rotation/scale`, đồng bộ trực tiếp với `SceneObject` trong `SceneIR`.
- **Guardrails / Anti-patterns bắt buộc:**
  - ❌ **SceneIR là Source of Truth**: Viewer chỉ là viewport hiển thị; mọi transform/edit phải gửi command về backend FastAPI để cập nhật `SceneIR` revision. Local state không bao giờ là canonical scene.
  - ❌ **SSR Bypass**: Component viewer trong Next.js bắt buộc dùng `next/dynamic(..., { ssr: false })` để tránh lỗi truy cập `window`/WebGL trên Node server.
  - ❌ **GPU Lifecycle**: Bắt buộc gọi `viewer.destroy()` khi unmount component để giải phóng WebGL/WebGPU context, tránh tràn VRAM trình duyệt.

## 9. Implementation Plan

2026-09-28: preview raw 3DGS có API/contract riêng, không cần fixture SceneIR.
UI hiển thị UNCONFIRMED/arbitrary, typed parser kiểm job/ref trước URL tải SOG;
pan/zoom/rotate dùng supersplat-viewer đã pin. Tiếp theo adapt công cụ inspection
theo nhóm; không scale/delete canonical scene chỉ bằng browser-local mutation.
Không chạy tests/browser theo yêu cầu owner; chưa có AC-11 acceptance.

1. Tạo client-only wrapper dùng `@playcanvas/supersplat-viewer/viewer`, stylesheet,
   `ui: false` và required `settings`. Resolve artifact refs thành HTTP/blob URLs;
   không truyền trực tiếp `artifact://` vào browser fetch. API mẫu đã kiểm chứng ở Audit #09.
2. Tích hợp Single Scene Graph PlayCanvas: nạp Visual SOG (từ `REC-04`) và `collision.glb` (từ `REC-05`/`SIM-02`) trên cùng Entity.
3. Camera dùng writable `viewer.state.cameraMode` và readiness/capability gates.
   Public handle không có `pickSurface`; adapt picking qua Engine/app và kiểm
   chứng SceneObject mapping. `captureFrame` là async, cleanup bằng `destroy()`.
4. Tích hợp PlayCanvas `TranslateGizmo` / `RotateGizmo` và gửi event cập nhật vị trí về backend SceneIR API.
5. Tận dụng `splat-transform` cho khâu tối ưu hóa, sinh LOD và SOG streaming.
6. Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

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
- [ ] PlayCanvas Engine layers dùng canonical coordinate/transform metadata.
- [ ] Transform edits persist through backend revision then re-render.
- [ ] Renderer capability/error state và cleanup rõ; synthetic visual hoặc mesh/point-cloud không bị báo cáo là Brush compatibility proof.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Interaction recording/screenshots.
- Real Brush `VisualArtifact` format/producer/version/checksum, các view artifact checksums, renderer/PlayCanvas/WebGL runtime version và browser environment.
- Save/reload revision/checksum.
- Render performance and error state.

## 13. Evidence nhánh `feat/product` — Three.js technical view (2026-09-24/25)

Nhánh `feat/product` fork từ `c007c26` (23/09) và dừng lại không nhận `develop`. Baseline
PlayCanvas bị khóa ở `dffcde7` ngày 25/09, **sau** khi nhánh đó bắt đầu viết viewer.
Vì vậy các mục dưới đây là bằng chứng về **technical view trên Three.js**, không phải
bằng chứng 3DGS. Không có gì ở đây thay thế mục DoD "render real Brush 3DGS" ở §11.

**Test backend:** `test_scene_editor.py` 23 passed · `test_scene_routes.py` 17 passed ·
`ruff check src/ tests/` sạch.

**Test frontend:** `npm test` → 54 passed (5 file) · `npm run build` exit 0.

**Ca âm quan trọng — `evaluation_only` không ra được product boundary:**
`GET /jobs/{id}/artifacts/content?artifact_uri=.../evaluation_only/...` → **404**;
artifact của job khác → 404; `..` trong URI → **422**.

**Revision persist rồi đọc lại:** edit publish `scene_ir.rev-002.json`; `rev-001` giữ
nguyên bytes cũ. Đã sửa lỗi `SceneEditor` chỉ giữ revision trong RAM: sau restart
`POST /scene/edits` trả 500; nay phục hồi revision cao nhất trên đĩa, fail closed, và
map `ArtifactStoreError` → 409.

**Guard chống bằng chứng 3DGS giả — phần này nên giữ lại bất kể renderer nào:**

```jsonc
// GET /jobs/{id}/scene
{ "visual": { "format": "real2sim.synthetic.visual.v1",
              "brush_compatibility_proof": false }}   // ← cờ đi kèm payload
// GET /jobs/{id}/validation
{ "isaac_runtime_proof": false }
```

UI render `data-testid="brush-proof-absent"` khi cờ false, nên visual tổng hợp **không
thể** bị trình bày nhầm là bằng chứng AC-11. Đây là điều `AGENTS.md` §8 yêu cầu và
không được mất khi đổi renderer.

**Browser smoke 25/09 (Chrome headless):** Three.js khởi tạo WebGL thật
(`<canvas data-engine="three.js r180">` do chính Three.js gắn), nhánh suy giảm
`webgl-unavailable` không xuất hiện, layer dựng từ SceneIR thật, và trình duyệt tự
tải bytes PLY qua `GET /artifacts/content`.

### 13.1 Ranh giới renderer — Three.js là fallback có điều kiện

- **Mặc định theo `INTEGRATION_PLAYBOOK:745`:** PlayCanvas Engine + `@playcanvas/supersplat-viewer`
  cho **toàn bộ** lớp (Visual SOG, Mesh GLB, Collider GLB) trong **một** scene graph
  `pc.Entity`. Không chia renderer theo view mode.
- **Three.js giữ lại làm fallback** trong lúc PlayCanvas chưa được qualification, vì
  máy hiện tại là Quadro T2000 — **không có WebGPU**, còn supersplat ưu tiên WebGPU.
- **`layers.ts` là nguồn transform duy nhất** cho cả hai renderer. Nếu hai renderer cùng
  tự quản lý transform thì sẽ vi phạm invariant canonical transform của SceneIR.
- **Điều kiện bỏ Three.js:** PlayCanvas đã render được **real Brush `VisualArtifact`**
  (SOG) trên browser mục tiêu và chứng minh được WebGL2 fallback. Trước thời điểm đó,
  code Three.js **không được xoá** nhưng **không được tính là bằng chứng 3DGS**.

### 13.3 Khoảng trống đã đo sau audit (2026-09-27)

Audit 7 repo tham chiếu + code quality tìm ra các mục sau. Mục nào đã sửa thì ghi
rõ; mục nào là **khoảng trống tính năng** thì ghi là khoảng trống, không tính là
sửa xong.

**Đã sửa:**

- `onFailed` inline làm viewer bị destroy/tạo lại mỗi render (tải lại SOG) → `useCallback`
  + test hồi quy.
- Docstring mô tả `viewer.app.root` dù không có dòng nào chạm nó → viết lại đúng thực tế.
- `viewer.css` chưa import; `next/dynamic({ ssr: false })` chưa dùng → `viewer.css` đã
  import, còn `next/dynamic` ghi dưới đây.
- `api.ts` lệch 16 field + 7 enum; `PrivacyResult` đoán sai hoàn toàn → đã sinh lại từ
  Pydantic, thêm `scripts/check_contract_mirror.py` để lệch là fail.
- `StageTimeline` vẽ 11 stage trong đó 9 không tồn tại, thiếu 18 stage thật, và
  `ExecutionError` không bao giờ hiện → dựng từ `STAGE_IDS` thật.
- Nút Approve/Reject không bao giờ hiện vì UI so `isFinal` với `"PENDING"` — giá trị
  backend không thể phát ra → `isFinal` dựa trên `approval` có tồn tại.
- Không có quy đổi Z-up→Y-up nên mọi object vẽ sai trục → dùng đúng `R_x(-90°)` của repo.
- Fixture dùng checksum `sha256:env0000` — không khớp `^sha256:[0-9a-f]{64}$` → helper `sha()`.
- Point cloud đoán từ `geometry_ref` rồi để canvas trắng → cờ `provisional` + banner.

**Khoảng trống, chưa xử lý (không phải bug):**

- **Single Scene Graph chưa trọn.** Đã có collider environment qua `collisionUrl`; ba
  view kỹ thuật còn lại vẫn ở renderer Three.js riêng. Cần `playcanvas/engine` thật.
- **Không có undo/redo.** `playcanvas/supersplat` chưa lấy `EditHistory`.
- **`playcanvas/engine` 0 import.** Không `TranslateGizmo`/`RotateGizmo`; translate hiện là
  nút số ±0.1/±0.5, rotate không sửa được.
- **`createViewer` dùng 3/16 API.** Chưa dùng `resetCamera`, `toggleWalk`, `seek`,
  `captureFrame`, `annotations`, `events` (ngoài `progress:changed`).
- **PLY parser đoán thứ tự property.** `parseHeader` đếm số property nhưng không đọc
  tên; đọc `parts[0..2]` là x/y/z. Một PLY có `intensity/confidence/x/y/z` sẽ ra sai
  mà không báo lỗi — trái với chính docstring file nói là strict.
- **`StageTimeline` chưa có test.** Đã sửa component nhưng chưa khoá bằng test.
- **Không có `AbortController`** ở 5 đường fetch; `setTimeout` ở 3 chỗ không clear.
- **409 không có đường thoát.** Edit scene trả 409 thì panel giữ revision cũ và mọi
  edit sau lại cũng 409 tới khi reload tay.
- **`PRODUCT-07` endpoint là fake stub** (tự thừa nhận ở `:144`).

### 13.2 Giới hạn của evidence trên

- AC-11 là mốc M3; mục DoD "render real Brush 3DGS" vẫn **để trống**, và phải để
  trống cho tới khi có PlayCanvas render SOG thật.
- Browser smoke dùng Chrome headless + `--dump-dom`, **không** phải E2E tự động; chưa
  kiểm orbit/pan/zoom bằng thao tác thật, chưa kiểm giải phóng GPU resource khi unmount.
- Chưa có khoá liên tiến trình cho hai client sửa cùng lúc; lỗi nay ra **409** thay vì
  500, nhưng chưa có arbitration thật.
- PLY chỉ hỗ trợ `format ascii 1.0`; PLY binary bị **từ chối thẳng** thay vì đoán layout.
- `SceneEditor` seed từ `fixtures/scene_ir/scene.json` — dữ liệu fixture, **không**
  phải output của EX-SCENE.
