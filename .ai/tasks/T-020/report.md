# Report T-020: Lựa chọn "Duyệt trước / Tạo mesh ngay" ở màn tạo job

## Done

Làm theo 4 bước của plan, mỗi bước một commit. Có thêm một điều chỉnh ở hook và một test ngoài danh sách Files (xem Deviations).

- **Bước 1** (`0005bc80`): khối "Sau khi tách vật" (hai radio) đặt ngay dưới phần chọn preset, ngoài `<details>`.
  Radio đọc và ghi qua state form của `scene.geometry_review`. Mặc định là "Dừng để duyệt..." theo preset, vì mọi preset
  đều niêm phong `required`. Chọn "Tạo mesh ngay" gửi `scene.geometry_review = "auto"`. Mô tả của `auto` đúng theo plan.
- **Điều chỉnh hook** (`fa4807bd`): xem Deviations 1 và 2.
- **Bước 2** (`17f406d0`): ẩn `scene.geometry_review` khỏi danh sách nâng cao. Số đếm "Thông số chi tiết (N tham số)"
  không tính ô này.
- **Bước 3** (`126a4fa1`): khi `editable=false`, khối hiện đúng giá trị niêm phong và khoá cả hai radio. Nếu giá trị không có
  khoá (video mẫu cũ), khối không chọn mặc định mà chỉ hiện dòng "Không được ghi lại trong video mẫu.", giống các ô khác.
- **Bước 4** (`b1862e39`): preset không có khoá thì không hiện khối. Code này đã có từ bước 1 (guard `reviewSpec`), nên
  test chỉ khoá hành vi và không đỏ trước khi sửa.
- **Test bổ sung** (`c936d5ef`): luồng tạo job thật, chọn "Tạo mesh ngay", thì payload `processing` có
  `scene.geometry_review: "auto"` (acceptance 2).

### Acceptance

1. Mặc định "Dừng để duyệt" theo preset: có test.
2. "Tạo mesh ngay" làm payload tạo job có `auto`: có test ở `unified-input-flow`.
3. Khoá không lặp trong mục nâng cao: có test.
4. Chỉ đọc hiện đúng giá trị niêm phong: có test với `editable=false`. Consumer chỉ đọc hiện nay là video mẫu (xem Known issues).
5. Không có khoá thì không có khối; các test cũ vẫn pass.

## Files changed

- `frontend/src/features/studio/ProcessingSettings.tsx`: hằng `GEOMETRY_REVIEW_KEY`, `REVIEW_CHOICES`, component `ReviewChoice`, và ẩn khoá khỏi danh sách nâng cao.
- `frontend/src/features/studio/useProcessingForm.ts`: `matchesPreset`, `keepReviewChoice`; `applyPreset` và `applyScenario` giữ lựa chọn duyệt.
- `frontend/tests/processing-settings.test.tsx`: 6 test mới.
- `frontend/tests/ux-processing-form.test.tsx`: 2 test mới cho hook.
- `frontend/tests/unified-input-flow.test.tsx`: 1 test mới, ngoài danh sách Files của plan, để khoá acceptance 2 ở đường tạo job.
- `.ai/tasks/T-020/report.md` (mới), `.ai/status.md` (chỉ dòng T-020).

Không sửa file nào của T-016 (region editor, `ObjectReviewView`).

## Tests

- `vitest run tests/processing-settings.test.tsx tests/ux-processing-form.test.tsx tests/unified-input-flow.test.tsx tests/studio-sample-pipeline.test.tsx`: **50 passed** (9 + 8 + 29 + 4). Hai file đầu là bộ của plan. Hai file sau render cùng component, nên chạy để kiểm hồi quy.
- `npm run typecheck`: passed.
- `eslint src/features/studio/ProcessingSettings.tsx src/features/studio/useProcessingForm.ts`: clean.
- `graphify update .`: đã chạy.

## Deviations from plan

1. **Preset và kịch bản không ghi đè lựa chọn duyệt.** Plan không nói về điều này. Roadmap ghi "Radio riêng", nên lựa chọn
   này độc lập với preset: đổi preset hay kịch bản vẫn giữ "Tạo mesh ngay" của người dùng. Nếu muốn preset đặt lại lựa chọn,
   bỏ `keepReviewChoice` trong `applyPreset` và `applyScenario`.
