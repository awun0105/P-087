# T-016: Region Editor panel

## Goal
Panel điều khiển chỉnh vùng một vật: thêm/xoá box cộng/trừ, góc nhìn, preview tự động (debounce), bộ đếm, cảnh báo chồng lấn
+ "Lấy luôn", Apply/Huỷ. Nối box model (T-014), overlay (T-015) và API (T-010/T-011).

## Context
`architecture.md` §9 (Region Editor), §7.3. API client cần thêm vào `frontend/src/lib/api/studio.ts`:
```ts
export interface RegionPreview { scene_revision: string; membership_checksum: string; object_id: string;
  added_count: number; removed_count: number; object_gaussian_count: number; protected_floor_count: number;
  overlaps: Record<string, number>; claimed: Record<string, number>;
  added_sample_m: [number, number, number][]; removed_sample_m: [number, number, number][];
  shell_glb_base64: string | null; shell_error: string | null }
export function previewObjectRegion(jobId: string, objectId: string, command: ObjectRegionCommand, signal?: AbortSignal): Promise<RegionPreview>;
export function applyObjectRegion(jobId: string, objectId: string, command: ObjectRegionCommand): Promise<SceneEditResponse | ObjectifyState>;
// 201 → SceneEditResponse (Draft), 202 → ObjectifyState (Ready)
```
Box ban đầu: dựng từ `primitive_dimensions_xyz_m` của vật (tâm 0, yaw 0, nửa kích thước = dims/2). Lúc tách, `transform`
của vật đặt ở tâm nhóm Gaussian nên box này khớp nhóm hiện tại. Gọi preview ngay khi mở để có vỏ phát sáng.
(`fitBoxToPoints` của T-014 dùng sau, khi muốn "Khớp lại" theo điểm của preview.)

## Files
- Tạo: `frontend/src/features/studio/region/RegionEditor.tsx`
- Tạo: `frontend/src/features/studio/region/useRegionPreview.ts` (debounce + huỷ request cũ)
- Sửa: `frontend/src/lib/api/studio.ts`
- Sửa: `frontend/src/features/studio/ObjectReviewView.tsx` (nút "Chỉnh vùng", mở RegionEditor thay vì `GaussianMembershipEditor`
  cho scene có `object_geometry`; giữ GaussianMembershipEditor (Brush/Lasso) như lựa chọn phụ "Chỉnh chi tiết (Brush/Lasso)")
- Tạo: `frontend/tests/region-editor.test.tsx`

## UI/UX
Panel nổi bên phải viewport (cùng chỗ panel vật), tiêu đề "Chỉnh vùng · {tên vật}".
- Danh sách box: mỗi dòng "Cộng #1" / "Trừ #2", bấm để chọn, nút xoá (không cho xoá box cộng cuối cùng).
- Nút: `+ Box cộng` (thêm box bằng box đang chọn thu 80%), `− Box trừ` (box nhỏ 30% ở tâm box chọn), `Đặt lại`.
- Góc nhìn: `Trên` `Trước` `Cạnh` → `RegionOverlay.viewFrom`.
- Bộ đếm: "+{added} / −{removed} · tổng {object_gaussian_count}" và "Bảo vệ sàn: {protected_floor_count}". Đang tính: spinner nhỏ cạnh bộ đếm.
- Chồng lấn: với mỗi `overlaps[id] > 0`: "Box chồng lên {tên} ({n} Gaussian) — giữ chủ cũ" + checkbox "Lấy luôn" → thêm id vào `claim_from` → preview lại.
- `shell_error` → cảnh báo vàng "Vỏ chưa dựng được: {lý do}. Apply vẫn được nhưng Tạo mesh sẽ báo lỗi cho vật này."
- Không gọi preview khi `validateBoxes(boxes)` khác null (hiện thông báo lỗi đó thay cho bộ đếm). `fitBoxToPoints` không kẹp
  kích thước nên box tự khớp có thể không hợp lệ (vật > 40 m hoặc quá mỏng): phải báo, không âm thầm sửa.
- **Apply** enabled chỉ khi: có preview thành công, `preview.key === boxesKey(boxes) + claim`, không đang tính, `validateBoxes` null.
  Draft → sau 201 đóng panel + tải revision mới. Ready → sau 202 đóng panel, `ObjectifyNotice` hiện tiến độ "region".
- **Huỷ**: đóng panel, xoá box, không gọi API ghi.
- 409 → "Scene đã đổi ở lượt khác. Tải lại để chỉnh tiếp." + nút Tải lại. 422 → hiện `message` server.
- Bàn phím: Delete xoá box đang chọn (trừ box cộng cuối), Esc huỷ kéo (T-015) hoặc đóng panel nếu không kéo.

## Steps
1. API client + test fetch (URL, body, xử lý 201/202). Commit.
2. `useRegionPreview`: debounce 250 ms sau `onChange`, `AbortController` huỷ request cũ, trả `{preview, key, loading, error}` + test (fake timers). Commit.
3. `RegionEditor` danh sách box + thêm/xoá + góc nhìn + test. Commit.
4. Bộ đếm, chồng lấn + Lấy luôn, shell_error + test. Commit.
5. Apply/Huỷ + 409/422 + test. Commit.
6. Nối vào `ObjectReviewView` (nút Chỉnh vùng, Brush/Lasso thành lựa chọn phụ) + test trong `object-review.test.tsx`. Commit.

## Acceptance criteria
1. Mở editor → 1 box cộng khớp `primitive_dimensions_xyz_m`; preview đầu tiên được gọi.
2. Kéo box (mô phỏng `onChange` 3 lần liên tiếp trong 100 ms) → chỉ 1 request preview sau 250 ms; request cũ bị abort.
3. Apply bị khoá khi box đổi sau preview cuối (key lệch) và mở lại khi preview mới về.
4. Tick "Lấy luôn" → command có `claim_from` chứa id đó.
5. Draft: Apply → gọi API, panel đóng, scene tải lại. Ready: Apply → 202, notice tiến độ hiện.
6. 409 → thông báo + Tải lại; box của người dùng không bị xoá.
7. Không thể xoá box cộng cuối cùng; có thể xoá box trừ.

## Tests required
```
cd frontend
./node_modules/.bin/vitest run tests/region-editor.test.tsx tests/object-review.test.tsx tests/region-box-model.test.ts
npm run typecheck
./node_modules/.bin/eslint <các file đã sửa>
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .` ở root, `report.md`, `status.md`.

## Out of scope
Vẽ vỏ phát sáng và điểm thêm/bớt (T-017) — task này chỉ chuyển `preview` xuống prop cho T-017 dùng.
