# T-014: Box model TypeScript thuần

## Goal
Toàn bộ toán của box nằm trong một module thuần, không phụ thuộc PlayCanvas, để overlay (T-015) và panel (T-016) chỉ gọi hàm.

## Context
`architecture.md` §7.3 (RegionBox), §9 (Region Editor). Toạ độ: hệ canonical **Z-up, mét**, box ở **object-local**
(cùng khung với `SceneObject.local_frame`). Contract TS `RegionBox`, `ObjectRegionCommand` đã mirror ở T-004
(`frontend/src/lib/contracts/api.ts`).

## Files
- Tạo: `frontend/src/features/studio/region/box-model.ts`
- Tạo: `frontend/tests/region-box-model.test.ts`

## Interfaces
```ts
export type Vec3 = [number, number, number];
export type BoxOp = "add" | "subtract";
export interface EditableBox { id: string; op: BoxOp; center: Vec3; half: Vec3; yaw: number }
export type FaceId = "+x" | "-x" | "+y" | "-y" | "+z" | "-z";

export const MIN_HALF_M = 0.005, MAX_HALF_M = 20, MAX_BOXES = 16;

/** OBB ban đầu từ điểm object-local: yaw theo PCA trên mặt XY, đáy z = min z, thêm lề `marginM` (mặc định 0.02). */
export function fitBoxToPoints(points: Float32Array, marginM?: number): Omit<EditableBox, "id" | "op">;

/** Kéo một mặt đi `deltaM` theo pháp tuyến ngoài của mặt đó (trong khung box); mặt đối diện đứng yên.
 *  Kẹp half trong [MIN_HALF_M, MAX_HALF_M]. */
export function dragFace(box: EditableBox, face: FaceId, deltaM: number): EditableBox;

export function translateBox(box: EditableBox, delta: Vec3): EditableBox;
export function rotateYaw(box: EditableBox, deltaRad: number): EditableBox;     // chuẩn hoá về (-π, π]

/** Không cho đáy box xuống dưới `floorZ` (object-local): nâng tâm/giảm half theo cách giữ đỉnh box. */
export function clampToFloor(box: EditableBox, floorZ: number): EditableBox;

export function faceCenter(box: EditableBox, face: FaceId): Vec3;               // vị trí tay nắm
export function faceNormal(box: EditableBox, face: FaceId): Vec3;               // pháp tuyến world (object-local)
export function contains(box: EditableBox, p: Vec3): boolean;                   // cùng quy tắc server (dung sai 1e-6)

export function toCommandBoxes(boxes: EditableBox[]): RegionBox[];              // center_m, half_extents_m, yaw_rad, op
export function validateBoxes(boxes: EditableBox[]): string | null;             // thông điệp lỗi tiếng Việt hoặc null
export function boxesKey(boxes: EditableBox[]): string;                         // chuỗi ổn định để so preview khớp box
```

## Steps
1. Kiểu + `contains` + `toCommandBoxes` + `validateBoxes` + test. Commit.
2. `dragFace`, `translateBox`, `rotateYaw`, `faceCenter`, `faceNormal` + test. Commit.
3. `fitBoxToPoints` + `clampToFloor` + test. Commit.
4. `boxesKey` + test. Commit.

## Acceptance criteria
1. `dragFace(box, "+x", 0.1)` với yaw 0: half.x +0,05, center.x +0,05; mặt −x đứng yên (kiểm toạ độ mặt −x trước/sau bằng nhau).
2. Cùng thao tác với yaw = π/2: dịch theo trục +y world, mặt đối diện đứng yên.
3. Kéo âm quá mức → half kẹp ở `MIN_HALF_M`, không đảo chiều.
4. `fitBoxToPoints` trên điểm của một hộp xoay 30° → yaw ≈ ±30° (mod π/2, sai ≤ 2°), half ≈ thật + lề.
5. `clampToFloor` giữ đỉnh box cố định, đáy = floorZ.
6. `contains` khớp quy tắc server: điểm trên mặt → true; box trừ không xử lý ở đây (logic cộng/trừ nằm server).
7. `validateBoxes`: không có box `add` → "Cần ít nhất một box cộng"; > 16 → thông báo; half ngoài khoảng → thông báo.
8. `boxesKey` đổi khi bất kỳ giá trị nào đổi ≥ 1e-6; không đổi khi chỉ đổi thứ tự thuộc tính object.

## Tests required
```
cd frontend
./node_modules/.bin/vitest run tests/region-box-model.test.ts
npm run typecheck
./node_modules/.bin/eslint src/features/studio/region/box-model.ts tests/region-box-model.test.ts
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .` ở root, `report.md`, `status.md`.

## Out of scope
Không vẽ, không PlayCanvas, không gọi API.
