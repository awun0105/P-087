# T-017: Vỏ phát sáng + điểm thêm/bớt

## Goal
Người dùng nhìn thấy ngay vật đang được tách thế nào:
- **Vỏ phát sáng** ôm sát Gaussian thuộc vật (vỏ thô 0,05 m từ preview, hoặc `geometry_ref` vỏ của vật khi chưa preview).
- **Điểm xanh** = Gaussian sẽ thêm, **điểm đỏ** = Gaussian sẽ bị loại.

Trong Draft, Studio không vẽ thêm Gaussian của vật (môi trường đã là 3DGS đầy đủ), chỉ vẽ vỏ.

## Context
`architecture.md` §7.1 (Draft rendering), §9. Code:
- `SceneOverlay` đã vẽ hình vật từ GLB qua `OverlayBox.shapeUrl` (load asset GLB, `paint(entity, material, wire)`).
- `ObjectReviewView` dựng danh sách `OverlayObject` (Gaussian của vật, `objectVisual`) — dòng ~397–430.
- Preview trả `shell_glb_base64`, `added_sample_m`, `removed_sample_m` (object-local).

## Files
- Tạo: `frontend/src/features/viewer/shell-glow.ts` (`ShellGlowLayer`)
- Sửa: `frontend/src/features/viewer/region-overlay.ts` (gắn layer khi editor mở) hoặc RegionEditor truyền vào
- Sửa: `frontend/src/features/studio/ObjectReviewView.tsx` (Draft: bỏ OverlayObject Gaussian của vật; thay bằng vỏ cho mọi vật,
  vật đang chọn sáng hơn)
- Tạo: `frontend/tests/shell-glow.test.ts`; cập nhật `frontend/tests/object-review.test.tsx`

## Interfaces
```ts
export class ShellGlowLayer {
  constructor(host: SceneOverlay);
  /** GLB bytes (vỏ) trong khung object-local, gắn làm con của root vật. Thay bản cũ của cùng objectId. */
  setShell(objectId: string, glb: ArrayBuffer | string /* URL */, style: "selected" | "idle"): Promise<void>;
  setPointSets(objectId: string, added: Float32Array, removed: Float32Array): void;  // object-local, xyz liên tiếp
  clear(objectId?: string): void;
  destroy(): void;
}
```

## UI/UX
- Vỏ `selected`: material emissive xanh ngọc (#2dd4bf), opacity 0,25, blend additive, `depthWrite=false`, cull none,
  cộng viền wireframe mảnh opacity 0,5. Vỏ `idle` (vật khác trong Draft): cùng màu, opacity 0,10, không viền.
- Hiệu ứng "phát sáng": tăng emissive intensity và thêm nhịp nhẹ (opacity dao động 0,22–0,28 chu kỳ 2 s) chỉ khi `selected`.
  Tôn trọng `prefers-reduced-motion`: tắt nhịp.
- Điểm: point sprite 4 px, xanh lục #22c55e (thêm) và đỏ #ef4444 (loại), luôn vẽ trên cùng (`depthTest=false`) để thấy được.
  Tối đa 20.000 điểm mỗi loại (server đã giới hạn).
- Khi preview đang tính: giữ vỏ cũ, giảm opacity về 0,12 tới khi vỏ mới về.
- `shell_error`: không vẽ vỏ mới; giữ vỏ cũ với màu cam (#f59e0b) để báo hiệu.

## Steps
1. `ShellGlowLayer.setShell` (GLB từ base64 hoặc URL), material, gắn vào root vật + test (entity tạo đúng cha, material đúng). Commit.
2. `setPointSets` + test (số điểm, màu, depthTest). Commit.
3. Nhịp phát sáng + reduced-motion + test. Commit.
4. RegionEditor: preview mới → `setShell`/`setPointSets`; đóng editor → `clear`. Test. Commit.
5. Draft rendering trong `ObjectReviewView`: không đưa Gaussian của vật vào overlay; vẽ vỏ `idle` cho mọi vật từ `geometry_ref`
   (URL `jobArtifactContentUrl`), `selected` cho vật đang chọn. Ready: hành vi cũ. Test. Commit.

## Acceptance criteria
1. Vỏ gắn làm con của root vật → di theo transform vật; trong Draft vật không Move nên trùng vị trí Gaussian.
2. Preview mới thay vỏ cũ (không chồng nhiều vỏ cho một vật).
3. Điểm xanh/đỏ đúng số lượng mẫu; xoá khi đóng editor.
4. Draft: không có OverlayObject Gaussian cho vật (tránh vẽ chồng hai lần); Ready: như cũ.
5. `prefers-reduced-motion: reduce` → không có nhịp.
6. `destroy()` không rò entity/asset.

## Tests required
```
cd frontend
./node_modules/.bin/vitest run tests/shell-glow.test.ts tests/region-editor.test.tsx tests/object-review.test.tsx
npm run typecheck
./node_modules/.bin/eslint <các file đã sửa>
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .` ở root, `report.md`, `status.md`.
Nhìn bằng mắt trên browser là việc của chủ dự án.

## Out of scope
Không đổi Walk/physics.
