# T-060 report
- `lib/api/client.ts`: `fetchConditional` (gửi `If-None-Match`, 304 → `notModified`, trả ETag). `lib/api/studio.ts`: `getJobPipeline(jobId, etag, signal)`.
- `scene/pipeline.ts`: `pipelinePollInterval(view)` — 3 s khi máy làm, 15 s khi chờ người, 60 s khi không còn gì gấp; không bao giờ dừng.
- `ScenePage`: poll `/pipeline` thay `/progress`, giữ nguyên logic đồng bộ thử lại / chống lùi trạng thái; 304 → không setState; `PipelineContext` cho cả trang. Vòng poll hỏi ngay khi bắt đầu một lượt Thử lại (khoá theo `retryRound`).
- `useObjectifyState`: nhận `external` (trạng thái từ pipeline) + `onRefresh`; khi có thì không tự đọc / tự poll; giá trị trả về `useMemo`.
- `GaussianMembershipEditor`: bỏ `setInterval` 1,5 s, dùng `usePolling` 3 s.
- `useNow`: 5 s một nhịp; ProgressTab/NextAction chỉ chạy đồng hồ khi máy đang làm (không khi chờ người).
- Test: use-pipeline (6), use-now-clock (2); ux-scene-flow và operator-time-scene chuyển mock sang `getJobPipeline` (giữ kỳ vọng); gaussian-membership-editor thêm mock trạng thái và nhịp 3 s.
- Lệch plan: không tách hook `usePipeline` riêng (logic đồng bộ thử lại của ScenePage gắn chặt với vòng poll; tách ra rủi ro cao) — chức năng tương đương nằm trong ScenePage + `pipelinePollInterval`. Không viết test đếm request/phút; nhịp được khoá bằng test đơn vị. Chuông vẫn tự tải scene/gói/duyệt cho tới T-062.
- Bảng nhịp (sau): máy đang chạy 20 request/phút; chờ người 4/phút; xong việc 1/phút; mỗi lần không đổi trả 304 không thân.
