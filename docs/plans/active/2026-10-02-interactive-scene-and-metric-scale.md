# Execution Plan: Scene tương tác (điều khiển viewer, đi bộ, nhân vật, đẩy vật), chọn vật theo hình dáng, đề xuất tỉ lệ mét, hàng đợi nhiều người dùng

## Status

PLANNED — kế hoạch do owner yêu cầu ngày 02/10/2026 sau chuỗi thảo luận; chưa có dòng code nào của kế hoạch này.

- **Người yêu cầu / Tech Lead:** Quân (EX-REC).
- **Branch:** `feat/pipeline-v2` (PR #17 vào `develop`).
- **Ownership theo `ARCHITECTURE.md`:** viewer và Studio thuộc EX-PRODUCT (`frontend/src/features/viewer`,
  `frontend/src/features/studio`); tách vật và SceneIR thuộc EX-SCENE; hệ mét và hình học thuộc EX-REC.
- **Kế hoạch liên quan, không trùng:** `2026-10-02-resource-management-cleanup.md` (tài nguyên worker, chạy song song),
  `2026-10-02-evaluation-system.md` (đánh giá pha 2–3).

## Quyết định owner đã chốt (02/10/2026)

- Giữ **SAM 2**; không dùng SAM 3.
- **Tuyệt đối không** làm chế độ hai camera cho COLMAP.
- Sản phẩm không tự gán nhãn vật thể; đặt nhãn là việc của người dùng.
- Muốn: đi lại trong scene bằng phím và chuột, góc nhìn thứ nhất và thứ ba với người 3D, va chạm và **đẩy được vật thể**;
  người mẫu ưu tiên lấy từ asset Isaac Sim.
- Viewer hiện khó điều khiển: zoom chậm, xoay khó.
- Bước chọn vật thể nên hiện khung theo **hình dáng vật** thay cho hộp.
- Đồng ý thứ tự cho tỉ lệ mét: kiểm giấy phép mô hình → viết bước đề xuất → đo sai số trên TorWIC so với LiDAR.
- Chạy song song nhiều job, tận dụng hết GPU nhưng không tràn RAM/VRAM (phần code đã xong ở kế hoạch tài nguyên).

## Hiện trạng đã kiểm (VERIFIED trừ khi ghi khác)

- Viewer dùng `@playcanvas/supersplat-viewer` 1.35.2 (MIT). Studio tắt UI gốc của thư viện (`ui: showControls`) nên chỉ
  còn chế độ xoay quanh tâm. Thư viện có sẵn `state.cameraMode` (orbit / fly / walk), `state.gamingControls`,
  `state.walkAllowed`, `setMoveInput`, `frameScene()`, `resetCamera()`, và nhận `collision` là `.glb` hoặc dữ liệu voxel.
  Chưa chạy thử chế độ walk với scene của ta.
- Mỗi job hoàn tất có `rec05/<checksum>/collision.glb` (mesh va chạm hệ mét của cả scene). `PlayCanvasScene.tsx` đã có
  prop `collisionUrl`.
- SceneIR mỗi vật có `visual_ref` (Gaussian của riêng vật), `collider.geometry_ref` (GLB phân rã lồi), `transform`,
  `primitive_dimensions_xyz_m`. Lớp phủ `scene-overlay.ts` hiện vẽ và bắt chọn bằng **hộp** (`setBoxes`, `rayUnitBox`).
- Frontend chưa có bộ máy vật lý (không có ammo/rapier trong `package.json`).
- Kho asset công khai Isaac Sim 5.1 có `Isaac/People/Characters/` (công nhân, cảnh sát, y tế, văn phòng), mỗi nhân
  vật một USD kèm texture. `scripts/scene/build_asset_previews.py` chỉ chuyển hình khối tĩnh sang GLB, không khung
  xương, không texture. Chưa mở file nhân vật: vị trí hoạt ảnh và khả năng chuyển sang GLB là **UNKNOWN**.
- Mesh va chạm chặn 50–66% vị trí camera thật đã đi qua trên hai scene mẫu (finding của hệ thống đánh giá, chưa xử lý).
- Bước xác nhận hệ mét (REC-06) cần người dùng chọn 7 điểm và nhập 2 số đo. `spirula-studio` (GPLv3, không chép code)
  lấy tỉ lệ từ IMU/GPS trong file của camera hành trình — không áp dụng cho video điện thoại thường; nó dùng MoGe-2 và
  Metric3D v2 chỉ để hỗ trợ train. Sai số của hướng "độ sâu mét từ một ảnh" trên dữ liệu kho: **UNKNOWN**.
- Ổ ngoài `/media/usb` đang mất kết nối: dữ liệu TorWIC gốc và LiDAR chưa đọc được.

## Các hạng mục, theo thứ tự làm

### H1 — Điều khiển viewer và đi bộ góc nhìn thứ nhất

Mục tiêu: xem bên trong scene dễ như trong game; đi bộ có trọng lực và bị tường/vật chặn.

1. Thanh công cụ camera trong viewer của job: chuyển Xoay quanh tâm / Bay tự do / Đi bộ; nút Về toàn cảnh và Về vị trí
   ban đầu; bật điều khiển kiểu game (WASD + chuột, khoá con trỏ).
2. Bấm đúp một điểm để đặt tâm xoay tại đó.
3. Tốc độ di chuyển và zoom chỉnh được, phím giữ để đi nhanh. Thư viện có tham số tốc độ zoom hay không: UNKNOWN; nếu
   không có thì tự xử lý con lăn ở lớp host.
4. Nạp `collision.glb` của job làm dữ liệu va chạm; chế độ Đi bộ chỉ bật khi `state.walkAllowed`, không thì ghi rõ lý do.
5. Gợi ý phím hiển thị trong viewer; thoát khoá con trỏ bằng Esc.

Proof: test đơn vị cho thanh công cụ và ánh xạ trạng thái; chạy thật trên scene `job-ab730e702ee9` hoặc scene Studio
local; owner tự kiểm bằng mắt. Rủi ro: chế độ walk của thư viện có thể không hợp với mesh của ta (xem H3).

### H2 — Chọn vật theo hình dáng thay cho hộp

1. Vẽ vật được chọn/ứng viên bằng chính collider phân rã lồi của nó (mặt mờ + viền), nạp lười theo vật; hộp chỉ còn là
   đường lùi khi collider chưa tải hoặc vật thêm từ thư viện dùng hộp.
2. Bắt chọn bằng tia cắt lưới collider thay cho `rayUnitBox`, để bấm vào khoảng trống trong hộp không chọn nhầm vật.
3. Tuỳ chọn tô sáng Gaussian của chính vật (`visual_ref`) khi rê chuột. Khả năng đổi màu từng nhóm Gaussian lúc chạy
   của viewer: UNKNOWN, kiểm trước khi hứa.

Proof: test tia–lưới (trúng, trượt, vật chồng nhau chọn vật gần hơn); test hiện có của bước duyệt vật vẫn xanh.

### H3 — Chất lượng mesh va chạm ("tường ma") — HOÃN theo owner

**DECISION (owner, 02/10/2026):** không ưu tiên. Owner nhận định nguyên nhân là chất lượng tái tạo 3DGS hiện chưa tốt,
không phải thông số dựng mesh; không đổi `geometry_v1.json`. Hệ quả chấp nhận: chế độ Đi bộ có thể bị chặn ở lối đi thật
trên các scene hiện có; chế độ Bay tự do (không va chạm) luôn dùng được để xem scene. Nội dung dưới đây giữ lại để tham
khảo khi chất lượng 3DGS được cải thiện.

Điều kiện để H1 dùng được trên scene thật. Việc: tái hiện bằng số đo `path clearance` đã có; tìm nguyên nhân (cỡ voxel
0,05 m, ngưỡng opacity, bước carve, điểm seed); đề xuất thay đổi thông số hình học. Đổi `configs/product/geometry_v1.json`
là đổi cấu hình đã khoá của EX-REC → cần owner duyệt sau khi có số so sánh trước/sau.

### H4 — Nhân vật 3D và góc nhìn thứ ba

1. Kiểm điều khoản asset Isaac cho việc phát trên web; mở một nhân vật để xem khung xương và hoạt ảnh.
2. Script dựng GLB có khung xương + hoạt ảnh đứng/đi/chạy từ USD (cùng nguyên tắc với asset preview: không commit asset
   NVIDIA, mỗi máy tự dựng, API phục vụ từ thư mục cấu hình). Nếu chuyển không sạch: dùng mô hình người định dạng web có
   giấy phép tự do cho trình duyệt, và ghi rõ nguồn trong `THIRD_PARTY_NOTICES.md`.
3. Bộ điều khiển nhân vật: viên nang va chạm, WASD, chạy, nhảy; camera bám sau lưng, không xuyên tường; phím chuyển
   góc nhìn thứ nhất ↔ thứ ba.

Giới hạn biết trước: nhân vật là lưới thường trong cảnh 3DGS nên ánh sáng/bóng không hoà hoàn toàn.

### H5 — Đẩy vật thể

1. Chọn bộ máy vật lý cho trình duyệt (ứng viên: ammo.js mà PlayCanvas hỗ trợ sẵn, hoặc Rapier); kiểm giấy phép, kích
   thước tải, và ghi quyết định vào `docs/decisions/`.
2. Scene tĩnh = `collision.glb`; vật động = vật có collider lồi và khối lượng trong SceneIR, theo cờ động/tĩnh của danh
   mục (kệ, dầm là tĩnh).
3. Gaussian của vật đi theo thân vật lý. **Rủi ro lớn nhất:** viewer có cho di chuyển từng vật Gaussian lúc chạy không
   — kiểm bằng một thử nghiệm nhỏ trước khi làm phần còn lại.
4. Nút Đặt lại vị trí. Tương tác chỉ ở phía trình duyệt, **không** ghi vào SceneIR (không tạo revision).

### H6 — Đề xuất tỉ lệ mét và mặt sàn tự động

1. Kiểm giấy phép và yêu cầu runtime của MoGe-2 và Metric3D v2 (mã và trọng số); ghi vào `THIRD_PARTY_NOTICES.md`.
2. Bước đề xuất trong EX-REC: chạy mô hình trên một số frame đã chọn, so độ sâu mét với độ sâu của các điểm COLMAP trong
   cùng frame, lấy trung vị → tỉ lệ; lấy mặt sàn từ pháp tuyến + điểm thấp. Xuất artifact đề xuất kèm độ phân tán, không
   thay bản xác nhận.
3. UI bước hệ mét điền sẵn đề xuất, ghi rõ "ước lượng tự động"; người dùng đồng ý hoặc sửa bằng số đo thật. PRD/contract
   yêu cầu con người xác nhận hệ mét: giữ nguyên, bỏ bước xác nhận là quyết định sản phẩm riêng.
4. Đo sai số so với LiDAR trên TorWIC và ghi vào `eval/` (cần ổ ngoài).

### H7 — Hàng đợi cho nhiều người dùng

1. Màn chờ hiện vị trí trong hàng và thời gian chờ ước tính từ thời lượng đã đo.
2. Xếp hàng xoay vòng theo người dùng thay cho thuần ai tới trước.
3. Preset nhanh cho lúc đông người: cần số đo trên GPU thuê trước khi chốt giá trị.

### H8 — Việc đang kẹt hoặc cần máy thuê

- **Kẹt vì ổ ngoài:** ghép các video demo từ dữ liệu đã tải (`scripts/demo/make_torwic_video.py`); đánh giá pha 2 so với
  dữ liệu chuẩn TorWIC; bước 4 của H6.
- **Cần GPU thuê:** thời gian thật của một job; hai worker chạy chung một GPU; máy 2 GPU; PostgreSQL + R2; số đo trong
  container.
- **Chờ quyết định owner:** để dành ảnh cho PSNR/SSIM/LPIPS (đánh giá pha 3).

## Ngoài phạm vi

SAM 3; chế độ hai camera cho COLMAP; tự gán nhãn vật thể; ghi kết quả tương tác vật lý vào SceneIR; mô phỏng vật lý
đạt mức Isaac Sim trong trình duyệt.

## Thứ tự và phụ thuộc

```text
H1 ──► H3 (H1 cho thấy mức ảnh hưởng của tường ma)
H1 ──► H4 ──► H5
H2 độc lập
H6: bước 1–3 độc lập; bước 4 chờ ổ ngoài
H7 độc lập
```

Làm H1 và H2 trước (nhỏ, thấy ngay), rồi H6, H4, H5, H7. H3 hoãn theo quyết định owner.

## Proof chung

Mỗi hạng mục: test đơn vị cho logic thuần; `npm test`, `npm run typecheck`, `npm run lint`; `pytest` + `ruff` khi đụng
backend; chạy thật trên một scene có sẵn. Kiểm bằng mắt trên trình duyệt là việc của owner. Không claim phần nào xong
khi chỉ có test giả lập.

## Progress

- [x] H1 Điều khiển viewer + đi bộ góc nhìn thứ nhất (02/10/2026; xem Result)
- [~] H2 Chọn vật theo hình dáng — code + test đơn vị xong (02/10/2026), chưa kiểm trên trình duyệt
- [ ] H3 Tường ma của mesh va chạm — hoãn (owner, 02/10/2026)
- [ ] H4 Nhân vật 3D, góc nhìn thứ ba
- [ ] H5 Đẩy vật thể
- [ ] H6 Đề xuất tỉ lệ mét tự động
- [ ] H7 Hàng đợi nhiều người dùng
- [ ] H8 Việc đang kẹt / cần máy thuê

## Result

### H1 (02/10/2026)

- `GET /api/v1/jobs/{job_id}/walk-collision/{filename}`: lưới va chạm của job xoay sang không gian hiển thị
  (`orchestration/jobs/display_glb.py`); quyền đọc theo allow-list như `artifacts/content`; artifact gốc không đổi.
  Lý do: viewer đọc toạ độ đỉnh thô của GLB va chạm, không áp transform của node, còn Studio hiển thị scene hệ mét
  bằng phép xoay `(x, y, z) → (x, z, −y)`.
- `PlayCanvasScene`: `ViewerControls.setCameraMode/frameScene/resetCamera`, `runtime.cameraMode`, `wheelFactor` (nhân
  bước cuộn ở lớp host vì tốc độ zoom của viewer là hằng số nội bộ `wheelSpeed`, không có trong settings).
- `CameraToolbar` trên `MetricSceneView`: Xoay / Bay / Đi bộ, Toàn cảnh, Về vị trí đầu, tốc độ zoom (mặc định ×2), gợi ý
  phím theo chế độ. Bấm đúp để lấy tâm xoay là hành vi có sẵn của viewer, chỉ ghi vào gợi ý.
- Validation: `pytest` test mới 14 (transform GLB + route) pass; `ruff check .` sạch; `npm test` 199 passed,
  typecheck + lint sạch.
- Chạy thật (Chrome headless, WebGL2 phần mềm) trên scene `job-ab730e702ee9` qua API + `next dev`: viewer nạp xong,
  `walk-collision/collision.glb` trả 200, nút Đi bộ được bật (viewer báo `walkAllowed`), bấm Bay → Đi bộ → Xoay → Toàn
  cảnh thì chế độ viewer báo về đổi đúng theo.
- **Chưa kiểm:** lưới va chạm có khớp hình với 3DGS khi đi bộ không (cần nhìn bằng mắt — việc của owner); cảm giác
  điều khiển; chuột thật với khoá con trỏ. H3 (tường ma) hoãn nên đi bộ có thể bị chặn ở lối đi thật.

### H2 (02/10/2026) — VALIDATING

- `scene-overlay.ts`: khung vật vẽ bằng GLB collider phân rã lồi của vật (`OverlayBox.shapeUrl`), vật đang chọn có thêm
  nét cạnh; hộp chỉ là hình lùi trong lúc GLB đang tải hoặc tải lỗi. Bắt chọn bằng tia cắt lưới (`rayTriangles`), vật
  chưa có hình thì vẫn theo hộp. Asset hình dáng nạp một lần cho cả vòng đời lớp phủ.
- `ObjectReviewView` truyền `collider.geometry_ref` (GLB) làm `shapeUrl`; nhãn lớp đổi thành "Khung vật thể".
- Validation: `npm test` 203 passed (4 test mới cho tia–lưới, gồm ca bấm vào khoảng trống trong hộp bao), typecheck +
  lint sạch.
- **Chưa kiểm trên trình duyệt:** lúc kiểm, một `next dev` khác (do Codex chạy, cổng 3000) đang giữ khoá dev của
  project nên không khởi động được server thứ hai; không dừng tiến trình của agent khác. Phần chưa được chứng minh:
  GLB collider hiển thị đúng vị trí/hướng trong scene, nét cạnh (wireframe) vẽ được, và tô sáng Gaussian theo vật
  (chưa làm).
