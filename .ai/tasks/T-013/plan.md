# T-013: API client + banner Draft + tiến độ build

## Goal
Studio nhận biết scene Draft: hiện banner "Đang duyệt tách vật" + nút **Tạo mesh**, khoá Walk/USD/Move/Rotate kèm
lý do, theo dõi tiến độ build (phase, huỷ, lỗi, thử lại), tải revision mới khi xong.

## Context
`architecture.md` §9 (Màn duyệt, Build). Code:
- `frontend/src/lib/api/studio.ts`: `requestObjectify`, `cancelObjectify(jobId, operationId)`, `getObjectifyState`, `ObjectifyState`.
- `frontend/src/features/studio/ObjectifyNotice.tsx`: đã có nhánh `mode === "membership"` → làm tương tự cho `geometry`, `region`.
- `frontend/src/features/studio/ObjectReviewView.tsx`: nút Move/Rotate (gizmo), panel vật.
- `frontend/src/features/studio/MetricSceneView.tsx`: nút Walk; nơi xuất USD (tìm `simulation-package` / `SimulationPackage` trong `frontend/src`).

## Files
- Sửa: `frontend/src/lib/api/studio.ts`
- Tạo: `frontend/src/features/studio/GeometryReviewBanner.tsx`
- Sửa: `frontend/src/features/studio/ObjectifyNotice.tsx`, `ObjectReviewView.tsx`, `MetricSceneView.tsx`
  (và component nút USD nếu ở file khác)
- Tạo: `frontend/src/lib/scene/geometry-state.ts`
- Test: `frontend/tests/geometry-review-banner.test.tsx` (mới), cập nhật `frontend/tests/object-review.test.tsx`,
  `frontend/tests/progress-objectify.test.tsx`

## Interfaces
```ts
// lib/scene/geometry-state.ts
export type ObjectGeometryState = "awaiting_review" | "ready";
export function objectGeometryState(scene: SceneIR): ObjectGeometryState;   // thiếu khóa → "ready"
export const GEOMETRY_NOT_READY_REASON = "Cần tạo mesh trước";

// lib/api/studio.ts
export function buildObjectGeometry(jobId: string, expectedRevision: string): Promise<ObjectifyState>;  // POST scene/geometry/build
```
Phase → nhãn tiếng Việt: `shell` "Dựng vỏ vật", `quality` "Kiểm tra chất lượng", `collider` "Tạo collider (CoACD)",
`objectgs` "Chạy ObjectGS", `environment` "Dựng nền và collision môi trường", `publish` "Lưu revision".

## UI/UX
- Banner (khi `awaiting_review`): nền ember nhạt, chữ "Đang duyệt tách vật · {n} vật · chưa có collider". Nút chính
  **Tạo mesh** (disabled khi đang có việc objectify chạy). Dòng phụ: "Chỉnh vùng từng vật nếu cần, rồi Tạo mesh. Bước này chạy một lần."
- Vật có `provenance.shell_error`: banner hiện cảnh báo "Vỏ của {tên} chưa dựng được — sửa vùng trước khi Tạo mesh", nút Tạo mesh vẫn bấm được
  (server sẽ báo lỗi rõ) nhưng có chấm cảnh báo.
- Khoá: nút Walk, xuất USD, gizmo Move/Rotate disabled, `title`/tooltip = `GEOMETRY_NOT_READY_REASON`.
- Đang build: `ObjectifyNotice` hiện "Đang tạo mesh · {phase}. Scene duyệt được giữ đến khi hoàn tất." + nút Huỷ (truyền `operation_id`).
- Lỗi/huỷ: "Tạo mesh {thất bại|đã huỷ}. Scene duyệt được giữ nguyên. {error}" + nút "Thử lại".
- Xong (`done`, `result_revision`): tải lại scene (cùng cơ chế `onRevision`/`setReload` hiện có).
- Ready: panel vật hiện dòng "Collider: Vỏ Gaussian" hoặc "Collider: ObjectGS", và lý do nếu `surface_selection.reason` có.

## Steps
1. `geometry-state.ts` + test. Commit.
2. `buildObjectGeometry` + mở rộng type `ObjectifyMode` (`geometry`, `region` nếu chưa có). Commit.
3. `GeometryReviewBanner` + test (render, bấm Tạo mesh gọi API với revision đúng, disabled khi đang chạy). Commit.
4. `ObjectifyNotice` nhánh `geometry`/`region` + test (phase, huỷ với operation_id, lỗi + Thử lại). Commit.
5. Khoá Walk/USD/gizmo trong Draft + test. Commit.
6. Dòng nguồn collider trong panel vật khi ready + test. Commit.

## Acceptance criteria
1. Scene Draft → banner hiện, nút Walk/USD/Move/Rotate disabled có tooltip đúng.
2. Bấm Tạo mesh → gọi `POST scene/geometry/build` với `expected_scene_revision` hiện tại; nút disabled trong lúc chờ.
3. Polling hiện phase tiếng Việt; Huỷ gửi đúng `operation_id`.
4. Thất bại → thông báo lỗi + Thử lại; scene hiển thị không đổi.
5. Xong → scene tải lại, banner biến mất, các nút mở khoá.
6. Scene cũ (không có khóa) → không có banner, hành vi như trước (test cũ PASS).

## Tests required
```
cd frontend
./node_modules/.bin/vitest run tests/geometry-review-banner.test.tsx tests/object-review.test.tsx tests/progress-objectify.test.tsx
npm run typecheck
./node_modules/.bin/eslint <các file đã sửa>
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .` ở root, `report.md`, `status.md`.

## Out of scope
Region Editor (T-015..T-017).
