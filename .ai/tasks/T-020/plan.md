# T-020: Lựa chọn "Duyệt trước / Tạo mesh ngay" ở màn tạo job

## Goal
Người dùng chọn ngay lúc tạo job: **Duyệt tách vật trước khi tạo mesh** (mặc định) hay **Tạo mesh ngay** (`auto`, cho chạy
hàng loạt). Lựa chọn hiển thị rõ, không nằm lẫn trong mục nâng cao.

## Context
`architecture.md` §5 (`scene.geometry_review`), §9. Param `scene.geometry_review` (choice `required` / `auto`) được thêm
vào presets ở T-013 (bước 7). `frontend/src/features/studio/ProcessingSettings.tsx` hiện tự vẽ mọi param theo nhóm (`GROUPS`, nhóm
`scene` "Tách vật thể · CoACD") bên trong `<details>` nâng cao; `useProcessingForm.ts` giữ giá trị form.

## Files
- Sửa: `frontend/src/features/studio/ProcessingSettings.tsx`
- Sửa (nếu cần): `frontend/src/features/studio/useProcessingForm.ts`
- Test: `frontend/tests/` file test hiện có của ProcessingSettings (tìm bằng `grep -l ProcessingSettings frontend/tests`),
  thêm case mới

## Steps
1. Thêm khối "Sau khi tách vật" **ngoài** `<details>` nâng cao, ngay dưới phần chọn preset: hai radio
   - "Dừng để duyệt và chỉnh vùng vật (khuyên dùng)" → `required`
   - "Tạo mesh ngay, không duyệt" → `auto`
   Mô tả phụ cho `auto`: "Nhanh cho chạy hàng loạt. Vật tách sai vẫn sửa được sau, nhưng mỗi lần sửa phải dựng lại hình học."
   Giá trị đọc/ghi qua cùng state form của param `scene.geometry_review`. Commit.
2. Ẩn param `scene.geometry_review` khỏi danh sách trong `<details>` để không hiện hai lần. Commit.
3. Khi `editable` false (xem lại job đã tạo), khối hiển thị chỉ đọc giá trị đã niêm phong. Commit.
4. Nếu preset không có param này (preset cũ/khác) → không hiện khối. Commit.

## Acceptance criteria
1. Mặc định chọn "Dừng để duyệt" theo preset.
2. Chọn "Tạo mesh ngay" → params gửi khi tạo job có `scene.geometry_review = "auto"`.
3. Param không xuất hiện lần thứ hai trong mục nâng cao.
4. Job đã tạo hiển thị chỉ đọc đúng giá trị.
5. Không có param → không có khối, các test cũ PASS.

## Tests required
```
cd frontend
./node_modules/.bin/vitest run <test ProcessingSettings hiện có>
npm run typecheck
./node_modules/.bin/eslint src/features/studio/ProcessingSettings.tsx src/features/studio/useProcessingForm.ts
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .` ở root, `report.md`, `status.md`.

## Out of scope
Backend `auto` (đã ở T-009).
