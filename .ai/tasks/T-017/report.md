# T-017: Vỏ phát sáng + điểm thêm/bớt — báo cáo

**Trạng thái:** implemented. Không có câu hỏi thiết kế chặn việc giao T-017. Một điểm lệch so với plan (cỡ điểm 1 px, không phải 4 px) nêu ở mục "Lệch khỏi plan" cần chủ dự án quyết.

**Branch:** `mvp-pipeline-v2`. Không tạo branch, không push.

## Đã làm

Thực hiện theo năm bước của `plan.md`, mỗi bước một commit.

1. **`ShellGlowLayer.setShell`** (`frontend/src/features/viewer/shell-glow.ts`): vỏ là GLB từ ArrayBuffer (đi qua blob URL, thu hồi sau khi nạp) hoặc từ URL. Vỏ là con của entity vật nên đi theo transform của vật. Vỏ mới thay vỏ cũ của cùng vật; asset cũ được gỡ khỏi registry và unload. Vỏ `selected` có thêm viền wireframe. Vật liệu cộng dồn, phát sáng, không ghi depth, hai mặt. `clear(id)` gỡ vỏ của một vật; `destroy()` gỡ hết và các lời gọi sau đó không làm gì.
2. **`setPointSets`**: điểm xanh (`#22c55e`) là Gaussian sẽ thêm, điểm đỏ (`#ef4444`) là Gaussian sẽ bị loại. Mỗi mảng là xyz liên tiếp trong khung object-local, con của entity vật. Gọi lại thì thay bộ cũ; hai mảng rỗng thì gỡ hết. Điểm có `depthTest = false`.
3. **Nhịp phát sáng và trạng thái**: vỏ `selected` nhấp nháy độ mờ 0,22–0,28 trong chu kỳ 2 s, kèm tăng nhẹ `emissiveIntensity`. Vỏ `idle` đứng yên. Khi người dùng bật giảm chuyển động thì không nhấp nháy và không yêu cầu khung hình; vỏ đang nhấp nháy mà bật thì trả về độ mờ gốc. `setTone` cho hai trạng thái: `pending` làm mờ vỏ về 0,12, `warning` đổi màu cam. Đăng ký nhịp khung hình khi có vỏ đầu tiên và gỡ đăng ký khi `destroy`.
4. **Nối với panel chỉnh vùng** (`RegionEditor.tsx`, `region-session.ts`, `MetricSceneView.tsx`): panel đẩy kết quả xem trước lên viewer qua `showPreview` (thêm vào `RegionViewApi`). Đang tính: vỏ cũ mờ. Có kết quả: điểm xanh và đỏ, vỏ mới thay vỏ cũ. `shell_error`: giữ vỏ cũ, đổi màu cam, điểm vẫn vẽ. Panel đóng (unmount): viewer trả vỏ gốc của vật và xoá điểm. `MetricSceneView` giữ một `ShellGlowLayer` cho overlay hiện tại, gỡ khi đổi app và khi unmount.
5. **Draft trong `ObjectReviewView`**: mọi vật có `url: null` cho Gaussian của chính nó (entity vẫn có để vỏ và overlay vùng gắn vào). Vỏ `idle` cho mọi vật từ `geometry_ref` (GLB), vật đang chọn là `selected`. Ready giữ như cũ: Gaussian được nạp, không có vỏ vẽ riêng.

## Commit

| Commit | Nội dung |
| --- | --- |
| `76dfa41c` | Đặt T-017 `in-progress` |
| `bbe89994` | Bước 1: `setShell` và vật liệu vỏ, gắn vào entity vật, thay vỏ cũ, gỡ và destroy |
| `14be4ea5` | Bước 2: `setPointSets`, điểm xanh và đỏ |
| `aefc5b3c` | Bước 3: nhịp phát sáng, giảm chuyển động, `setTone` (pending, warning) |
| `9859a6be` | Bước 4: panel đẩy xem trước lên viewer, trả vỏ gốc khi đóng |
| `e6bbfd3a` | Bước 5: Draft vẽ vỏ cho mọi vật, bỏ Gaussian của vật |
| (commit này) | `report.md`, `status.md` |

