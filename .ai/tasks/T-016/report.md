# T-016: Region Editor panel — báo cáo

**Trạng thái:** implemented. Không có câu hỏi thiết kế chặn việc giao T-016. Các điểm ở mục "Vấn đề còn lại" cần chủ dự án quyết hoặc kiểm tra bằng mắt.

**Branch:** `mvp-pipeline-v2`. Không tạo branch, không push, không tạo PR.

## Đã làm

Thực hiện theo các bước 1–6 của `plan.md`, mỗi bước một commit.

1. **API client** (`frontend/src/lib/api/studio.ts`): `RegionPreview`, `previewObjectRegion(jobId, objectId, command, signal?)`, `applyObjectRegion(...)` trả `SceneEditResponse | ObjectifyState`, `isSceneEditResponse` (phân biệt 201 và 202 theo khoá `scene` + `scene_revision`).
2. **Xem trước có debounce** (`frontend/src/features/studio/region/useRegionPreview.ts`): chờ 250 ms sau thay đổi cuối, huỷ yêu cầu bị thay thế, `preview` chỉ trả kết quả đúng khoá hiện tại. Khoá gồm box, claim, revision scene và checksum membership.
3. **Panel và bàn giao T-015**:
   - `region-session.ts` (phiên thuần: box, chọn, claim; quy tắc thêm/xoá).
   - `RegionEditor.tsx`: danh sách box cộng/trừ, "+ Box cộng" (80% box nguồn), "− Box trừ" (30% ở tâm), "Đặt lại", ba góc nhìn Trên/Trước/Cạnh, Delete, Esc.
   - `MetricSceneView.tsx`: bàn giao 1 (gotoPose của viewer nối vào overlay), 2 (không ghi box khi đang kéo), 3 (dựng lại overlay khi entity của vật đổi), 4 (gắn vào `objectEntity` và báo khi vật chưa có trên viewport).
4. **Bộ đếm và cảnh báo**: "+a / −r · tổng n", "Bảo vệ sàn: k", spinner khi đang tính (bộ đếm cũ ẩn đi), mỗi vật chồng lấn một dòng "Box chồng lên {tên} ({n} Gaussian) — giữ chủ cũ" kèm checkbox "Lấy luôn" (đưa id vào `claim_from`), cảnh báo vàng khi `shell_error`, thông báo lỗi xem trước của máy chủ.
5. **Apply / Huỷ**: Apply chỉ bật khi có xem trước khớp box và box hợp lệ. 201 → cha đóng panel và tải lại scene. 202 → cha đóng panel và đọc tiến độ qua `refresh()`. 409 → thông báo "Scene đã đổi ở lượt khác. Tải lại để chỉnh tiếp." kèm nút "Tải lại", box được giữ. 422 → hiện `detail` của máy chủ. Huỷ đóng panel, không gửi ghi nào.
6. **Gắn vào ObjectReviewView** (scene có khoá `object_geometry`): nút "Chỉnh vùng" mở panel nổi trên viewport, cùng điều kiện hiện nút như trước. "Chỉnh chi tiết (Brush/Lasso)" mở `GaussianMembershipEditor` cũ. Scene không có khoá giữ nguyên nút cũ. Chọn vật khác thì panel đóng.

## Commit

| Commit | Nội dung |
| --- | --- |
| `c3214020` | Đặt T-016 `in-progress` |
| `794005bd` | Bước 1: API client xem trước và áp vùng, test API |
| `78521ea4` | Bước 2: hook xem trước debounce 250 ms, huỷ yêu cầu cũ |
| `c4b82503` | Bước 3a: phiên chỉnh vùng và cờ `isGesturing()` của overlay |
| `4440e4a4` | Bước 3b: panel danh sách box, góc nhìn, nối overlay vào viewer |
| `acb7afaa` | Bước 4: bộ đếm, vật chồng lấn, "Lấy luôn", cảnh báo vỏ |
| `d8f65415` | Bước 5: Apply, Huỷ, 409, 422 |
| `2a9a04d8` | Bước 6a: nút Chỉnh vùng trong ObjectReviewView, refresh tiến độ |
| `53e41d93` | Bước 6b: test nối ObjectReviewView |
| (commit này) | `report.md`, `status.md` |

## Tiêu chí chấp nhận

