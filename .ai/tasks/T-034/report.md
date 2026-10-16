# Report T-034: Thẻ "Giá trị" + trang /benchmark + nút xuất

## Done
- **Step 1 (API client + ValueCard):** `lib/api/value.ts` có kiểu và hàm gọi `value-metrics`, benchmark, và URL tải thật tới API.
  `features/studio/value/ValueCard.tsx`: hàng đầu là Người / Máy trên GPU / Chi phí; bốn ô P1 can thiệp, P2, P3, P4.
  Mỗi số có nhãn nguồn: "đo", "khai báo", "chưa có". **P2 luôn ghi "đo, so với số thước"**, không dùng chữ "khai báo".
  **Bậc L4 hiện nhãn "khai báo"**; L0–L3 ghi "đo". Số thiếu dữ liệu hiện "chưa đo được" kèm lý do.
- **Step 2 (đặt thẻ, thu gọn kỹ thuật):** `features/studio/scene/ReviewTab.tsx` đặt `ValueCard` trên `EvaluationCard`;
  nhóm kỹ thuật bọc trong `<details>` thu gọn mặc định, nhãn "Chi tiết kỹ thuật". `EvaluationCard` không đổi.
- **Step 3 (trang /benchmark + điều hướng):** `app/(studio)/benchmark/page.tsx` → `features/studio/value/BenchmarkPage.tsx`
  (ô tổng hợp, lọc theo nguồn dữ liệu, trạng thái rỗng, nút tải CSV/Markdown). `BenchmarkTable.tsx`: một dòng một scene,
  đúng thứ tự cột CSV. Mục "Benchmark" thêm vào sidebar (`AppShell.tsx`) và breadcrumb (`Breadcrumbs.tsx`).

## Files changed
- `frontend/src/lib/api/value.ts` (thêm phần bảng metric)
- `frontend/src/features/studio/value/ValueCard.tsx` (mới)
- `frontend/src/features/studio/value/BenchmarkPage.tsx` (mới)
- `frontend/src/features/studio/value/BenchmarkTable.tsx` (mới)
- `frontend/src/app/(studio)/benchmark/page.tsx` (mới)
- `frontend/src/features/studio/scene/ReviewTab.tsx` (đặt thẻ, thu gọn kỹ thuật)
- `frontend/src/features/shell/AppShell.tsx`, `frontend/src/features/shell/Breadcrumbs.tsx` (điều hướng)
- `frontend/tests/value-card.test.tsx` (mới), `frontend/tests/benchmark-page.test.tsx` (mới)

Không sửa `ObjectReviewView.tsx` và `StudioTab.tsx` (theo yêu cầu, đang do agent T-033 sửa).

## Tests
```
cd frontend && ./node_modules/.bin/vitest run tests/value-card.test.tsx tests/benchmark-page.test.tsx tests/evaluation-card.test.tsx
→ 27 passed (evaluation-card, review-panel, value-card 7); benchmark-page 5 passed

tests/ux-scene-flow, operator-time-scene, floor-fit-diagnostics, unified-input-flow (các màn có ReviewTab)  → 57 passed
tests/studio-navigation, ux-navigation-guard, shell-glow (điều hướng)                                    → 33 passed
npm run typecheck                                                                                       → không lỗi
eslint: value.ts, ValueCard.tsx, BenchmarkPage.tsx, BenchmarkTable.tsx, page.tsx, AppShell.tsx, Breadcrumbs.tsx, ReviewTab.tsx,
        test mới → 0 error (1 warning đã sửa: import Badge thừa)
```
Lưu ý: lệnh trong plan ghi `<test đánh giá hiện có>`; tôi chạy `evaluation-card.test.tsx` và các test màn có `ReviewTab`.

## Commits
- `2f85a3f1` Show the value card with the five metrics and their source labels (Step 1)
- `4c04622c` Place the value card above the evaluation card and fold technical details (Step 2)
- `b447cf93` Add the benchmark page with the scene table, source filter and CSV/Markdown downloads (Step 3, trang)
- `d0ca317c` Link the benchmark page from the studio sidebar and breadcrumbs (Step 3, điều hướng)

## Acceptance
1. **Số `unavailable` không bao giờ hiện là 0.** Có test: số thiếu hiện "chưa đo được" và lý do; không có "0 phút".
2. **Nguồn "khai báo" phân biệt với "đo".** Có test nhãn nguồn; P2 không bao giờ là "khai báo".
3. **Tải CSV/MD là link thật tới API.** `href` = `/api/v1/jobs/{id}/value-metrics.csv` (và `.md`, `/benchmark.csv`, `/benchmark.md`); không tạo file phía client.

## Deviations from plan
1. **Nút "Mở Benchmark" không mở thẳng panel T-033.** Panel nằm trong `ObjectReviewView.tsx`, mà bạn yêu cầu không sửa. Nút trỏ tới
   `/scenes/{id}?tab=studio`; người dùng bấm nút "Benchmark" ở đó. Nếu muốn mở thẳng, cần một query/state trong `ObjectReviewView`
   (file đang do T-033 sửa), làm sau khi T-033 xong.
2. **Thu gọn kỹ thuật ở `ReviewTab`, không ở `EvaluationCard`.** Plan ghi "nơi render EvaluationCard". Thu gọn bằng `<details>` bọc bên
   ngoài, nên `EvaluationCard` và test cũ không đổi.
3. **Nhãn bậc L4 "khai báo" hiện trên dòng P4** (thẻ và bảng), theo yêu cầu. Bậc L0–L3 ghi "đo".
4. **Test dùng `fireEvent` thay vì `@testing-library/user-event`**: thư viện này không có trong dự án.
5. **Lọc nguồn dữ liệu ở `BenchmarkPage`** chỉ lọc phía client trên dữ liệu đã tải (không có tham số API).

## Known issues / TODO
- Chưa kiểm bằng mắt bố cục thẻ và trang (việc của chủ dự án, theo quy ước).
- `ValueCard` và `ReviewTab` tải dữ liệu khi mở tab; `EvaluationCard` vẫn được mount khi thẻ thu gọn (vẫn tải dữ liệu như trước).
- `/benchmark` tải toàn bộ benchmark mỗi lần mở; hiệu năng phụ thuộc API T-032 (đã ghi trong report T-032).
