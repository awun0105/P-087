# Review T-010

Verdict: ACCEPTED

Đã đọc `report.md` và toàn bộ `src/services/orchestration/scene/object_region.py`. Chạy lại Tests required + `test_objectify_draft.py`:
140 passed.

## Acceptance criteria
1. Preview không tạo artifact, không đổi revision: **pass** (`test_preview_is_read_only_and_uses_source_pose`).
2. Bộ đếm khớp `resolve_region`, mẫu ≤ 20.000, vỏ GLB base64: **pass**. Vỏ preview lấy mẫu đều tối đa 100k hàng, có `shell_sample_rows`;
   số đếm vẫn chính xác.
3. Apply trên Draft → membership/Gaussian/vỏ mới cho vật bị ảnh hưởng, vật khác giữ ref: **pass**.
4. Claim làm vật B < 50 → 422 trước khi publish: **pass** (`test_apply_rejects_before_any_artifact_publish`).
5. Revision/checksum cũ → 409, không publish: **pass**.
6. Ready → 422: **pass**.
7. Vật đã Move dùng `source_transform`: **pass**.
8. Role matrix: **pass**.
Hiệu năng: 300k hàng trong ngân sách (`test_preview_three_hundred_thousand_rows_budget`).

## Quy tắc khung (architecture §7.1)
Hàng nguồn đổi sang local bằng `Rᵀ(p − t)` của `source_transform` của **chính vật đó**, không căn tâm lại, không gọi `split()`;
quaternion Gaussian (`rot_0..3`, wxyz) cũng đổi về khung local: đúng. Test `..._without_recentering` có pose xoay 90° và hai vật khác tâm.

## Quyết định Engineer (chấp nhận)
- Tách `_load_membership_source` dùng chung, `prepare_correction` giữ hành vi cũ (chỉ bảo vệ sàn khi đích là nền).
- Cache nguồn bất biến 2 mục, không cache nhãn.
- Vỏ lỗi khi Apply → hộp chỉ để hiển thị + `shell_error`, collider null; vỏ dựng lại được thì xoá cờ lỗi: khớp T-005/T-007.
- Publish manifest membership riêng làm evidence.
- Artifact bất biến có thể còn lại nếu `publish_next` thua race; head không đổi. Giống các writer khác, chấp nhận.
