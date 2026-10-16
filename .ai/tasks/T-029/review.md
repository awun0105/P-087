# Review T-029

Verdict: ACCEPTED (Architect tự sửa 2 lỗi, commit `1dc1afda`)

Đọc `operator-clock.ts`, `useOperatorTime.ts`, `useWalkSession.ts`, `tracking-context.ts`, `lib/api/value.ts` (phần gửi lô) và
chỗ gắn trong `ScenePage.tsx`, `MetricSceneView.tsx`. Chạy operator-time, operator-time-scene, walk-session, value-api: 23 PASS;
typecheck, eslint sạch.

Đồng hồ đúng quy tắc: chỉ cộng khi có thao tác trong 60 s và tab hiện; mỗi nhịp tối đa 2 s; lô ≤ 300 s, `active ≤ wall`; cửa sổ kế
tiếp bắt đầu đúng lúc lô trước kết thúc nên không chồng; gửi tuần tự qua một hàng đợi promise nên thứ tự lô giữ nguyên cho luật
"không chồng" của máy chủ; `pagehide` + `visibilitychange` cùng bắn chỉ gửi một lô.

## Lỗi tìm ra khi audit và đã sửa
1. **Phiên Walk mất khi đóng tab.** Phiên chỉ gửi trong cleanup của effect, mà đóng tab thì React không unmount. Sửa: gửi thêm ở
   `pagehide` (keepalive), có cờ để chỉ gửi một lần. Test mới.
2. **Ánh xạ surface ngược.** `EvaluationCard` nằm ở tab `review` (`ReviewTab.tsx:99`) nhưng `review` bị gán `other`, `results`
   bị gán `evaluation`. Sửa: `review → evaluation`, `results → other`; test khoá ánh xạ.

## Trả lời điểm cần Architect
2. Tách trước/sau ready làm ở **tầng tổng hợp** (T-032 `hands_on` theo `ready_at`), không thêm trường vào API: đúng, đã có.
3. Ánh xạ surface: đã sửa (xem trên).
4. Walk chỉ đo ở tab Studio: chấp nhận.
5. Context thay vì prop, thêm `tracking-context.ts`: chấp nhận.
7. Đồng hồ máy khách lệch > 60 s → mọi lô bị 422 im lặng: chấp nhận cho Sprint 6, ghi vào T-035 (giới hạn đo).
