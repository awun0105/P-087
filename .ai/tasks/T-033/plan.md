# T-033: Panel "Benchmark" trong Studio — nhập ground truth

## Goal
Kỹ sư nhập số đo thước ngay trên scene: chọn hai điểm cho đoạn đo và khe kiểm, đánh dấu vật cản chính, gắn revision hiện tại
là bố trí A hoặc B, nhập mốc làm tay và khai báo L4. Lưu qua API T-030.

## Context
§15.2. Chọn điểm trên scene đã có: `MetricConfirmView` dùng `SplatInspection` (`setMeasuring`, `setPoints`, `points`) trên
`PlayCanvasScene`. Studio scene: `ObjectReviewView` (danh sách vật, `MetricSceneView`). Toạ độ phải lưu ở **canonical**
(mét, Z-up); kiểm hàm đổi khung hiển thị ↔ canonical ở `viewer/source-frame.ts`.

## Files
- Tạo: `frontend/src/features/studio/value/BenchmarkPanel.tsx`, `frontend/src/lib/api/value.ts` (thêm hàm truth)
- Sửa: `ObjectReviewView.tsx` (nút "Benchmark" mở panel, chỉ khi có quyền sửa), viewer để chọn hai điểm khi panel mở
- Test: `frontend/tests/benchmark-panel.test.tsx`

## UI/UX
Panel bên phải, cùng kiểu với panel Chỉnh vùng. Các khối:
1. **Robot**: bề rộng, khoảng an toàn, dải độ cao (mặc định 0,6 / 0,05 / 0,05–1,2 m).
2. **Đoạn đo**: "Thêm đoạn" → bấm hai điểm trên scene → nhập mét thật. Danh sách hiện sai số ngay (sim |b−a| so với thật).
3. **Khe kiểm**: "Thêm khe" → bấm hai điểm trên sàn hai bên khe → chọn layout A/B, "Ngoài đời robot qua được?" Có/Không, bề rộng
   thật (tuỳ chọn).
4. **Vật cản chính**: checklist các vật của scene.
5. **Bố trí**: "Gắn revision hiện tại là A" / "là B" (hiện revision đã gắn và thời điểm). `tagged_at` do máy chủ đặt
   (client gửi giá trị bất kỳ, hiển thị giá trị máy chủ trả về); A và B phải khác revision (máy chủ trả 422).
6. **Khác**: nguồn dữ liệu, đưa vào benchmark, mốc làm tay (phút), khai báo L4 (ba ô + bằng chứng), ghi chú.
Lưu: nút "Lưu" gửi PUT với `expected_version`; 409 → thông báo "Người khác vừa sửa; tải lại" kèm nút, không mất nhập liệu đang có.
Trạng thái: đang tải, lỗi, chưa có quyền (chỉ xem).

## Steps
1. API client + panel chỉ form (robot, vật cản, bố trí, khác) + lưu/409. Commit.
2. Chọn hai điểm trên viewer cho đoạn đo và khe (tái dùng cơ chế đo của SplatInspection), đổi sang canonical, hiện marker. Commit.
3. Test: thêm đoạn với điểm giả → PUT đúng toạ độ canonical; 409 giữ nhập liệu; không quyền → chỉ đọc. Commit.

## Acceptance criteria
1. Toạ độ lưu là canonical; test đổi khung với một điểm biết trước.
2. Không gửi gì khi chưa bấm Lưu; rời panel khi có thay đổi chưa lưu → hỏi trong panel (không dùng `confirm()`).
3. Không đổi hành vi Chỉnh vùng, Walk, xác nhận mét.

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run tests/benchmark-panel.test.tsx tests/object-review.test.tsx && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`. Kiểm bằng mắt là việc chủ dự án.