| # | Tiêu chí | Test |
| --- | --- | --- |
| 1 | Mở → một box cộng đúng kích thước vật; xem trước được gọi | "mở với một box cộng bằng nửa kích thước vật, đang được chọn"; "vật có kích thước: một box cộng, tâm gốc, nửa kích thước bằng nửa vật"; "đang tính thì hiện spinner; xong thì hiện bộ đếm và bảo vệ sàn" |
| 2 | Ba thay đổi trong 100 ms → một yêu cầu sau 250 ms; yêu cầu cũ bị huỷ | "kéo liên tục chỉ gửi một yêu cầu, sau 250 ms kể từ thay đổi cuối"; "yêu cầu đang chờ bị huỷ khi box đổi; yêu cầu mới có tín hiệu riêng" |
| 3 | Apply tắt khi box đổi sau xem trước cuối; bật lại khi xem trước mới về | "Apply tắt cho tới khi có xem trước khớp box; đổi box thì tắt lại" |
| 4 | "Lấy luôn" → `claim_from` chứa id | "vật chồng lấn nêu tên và số Gaussian; Lấy luôn đưa id vào claim_from của lần xem trước sau"; "Apply gửi revision, membership, box và claim hiện tại; kết quả 201 đưa cho cha" |
| 5 | Draft Apply → gọi API, đóng panel, tải lại scene; Ready Apply → 202 và đọc tiến độ | Draft: "Apply trên Draft (201) gửi revision và membership, đóng panel rồi tải lại scene". Ready: "Apply trên Ready (202) đóng panel và yêu cầu đọc lại tiến độ qua trạng thái tách vật chung" (kiểm tra `refresh` được gọi); "Apply trên scene Ready (202) đưa kết quả tiến độ cho cha" |
| 6 | 409 → thông báo và nút Tải lại; box không bị xoá | "409: báo scene đã đổi, giữ nguyên box, nút Tải lại gọi onReload" |
| 7 | Không xoá được box cộng cuối; xoá được box trừ | "không xoá box cộng cuối cùng; xoá được box trừ và box cộng khi còn box cộng khác"; "Delete xoá box đang chọn, không xoá box cộng cuối cùng" |
| H1–H4 | Bàn giao từ T-015 | "đưa lệnh chuyển camera của viewer vào overlay..."; "không ghi box vào overlay khi đang kéo..."; "dựng lại entity của vật thì gỡ overlay cũ..."; "vật đang chỉnh chưa có trên viewport thì báo..."; "regionApi: góc nhìn và trạng thái kéo đi qua overlay vùng" |

## Tệp đã đổi

| Đường dẫn | Nội dung |
| --- | --- |
| `frontend/src/lib/api/studio.ts` | Kiểu và hàm gọi preview/apply |
| `frontend/src/features/studio/region/useRegionPreview.ts` | (mới) hook xem trước |
| `frontend/src/features/studio/region/region-session.ts` | (mới) phiên chỉnh vùng |
| `frontend/src/features/studio/region/RegionEditor.tsx` | (mới) panel chỉnh vùng |
| `frontend/src/features/viewer/region-overlay.ts` | Thêm `isGesturing()` (T-015, chỉ một accessor) |
| `frontend/src/features/studio/MetricSceneView.tsx` | Props `regionEdit`, `regionApi`; nối gotoPose; vòng đời overlay; thông báo chưa có trên viewport |
| `frontend/src/features/studio/ObjectReviewView.tsx` | Nút Chỉnh vùng và Chỉnh chi tiết; mở panel; xử lý Apply |
| `frontend/src/features/studio/scene/useObjectify.ts` | Thêm `refresh()` |
| `frontend/tests/region-editor.test.tsx` | (mới) 49 test |
| `frontend/tests/object-review.test.tsx` | Thêm 5 test chỉnh vùng |
| `frontend/tests/metric-effective-collision.test.tsx` | Mock `SceneOverlay` thêm `bindViewerGotoPose` |
| `.ai/tasks/T-016/report.md`, `.ai/status.md` | Báo cáo và trạng thái |

## Kiểm thử

Chạy trên code cuối (`2a9a04d8`, `53e41d93`). Không chạy full suite.

