# Review T-005

Verdict: ACCEPTED

Đã đọc `report.md` và diff `src` từ `cc414a9a` tới `5f12970a`. Chạy lại Tests required cộng `test_objectgs_required_stage.py` và
`test_membership_regeneration.py`: 86 passed.

## Acceptance criteria
1. Draft không gọi ObjectGS/convex/inpaint/package: **pass** (`test_draft_never_calls_geometry_or_background_providers`).
2. `object_geometry=awaiting_review`, collider null, `geometry_ref` loại `ObjectShellMesh`, có `source_transform`: **pass**.
3. Environment giữ visual đầy đủ của bundle + membership, không có object-aware collision: **pass**.
4. Vỏ thô là GLB watertight đọc lại được: **pass**.
5. Vỏ lỗi → vật vẫn còn, `shell_error`, hộp chỉ để hiển thị, collider null: **pass**.
6. ObjectGS + required không cần runtime ObjectGS: **pass**.
7. legacy / auto / không có khóa → hành vi cũ: **pass** (regression thêm cho `legacy`, `auto`, `shell + auto`).
Bước 7 (dọn từ T-003): đổi tên biến, thông điệp, xoá alias, nới Literal: **pass**.

## Lệch plan (chấp nhận, và là phát hiện quan trọng)
1. `gaussian_split.split()` đã trả hàng object-local theo tâm AABB. Plan bảo trừ `part.center` lần nữa là **sai**; Engineer đã kiểm và
   có test với tâm world khác 0. Architect đã thêm "Quy tắc khung" vào `architecture.md` §7.1 và sửa T-007 (lấy hàng từ PLY nguồn
   world) và T-010 (đổi local theo `source_transform` cũ, không căn tâm lại) để lỗi này không lặp lại.
2. Giữ `bind_source_collision_ownership` trong extraction: hàm chỉ ghi metadata nguồn, không tạo collider. Hợp lý.
3. Commit (a) tạo khi fixture còn lỗi, sửa ngay ở commit sau; đã ghi nhận trung thực. Chấp nhận, lần sau commit sau khi test xanh.

## Required changes
Không có.

## Ghi chú cho T-007
Từ chối build vật có `shell_error` cho tới khi người dùng sửa vùng (plan T-007 bước 3 đã có).
