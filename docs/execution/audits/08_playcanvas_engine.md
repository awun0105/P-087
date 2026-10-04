# Audit #8 — `playcanvas/engine`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Repository:** [`playcanvas/engine`](https://github.com/playcanvas/engine)  
> **Pinned Version:** 2.22.4  
> **License:** MIT  
> **Ngày audit:** 2026-09-25  
> **Trạng thái:** Hoàn tất Audit #8 (Web 3D Runtime Core Deep Dive)

---

## Kết luận trước

> **`playcanvas/engine` được chọn làm Web 3D Runtime Core cho Real2Sim Web Studio, thay thế hoàn toàn kế hoạch tự xây dựng viewer/editor dựa trên Three.js.**

PlayCanvas Engine cung cấp sẵn hạ tầng đồ họa WebGL2/WebGPU cấp độ production với hỗ trợ first-class cho Gaussian Splatting, unified scene graph, depth buffer đồng bộ, và hệ thống transform gizmo chuẩn mực.

Phân loại đề xuất:

```text
playcanvas/engine (v2.22.4)

Tier A — Core Reuse

EX-PRODUCT      REUSE CORE (Toàn bộ Web 3D Viewport)
EX-SCENE        HIGH (Direct Scene Graph mapping)
EX-SIM          MEDIUM (Collision & primitive preview)
EX-REC          MEDIUM (SOG / Web delivery visual consumption)
```

---

## 1. Các thành phần có sẵn trong mã nguồn (Source Tree Audit)

PlayCanvas Engine 2.22.4 sở hữu đầy đủ các module cần thiết cho Web Studio mà không cần tự phát triển:

```text
GSplatComponent           - Quản lý vòng đời và tham chiếu Gaussian Splat
GSplatAssetLoader         - Nạp file PLY, SOG, compressed PLY
GSplatProcessor           - Xử lý shader lọc, chọn lọc (selection) và biến đổi hạt
GSplat Unified Renderer   - Tích hợp 3DGS trực tiếp vào engine render pipeline
SOG / Streamed SOG LOD    - Tự động streaming theo cây phân cấp octree/LOD
Picker / RenderPassPicker - Raycast và chọn đối tượng/hạt Gaussian chính xác
TranslateGizmo            - Trục điều khiển dịch chuyển 3D
RotateGizmo               - Vòng xoay điều khiển góc quay 3D
ScaleGizmo                - Khối điều khiển tỉ lệ kích thước
Entity Scene Graph        - Quản lý phân cấp cha-con, transform position/rotation/scale
Mesh Rendering            - Render mesh đa giác (GLB/glTF), gán vật liệu chuẩn
CollisionComponent        - Quản lý hình khối va chạm (Box, Sphere, Capsule, Mesh)
RigidBodyComponent        - Tích hợp động lực học Ammo.js (cho preview tức thì)
```

---

## 2. Bước ngoặt kiến trúc: Single Scene Graph thay thế Dual Scene Graph

### Baseline cũ (Three.js + Gaussian Renderer riêng):
Trước đây, hệ thống định sử dụng 2 scene graph tách rời: Three.js quản lý Mesh/Collider, còn một renderer riêng quản lý 3DGS. Điều này dẫn tới 4 vấn đề nghiêm trọng:
1. **Lỗi Depth Buffer:** Không đồng bộ được Z-buffer giữa hạt Gaussian và Mesh đa giác, gây hiện tượng z-fighting hoặc hạt bị vẽ đè lên vật thể.
2. **Trùng lặp Camera:** Phải đồng bộ ma trận góc nhìn (ViewMatrix/ProjectionMatrix) thủ công giữa 2 renderer.
3. **Phân mảnh Transform:** Phải tự viết adapter ánh xạ position/rotation/scale từ SceneIR sang 2 scene graph.
4. **Phức tạp hóa thao tác chọn:** Phải viết 2 raycaster/picker riêng biệt.

### Baseline mới (PlayCanvas Single Scene Graph):
Toàn bộ các lớp biểu diễn của một đối tượng đều được gắn trên **cùng một `pc.Entity`**:

```text
PlayCanvas Scene Graph
├── Environment Entity
│   ├── GSplatComponent (Visual 3DGS / SOG)
│   ├── RenderComponent (Optional coarse GLB mesh)
│   └── CollisionComponent (Environment collision.glb)
└── SceneObject Entities (Pallet_01, Rack_01, Box_02)
    ├── GSplatComponent (Object Gaussian membership mask)
    ├── RenderComponent (Asset/Primitive mesh)
    └── CollisionComponent (Box / OBB Collider)
```

**Lợi ích bất biến:**
- Cùng chia sẻ một transform duy nhất: `Entity.position`, `Entity.rotation`, `Entity.scale`.
- Khi người dùng dùng `TranslateGizmo` kéo Entity, cả Visual, Mesh và Collider di chuyển đồng bộ 100%.
- Chia sẻ chung WebGL2/WebGPU Depth Buffer trong cùng một Render Pass.
- Ánh xạ 1:1 sang cấu trúc `SceneIR` ở backend.

---

## 3. Khóa phiên bản và Quản lý vòng đời GPU (Lifecycle)

- **Pinned Version:** `2.22.4` (Tránh dùng nhánh `main` hiện đang trong giai đoạn `2.23.0-beta`).
- **WebGPU / WebGL2 Fallback:** Engine tự động kiểm tra khả năng của trình duyệt: ưu tiên WebGPU, tự động fallback sang WebGL2 nếu client không hỗ trợ.
- **Dọn dẹp tài nguyên (Memory Leak Guard):**
  Khi component React/Next.js bị unmount (chuyển job, đóng viewer):
  - Gọi `app.destroy()` để hủy toàn bộ WebGL/WebGPU context.
  - Hủy bộ nhớ đệm `AssetRegistry` và giải phóng GPU buffers của 3DGS.

---

## 4. Code Reuse Matrix cho `playcanvas/engine`

| Module / Tính năng | Track | Quyết định | Ghi chú tích hợp |
| :--- | :--- | :--- | :--- |
| `GSplatComponent` & Loader | `EX-PRODUCT` | **REUSE CORE** | Nạp Visual SOG từ `splat-transform` |
| Scene Graph (`pc.Entity`) | `EX-PRODUCT` / `EX-SCENE` | **REUSE CORE** | Đồng bộ trực tiếp với `SceneObject` |
| `TranslateGizmo`, `RotateGizmo` | `EX-PRODUCT` | **REUSE CORE** | Thay thế code gizmo Three.js tự viết |
| `RenderPassPicker` | `EX-PRODUCT` | **REUSE CORE** | Hỗ trợ chọn bề mặt và chọn hạt |
| `StandardMesh` (GLB) | `EX-PRODUCT` | **REUSE CORE** | Hiển thị geometry và preview collider |
| Ammo.js Physics | `EX-PRODUCT` | **REUSE-PREVIEW** | Chỉ dùng cho preview cục bộ, không thay Isaac |