## Tệp đã đổi

| Đường dẫn | Nội dung |
| --- | --- |
| `frontend/src/features/viewer/shell-glow.ts` | (mới) `ShellGlowLayer`, `decodeShellGlb`, kiểu `ShellSpec`, `ShellStyle`, `ShellTone` |
| `frontend/src/features/studio/MetricSceneView.tsx` | Giữ lớp vỏ, nhận prop `shells`, đồng bộ vỏ gốc, nhận `showPreview` qua `regionApi` |
| `frontend/src/features/studio/region/region-session.ts` | `showPreview` trong `RegionViewApi` |
| `frontend/src/features/studio/region/RegionEditor.tsx` | Đẩy xem trước và trạng thái tính lên viewer; trả vỏ gốc khi đóng |
| `frontend/src/features/studio/ObjectReviewView.tsx` | Draft: bỏ Gaussian của vật, vẽ vỏ cho mọi vật, vật chọn là `selected` |
| `frontend/tests/shell-glow.test.ts` | (mới) 18 test: vỏ, điểm, nhịp, giảm chuyển động, trạng thái, destroy |
| `frontend/tests/region-editor.test.tsx` | Thêm test đẩy xem trước, test nối viewer (vỏ gốc, thay vỏ, lỗi vỏ, đang tính); fakes có `showPreview` |
| `frontend/tests/object-review.test.tsx` | Stub viewer nhận `shells`; thêm 2 test Draft và Ready |

## Kiểm thử

Chạy trên code cuối (`e6bbfd3a`). Không chạy full suite.

- `vitest run tests/shell-glow.test.ts tests/region-editor.test.tsx tests/object-review.test.tsx tests/metric-effective-collision.test.tsx tests/stage-view-selection.test.tsx tests/region-overlay.test.ts`: **182/182 pass** (6 file). Chi tiết: shell-glow 18, region-editor 55, object-review 58, metric-effective-collision 11, stage-view-selection 4, region-overlay 36.
- `npm run typecheck` (next typegen + tsc): **exit 0**.
- `eslint` trên 8 file đã sửa hoặc tạo: **exit 0**.
- `graphify update .`: exit 0.

Kiểm tra test có bắt được lỗi: tạm bỏ quy tắc Gaussian của Draft trong `ObjectReviewView` thì test "Draft: không nạp Gaussian của vật nào…" đỏ ("expected false to be true"). Đã khôi phục đúng một dòng, chạy lại 58/58.

## Tiêu chí chấp nhận

| # | Tiêu chí | Test |
| --- | --- | --- |
| 1 | Vỏ là con của root vật, đi theo transform | "vỏ là con của entity vật, nên đi theo transform của vật" |
| 2 | Preview mới thay vỏ cũ, không chồng | "vỏ mới của cùng vật thay vỏ cũ: chỉ còn một vỏ, asset cũ được gỡ và unload"; "vỏ gốc của vật trong Draft được nạp; lần xem trước thay vỏ…" |
| 3 | Điểm xanh và đỏ đúng số mẫu; xoá khi đóng editor | "mỗi loại một mesh điểm: xanh là Gaussian thêm, đỏ là bị loại…"; "panel đưa xem trước và trạng thái đang tính lên viewer; đóng panel thì viewer nhận lệnh trả vỏ gốc" |
| 4 | Draft không có Gaussian của vật; Ready như cũ | "Draft: không nạp Gaussian của vật nào; mọi vật có vỏ, vật đang chọn là selected"; "Ready: vật đã xác nhận nạp Gaussian như trước và không có vỏ vẽ riêng" |
| 5 | Giảm chuyển động thì không có nhịp | "bật giảm chuyển động thì vỏ không nhấp nháy; đang nhấp nháy mà bật thì trả về độ mờ gốc" |
| 6 | `destroy()` không rò entity hay asset | "clear(id) chỉ gỡ vỏ của vật đó; destroy gỡ hết, unload asset và không nạp gì nữa"; "clear(id) và destroy gỡ điểm của vật, không để lại entity nào"; "destroy gỡ đăng ký nhịp khung hình" |

