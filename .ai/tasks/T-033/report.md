# Report T-033

## Done

- **Step 1 — client và panel dạng form** (`ab8f97ab`):
  - `frontend/src/lib/api/value.ts`: thêm kiểu và hai hàm `getBenchmarkTruth`, `putBenchmarkTruth` cho route T-030.
    File này do T-029 tạo; chỉ thêm vào cuối, import `apiFetch` ở đầu. Diff không xoá dòng nào.
  - `features/studio/value/benchmark-draft.ts`: nháp form, đổi qua lại với `BenchmarkTruth`, kiểm dirty, vật cản thiếu,
    id tiếp theo, kiểm robot theo biên của máy chủ.
  - `features/studio/value/BenchmarkPanel.tsx`: các khối Robot, Đoạn đo, Khe kiểm, Vật cản chính, Bố trí, Khác (L4, ghi chú).
    Lưu gửi `expected_version`; 409 hiện thông báo kèm nút "Tải lại" và giữ nhập liệu; 422 hiện chi tiết của máy chủ;
    không có quyền ghi thì chỉ xem; đóng khi có thay đổi chưa lưu thì hỏi trong panel (không dùng `confirm()`).
- **Step 2 — chọn hai điểm trên viewer** (`9b7d338d`):
  - `MetricSceneView`: prop tuỳ chọn `inspection` truyền xuống `PlayCanvasScene` (`enableInspection`, `onInspectionReady`,
    `onInspectionState`).
  - `ObjectReviewView`: nối `inspection` vào `MetricSceneView`; nút "Benchmark" (chỉ khi có quyền ghi) mở panel;
    `BenchmarkPanel` nhận `picker` để bắt đầu/dừng chọn và đọc hai điểm; điểm đưa vào nháp qua `sourceToCanonical("z_up", …)`.
  - `viewer/source-frame.ts`: thêm `displayToZUp` (nghịch đảo của `toDisplay` cho `z_up`) và `sourceToCanonical`.
  - `AuthProvider.tsx`: thêm `useOptionalAuth` (trả null ngoài provider, để `ObjectReviewView` tự coi là chỉ xem).
- **Step 3 — test** (`54af73f4`): `frontend/tests/benchmark-panel.test.tsx` và sửa `nextId` (id nhỏ nhất còn trống; test bắt
  được lỗi cũ `d4` thay vì `d2`).

## Files changed

- `frontend/src/lib/api/value.ts`: client truth (thêm cuối file; T-029 giữ nguyên).
- `frontend/src/features/studio/value/benchmark-draft.ts`: mới, logic nháp thuần.
- `frontend/src/features/studio/value/BenchmarkPanel.tsx`: mới, panel.
- `frontend/src/features/studio/ObjectReviewView.tsx`: nút Benchmark, panel, nối inspection và picker.
- `frontend/src/features/studio/MetricSceneView.tsx`: prop `inspection`.
- `frontend/src/features/studio/AuthProvider.tsx`: `useOptionalAuth`.
- `frontend/src/features/viewer/source-frame.ts`: `displayToZUp`, `sourceToCanonical`.
- `frontend/tests/benchmark-panel.test.tsx`: mới, 11 test.

Không sửa `ScenePage.tsx`.

## Tests (kết quả thật)

- `./node_modules/.bin/vitest run tests/benchmark-panel.test.tsx tests/object-review.test.tsx`: **72 passed, 0 failed**
  (benchmark-panel 11, object-review 61). Lần đầu có 1 fail (`nextId`), đã sửa và chạy lại.
- `npx tsc --noEmit`: **exit 0**. Lần chạy trước có lỗi trong `tests/operator-time-scene.test.tsx` (file của T-029), lần này sạch.
- `eslint` trên các file đã sửa và test: **exit 0**.
- Không chạy full suite (theo hướng dẫn).

## Acceptance criteria

1. Toạ độ lưu là canonical; test đổi khung với điểm `[1,2,3]`: `toDisplay("z_up")` → `[1,3,-2]` → `displayToZUp` → `[1,2,3]`.
   Test PUT kiểm `a`/`b` của đoạn đo đúng bằng điểm đã chọn.
