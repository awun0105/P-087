# Real2Sim Studio — Web Studio (`frontend/`)

Web shell và scene viewer của EX-PRODUCT. Next.js 16 (App Router) + React 19 +
TypeScript + Tailwind 4.

## Chạy

Backend phải chạy trước, ở cổng 8000:

```bash
# từ gốc repo
make run            # hoặc: uvicorn src.main:app --reload
```

Rồi:

```bash
cd frontend
npm install
npm run dev         # http://localhost:3000
```

`next.config.ts` proxy `/api/v1/*` sang backend, nên trình duyệt chỉ nói chuyện
same-origin — không cần bật CORS. Đổi địa chỉ backend bằng biến môi trường
`REAL2SIM_API_URL` (mặc định `http://127.0.0.1:8000`).

## Kiểm tra

```bash
npm run typecheck   # next typegen && tsc --noEmit
npm run lint        # eslint
npm test            # vitest run
npm run build       # next build
```

`typecheck` chạy `next typegen` trước vì `PageProps`/`LayoutProps` là kiểu do
Next sinh ra trong `.next/types`; chạy `tsc` trần trên máy sạch sẽ báo thiếu kiểu.

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `src/app/` | Route: `/projects`, `/jobs/[jobId]`, `/jobs/[jobId]/viewer`, `/validation`, `/review` |
| `src/features/viewer/` | Viewer 3D: `layers.ts` (SceneIR → layer, thuần, không import Three.js), `ply.ts`, `SceneCanvas.tsx`, `ViewerPanel.tsx` |
| `src/components/` | Shell, các trạng thái lỗi/rỗng/đang tải |
| `src/lib/contracts/api.ts` | Bản mirror TypeScript của shared contract trong `src/models/contracts/` |
| `src/lib/api/` | Client không ném (`ApiResult`) + endpoint có type |

## Ràng buộc

- **Canonical state nằm ở backend.** React state chỉ giữ *view preference* (view
  mode, ẩn/hiện layer, đang chọn gì). Sau mọi lệnh ghi, client gọi
  `router.refresh()` để đọc lại từ backend.
- **Không lộ đường dẫn filesystem.** Mọi tham chiếu artifact là `artifact://` URI
  kèm checksum.
- **`VISUAL` chưa phải 3DGS thật.** Fixture hiện chỉ có visual tổng hợp
  (`brush_compatibility_proof: false`). Render 3DGS thật là AC-11, mốc M3, chờ
  `REC-04`. Ba view Geometry/Point Cloud/Collider là view kỹ thuật ngang hàng,
  không phải fallback và không thay thế AC-11.