2. **Khớp preset bỏ qua khoá này.** Nếu không, chọn "Tạo mesh ngay" sẽ bỏ đánh dấu preset và hiện "Đang dùng thông số tùy
   chỉnh", dù người dùng chỉ đổi lựa chọn duyệt. `samePreset` cũ vẫn dùng cho đường ước lượng mặc định nên không đổi.
3. **Kịch bản dùng lại ước lượng tài nguyên của gợi ý.** Việc này đúng vì không có tham chiếu nào tới `geometry_review` trong
   `src/services/orchestration/processing/` và `src/api/studio/`, và `interpolate` giữ nguyên tham số kiểu choice. Lý do đã ghi trong code.
4. **Bước 4 là commit chỉ có test.** Code guard đã có từ bước 1, nên test không đỏ trước khi sửa.
5. **Acceptance 4 kiểm ở mức component** (`editable=false`). Trong cây hiện tại, `ProcessingSettings` chỉ được dùng chỉ đọc ở
   video mẫu. Không có màn job đã tạo nào dùng nó.
6. Thêm một case vào `unified-input-flow.test.tsx`, ngoài danh sách Files của plan, vì acceptance 2 chỉ được chứng minh đầy đủ
   ở đường tạo job.

## Known issues / TODO

- **Giao diện chưa được xem bằng mắt.** Test chỉ kiểm ARIA, trạng thái và payload. Bố trí khối, khoảng cách và màu là phần để
  người dùng xem.
- Bảng tóm tắt trong `UnifiedInputFlow.tsx` (quanh dòng 1476) hiện giá trị thô của mọi tham số, nên khối này sẽ hiện
  "required" và "auto" thay vì nhãn tiếng Việt. Không thuộc T-020; có thể sửa sau.
- Màn xem lại job đã tạo chưa có consumer chỉ đọc của `ProcessingSettings`. Nếu cần, phải thêm ở task riêng.

## Round 2

Sửa hai điểm trong `review.md` (CHANGES REQUESTED). Mỗi điểm là một commit riêng.

1. **Tóm tắt hiện nhãn lựa chọn thay vì giá trị thô** (`28cf8de8`). Trong "Xem thông số đã chọn" ở `UnifiedInputFlow.tsx`,
   tham số `kind === "choice"` hiện `choices[].label`; hàm `summaryValue` ở mức module. Áp cho mọi tham số choice, nên
   `shell`, `multiview_v1`, `required`, `auto` không còn hiện thô. Test mới dùng nhãn thật từ
   `configs/product/processing_presets_v1.json`: tóm tắt phải hiện "Vỏ Gaussian (mặc định)" và "Dừng để duyệt tách vật",
   và không còn "shell" hay "required" trong khối tóm tắt.
2. **Câu chữ khi chỉ đọc mà thiếu giá trị** (`bfcdd86f`). Khối "Sau khi tách vật" hiện
   "Job này tạo trước khi có lựa chọn này; dùng hành vi cũ (không dừng duyệt)." Chỉ đổi ở khối này. Dòng
   "Không được ghi lại trong video mẫu." của các ô khác giữ nguyên, vì test cũ khoá chữ đó. Test
   "không bịa lựa chọn..." đã cập nhật theo câu mới.

Mục "Known issues" của Round 1 về tóm tắt hiện giá trị thô đã đóng ở đây.

### Kiểm tra lại

- `vitest run` trên `processing-settings`, `ux-processing-form`, `unified-input-flow` và thêm `studio-sample-pipeline`
  (cùng render component): **51 passed** (9 + 8 + 30 + 4).
- `npm run typecheck`: passed.
- `eslint` trên ba file nguồn đã sửa (`ProcessingSettings.tsx`, `useProcessingForm.ts`, `UnifiedInputFlow.tsx`): clean.

Giao diện vẫn chưa được xem bằng mắt; phần đó thuộc chủ dự án, như review đã ghi.

Đã dừng chờ review.