2. Không gửi gì khi chưa bấm Lưu (không có lệnh ghi nào tự chạy). Đóng khi dirty: hỏi trong panel, có test.
3. Không đổi hành vi Chỉnh vùng, Walk, xác nhận mét: xem "Lệch so với plan" bên dưới về việc bật inspection.

## Deviations from plan

1. **Bật inspection ngay khi mount `ObjectReviewView`, không bật theo lúc mở panel.** `PlayCanvasScene` có `enableInspection`
   trong deps của effect dựng viewer, nên đổi cờ này sẽ dựng lại toàn bộ viewer. `SplatInspection` khi không chọn điểm thì
   các handler con trỏ đều return sớm (kiểm `measuring`), nhưng vẫn tạo một `Picker` và một hook `prerender`. Chi phí này
   xuất hiện trong mọi phiên Studio có scene hệ mét, kể cả khi người dùng không mở Benchmark.
2. **Quyền ghi lấy qua `useOptionalAuth` (thêm vào `AuthProvider.tsx`)**, không qua prop từ `StudioTab`/`ScenePage`, để
   không đổi chữ ký các màn hình khác và không cần sửa `ScenePage.tsx`.
3. **Robot mặc định được gửi khi lưu** nếu scene chưa có robot: nháp dùng 0,6 / 0,05 / 0,05 / 1,2 nên PUT luôn có `robot`.
4. **409 "Tải lại" chỉ cập nhật phiên bản và bản đã lưu, giữ nhập liệu.** Lưu sau đó ghi đè bản trên máy chủ. Đây là cách
   hiểu "không mất nhập liệu đang có" trong plan; nếu chủ dự án muốn tải bản máy chủ thì cần thêm nút khác.
5. **`value.ts` bị ghi đè một lần rồi khôi phục.** Lần ghi đầu tôi dùng công cụ ghi toàn file và làm mất nội dung T-029
   đang có trên đĩa; ngay sau đó tôi khôi phục đúng bản commit `1917411c` và thêm phần truth vào cuối (diff 0 dòng xoá).
   Nếu T-029 có chỉnh sửa chưa commit trong khoảng giữa lúc họ commit và lúc tôi ghi, phần đó đã mất; nên T-029 kiểm
   lại file của họ.
6. **`eslint-disable-next-line react-hooks/set-state-in-effect`** ở effect nhận cặp điểm từ viewer (hệ bên ngoài React).
   Repo đã có một chỗ dùng cùng cách.

## Chưa kiểm được (cần chủ dự án kiểm bằng mắt)

- **Khung toạ độ khi chọn trên viewer.** Điểm lấy từ `sourceFromWorld` (hệ của splat) và `MetricSceneView` dùng khung
  `z_up`, nên coi hệ nguồn là canonical. Đây là suy luận từ code (`PlayCanvasScene` áp `DISPLAY_EULER` lên entity),
  chưa chạy trong viewer thật. Nếu sai, mọi toạ độ đoạn đo và khe sẽ lệch.
- **Bố cục.** Nút "Benchmark" nằm góc dưới phải; panel nằm góc trên phải (`z-30`), có thể che Inspector bên phải.
- **Hiệu năng và hành vi Chỉnh vùng/Walk** khi inspection luôn bật (xem deviation 1).

## Việc còn dở

- Không có. Step 1–3 đã xong, nhưng phần viewer chỉ được kiểm bằng test props, chưa có test chạy viewer thật.

## Câu hỏi cho Architect

Không có câu hỏi chặn. Có một quyết định nên được xác nhận: deviation 4 (409 chỉ tải lại bản đã lưu, giữ nhập liệu).

## Round 2

Đã làm theo `review.md`, mục "Required changes" (3 mục), và xử lý ghi chú về nút/quyền.

### 1. Khe/đoạn lần hai lấy lại hai điểm cũ — đã sửa, có test đỏ/xanh

- `BenchmarkPanel.tsx`: thêm `pickBaseline` (ref) lưu `picker.points` tại lúc `startPick`. Effect nhận điểm chỉ khi
  `picker.points` khác bộ đó. Bỏ dòng `eslint-disable-next-line react-hooks/set-state-in-effect` vì eslint báo
  "Unused eslint-disable directive" (đúng hướng dẫn review).
