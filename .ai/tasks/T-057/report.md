# T-057 report
- `objectify_queue`: `ObjectifyPhase` (queued, observations, collider_and_background, shell, objectgs, quality, collider, environment, publish, done); `_Record.phase`/`ObjectifyState.phase` có kiểu, giá trị lạ đọc thành None.
- Xoá pha khi lượt kết thúc `failed`/`cancelled` (`_finish`, `recover_interrupted`); xếp lại chờ tài nguyên đặt `phase="queued"`.
- Mốc `scene_operation`, run_id `<mode>:<operation_id>`: `queue` (requested_at → lúc chạy), `operation`, từng pha (pha trước kết thúc khi pha sau bắt đầu); kết thúc lượt ghi `operation` + đóng mốc mở theo kết quả. Mốc chỉ ghi khi lượt đã qua cổng tài nguyên (không ghi lúc xếp lại chờ).
- Frontend: `OBJECTIFY_PHASES`, nhãn tiếng Việt cho mọi pha.
- Test: 10 test giá trị pha cũ + 1 pha lạ, `test_geometry_operation_records_phase_marks`, `test_failed_operation_closes_marks_and_clears_phase`, frontend `geometry-phase-label`.
- Lệch plan: test membership dùng pha giả `surface_quality` → đổi sang pha thật `quality`. Kiểu `phase` ở `lib/api/studio.ts` giữ `string | null` (chịu được API cũ); nhãn dùng bảng mới.
- Tương thích: không đổi schema DB; worker image cũ ghi đúng các pha trong danh sách, API mới đọc được.
