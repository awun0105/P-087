# T-045: Cho 9 scene từ bộ ảnh Deep Blending và Mip-NeRF 360 chạy hết pipeline, kèm video ghép để phát lại

## Goal
Chín scene sau chạy trọn pipeline của Real2Sim (từ đầu vào tới khi scene có mesh và lưới va chạm cho từng vật), **đầu vào là
ảnh gốc của dataset**, không phải video:

| Bộ | Scene | Thư mục ảnh dùng | Số ảnh | Cỡ ảnh |
| --- | --- | --- | --- | --- |
| Deep Blending | drjohnson | `db/drjohnson/images` (bộ này không có bản thu nhỏ; ảnh đã ~1300 px) | 263 | 1332×876 |
| Deep Blending | playroom | `db/playroom/images` | 225 | 1264×832 |
| Mip-NeRF 360 | bicycle | `mipnerf360/bicycle/images_2` (bản 1/2) | 194 | 2473×1643 |
| Mip-NeRF 360 | bonsai | `mipnerf360/bonsai/images_2` | 292 | 1559×1039 |
| Mip-NeRF 360 | counter | `mipnerf360/counter/images_2` | 240 | 1558×1038 |
| Mip-NeRF 360 | garden | `mipnerf360/garden/images_2` | 185 | 2594×1681 |
| Mip-NeRF 360 | kitchen | `mipnerf360/kitchen/images_2` | 279 | 1558×1039 |
| Mip-NeRF 360 | room | `mipnerf360/room/images_2` | 311 | 1557×1038 |
| Mip-NeRF 360 | stump | `mipnerf360/stump/images_2` | 125 | 2489×1650 |

Gốc: `/media/usb/AI20K/gaussian_training_datasets/`. Không dùng `tandt/`, `tested_outputs/`.

Yêu cầu của chủ dự án:
1. Ghép ảnh mỗi scene thành một video. **Video không phải đầu vào**; nó được gắn vào project để phát lại (giả lập rằng hệ thống đã
   tách đúng các ảnh này từ video đó).
2. Đầu vào của pipeline là **chính các ảnh** (bản 1/2 nếu dataset có).
3. **Không dùng `sparse/`, `poses_bounds.npy`** hay bất kỳ dữ liệu COLMAP có sẵn nào của dataset: camera phải do COLMAP trong
   pipeline của mình tính.
4. Agent tự chạy, theo dõi, tìm và sửa lỗi pipeline cho tới khi xử lý hết 9 scene.

## Context (đã kiểm trong code)
- Đường tải lên của giao diện chỉ nhận video (`InputAssetFormat` không có loại ảnh, `input_assembly.py:37–56`). Ảnh chỉ vào
  pipeline qua `SourceType.DATASET` (`manifests.py:21–25`), như cách bộ TorWIC đã làm (xem `scripts/torwic/`).
- Bước tách khung hình chỉ nhận `image/png` (`rgb/frames/frame_extraction.py:348`, `rgb/frames/manifest_frames.py:35`);
  `ColmapInputAdapter` chép mọi frame thành `{frame_id:06d}.png` (`adapters/colmap_input.py:37`). Ảnh dataset là JPG.
- Project chỉ lưu tên/loại/cỡ video đầu vào (`InputVideoSummary`, `projects/registry.py:430`); chưa có chỗ gắn một video **chỉ
  để xem**. Trang phát lại và xuất mẫu lấy video từ đầu vào.
- Scene Room hiện có (`job-a14981f78f85`) trước đây được nạp **dưới dạng video** `data/datasets/mipnerf360_room/room.mp4` —
  không phải cách task này yêu cầu. Không đụng job đó.
- Ổ laptop còn khoảng 14 GB; một scene Room chiếm 3,7 GB artifact. 9 scene không đủ chỗ trên laptop. Ổ USB
  (`/media/usb`, 276 GB trống) là `fuseblk` (NTFS qua FUSE): chưa biết kho artifact (đổi tên file nguyên tử, quyền, liên kết)
  có chạy đúng trên đó không.
