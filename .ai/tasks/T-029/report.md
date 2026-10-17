# Report T-029

## Done
- **Step 1 — client + đồng hồ + hook** (`1917411c`, `383cce71`):
  - `frontend/src/lib/api/value.ts`: `postOperatorTime`, `postWalkSession`. Các lô gửi tuần tự qua một hàng đợi chung, không bao giờ reject, thử lại đúng một lần khi lỗi mạng hoặc 5xx, không thử lại 4xx.
  - `features/studio/value/operator-clock.ts`: đồng hồ thuần. Luật rảnh 60 s, nhịp tối đa 2 s, cửa sổ 30 s, lô kế tiếp bắt đầu đúng tại `ended_at` lô trước, không vượt 300 s, `active_seconds` không vượt thời lượng lô.
  - `features/studio/value/useOperatorTime.ts`: hook. Đóng lô khi tab ẩn, đổi surface, `pagehide`, unmount. Gửi bằng `keepalive`. `session_key` là UUID theo mỗi lần mount. Chỉ tính `pointermove` khi có nút đang giữ.
- **Step 2 — gắn vào ScenePage** (`89ba5316`): `OPERATOR_SURFACE` ánh xạ tab → surface (`progress`→progress, `studio`→studio, `review`→other, `results`→evaluation). Hook bật khi `canMutateJob`.
- **Step 3 — Walk** (`11c5d324`): `useWalkSession` ghi phiên khi Walk bật rồi tắt, khi đổi `sceneRevision`, khi rời tab Studio hoặc rời trang. `outcome = completed` nếu ≥ 5 s, ngược lại `aborted`. Context `ValueTrackingContext` do `ScenePage` cấp, chỉ bật khi `canMutateJob` và đang ở tab Studio.

## Files changed
- `frontend/src/lib/api/value.ts`: client gửi lô (hàm của tôi nằm trong commit `1917411c`; T-030 đã thêm phần benchmark-truth vào cùng file ở `ab8f97ab`).
- `frontend/src/features/studio/value/operator-clock.ts`: đồng hồ đếm thuần.
- `frontend/src/features/studio/value/useOperatorTime.ts`: hook đếm phút công người.
- `frontend/src/features/studio/value/tracking-context.ts`: context bật/tắt đo cho trang scene (file thêm ngoài plan).
- `frontend/src/features/studio/value/useWalkSession.ts`: hook phiên Walk.
- `frontend/src/features/studio/ScenePage.tsx`: gắn `useOperatorTime`, cấp `ValueTrackingContext`.
- `frontend/src/features/studio/MetricSceneView.tsx`: một dòng import + `useWalkSession({ walking, sceneRevision })`.
- `frontend/tests/operator-time.test.ts`, `frontend/tests/value-api.test.ts`, `frontend/tests/operator-time-scene.test.tsx`, `frontend/tests/walk-session.test.tsx`.

## Tests
Lệnh "Tests required" của plan và các test liên quan (kết quả thật):
- `./node_modules/.bin/vitest run tests/operator-time.test.ts tests/value-api.test.ts tests/operator-time-scene.test.tsx tests/walk-session.test.tsx tests/ux-scene-flow.test.tsx tests/object-review.test.tsx tests/region-editor.test.tsx` → **7 file, 162 test, 162 pass, 0 fail**. Trong đó 21 test mới: `operator-time` 10, `value-api` 4, `operator-time-scene` 2, `walk-session` 5. `ux-scene-flow`, `object-review`, `region-editor` là hồi quy cho `ScenePage` và `MetricSceneView`.
- `npm run typecheck` → exit 0.
- `eslint` trên các file đã sửa/thêm → exit 0, không có cảnh báo.
- Không chạy full suite (README mục 4).

## Deviations from plan
1. **Context thay vì truyền prop**: `MetricSceneView` được dùng bởi `ObjectReviewView`, mà T-033 đang sửa nên tôi không được sửa file này. Trang scene cấp trạng thái qua context, nên không cần đổi chữ ký của view.
2. **Walk chỉ đo khi đang ở tab Studio** (plan không nói). Lý do: tab Studio vẫn được giữ mount khi người dùng sang tab khác, nên nếu không gate thì phiên Walk đang chạy sẽ tiếp tục được tính.
3. **Ánh xạ surface**: plan không nói `review`→`other` và `results`→`evaluation`. Đây là lựa chọn của tôi, cần Architect xác nhận.
4. **Thêm `tracking-context.ts`** (file không có trong plan).
5. **Phụ thuộc T-027**: T-027 vẫn ở `implemented`, chưa `accepted`, nên README mục 1 chưa cho phép làm T-029. Làm theo yêu cầu trực tiếp; cần Architect xác nhận.

## Known issues / TODO
- **Chưa tách theo giai đoạn** (§15.3 quy tắc 1: trước/sau khi `object_geometry = ready`). Route ở T-027 không nhận trường phase nên frontend không có gì để gửi. Cần Architect quyết định: thêm trường `phase` vào API hay tách ở tầng tổng hợp.
- **Không có test ở mức component cho `MetricSceneView`** (jsdom không dựng được WebGL). Phần Walk được kiểm ở mức hook, còn việc gắn hook vào `MetricSceneView` chỉ kiểm bằng typecheck và các test hồi quy hiện có.
- **Đồng hồ máy khách**: nếu đồng hồ trình duyệt nhanh hơn máy chủ hơn 60 s, máy chủ sẽ từ chối mọi lô với 422 mà không có thông báo nào cho người dùng. Chưa có cơ chế đồng bộ thời gian.
- **Mẫu video**: trang mẫu không dùng `ScenePage` (blast radius cho thấy chỉ `app/(studio)/scenes/[jobId]/page.tsx` gọi nó), nên không có context bật và không gửi gì. Chưa mở trang mẫu trong trình duyệt để xác nhận.
- Hai file chưa commit của agent khác (`frontend/src/features/studio/value/benchmark-draft.ts` và `frontend/tests/benchmark-panel.test.tsx`) và phần `MetricSceneView.tsx` do T-033 sửa vẫn nằm trong working tree. Tôi không commit chúng; commit `11c5d324` chỉ có hai dòng của tôi trong `MetricSceneView.tsx`.
