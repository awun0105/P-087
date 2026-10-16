# Review T-024

Verdict: ACCEPTED

Đọc diff `GeometryReviewBanner.tsx`, `object_region._donor_status`, `RegionEditor.tsx`, `useRegionPreview.ts`.

## Acceptance criteria
1. Pass (GR-03). Banner tính lỗi vỏ trên mọi vật có nhãn trong membership; vật đã loại có hướng "Khôi phục, sửa vùng, rồi Tạo mesh".
2. Pass (GR-04). Preview trả `donor_remaining` + `blockers` (không raise); Apply khoá kèm tên và số, có tooltip. Apply phía máy chủ
   vẫn giữ `_require_remaining_rows`.
3. Pass (GR-06). Lỗi preview giữ `errorStatus`; 409 ở preview hoặc Apply đều hiện "Tải lại", boxes/claims giữ nguyên.
4. Pass. Bộ đếm cũ không đổi. Thêm: vật đã tick vẫn hiện khi chưa có kết quả preview ("chưa có kết quả xem trước").

## Suggestions
- Chưa có test riêng cho donor trên Ready (engineer đã nêu). Cùng đường code với Draft nên không chặn; thêm khi đụng lại file.