- Máy local: Quadro T2000 4 GB. **Một việc nặng một lúc**, có `scripts/gpu/thermal_guard.sh`. Một scene có thể mất vài giờ.
- Bước người dùng: xác nhận tỉ lệ mét (hệ thống có đề xuất tự động MoGe-2), duyệt vật và bấm Tạo mesh. ObjectGS **tắt** (backlog
  chất lượng mesh). Lưới va chạm của scene trong nhà nhiều vật có thể bị từ chối bởi kiểm "vết cắt phải kín" (backlog, xem
  scene Room) — ghi nhận, không sửa trong task này.
- Bản quyền: Deep Blending và Mip-NeRF 360 có giấy phép riêng của tác giả (README của dataset). Chỉ dùng nội bộ cho tới khi chủ
  dự án kiểm giấy phép; không công khai bản mẫu.

## Phần A — Code: nhận bộ ảnh làm đầu vào và gắn video chỉ để xem (mỗi ý một commit có test, test mới đỏ trên code cũ)
1. **Ảnh JPEG giữ nguyên byte.** Cho đường dataset nhận `image/jpeg` cạnh `image/png` (frame extraction, manifest frames,
   frame set), giữ đúng phần mở rộng thật khi chép cho COLMAP và Brush (không đặt `.png` cho file JPEG). Không chuyển đổi hay nén
   lại ảnh. Test: bộ frame JPEG đi qua tách khung hình → COLMAP input có đúng tên đuôi `.jpg` và đúng checksum.
   Nếu thấy thay đổi này đụng quá nhiều chỗ (hơn khoảng 6 file sản phẩm) thì dừng, ghi lý do và hỏi Architect trước khi chuyển sang
   cách đổi JPG → PNG.
2. **Lệnh nạp một bộ ảnh**: `scripts/datasets/import_image_scene.py --images <thư mục> --name <tên> --video <mp4>` tạo project +
   job theo đúng đường `SourceType.DATASET` hiện có (đọc `scripts/torwic/` để dùng lại, không viết đường mới song song). Ảnh sắp
   theo tên file. Lệnh **từ chối** nếu thư mục có `sparse/` hoặc `poses_bounds.npy` được truyền vào làm đầu vào; chỉ đọc thư
   mục ảnh được chỉ định. Lời khai nguồn dữ liệu: `public_or_synthetic`, chủ sở hữu ghi tên dataset gốc, mục đích "kiểm thử
   nội bộ".
3. **Video chỉ để xem**: thêm trường tuỳ chọn trên project (đề xuất `display_video_ref`) trỏ tới artifact mp4; pipeline **không
   đọc** trường này. Trang scene, trang phát lại và xuất mẫu dùng `display_video_ref` khi project không có video đầu vào, kèm
   nhãn "Video ghép từ ảnh gốc, chỉ để xem lại". Hợp đồng frontend/backend mirror xanh. Test: job dataset có video xem → xuất mẫu
   có video; pipeline không dùng video đó (job vẫn chạy khi xoá file video khỏi thư mục làm việc).
4. **Ghép video**: hàm trong lệnh ở ý 2: `ffmpeg` ghép ảnh theo thứ tự tên, **3 khung/giây** (khớp lấy mẫu 3 ảnh/giây của
   preset trong nhà, nên mỗi ảnh ứng với một khung được "tách"), H.264, `yuv420p`, kích thước chẵn, cạnh dài tối đa 1920 px (chỉ
   video bị thu nhỏ, ảnh đầu vào giữ nguyên). Ghi số khung = số ảnh vào report.

## Phần B — Chạy 9 scene (vận hành; dừng hỏi chủ dự án ở các điểm đánh dấu)
0. **Dung lượng (dừng hỏi trước khi chạy scene đầu tiên).** Đo: cỡ ảnh mỗi scene, ước artifact mỗi scene (dựa trên Room 3,7 GB),
   chỗ trống laptop. Thử kho artifact trên USB bằng một kho tạm (`ARTIFACT_ROOT` trỏ vào thư mục trên `/media/usb`, chạy test
   `tests/test_orchestration/test_artifact_store.py` với thư mục đó) và báo kết quả. Trình chủ dự án ba lựa chọn kèm số liệu:
   (a) chạy một stack riêng cho việc này với kho artifact và DB trên USB (nếu test kho đạt); (b) dọn thêm laptop; (c) chạy lần
   lượt, xuất mẫu ra USB rồi bỏ job khỏi laptop qua thùng rác. Chờ quyết định.
