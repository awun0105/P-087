# Audit #4 — `playcanvas/supersplat` & `playcanvas/splat-transform`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Repository:** [`playcanvas/supersplat`](https://github.com/playcanvas/supersplat)  
> **Companion Utility:** [`playcanvas/splat-transform`](https://github.com/playcanvas/splat-transform)  
> **Commit audit:** `f76e67633f21b298846c29eceab48ae20579fb4e` (v3.4.2, 2026-09-23)  
> **License:** MIT (Cả SuperSplat và splat-transform)  
> **Ngày audit:** 2026-09-24  
> **Trạng thái:** Hoàn tất Audit #4 (4/7 trong Audit Queue)

---

## Kết luận trước

> **SuperSplat không chỉ là “3DGS renderer”. Nó là một editor 3DGS hoàn chỉnh trên browser và có khả năng thay thế một phần rất lớn code chúng ta đang định tự viết trong `PRODUCT-06 — 3D Viewer`, đồng thời giảm một phần `PRODUCT-07 — Object Actions`.**

Nhưng nó **không thể được đưa nguyên xi vào Real2Sim Studio** vì ba vấn đề chính:
1. SuperSplat hiện là standalone WebGPU application, không phải React component/library.
2. Nó chỉnh "Gaussian/Splat layers", không hiểu SceneIR/Object/Collider của chúng ta.
3. iframe API hiện tại quá nhỏ để làm integration contract với Real2Sim.

Do đó hướng có tiềm năng cao nhất là:
```text
SuperSplat
    ↓
self-hosted / pinned fork
    ↓
giữ rendering + editor primitives
    ↓
thêm Real2Sim postMessage bridge
    ↓
SceneIR vẫn là source of truth duy nhất
```

Đồng thời, phát hiện repo phụ cực kỳ đáng giá: **`playcanvas/splat-transform`** (MIT, v3.6.4). Repo này hữu ích cho **cả EX-REC + EX-PRODUCT + một phần EX-SIM**, là ứng viên Core Utility cho toàn dự án.

---

## 1. SuperSplat mạnh hơn baseline PRODUCT-06 ban đầu

Baseline dự kiến tự viết bằng Three.js: orbit, pan, zoom, select, hide/show, layer toggles, transform editing.

SuperSplat đã có sẵn gần như toàn bộ phần **Visual 3DGS Editor**:
- Camera navigation: Orbit, Fly, Orthographic views, axis alignment, reset.
- Selection đa dạng: point, rectangle, brush, sphere volume, box volume, lasso, polygon, flood selection.
- Transform gizmos: Move, Rotate, Scale trên entity/layer.
- Layer management: visibility, solo, delete, duplicate, separate.
- Edit history: Undo / Redo hoàn chỉnh (`EditHistory`, `EditOp`).
- Đo lường (measure), định hướng (orientation), import camera poses (COLMAP `images.txt`).
- Tối ưu hóa scene lớn: LOD streaming, Morton reordering (lên đến 20M splats).

Viết lại toàn bộ bằng Three.js sẽ lãng phí nguồn lực lớn.

---

## 2. Rendering & Rào cản WebGPU

Repo sử dụng PlayCanvas Engine 2.22.4 và WebGPU (`deviceTypes: ['webgpu']`), **không có WebGL fallback**. Trong `src/index.ts` hiển thị lỗi nếu browser không hỗ trợ WebGPU.

Docs hiện tại khóa: *WebGL/WebGL2 là P0 baseline; WebGPU là backend tùy chọn*.

Nếu chọn SuperSplat cho Visual Editor P0, cần thực hiện một **Qualification Spike (`PRODUCT-06Q`)** để xác nhận WebGPU hoạt động ổn định trên máy và trình duyệt mục tiêu trước khi chuyển baseline.

---

## 3. Tương thích định dạng & Khả năng đọc output của Brush

SuperSplat dùng `@playcanvas/splat-transform` 3.6.4, hỗ trợ: PLY, Compressed PLY, SOG, Streamed SOG, SPZ, SPLAT, KSPLAT, LCC, LCC2.

Điểm đặc biệt quan trọng: `splat-transform` **tương thích trực tiếp với Brush PLY metadata** (đọc được comment `SplatRenderMode: default/mip/2dgs` của Brush).

Integration path tự nhiên:
```text
Brush → VisualArtifact (.ply) → SuperSplat
```
Không cần viết lại parser PLY 3DGS từ đầu.

---

## 4. Load Artifact qua URL

`main.ts` hỗ trợ query parameters `?load=<url>&filename=<filename>` để tải file từ xa. Hoàn toàn ăn khớp với Artifact Store:
```text
VisualArtifact (artifact://jobs/.../visual.ply)
        ↓
PRODUCT-04 resolver (HTTP URL)
        ↓
SuperSplat Visual Editor
```

---

## 5. Selection System & Hỗ trợ Human Object Correction

SuperSplat có hệ thống selection chạy WebGPU compute shader (`intersect.ts`, `picker.ts`):
- Selection operations: SET, ADD, REMOVE, INTERSECT, INVERT.
- Depth-aware / frontmost selection.

**Kết hợp với R2G**:
- `R2G (SAMPro3D)`: Đề xuất object association tự động bằng máy.
- `SuperSplat Selection`: Cung cấp công cụ cho con người dùng brush/lasso/box khoanh vùng sửa lỗi, tách cụm (Separate) hoặc gán lại (Reassign).

---

## 6. Phân biệt: Gaussian Selection vs. SceneObject Selection

- **SuperSplat**: Thao tác trên chỉ số điểm Gaussian (`selected Gaussian indices`).
- **Real2Sim**: Thao tác trên `SceneObject ID` (bao gồm cả visual, geometry, collider và transform).

Khi người dùng thao tác một vật thể, không thể chỉ di chuyển hạt Gaussian mà bỏ lại mesh/collider.

**Giải pháp**: Mỗi `SceneObject` tương ứng một **Splat layer** độc lập trong SuperSplat.
```text
Scene
├── environment (Splat layer 0)
├── pallet_001  (Splat layer 1)
└── shelf_002   (Splat layer 2)
```
Khi người dùng chọn `pallet_001` và di chuyển, `EntityTransformHandler` của layer đó sẽ phát tín hiệu để cập nhật `SceneObject.transform`.

---

## 7. Giới hạn Transform & Kiểm soát Scale

SuperSplat hỗ trợ Move, Rotate, Scale. Tuy nhiên, P0 của Real2Sim Studio **không cho phép scale tự do** nếu chưa đồng bộ được đồng thời cả Visual, Geometry và Collider.

Khi adapt SuperSplat: Cần vô hiệu hóa tính năng Scale tự do trên UI, chỉ giữ **Move và Rotate** theo đúng SceneIR operation contract.

---

## 8. Undo/Redo & Quản lý State

- SuperSplat có `EditHistory` (`EntityTransformOp`, `SplatsTransformOp`, `RemoveInstancesOp`, ...). Đây là tương tác UI cục bộ rất tốt.
- Tuy nhiên: **Backend SceneIR Revision mới là Source of Truth duy nhất**. Local history chỉ phục vụ trải nghiệm người dùng trong phiên làm việc.
- Thao tác Delete: Delete Gaussian subset trên SuperSplat **không được tự tiện map thành Delete SceneObject**. Delete SceneObject phải xóa đồng bộ cả visual, geometry, collider trong backend revision.

---

## 9. Định dạng dự án `.ssproj`

SuperSplat có định dạng `.ssproj` (ZIP chứa `document.json`, static PLY resources, layer instance palettes).
- Đây là kỹ thuật lưu trữ static data 1 lần rất hay.
- Nhưng `.ssproj` **không thay thế SceneIR**. `.ssproj` chỉ đóng vai trò editor session/cache; `SceneIR` sở hữu semantic ID, physics, provenance, checksum và lifecycle.

---

## 10. `playcanvas/splat-transform`: Tiện ích cốt lõi cho Pipeline

Repo độc lập `splat-transform` (MIT, v3.6.4) chạy được trên Node.js, CLI, Docker và Browser:
1. **EX-REC / EX-PRODUCT**:
   - Validate Brush PLY, kiểm tra NaN/inf.
   - Thống kê (stats), sắp xếp không gian (Morton reorder).
   - Nén sang định dạng SOG (Streamed SOG) và sinh LOD cho các cảnh kho bãi hàng triệu splats.
2. **EX-SIM (Fallback Collider)**:
   - `splat-transform` hỗ trợ voxelization, external-fill, floor-fill, carve navigation volume và xuất collision mesh (`*.collision.glb`).
   - Có thể dùng làm baseline đối chứng hoặc fallback khi OpenMVS geometry gặp khuyết tật.

---

## 11. Hạn chế: SuperSplat thiếu Geometry & Collider Views

SuperSplat tập trung vào hạt Gaussian, không có sẵn giao diện hiển thị GLB geometry mesh và collider wireframe (box, convex hull) như yêu cầu của `PRODUCT-06`.

**Phương án kiến trúc tối ưu**:
Tạo fork của SuperSplat (dựa trên engine PlayCanvas có khả năng render mesh) và mở rộng thêm các element hiển thị Geometry và Collider; hoặc nhúng qua iframe có postMessage bridge liên kết chặt chẽ với Next.js shell.

---

## 12. Kiến trúc Tích hợp Đề xuất (Next.js + SuperSplat Fork)

```text
                   REAL2SIM WEB STUDIO
                            │
                  Next.js Product Shell
                            │
           ┌────────────────┼────────────────┐
           │                │                │
           ▼                ▼                ▼
     Project/Jobs       Review UI        Validation
                                              
                            │ (postMessage / typed bridge)
                            ▼
                 SuperSplat-derived Editor
                   /                  \
                  /                    \
          Visual 3DGS             extensions
          rendering              Geometry/Collider
                  \                    /
                   \                  /
                     SceneIR mapping
                            │
                            ▼
                        FastAPI
                            │
                            ▼
                     SceneIR Revision
```

Loại bỏ tính năng `Publish to PlayCanvas service` (`publish.ts`), thay bằng `Save Draft / Submit for Validation`.

---

## 13. Kế hoạch Qualification Spike: `PRODUCT-06Q`

Trước khi thay đổi baseline công nghệ chính thức, thực hiện 7 bài kiểm tra:
1. Load được file `VisualArtifact.ply` sinh ra từ Brush qua HTTP URL.
2. Render đúng 3DGS thực tế (không fallback về point cloud).
3. Load đồng thời ít nhất 1 environment + 2 SceneObject layers.
4. Chọn 1 object → Move/Rotate → phát event transform ra host.
5. Reload trang từ SceneIR backend → object hiển thị đúng transform mới.
6. WebGPU hoạt động ổn định trên máy/trình duyệt demo.
7. Đổi scene → dọn dẹp sạch sẽ tài nguyên GPU (không leak VRAM).

---

## 14. Code Reuse Matrix cho SuperSplat & splat-transform

| Component                              | Real2Sim phần tương ứng      | Quyết định                                    |
| -------------------------------------- | ---------------------------- | --------------------------------------------- |
| SuperSplat Gaussian rendering          | `PRODUCT-06` Visual view     | **ADAPT-HIGH** (cần qualification WebGPU)     |
| Camera orbit / fly / orthographic      | `PRODUCT-06` Navigation      | **REUSE-HIGH**                                |
| Multi-layer Splats                     | SceneObject Visual mapping   | **ADAPT-HIGH**                                |
| Entity transform gizmos                | `PRODUCT-07` Move/Rotate     | **ADAPT-HIGH**                                |
| Selection tools (brush, lasso, volume) | Human Object Correction      | **ADAPT-HIGH**                                |
| Undo / Redo engine                     | `PRODUCT-07` Interaction UX  | **REUSE-HIGH**                                |
| Separate layer                         | Tách vật thể (P1)            | **P1 ADAPT**                                  |
| `.ssproj` session structure            | Editor cache                 | **REFERENCE only**                            |
| SuperSplat Cloud Publish               | —                            | **DO NOT USE**                                |
| Scale gizmo                            | `PRODUCT-07`                 | **RESTRICT / DISABLE** (theo contract)        |
| `splat-transform` SOG / LOD / optimize | `EX-REC` / `EX-PRODUCT`      | **REUSE-HIGH** (Core utility candidate)       |
| `splat-transform` collision mesh       | `EX-SIM` Collider            | **REFERENCE / Fallback only**                 |

---

## 15. Quyết định phân loại sau Audit #4

```text
playcanvas/supersplat

Tier-0 Code Donor — EX-PRODUCT Visual Editor & 3D Viewer (PRODUCT-06)
Tier-0 UX/Interaction Donor — Scene correction & transform tools (PRODUCT-07)
P1 Donor — per-Gaussian split / reassign tooling
NOT canonical scene model
NOT backend lifecycle

playcanvas/splat-transform

Tier-0 Core Utility Candidate
— Visual artifact conversion, validation/stats, LOD streaming
— Collider fallback generation
```

---

## 16. Bảng tổng hợp sau 4 audit

| Capability            |  OpenReal2Sim |           R2G |       VR-Robo |                        SuperSplat |
| --------------------- | ------------: | ------------: | ------------: | --------------------------------: |
| Reconstruction        |           Med |           Med |           Low |                              None |
| Object association    |           Low | **Very High** |           Low |                    Human-assisted |
| Object decomposition  |           Med | **Very High** |           Low |                     Visual manual |
| 3DGS render           |           Low |           Med |      **High** |                 **Very High Web** |
| Object-level GS edit  |           Low |          High |           Med |         **Very High interactive** |
| USD build             | **Very High** |          None |           Low |                              None |
| Isaac runtime         |          High |          None | **Very High** |                              None |
| GS ↔ Isaac sync       |           Low |          None | **Very High** |                              None |
| Browser editor        |          None |          None |          None |                     **Very High** |
| Select/transform      |          None |          None |          None |                     **Very High** |
| Undo/redo             |          None |          None |          None |                     **Very High** |
| Artifact format tools |           Low |           Med |           Low | **Very High via splat-transform** |
| Collider generation   |          High |           Low |           Low |        Medium via splat-transform |

Audit tiếp theo: **#5 `DISCOVERSE` + `DISCOVERSE-Real2Sim`**.
