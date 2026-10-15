# Review T-020

Verdict: CHANGES REQUESTED (hai sửa nhỏ về chữ hiển thị; logic đạt)

Review code: đọc trọn diff `ProcessingSettings.tsx` (khối `ReviewChoice`) và `useProcessingForm.ts` (`matchesPreset`, `keepReviewChoice`),
và đoạn tóm tắt trong `UnifiedInputFlow.tsx`. Chạy `processing-settings`, `ux-processing-form`, `unified-input-flow`: 46 passed.

## Acceptance criteria
1. Mặc định "Dừng để duyệt" theo preset: **pass**.
2. Chọn "Tạo mesh ngay" → payload tạo job có `scene.geometry_review = "auto"`: **pass** (test mới trong `unified-input-flow.test.tsx`, chấp nhận
   dù file không có trong plan).
3. Không hiện lần hai trong mục nâng cao (bộ đếm tham số cũng trừ đi): **pass**.
4. Chỉ đọc: **pass** ở mức component.
5. Preset không có param → không có khối: **pass**.

## Quyết định Engineer
- Đổi preset/kịch bản **giữ** lựa chọn duyệt của người dùng, và không tính khóa này khi so khớp preset: **chấp nhận**. Đây là lựa chọn về quy
  trình làm việc, không phải về chất lượng, nên không nên bị preset ghi đè.
- Kịch bản dùng lại kết quả ước lượng tài nguyên vì bộ ước lượng không đọc `geometry_review`: đúng.

## Required changes
1. **Tóm tắt hiển thị giá trị thô** (`UnifiedInputFlow.tsx` ~dòng 1476, "Xem thông số đã chọn"): với tham số `kind === "choice"`, hiện nhãn của
   lựa chọn (`parameter.choices.find(c => c.value === v)?.label`) thay cho giá trị thô. Áp cho mọi tham số choice, vì `shell`, `multiview_v1`,
   `required`, `auto` đều đang hiện thô. Test: tóm tắt hiện "Vỏ Gaussian (mặc định)" và "Dừng để duyệt tách vật", không hiện "shell"/"required".
2. **Câu chữ khi chỉ đọc mà không có giá trị**: "Không được ghi lại trong video mẫu." chỉ đúng cho video mẫu. Đổi thành câu chung:
   "Job này tạo trước khi có lựa chọn này; dùng hành vi cũ (không dừng duyệt)." Cập nhật test tương ứng.
3. Chạy lại 3 file test trên + typecheck + eslint. Thêm "Round 2" vào report, đặt `implemented`.

## Ghi chú
- Kiểm bố cục bằng mắt là việc của chủ dự án.