1. Tạo video và nạp 9 scene bằng lệnh ở Phần A (không dùng giao diện tải lên).
2. Chạy **lần lượt từng scene** (một việc nặng một lúc, bật `thermal_guard`): preset "quay đi trong nhà"
   (`video_indoor_walkthrough`) cho Deep Blending, counter, kitchen, room, bonsai; preset vật đơn/ngoài trời phù hợp cho bicycle,
   garden, stump (chọn theo `configs/product/processing_presets_v1.json`, ghi lý do).
3. Bước cần người, làm qua API với tài khoản Reviewer local (mật khẩu chủ dự án cung cấp, chỉ dùng qua biến môi trường):
   - Xác nhận tỉ lệ mét: chấp nhận đề xuất tự động; nếu không có đề xuất thì dừng scene đó, ghi lại, sang scene khác.
   - Duyệt vật: chấp nhận các vật ứng viên như hệ thống đề xuất, không sửa tay; bấm Tạo mesh với phương pháp mặc định (không bật
     ObjectGS).
4. **Theo dõi và sửa lỗi**: mỗi lỗi ghi: scene, bước, mã lỗi, trích log, nguyên nhân. Lỗi do code pipeline: sửa trong phạm vi nhỏ,
   mỗi lỗi một commit có test đỏ trên code cũ, rồi chạy lại từ bước lỗi (dùng "Thử lại"). Lỗi cần thay đổi thiết kế (hợp đồng dữ
   liệu, migration, đổi hành vi người dùng thấy) → dừng scene đó, ghi vào report "cần Architect", chạy tiếp scene khác. Lỗi đã
   biết trong backlog (lưới va chạm bị từ chối do vết cắt không kín) → ghi nhận, không sửa.
5. Khi một scene xong: xuất gói mẫu bằng lệnh xuất hiện có vào **thư mục trên USB** `/media/usb/AI20K/real2sim_samples/<scene>/`
   (không ghi vào `data/demo/library`), kiểm trang phát lại đọc được gói.
6. Bảng kết quả trong report, mỗi scene một dòng: thời gian từng bước, VRAM đỉnh, số vật, tỉ lệ mét và nguồn, trạng thái lưới va
   chạm, lỗi gặp và cách xử lý, đường dẫn gói mẫu.

## Acceptance criteria
1. Đầu vào của cả 9 job là ảnh của dataset (đúng bản 1/2 với Mip-NeRF 360); không job nào đọc `sparse/` hay
   `poses_bounds.npy`; camera do COLMAP của pipeline tính (log COLMAP có trong artifact).
2. Mỗi project có video ghép để xem lại; pipeline không dùng video đó.
3. Mỗi scene hoặc tới được "mesh và lưới va chạm cho từng vật", hoặc có lý do dừng rõ ràng trong report.
4. Mọi sửa lỗi pipeline có test và commit riêng; không sửa lỗi đã có trong backlog.
5. Không ghi vào `data/demo/library`; không công khai mẫu.

## Tests required
Phần A:
```
.venv/bin/python -m pytest tests/test_reconstruction/test_rec02a_frame_extraction.py tests/test_reconstruction/test_rec03_colmap.py \
  tests/test_reconstruction/test_rec04_brush.py tests/test_orchestration/test_sample_export.py tests/test_orchestration -q
.venv/bin/python scripts/check_contract_mirror.py
cd frontend && ./node_modules/.bin/vitest run <test trang scene/phát lại đã sửa> && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```
Phần B: mỗi bản sửa lỗi kèm test riêng; cuối task chạy full backend một lần.

## Commit
Phần A theo từng ý; Phần B mỗi bản sửa một commit. Report cập nhật dần sau mỗi scene. Không push, không tạo branch, không
Co-Authored-By. Không khởi động lại stack `r2s-stack` khi chưa được chủ dự án đồng ý. Không xoá gì ngoài file tạm của bạn.
