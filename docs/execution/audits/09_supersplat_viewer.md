# Audit #9 — `@playcanvas/supersplat-viewer`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Package:** [`@playcanvas/supersplat-viewer`](https://github.com/playcanvas/supersplat-viewer) (NPM Package)  
> **Pinned Version:** 1.35.2  
> **License:** MIT  
> **Ngày audit:** 2026-09-25  
> **Trạng thái:** Hoàn tất Audit #9 (Embedded 3DGS Viewer Deep Dive)

---

## Kết luận trước

> **`@playcanvas/supersplat-viewer` được chọn làm thư viện viewer nhúng cốt lõi trong `PRODUCT-06`, giải quyết dứt điểm rào cản nhúng của SuperSplat standalone app.**

Trong Audit #4, ta nhận thấy ứng dụng SuperSplat tuy mạnh nhưng là standalone application (chỉ chạy WebGPU, phụ thuộc UI riêng, khó nhúng vào React). Package `@playcanvas/supersplat-viewer` chính là câu trả lời: PlayCanvas đã tách rời lõi viewer và đóng gói thành thư viện NPM chính thức, hỗ trợ chạy ẩn UI (`ui: false`) và tự động fallback sang WebGL2.

Phân loại đề xuất:

```text
@playcanvas/supersplat-viewer (v1.35.2)

Tier A — Core Reuse

EX-PRODUCT      REUSE CORE (Primary 3DGS Viewport Engine)
EX-REC          HIGH (Consumer of SOG & Compressed PLY artifacts)
```

---

## 1. Các API và Khả năng Thực tế

Package cung cấp API lập trình gọn gàng, phù hợp hoàn hảo với Next.js / React component:

```typescript
// Khởi tạo viewer không có UI mặc định (Real2Sim tự dựng UI bằng Next.js / Tailwind)
const viewer = await createViewer({
    container: htmlElement,
    contentUrl: 'artifact://jobs/.../scene.sog',
    ui: false
});

// Điều khiển Camera
viewer.frameScene();
viewer.resetCamera();
viewer.setCameraMode('orbit' | 'fly' | 'walk' | 'anim');

// Tương tác & Trích xuất
viewer.pickSurface(screenX, screenY);
const dataUrl = viewer.captureFrame();

// Quản lý vòng đời
viewer.destroy();
```

### Định dạng đầu vào được hỗ trợ tự nhiên:
- `.ply` (chuẩn và compressed PLY).
- `.sog` và `.lod-meta.json` (Streamed SOG do `splat-transform` xuất).
- `collision = .glb` hoặc dữ liệu voxel để hiển thị va chạm và hỗ trợ walk-mode.

### WebGPU & WebGL2:
- Tự động phát hiện WebGPU khi trình duyệt hỗ trợ.
- Tự động fallback sang WebGL2 mà không cần cấu hình thêm, đáp ứng 100% yêu cầu P0 của dự án (WebGL2 baseline).

---

## 2. Tác động Giảm tải Code cho `PRODUCT-06`

Nhờ tái sử dụng trực tiếp package này, Track `EX-PRODUCT` **không cần tự viết**:
1. Pipeline nạp và giải mã SOG / Gaussian PLY.
2. Bộ quản lý Camera Navigation (Orbit, Fly, Walk modes).
3. Logic phân cấp chi tiết LOD streaming khi tải cảnh kho bãi lớn.
4. Cơ chế đồng bộ Resize cửa sổ và Pixel Ratio của màn hình Retina.
5. Vòng đời khởi tạo và dọn dẹp WebGL2 / WebGPU context.

Toàn bộ khối lượng công việc của `PRODUCT-06` chỉ còn tập trung vào:
- Nhúng `createViewer` vào một component React (`next/dynamic` với `ssr: false`).
- Bắt sự kiện click để kết nối với `SceneIR` backend API.
- Tích hợp Transform Gizmo và hiển thị các lớp Mesh/Collider bổ trợ.

---

## 3. Code Reuse Matrix cho `supersplat-viewer`

| Tính năng | Track | Quyết định | Ghi chú |
| :--- | :--- | :--- | :--- |
| `createViewer({ ui: false })` | `EX-PRODUCT` | **REUSE CORE** | Nhúng trực tiếp vào Studio UI |
| SOG / LOD Streaming Loader | `EX-PRODUCT` | **REUSE CORE** | Nạp cảnh kho bãi lớn mượt mà |
| WebGPU ➔ WebGL2 Fallback | `EX-PRODUCT` | **REUSE CORE** | Đảm bảo tương thích mọi client |
| Orbit / Fly / Walk Camera | `EX-PRODUCT` | **REUSE CORE** | Điều hướng góc nhìn kỹ sư |
| Surface Picking | `EX-PRODUCT` | **REUSE CORE** | Bắt tọa độ click trên mô hình 3D |
| Snapshot / Frame Capture | `EX-PRODUCT` | **REUSE CORE** | Xuất thumbnail preview cho Job |
