# T-015: Box overlay + tay nắm + góc nhìn

## Goal
Trong viewport Studio (PlayCanvas, cùng `SceneOverlay`), vẽ các box của Region Editor gắn theo vật, có tay nắm:
6 mặt (kéo mặt), vòng xoay quanh Z, dịch tâm; nút góc nhìn Trên / Trước / Cạnh. Mọi thay đổi đi qua box model (T-014).

## Context
`architecture.md` §9 (Region Editor). Code:
- `frontend/src/features/viewer/scene-overlay.ts`: `SceneOverlay`, `attachGizmo(id, mode, handlers)` dùng `TranslateGizmo`/
  `RotateGizmo` của PlayCanvas, cơ chế chặn `pointerdown` để camera không tranh con trỏ (đọc kỹ đoạn comment ~dòng 683–704
  và **dùng lại** cách đó). `rayUnitBox` có sẵn để bắt tia vào box.
- Test mẫu: `frontend/tests/scene-overlay-gizmo.test.ts` (cách mock PlayCanvas app/camera).
- `MetricSceneView.tsx` tạo `SceneOverlay` và truyền vào con.

## Files
- Tạo: `frontend/src/features/viewer/region-overlay.ts` (lớp `RegionOverlay`, dùng `SceneOverlay` làm host, không nhồi thêm vào file 40k)
- Sửa: `frontend/src/features/viewer/scene-overlay.ts` (chỉ thêm accessor tối thiểu: `app`, `camera`, entity root của vật theo id,
  hàm chặn/khôi phục pointer camera nếu đang private)
- Sửa: `frontend/src/features/viewer/CameraToolbar.tsx` hoặc thêm nút trong Region Editor (T-016) cho góc nhìn; task này cung cấp hàm
- Tạo: `frontend/tests/region-overlay.test.ts`

## Interfaces
```ts
export interface RegionOverlayHandlers {
  onChange(boxes: EditableBox[]): void;      // gọi khi THẢ tay nắm (không gọi liên tục khi kéo)
  onSelect(boxId: string | null): void;
}
export type ViewPreset = "top" | "front" | "side";

export class RegionOverlay {
  constructor(host: SceneOverlay, objectId: string, handlers: RegionOverlayHandlers);
  setBoxes(boxes: EditableBox[], selectedId: string | null): void;
  setFloorZ(floorZ: number): void;            // object-local; dùng clampToFloor khi thả
  viewFrom(preset: ViewPreset): void;         // camera nhìn vuông góc vào box đang chọn, giữ khoảng cách vừa khung
  destroy(): void;                             // gỡ entity, gizmo, listener; khôi phục camera controller
}
```

## UI/UX
- Box `add`: viền xanh lục (#22c55e) + mặt mờ 8%; box `subtract`: viền đỏ (#ef4444) nét đứt (dùng nhiều đoạn), mặt mờ 8%.
  Box đang chọn: viền dày hơn và hiện tay nắm; box khác chỉ có viền.
- Tay nắm mặt: hình cầu/đĩa nhỏ 2,5 cm (scale theo khoảng cách camera để luôn ~14 px) tại `faceCenter`. Kéo: chiếu chuyển động
  con trỏ lên trục `faceNormal` (ray–line closest point), cập nhật preview hình box tức thì, **thả** mới gọi `onChange`.
- Vòng xoay: dùng `RotateGizmo` của PlayCanvas giới hạn trục Z (ẩn trục X/Y); thả → `rotateYaw`.
- Dịch tâm: `TranslateGizmo` ở tâm box; thả → `translateBox`.
- Trong lúc kéo: tắt camera controller (như gizmo hiện có); thả hoặc Esc → bật lại. Esc giữa chừng → huỷ thao tác đang kéo.
- `viewFrom`: Trên = nhìn xuống −Z; Trước = nhìn theo +Y của box; Cạnh = nhìn theo +X của box; khung vừa box + 20%.
- Toạ độ: entity box là con của root vật (đã mang `transform` hiện tại của vật) → box hiển thị theo pose hiện tại nhưng giá trị
  lưu là object-local.

## Steps
1. Accessor tối thiểu trong `SceneOverlay` + test cũ PASS. Commit.
2. `RegionOverlay.setBoxes` vẽ box (màu theo op, chọn/không chọn) + test (đếm entity, màu). Commit.
3. Tay nắm mặt + kéo theo pháp tuyến + `onChange` khi thả + test (mô phỏng pointer down/move/up, kiểm box mới đúng `dragFace`). Commit.
4. Xoay Z + dịch tâm qua gizmo PlayCanvas + test. Commit.
5. `setFloorZ` + clamp khi thả + test. Commit.
6. `viewFrom` + test (vị trí/hướng camera). Commit.
7. `destroy` không rò entity/listener + test. Commit.

## Acceptance criteria
1. Box hiển thị đúng vị trí khi vật có transform ≠ identity (box là con của root vật).
2. Kéo tay nắm `+x` 10 cm (mô phỏng) → `onChange` nhận box có half.x +5 cm, mặt −x đứng yên; trong lúc kéo không gọi `onChange`.
3. Kéo làm đáy xuống dưới sàn → thả xong đáy = floorZ.
4. Khi kéo, camera controller tắt; sau khi thả/Esc, bật lại.
5. Chọn box khác → tay nắm chuyển sang box đó, `onSelect` được gọi.
6. `destroy()` → không còn entity của RegionOverlay trong scene graph, không còn listener trên canvas.

## Tests required
```
cd frontend
./node_modules/.bin/vitest run tests/region-overlay.test.ts tests/scene-overlay-gizmo.test.ts tests/scene-overlay-pick.test.ts
npm run typecheck
./node_modules/.bin/eslint src/features/viewer/region-overlay.ts src/features/viewer/scene-overlay.ts tests/region-overlay.test.ts
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .` ở root, `report.md`, `status.md`.
Kiểm tra bằng mắt trên browser là việc của chủ dự án; agent không cần chụp màn hình.

## Out of scope
Gọi API preview, vỏ phát sáng, panel nút (T-016, T-017).