## Lệch khỏi plan

1. **Cỡ điểm 1 px, không phải 4 px.** Điểm dùng `PRIMITIVE_POINTS` mặc định của engine, như điểm LiDAR của `setPoints`. Cỡ 4 px cần point-sprite shader tự viết; repo chưa có, và tôi không kiểm được shader trên GPU ở đây. Tôi không tự viết shader chưa kiểm để tránh vỡ viewer. Cần chủ dự án quyết sau khi nhìn bằng mắt.
2. **Chủ sở hữu lớp vỏ.** Plan viết "`region-overlay.ts` gắn layer hoặc `RegionEditor` truyền vào". Tôi chọn `MetricSceneView` giữ một `ShellGlowLayer` cho overlay, vì vỏ của Draft vẽ cho mọi vật chứ không chỉ vật đang chỉnh. Panel đẩy xem trước qua `regionApi`. Nhờ vậy chỉ có một slot vỏ cho mỗi vật, không chồng hai vỏ.
3. **Thêm vào interface của plan.** `setTone(objectId, tone)` để làm mờ 0,12 khi đang tính và đổi màu cam khi lỗi vỏ. Plan không liệt kê nhưng hai trạng thái này được yêu cầu. Ngoài ra có `decodeShellGlb` (base64 → ArrayBuffer), kiểu `ShellSpec`, prop `shells` của `MetricSceneView`, và `showPreview` trong `RegionViewApi`. Constructor giữ đúng `host: SceneOverlay` như plan.
4. **File ngoài danh sách plan.** Đã sửa `MetricSceneView.tsx`, `region-session.ts` và `tests/region-editor.test.tsx`. Cần để nối panel với viewer.
5. **Vỏ Draft chỉ lấy `geometry_ref` có đuôi `.glb`**, cùng quy tắc với `colliderShapeUrl`. Artifact khác đuôi thì vật đó không có vỏ.
6. **Trạng thái `pending` cũng làm mờ viền wireframe** (xuống 0,12). Plan chỉ nói về vỏ; viền đi cùng vỏ nên làm vậy.

## Vấn đề còn lại

1. **Chưa nhìn bằng mắt.** Theo quy ước của chủ dự án, phần này chủ dự án tự xem: màu, nhịp, độ mờ, cỡ điểm. Mọi kiểm tra ở đây là test với viewer giả, không có WebGL thật.
2. **Điểm 1 px** (xem lệch khỏi plan, mục 1).
3. **Lỗi nạp vỏ bị nuốt.** `MetricSceneView` bắt lỗi `setShell` và bỏ qua (`catch(() => undefined)`), nên vật lỗi vỏ chỉ không có vỏ, không báo gì. Cân nhắc hiện thông báo khi chủ dự án muốn.
4. **Xem trước không có GLB và không có `shell_error`** thì vỏ cũ vẫn còn, không được thay. Theo T-010 máy chủ luôn trả một trong hai, nên chưa cần xử lý, nhưng chưa kiểm chứng trên máy chủ thật.
5. **Không cache GLB vỏ.** Mỗi lần xem trước (sau mỗi nhịp 250 ms) giải mã base64 và nạp lại GLB. Nếu thấy chậm thì cache theo checksum.
6. **Thứ tự gỡ khi đổi app.** Khi `MetricSceneView` đổi app, lớp vỏ cũ được gỡ trước overlay cũ. Đã có test `destroy`, nhưng chưa có test ghép cả hai trên viewer thật.