- Test mới: "thêm khe ngay sau một đoạn: không lấy lại hai điểm cũ còn trên viewer, chờ hai điểm mới".
- Kiểm chứng: bỏ điều kiện so sánh bộ điểm thì test này **đỏ** (`× … không lấy lại hai điểm cũ`); khôi phục thì xanh.

### 2. Quyền sửa lấy từ nguồn của máy chủ — đã sửa

- Nguồn: `ScenePage` đã tính `canMutateJob = resourceCapabilityAllowed(me, progress.capabilities.can_mutate)` và truyền
  `canMutate` xuống `StudioTab` (đã có sẵn). `StudioTab` chỉ render `ObjectReviewView` khi `sceneReady`, nên prop được
  truyền thêm vào đây: `<ObjectReviewView canMutateJob={canMutate} …/>`. Không sửa `ScenePage.tsx`.
- `ObjectReviewView`: prop mới `canMutateJob?: boolean` (mặc định `false`); `benchmarkEditable = canMutateJob`.
  Bỏ `useOptionalAuth`/`canEdit` khỏi `ObjectReviewView`; gỡ `useOptionalAuth` khỏi `AuthProvider.tsx` vì không còn nơi gọi.
- Lựa chọn về nút (review cho chọn một): nút **"Benchmark" hiện với mọi scene**; panel nhận `canEdit = canMutateJob`, nên
  người không có quyền sửa job mở được panel ở chế độ chỉ đọc (ô khoá, không có nút Lưu hoạt động). Ghi chú: `StudioTab`
  vẫn chặn cả tab khi `canMutate` false, nên trên đường đi thực tế người không có quyền hiện không tới được panel; test
  kiểm chế độ chỉ đọc ở mức `ObjectReviewView`.
- Test mới trong `tests/object-review.test.tsx` (describe "ObjectReviewView Benchmark theo quyền sửa job (T-033)"):
  - `canMutateJob={false}`: ô "Bề rộng (m)" bị khoá, nút Lưu bị khoá, có thông báo "chỉ có quyền xem".
  - `canMutateJob` (true): ô sửa được, đổi giá trị thì Lưu bật.

### 3. Mốc làm tay nhập sai bị bỏ im lặng — đã sửa, có test

- `draftProblems` thêm kiểm tra: `manualBaselineMinutes` không rỗng mà `parseMinutes` trả null → báo
  "Mốc làm tay phải là số phút ≥ 0 (dùng dấu chấm cho phần thập phân)", nút Lưu bị khoá.
- Test mới: nhập "-5" → hiện lỗi, Lưu khoá; nhập "12.5" → PUT gửi `manual_baseline_minutes: 12.5`.

### Kết quả kiểm (lệnh thật)

- `vitest run tests/benchmark-panel.test.tsx tests/object-review.test.tsx`: **76 passed, 0 failed** (benchmark-panel 13,
  object-review 63).
- `vitest run tests/studio-ownership.test.tsx tests/ux-scene-flow.test.tsx tests/operator-time-scene.test.tsx`:
  **25 passed, 0 failed** (các file dùng `StudioTab`/`ObjectReviewView` trên đường đi này).
- `npx tsc --noEmit`: **exit 0**.
- `eslint` trên `value/`, `ObjectReviewView.tsx`, `StudioTab.tsx`, `AuthProvider.tsx` và hai file test: **exit 0**.

### Commit (Round 2)

- `02ce031d` Ignore stale picked points when adding a second benchmark item (mục 1 và 3, kèm test)
- `10880451` Take benchmark edit permission from the job's mutate capability (mục 2, kèm test)

### Chưa làm (không chặn, từ phần Suggestions)

- Chưa tắt lớp phủ collider/vỏ/box trong lúc chọn điểm Benchmark (`Picker` đang trên cả `app.scene`).
- Chưa đổi nhãn "Bỏ chọn {id}" thành "vật đã xoá ({id})".
- Ghi chú: `frontend/src/lib/api/value.ts` đang có thay đổi chưa commit không do tôi (có `ValueCard.tsx` mới của
  người khác); tôi không đụng vào.