- `vitest run tests/region-editor.test.tsx tests/object-review.test.tsx tests/region-box-model.test.ts` (khối "Tests required"), cộng các file liên quan `tests/region-overlay.test.ts tests/progress-objectify.test.tsx tests/anonymization-review.test.tsx tests/stage-view-selection.test.tsx tests/metric-effective-collision.test.tsx`: **232/232 pass** (8 file). Chi tiết: region-editor 49, object-review 55, region-box-model 55, region-overlay 36, progress-objectify 17, metric-effective-collision 11, anonymization-review 5, stage-view-selection 4.
- `npm run typecheck` (next typegen + tsc): **exit 0**.
- `eslint` trên 11 file đã sửa: **exit 0**.
- `graphify update .`: exit 0 (AST, không tốn API).

Kiểm tra backend chỉ bằng đọc mã: `src/api/product/scene.py` (route region/apply trả 202 khi scene đã `ready`, qua hàng đợi objectify chế độ `region`; 201 khi Draft). Chưa chạy máy chủ thật.

## Lệch khỏi plan

1. **`isGesturing()` trong `region-overlay.ts`** (file của T-015). Cần cho bàn giao 2: cha không ghi box trong lúc kéo. Chỉ thêm một accessor, không đổi hành vi; 36 test của T-015 vẫn pass.
2. **`refresh()` trong `useObjectifyState`**. Plan có nhắc nhưng `useObjectify.ts` không nằm trong danh sách file. Thêm để đọc tiến độ sau 202 mà không đi qua `send`.
3. **ObjectReviewView dùng `useContext(ObjectifyContext)`** thay vì gọi `useObjectify`. Lý do: ngoài trang scene, `useObjectify` sẽ mở một poller thứ hai.
4. **`regionApi` dùng `useImperativeHandle`**, không gán `ref.current` trong effect. ESLint (`react-hooks/immutability`) từ chối cách gán trong effect.
5. **Khoá xem trước có thêm revision và checksum** (sửa file bước 2). Sau khi tải lại, bộ đếm cũ không được hiện nữa.
6. **Chi tiết giao diện thêm vào**, plan không ghi: dòng "— sẽ lấy về vật này" khi đã tích "Lấy luôn" (dòng gốc vẫn là "— giữ chủ cũ"); thông báo khi vật chưa có trên viewport; Esc bắt ở pha capture để đọc trạng thái kéo trước khi overlay huỷ kéo; Delete không xoá khi đang gõ trong ô nhập.
7. **Vị trí nút "Chỉnh vùng"**: nằm trong mục "Gộp ứng viên / Sửa nhóm Gaussian", đúng chỗ nút cũ, không tạo mục mới.

## Vấn đề còn lại

1. **Chưa kiểm tra bằng mắt.** Theo quy ước của chủ dự án, phần này chủ dự án tự xem. Không có trình duyệt và không có ảnh chụp. Overlay và viewer được mock trong test panel và test viewer, nên kéo tay thật bằng chuột và góc nhìn camera thật chưa được xác minh.
2. **Không kẹp sàn ở client.** `setFloorZ` không được gọi, nên kéo box xuống dưới sàn không bị chặn trên viewer. Máy chủ vẫn đếm Gaussian trong vùng bảo vệ sàn và hiển thị ở "Bảo vệ sàn". Nếu cần kẹp ở client, phải truyền mặt sàn trong hệ object-local vào overlay. Chủ dự án cần quyết.
3. **Claim có thể còn sau khi hết chồng lấn.** Id đã tích "Lấy luôn" vẫn nằm trong `claim_from` khi box không còn chồng lên vật đó. Vật đó không còn dòng nào để bỏ tích, nên trạng thái này không hiện trên giao diện. Chưa kiểm chứng máy chủ xử lý ra sao với id không chồng lấn. Cách sửa đề xuất: lọc `claimFrom` theo các vật còn trong `overlaps` của xem trước mới nhất.
4. **Dòng chồng lấn nhấp nháy** khi tích "Lấy luôn": bộ đếm và dòng chồng lấn ẩn trong lúc xem trước đang tính lại (khoảng 250 ms cộng thời gian máy chủ).
5. **Góc nhìn khoá sau lần đầu thất bại.** Khi `viewFrom` trả false lần đầu, các nút góc nhìn khoá tới khi mở lại panel, đúng như plan. Nếu viewer sẵn sàng sau đó, phải mở lại panel.
6. **Nhánh 202 chỉ được kiểm bằng phản hồi giả.** Đã có test cho phía frontend. Phía backend đã đọc mã nhưng chưa chạy end-to-end.

