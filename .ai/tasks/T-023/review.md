# Review T-023

Verdict: ACCEPTED

Đọc diff `object_region.fit_region`, route GET `region/fit`, `RegionFitGate.tsx`, `region-session.ts`, phần mở phiên trong
`ObjectReviewView.tsx`, `RegionEditor` (Đặt lại). Chạy lại backend region/queue/regeneration (140 PASS) và frontend
region-editor/object-review (PASS).

## Acceptance criteria
1. Pass. Fit dùng `_local` (pose nguồn, cùng phép đổi với `resolve_region`), `center=(min+max)/2`, `half+1e-4`, kẹp [0.005, 20].
2. Pass. Draft/Ready, donor, vật đã Move: fit theo `source_transform`, không theo `transform`.
3. Pass. 409 revision lệch; 422 dưới 50 hàng hoặc vật đã xoá/bỏ qua/gộp; 404 vật không có trong membership.
4. Pass. Panel chỉ mở sau khi có fit; lỗi → Thử lại/Đóng, không tạo box. "Đặt lại" về đúng fit.
5. Pass. Không còn đường tạo box từ `primitive_dimensions_xyz_m`; nút "Chỉnh vùng" không còn phụ thuộc kích thước.

## Suggestions
- Route fit nạp nguồn vào cache, nên preview đầu tiên sau khi mở panel thường đã "warm" (giảm tác động cold 4 s của T-025).
