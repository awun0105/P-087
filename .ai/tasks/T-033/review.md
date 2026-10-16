# Review T-033

Verdict: CHANGES REQUESTED (3 sửa, kèm hướng dẫn chi tiết)

Audit: đọc trọn `value/BenchmarkPanel.tsx` (509 dòng), `value/benchmark-draft.ts`, `source-frame.ts` (`sourceToCanonical`),
`AuthProvider.useOptionalAuth`, phần gắn trong `ObjectReviewView.tsx` và `MetricSceneView.tsx`, `SplatInspection.onPointerDown`.
Chạy benchmark-panel + object-review: 73 PASS; typecheck sạch.

Đã kiểm, đúng: khung toạ độ. `MetricSceneView` cố định `sourceFrame = "z_up"` (dòng 222); `SplatInspection` trả điểm trong hệ
nguồn của splat môi trường (`sourceFromWorld`), mà splat môi trường của scene đã là canonical → `sourceToCanonical("z_up")` là
đồng nhất, đúng. Lưu có CAS, 409 giữ nhập liệu, rời panel khi còn thay đổi hỏi trong panel, `tagged_at` hiển thị giá trị máy chủ.

## Required changes

### 1. Thêm khe/đoạn lần hai lấy lại hai điểm cũ (lỗi thật, đã tái hiện bằng test)
`BenchmarkPanel.tsx` ~dòng 131–163 và `startPick` ~dòng 197. Sau lần chọn đầu, viewer vẫn giữ 2 điểm cũ. Bấm "Thêm khe":
`startPick` đặt `pending` rồi gọi `picker.start()`, nhưng `start()` xoá điểm **bất đồng bộ** (`setPoints([])` đi qua hàng đợi
history). Lần render ngay sau đó effect thấy `pending` và `picker.points.length >= 2` (vẫn là điểm cũ) → tạo khe mới bằng hai
điểm của đoạn trước, người dùng chưa kịp bấm điểm nào.

Sửa (đúng 4 chỗ):
```tsx
// import
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

// sau dòng `const [confirmClose, setConfirmClose] = useState(false);`
// Bộ điểm của viewer lúc bắt đầu chọn. `picker.start()` xoá điểm cũ bất đồng bộ, nên chỉ nhận bộ điểm MỚI so với bộ này.
const pickBaseline = useRef<BenchmarkPickerApi["points"] | null>(null);

// điều kiện đầu effect nhận điểm
if (!pending || !picker || picker.points.length < 2 || picker.points === pickBaseline.current) return;

// trong startPick, trước setPending(purpose)
pickBaseline.current = picker.points;
```
Cách này dựa vào việc `picker.points` có identity mới mỗi khi `inspectionState.points` đổi (`useMemo` trong `ObjectReviewView`
map lại mảng) — giữ nguyên tính chất đó.

Test thêm vào `tests/benchmark-panel.test.tsx` (Architect đã chạy: **đỏ** trên code hiện tại, **xanh** sau sửa):
```tsx
it("thêm khe ngay sau một đoạn: không lấy lại hai điểm cũ còn trên viewer, chờ hai điểm mới", async () => {
  const stale = fakePicker([[1, 2, 3], [4, 6, 3]]); // điểm của lần chọn trước, viewer chưa kịp xoá
  const view = await loaded({ picker: stale });
  fireEvent.click(screen.getByRole("button", { name: "Thêm khe" }));
  expect(stale.start).toHaveBeenCalledTimes(1);
  expect(screen.queryByLabelText("Tên khe g1")).toBeNull();

  view.rerender(element({ picker: fakePicker([]) })); // viewer đã xoá
  expect(screen.queryByLabelText("Tên khe g1")).toBeNull();
  view.rerender(element({ picker: fakePicker([[0, 0, 0], [0.8, 0, 0]]) }));
  await screen.findByLabelText("Tên khe g1");
});
```
Sau khi thêm `useRef`, nếu eslint báo dòng `eslint-disable-next-line react-hooks/set-state-in-effect` thừa thì giữ nguyên nếu
không có cảnh báo, chỉ bỏ khi eslint báo "Unused eslint-disable directive".

### 2. Quyền sửa lấy sai nguồn
`ObjectReviewView.tsx` ~dòng 304–305: `benchmarkEditable = auth !== null && canEdit(auth.me)`. `canEdit` chỉ nghĩa là "đã đăng
nhập" (`lib/api/auth.ts:97`). Guest xem job của người khác vẫn thấy nút "Benchmark" và form sửa được, rồi bấm Lưu nhận 403.
Máy chủ quyết theo quyền sửa job (`authorize_job_mutation`), nên client phải theo cùng nguồn đó.

Sửa: `ScenePage` đã có `canMutateJob` (từ `progress.capabilities.can_mutate`). Truyền xuống:
- `StudioTab` nhận prop `canMutateJob: boolean` và truyền cho `ObjectReviewView`;
- `ObjectReviewView` thêm prop `canMutateJob?: boolean` (mặc định `false`), và
  `const benchmarkEditable = canMutateJob;` (bỏ `useOptionalAuth`/`canEdit` nếu không còn dùng; nếu bỏ thì gỡ luôn
  `useOptionalAuth` khỏi `AuthProvider.tsx` khi không còn nơi nào gọi).
- Nút "Benchmark" vẫn hiện cho người chỉ xem nếu muốn họ đọc được ground truth: hiện nút khi có scene, nhưng `canEdit` của panel
  = `canMutateJob`. (Plan nói "chỉ khi có quyền sửa" cho nút mở; chọn một và ghi vào report — Architect chấp nhận cả hai.)
Test: render `ObjectReviewView` với `canMutateJob={false}` → panel (nếu mở được) ở chế độ chỉ xem, không có nút Lưu hoạt động;
`canMutateJob={true}` → sửa được.

### 3. Mốc làm tay nhập sai bị bỏ im lặng
`benchmark-draft.ts` `parseMinutes`: chuỗi không hợp lệ hoặc âm trả `null`, và `truthFromDraft` gửi `null` ("chưa khai báo")
mà không báo. Người dùng gõ "-5" hoặc "12,5" thấy ô vẫn có chữ nhưng giá trị bị mất khi lưu.

Sửa trong `draftProblems` (`BenchmarkPanel.tsx`):
```ts
if (draft.manualBaselineMinutes.trim() !== "" && parseMinutes(draft.manualBaselineMinutes) === null) {
  problems.push("Mốc làm tay phải là số phút ≥ 0 (dùng dấu chấm cho phần thập phân)");
}
```
(import `parseMinutes` từ `benchmark-draft`). Test: nhập "-5" → hiện lỗi, nút Lưu bị khoá; nhập "12.5" → Lưu gửi `12.5`.

## Suggestions (không chặn)
- `SplatInspection` dùng `Picker` trên cả `app.scene`, nên bấm trúng collider/vỏ/box của lớp phủ sẽ lấy điểm trên lớp phủ, không
  phải bề mặt scene. Cân nhắc tắt lớp phủ (collider, vỏ, box) trong lúc chọn điểm Benchmark.
- Nút "Bỏ chọn {id}" hiện id thô; vật đã mất khỏi scene nên không còn tên — có thể ghi "vật đã xoá ({id})".

## Sau khi sửa
Chạy: `./node_modules/.bin/vitest run tests/benchmark-panel.test.tsx tests/object-review.test.tsx <test StudioTab nếu có>`,
`npm run typecheck`, eslint các file đã sửa. Thêm mục "Round 2" vào report, đặt `implemented`.
