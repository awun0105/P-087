# Review T-016

Verdict: CHANGES REQUESTED

Review **code** (không chỉ diff): đọc trọn `RegionEditor.tsx`, `region-session.ts`, `useRegionPreview.ts`, phần sửa `MetricSceneView.tsx`,
`ObjectReviewView.tsx`, `useObjectify.ts`, và đối chiếu `src/services/scene/editing/region_box.py`.

## Đạt
- Debounce 250 ms + abort request cũ; preview chỉ hiện khi khoá (box + claim + revision + checksum) khớp: đúng.
- Không gọi preview khi `validateBoxes` lỗi; Apply chỉ bật khi có preview khớp: đúng.
- Bàn giao T-015: nối `gotoPose`, không `setBoxes` khi đang kéo (`isGesturing`), tạo lại overlay khi entity vật đổi, thông báo khi vật chưa
  có trên viewport: đúng. Esc bắt ở pha capture để không đóng panel khi đang kéo: đúng.
- 201 (Draft) tải lại scene, 202 (Ready) gọi `refresh()` để hiện tiến độ: đúng.
- Thêm `isGesturing()` vào `region-overlay.ts`, `refresh()` vào `useObjectify.ts`, câu "sẽ lấy về vật này": chấp nhận.

## Lỗi phải sửa
1. **Nút "Chỉnh vùng" bị ẩn trên scene Draft.** `ObjectReviewView.tsx:1007` vẫn giữ điều kiện cũ
   `scene.environment.object_aware_collision_ref && …`. Draft (T-005) **không có** `object_aware_collision_ref`, nên tính năng chính không mở
   được đúng lúc cần. Test qua vì fixture có ref đó (không giống Draft thật).
   Sửa: hiện nhóm nút khi scene có khóa `object_geometry` + `membership` + vật thuộc membership, **không** phụ thuộc `object_aware_collision_ref`;
   scene cũ (không có khóa) giữ điều kiện cũ cho nút Brush/Lasso.
   Test: fixture Draft thật (provenance `object_geometry: "awaiting_review"`, có `membership`, **không** có `object_aware_collision_ref`,
   vật `collider: null`) → nút "Chỉnh vùng" hiện và mở được panel.
2. **Brush/Lasso trên Draft luôn thất bại.** Nút "Chỉnh chi tiết (Brush/Lasso)" mở `GaussianMembershipEditor`, mà Apply của nó đi qua
   `membership/regenerate` (T-011 yêu cầu scene Ready). Khi `object_geometry == "awaiting_review"`: disable nút, tooltip
   "Dùng Chỉnh vùng khi đang duyệt; Brush/Lasso dùng được sau khi Tạo mesh". Test cho cả Draft (disabled) và Ready (enabled).
3. **Dòng "Lấy luôn" biến mất ngay sau khi tick.** Server bỏ vật đã claim khỏi `overlaps` (`region_box.py:123`) và đưa vào `claimed`.
   Panel chỉ vẽ từ `overlaps`, nên sau preview kế tiếp dòng đó biến mất và không bỏ tick được. Agent nêu "claim cũ" nhưng lỗi xảy ra ngay cả
   khi box không đổi.
   Sửa: danh sách dòng = hợp của `preview.overlaps` (count > 0), `preview.claimed`, và `session.claimFrom`.
   - Vật trong `claimed`: "Box lấy {n} Gaussian từ {tên} — sẽ lấy về vật này", checkbox đang tick.
   - Vật trong `claimFrom` nhưng không có trong `overlaps`/`claimed`: "{tên} không còn trong box", checkbox tick để bỏ được.
   Test: tick → preview trả `overlaps: {}`, `claimed: {b: 12}` → dòng vẫn hiện, đang tick; bỏ tick → command sau không có `b`.

## Quyết định cho câu hỏi
- **Kẹp sàn phía client: không làm.** Server bảo vệ hàng sàn và trả `protected_floor_count`; box xuống dưới sàn không lấy thêm gì. Đưa độ cao
  sàn object-local xuống client tốn công mà không đổi kết quả. `architecture.md` §9 đã sửa câu "đáy tự bám sàn".
- **Claim cũ:** xử lý theo Required change 3 (hiện để bỏ tick), không tự xoá âm thầm.
- **Kiểm bằng mắt và đường Ready thật:** để chủ dự án kiểm khi chạy scene mới; đường 202 phía backend đã có test ở T-011.

## Lệnh kiểm tra
```
cd frontend
./node_modules/.bin/vitest run tests/region-editor.test.tsx tests/object-review.test.tsx tests/region-box-model.test.ts
npm run typecheck && ./node_modules/.bin/eslint <các file đã sửa>
```
Thêm "Round 2" vào report, đặt `implemented`.
