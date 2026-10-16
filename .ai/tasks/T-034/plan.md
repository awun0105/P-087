# T-034: Thẻ "Giá trị" + trang /benchmark + nút xuất

## Goal
Người xem thấy 5 metric của một scene ở đầu tab đánh giá, và bảng nhiều scene ở trang `/benchmark`; xuất CSV/Markdown.

## Context
§15.1. API T-032. Tab đánh giá hiện có: `features/studio/evaluation/EvaluationCard.tsx` (nhóm kỹ thuật, nút tải report.md).

## Files
- Tạo: `frontend/src/features/studio/value/ValueCard.tsx`, `frontend/src/app/(studio)/benchmark/page.tsx`,
  `frontend/src/features/studio/value/BenchmarkTable.tsx`
- Sửa: nơi render `EvaluationCard` (đặt `ValueCard` lên trên; nhóm kỹ thuật thu gọn mặc định với nhãn "Chi tiết kỹ thuật"),
  điều hướng Studio (thêm mục "Benchmark")
- Test: `frontend/tests/value-card.test.tsx`, `frontend/tests/benchmark-page.test.tsx`

## UI/UX
- **ValueCard**: hàng đầu là metric chính: "Người N phút · Máy M phút trên {GPU} · ~${cost}" (thiếu số thì "chưa đo được" kèm
  lý do). Bốn ô P1 can thiệp, P2 "khe khớp x/y · bỏ sót a · giả b", P3 "đổi→thử N phút · nhất quán Đạt/Không", P4 bậc kèm lý do
  chưa lên bậc tiếp. Mỗi số có nhãn nguồn: "đo" / "khai báo" / "chưa có". Nút "Mở Benchmark" (sang panel T-033) và "Tải CSV",
  "Tải Markdown" (link tới route T-032).
- **/benchmark**: ô tổng hợp (cùng các ô của sổ kết quả Playbook), bảng một dòng một scene (cột như CSV), lọc theo nguồn dữ liệu,
  nút tải CSV/Markdown của cả bộ. Trạng thái rỗng: "Chưa có scene nào được đưa vào benchmark. Bật 'Đưa vào benchmark' trong
  panel Benchmark của scene."

## Steps
1. API client + ValueCard + test các trạng thái (đủ số, thiếu số, bậc 0). Commit.
2. Đặt ValueCard trên EvaluationCard, thu gọn nhóm kỹ thuật. Test không vỡ test đánh giá cũ. Commit.
3. Trang /benchmark + điều hướng + test. Commit.

## Acceptance criteria
1. Số `unavailable` không bao giờ hiện là 0.
2. Nguồn "khai báo" phân biệt rõ với "đo".
3. Tải CSV/MD là link thật tới API (không tạo file phía client).

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run tests/value-card.test.tsx tests/benchmark-page.test.tsx <test đánh giá hiện có> && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`. Kiểm bằng mắt là việc chủ dự án.
