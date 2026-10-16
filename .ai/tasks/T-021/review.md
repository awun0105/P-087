# Review T-021

Verdict: ACCEPTED

Đọc diff `objectify_queue._object_geometry`, `geometryReviewStep`, `objectifyStageOverride`, `stages.ts`, `PipelineTimeline.tsx`,
`ProgressTab.tsx`, `NextAction.tsx`, `sceneStatus.ts`, `ScenePage.tsx`. Chạy lại `geometry-review-{step,row,bell,banner}` (PASS).

## Acceptance criteria
1. Pass. Hàng ảo chèn ngay sau `ST-OBJECT-EXTRACT`, chỉ khi `object_geometry` khác null và bước tách đã xong; Draft → `waiting` + "Mở để duyệt".
2. Pass. Việc dựng (`geometry/region/membership`) → hàng mới `running` + nhãn phase; hàng "Tách vật thể" chỉ chạy lại với `objectify/boxes`.
3. Pass. Build lỗi cùng revision → `failed` + lý do + "Mở để sửa vùng" / "Thử lại Tạo mesh" (`mode=geometry`, revision hiện tại).
4. Pass. Ready → `succeeded`; scene thiếu khoá → không có hàng.
5. Pass. Nhánh Draft của chuông đứng trước mọi nhánh gói/duyệt/phát hành.
6. Pass. Đầu trang: "Đang tạo mesh" / "Chờ duyệt vật".
7. Pass. `UI-GEOMETRY-REVIEW` chỉ ở `stages.ts`; hàng ảo không có link inspect; mirror PASS.
8. Pass. Nút chỉ khi `canAccept`/`onOpenStudio` (undefined khi không có quyền).

## Suggestions (không chặn)
1. Đầu trang khi Tạo mesh lỗi đang ghi "Chờ duyệt vật"; "Tạo mesh lỗi" (tone rust) rõ hơn.
2. `rebuildFailed` (Ready) không kiểm revision: một lần sửa khác tạo revision mới (vd. Move) vẫn còn ghi chú lỗi cũ tới yêu cầu dựng tiếp theo.
3. Danh sách scene ở trang tổng quan (`sceneSummaryStatus`) vẫn ghi "Hoàn tất" cho scene Draft — ngoài phạm vi, cần trường Draft trong SceneSummary.