## Round 2

Sửa ba Required changes trong `review.md`. Mọi kết luận "đạt" của review giữ nguyên, không đổi code ở phần đó.

1. **Nút "Chỉnh vùng" hiện trên Draft.** Nhóm nút của scene có khoá `object_geometry` không còn điều kiện `object_aware_collision_ref`. Nhánh cũ (nút "Chỉnh vùng Gaussian · Box / Brush / Lasso") chỉ dành cho scene không có khoá, và giữ điều kiện cũ. Test Draft dùng fixture thật: `object_geometry: "awaiting_review"`, có membership, không có collision ref, vật `collider: null`. Nút "Chỉnh vùng" hiện và mở được panel.
2. **Brush/Lasso trên Draft bị khoá.** Khi `objectGeometryState(scene) === "awaiting_review"`, nút "Chỉnh chi tiết (Brush/Lasso)" bị disable, kèm tooltip "Dùng Chỉnh vùng khi đang duyệt; Brush/Lasso dùng được sau khi Tạo mesh". Test: Draft bị disable và có tooltip; Ready vẫn bật.
3. **Dòng "Lấy luôn" không còn biến mất sau khi tick.** Danh sách là hợp của ba nguồn:
   - `claimed` (count > 0): "Box lấy {n} Gaussian từ {tên} — sẽ lấy về vật này", đang tick.
   - `overlaps` (count > 0): chữ cũ, "giữ chủ cũ" khi chưa tick.
   - `claimFrom` nhưng không có trong hai nguồn trên: "{tên} không còn trong box", đang tick để bỏ được.

   Đối chiếu máy chủ (`src/services/scene/editing/region_box.py`, dòng 115–127): `claimed[id]` chỉ có khi vật trong `claim_from` có Gaussian được lấy về, còn `overlaps` bỏ mọi vật trong `claim_from`. Vì vậy một mình `overlaps` làm mất dòng ngay sau khi tick. Vấn đề 3 ở trên đã được xử lý ở đây.

Test mới (`tests/region-editor.test.tsx`): tick → máy chủ trả `overlaps: {}`, `claimed: {chair: 12}` → dòng còn, đang tick; bỏ tick → yêu cầu sau có `claim_from: []`. Test thứ hai: vật đang tick mà box không còn chồng lên thì hiện "không còn trong box" và vẫn bỏ tick được. Review ghi id `b`; test dùng `chair` với nhãn "Ghế", cùng logic.

Kiểm tra test có bắt được lỗi cũ: tạm đặt lại điều kiện `object_aware_collision_ref` → test Draft đỏ ("Unable to find … Brush/Lasso"); tạm bỏ nguồn `claimed` → test Lấy luôn đỏ. Đã khôi phục đúng từng dòng, không còn đánh dấu tạm nào.

### Commit round 2

| Commit | Nội dung |
| --- | --- |
| `3a03a0e8` | Đặt T-016 `in-progress` cho vòng 2 |
| `2ab02fee` | Required 1 và 2: nút Chỉnh vùng trên Draft, Brush/Lasso bị khoá khi đang duyệt, kèm test |
| `7e99a225` | Required 3: dòng Lấy luôn lấy từ claimed, overlaps và claimFrom, kèm test |
| (commit này) | `report.md` (Round 2), `status.md` |

### Lệnh kiểm tra round 2

Chạy trên code cuối (`7e99a225`), đúng khối lệnh trong `review.md`:

- `vitest run tests/region-editor.test.tsx tests/object-review.test.tsx tests/region-box-model.test.ts` → **162/162 pass** (region-editor 51, object-review 56, region-box-model 55).
- `npm run typecheck` → **exit 0**. Lần chạy đầu bị lỗi kiểu ở mock trong test mới (union không khớp `RegionPreview`), đã sửa bằng chú thích `Promise<RegionPreview>` cho hai mock.
- `eslint` trên `RegionEditor.tsx`, `ObjectReviewView.tsx`, `region-editor.test.tsx`, `object-review.test.tsx` → **exit 0**.
- `graphify update .` → exit 0.

### Quyết định của review, không thay đổi

- Không kẹp sàn phía client (review: server bảo vệ hàng sàn).
- Kiểm bằng mắt và đường Ready thật thuộc chủ dự án khi chạy scene mới.
