# Audit #9 — `@playcanvas/supersplat-viewer`

> **Tài liệu tham chiếu:** Repository Audit cho Real2Sim Studio (AI20K RAV-01)  
> **Package:** [`@playcanvas/supersplat-viewer`](https://github.com/playcanvas/supersplat-viewer) (NPM Package)  
> **Pinned Version:** 1.35.2  
> **Source kiểm chứng:** `c52f5258df424635323f26aaeebe51361dc0f8e6` (`package.json`, `src/options.ts`, `src/types.ts`, `src/index.ts`)
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

Source xác nhận browser API sau. Đây là ví dụ tích hợp, chưa phải browser smoke
của Real2Sim. Host cung cấp container, experience settings hợp lệ và URL HTTP/blob
đã resolve từ artifact API sau kiểm tra checksum; không truyền `artifact://` trực
tiếp vào browser fetch. SOG/LOD có relative resources cần URL base và các chunk refs
được resolve tương ứng.

```typescript
import { createViewer } from '@playcanvas/supersplat-viewer/viewer';
import '@playcanvas/supersplat-viewer/viewer.css';

// Các biến do host cung cấp sau khi resolve artifact và experience settings.
const viewer = await createViewer({
    container: htmlElement,
    contentUrl: resolvedContentUrl,
    settings: experienceSettings,
    ui: false
});

// Capture đợi frame đầu tiên; frameScene/resetCamera yêu cầu state.loaded.
const capture = await viewer.captureFrame();
// capture có width, height và data (base64), không phải data URL đồng bộ.
if (viewer.state.loaded) {
    viewer.state.cameraMode = 'orbit';
    viewer.frameScene();
}

// Gọi trong lifecycle cleanup của host khi unmount.
viewer.destroy();
```

- Root package export phục vụ `renderViewerHtml`; browser embedding dùng subpath `/viewer`.
- `settings` là required option. `captureFrame()` trả `Promise<CaptureResult>`.
- Camera mode là writable `viewer.state.cameraMode`, không có `setCameraMode()`.
- `ViewerHandle` không expose `pickSurface()`. Picker nội bộ không phải public API;
  EX-PRODUCT phải adapt selection qua Engine/app và ánh xạ về SceneObject ID,
  rồi kiểm chứng bằng integration test. Không import internals như stable API.

### Định dạng đầu vào được hỗ trợ tự nhiên:
- `.ply` (chuẩn và compressed PLY).
- `.sog` và `.lod-meta.json` (Streamed SOG do `splat-transform` xuất).
- `collision = .glb` hoặc dữ liệu voxel để hiển thị va chạm và hỗ trợ walk-mode.

### WebGPU & WebGL2:
- Tự động phát hiện WebGPU khi trình duyệt hỗ trợ.
- Source có WebGL fallback; PRODUCT-06 phải kiểm chứng WebGL2 và WebGPU khi khả dụng
  trên browser mục tiêu. Nếu cả hai không dùng được, host hiển thị capability error.

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
| WebGPU ➔ WebGL2 Fallback | `EX-PRODUCT` | **REUSE + QUALIFY** | Kiểm chứng browser mục tiêu và error state |
| Orbit / Fly / Walk Camera | `EX-PRODUCT` | **REUSE CORE** | Điều hướng góc nhìn kỹ sư |
| Surface/Object Picking | `EX-PRODUCT` | **ADAPT + QUALIFY** | Không có `pickSurface` trên public handle; host sở hữu SceneObject mapping |
| Snapshot / Frame Capture | `EX-PRODUCT` | **REUSE CORE** | Xuất thumbnail preview cho Job |
