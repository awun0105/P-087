# Real2Sim Studio — Toàn bộ Danh mục Tham số Cấu hình Pipeline (Config Catalog)

> **Mục đích tài liệu:**
> Rà soát, kiểm toán (audit) toàn diện và chuẩn hóa tất cả các thông số, cờ CLI (flags), hằng số cấu hình của mọi công cụ qua đầy đủ 8 chặng trong Real2Sim Studio pipeline.
> Tài liệu này là **nguồn sự thật (Source of Truth)** tối cao phục vụ cho việc:
> 1. Gỡ bỏ triệt để các điểm bị hardcode ngầm trong mã nguồn.
> 2. Đưa các thông số quan trọng lên bảng cấu hình giao diện Web Studio (`ProcessingSettings.tsx`).
> 3. Xây dựng các bộ Presets thông minh theo kịch bản sử dụng thực tế.
> 4. Cung cấp tài liệu tham chiếu kỹ thuật cho toàn bộ nhóm phát triển và các tác vụ tiếp theo.

---

## 1. Tổng quan phân loại hiện trạng cấu hình

| Ký hiệu | Ý nghĩa |
| :---: | :--- |
| 🟢 **UI** | Đã có trên giao diện Web Studio (`processing_presets_v1.json`). |
| 🟡 **PROFILE** | Nằm trong file profile JSON (`geometry_indoor_v1.json`, `upload_quality_v2.json`...) nhưng chưa cho user chọn trên UI. |
| 🔴 **HARDCODED** | Đang bị gán cứng cố định trong mã nguồn Python / Node.js CLI / C++. |

---

## 2. Chi tiết cấu hình từng chặng trong Pipeline

### Chặng 1 & 2: `ST-INPUT-VALIDATE` & `ST-FRAME-EXTRACT`
* **Công cụ thực thi:** FFmpeg (libavcodec), OpenCV, EgoBlur (mô hình làm mờ bảo mật khuôn mặt / biển số).
* **Vị trí mã nguồn:** `src/services/reconstruction/rgb/frames/frame_extraction.py`, `src/services/reconstruction/rgb/preflight/quality.py`, `configs/product/upload_quality_v2.json`.

| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `sampling.sample_fps` | 🟢 UI | `number` (fps) | `3.0` | `0.5` – `10.0` (bước 0.5) | Tần suất trích xuất ảnh từ video. Đi bộ chậm chỉ cần 2–4 fps; chạy xe hoặc camera lia nhanh cần 6–8 fps. |
| `sampling.max_frames` | 🟢 UI | `integer` (frame) | `300` | `30` – `2000` (bước 10) | Giới hạn số khung hình tối đa đưa vào tái tạo. Càng nhiều ảnh thì độ phủ càng rộng nhưng tăng thời gian COLMAP và VRAM. |
| `sampling.sampling_policy` | 🔴 HARDCODED | `choice` | `quality_sharpest_window` | `quality_accepted`<br>`quality_accepted_stride`<br>`quality_sharpest_window` | Chiến lược lấy mẫu: `quality_sharpest_window` chia video thành các cửa sổ thời gian và chọn ra bức ảnh nét nhất (ít mờ nhất) trong mỗi cửa sổ. |
| `sampling.blur_exclude_gt` | 🟡 PROFILE | `float` | `null` (tắt) | `5.0` – `50.0` | Ngưỡng Laplacian variance loại bỏ ảnh mờ chuyển động (motion blur). |
| `sampling.active_transition_px_gt`| 🟡 PROFILE | `float` (px) | `1.0` | `0.5` – `5.0` | Ngưỡng dịch chuyển điểm ảnh tối thiểu giữa 2 frame để coi camera có di chuyển. |
| `sampling.warn_active_ratio_lt` | 🟡 PROFILE | `float` | `0.5` (50%) | `0.1` – `0.9` | Cảnh báo khi tỉ lệ frame có di chuyển thấp hơn 50%. |
| `sampling.warn_static_run_gt` | 🟡 PROFILE | `integer` (frame) | `90` | `30` – `300` | Cảnh báo khi máy quay đứng yên một chỗ quá 90 frames liên tiếp. |
| `sampling.anonymize_input` | 🟢 UI | `boolean` | `false` | `true` / `false` | Tự động làm mờ khuôn mặt và biển số xe trước khi đưa vào pipeline (EgoBlur). |
| `sampling.measurement_res` | 🟡 PROFILE | `tuple` (w, h) | `(640, 360)` | `(320, 180)` – `(1280, 720)` | Độ phân giải khung hình dùng để đo nhanh độ mờ và chuyển động quang học. |

---

### Chặng 3: `ST-CAMERA-POSE` (COLMAP Structure-from-Motion)
* **Công cụ thực thi:** `colmap` (C++ runtime via Docker container / host binary).
* **Vị trí mã nguồn:** `src/services/reconstruction/adapters/colmap_runtime.py`, `src/services/reconstruction/rgb/pose/camera_pose.py`.

| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`colmap.matching_mode`** | 🔴 HARDCODED *(Đang gán cứng `sequential`)* | `choice` | **`sequential`** | **`sequential`**<br>**`sequential_vocab_tree`**<br>**`exhaustive`**<br>**`spatial`** | **Phương pháp so khớp ảnh:**<br>• `sequential`: So khớp theo chuỗi thời gian lân cận. Siêu nhanh (1–2 phút), dùng cho video đi bộ quay liên tục.<br>• `sequential_vocab_tree`: So khớp chuỗi kết hợp phát hiện vòng lặp qua từ điển Vocab Tree. Dùng cho video quay vòng tròn 360° hoặc có đoạn nhảy góc máy (chống đứt gãy mô hình).<br>• `exhaustive`: So khớp mọi cặp ảnh $O(N^2)$. Dùng cho tập ảnh tĩnh chụp rời rạc ít ảnh ($<150$ ảnh).<br>• `spatial`: So khớp theo vị trí tọa độ (nếu có GPS/prior). |
| `colmap.sequential_overlap` | 🟢 UI | `integer` (ảnh) | `10` | `3` – `30` (bước 1) | Kích thước cửa sổ so khớp lân cận trong `sequential_matcher`. Tăng lên 15–20 khi camera di chuyển nhanh hoặc quay góc rộng. |
| `colmap.camera_model` | 🟢 UI | `choice` | `SIMPLE_RADIAL` | `SIMPLE_RADIAL`<br>`OPENCV`<br>`PINHOLE`<br>`RADIAL`<br>`FULL_OPENCV`<br>`SIMPLE_PINHOLE` | Mô hình hình học camera:<br>• `SIMPLE_RADIAL`: Phù hợp điện thoại, camera tiêu chuẩn.<br>• `OPENCV`: Mô hình méo 8 tham số cho camera góc rộng / fisheye.<br>• `PINHOLE`: Ống kính không méo (ảnh đã khử méo trước). |
| `colmap.max_image_size` | 🟢 UI | `integer` (px) | `1600` | `640` – `3200` (bước 160) | Cạnh ảnh tối đa khi trích xuất đặc trưng SIFT. Lớn hơn giúp pose chính xác hơn nhưng tốn RAM và chậm hơn. |
| `colmap.max_num_features` | 🟢 UI | `integer` (điểm) | `8192` | `1024` – `32768` (bước 1024) | Số điểm đặc trưng tối đa trích xuất trên mỗi ảnh. Tăng lên 16K ở cảnh tường trơn, ít vân hoa. |
| **`colmap.vocab_tree_path`** | 🔴 HARDCODED | `filepath` | `null` | Đường dẫn file `.bin` | Đường dẫn file từ điển thị giác (`vocab_tree_clustering_flickr100k_words256K.bin`, ~112 MB) dùng cho loop detection. |
| `colmap.loop_detection_period` | 🔴 HARDCODED | `integer` (ảnh) | `10` | `2` – `50` | Chu kỳ truy vấn từ điển: cứ mỗi $N$ frame thì truy vấn Vocab Tree 1 lần để tìm liên kết vòng lặp. |
| `colmap.loop_detection_num_images`| 🔴 HARDCODED | `integer` (ảnh) | `50` | `10` – `200` | Số ảnh ứng viên tương đồng trích xuất từ từ điển để thử so khớp đóng vòng. |
| `colmap.loop_detection_min_index_distance`| 🔴 HARDCODED | `integer` (ảnh) | `50` | `10` – `200` | Khoảng cách chỉ số tối thiểu giữa 2 frame để xét là vòng lặp (tránh lãng phí truy vấn vào frame ngay sát cạnh). |
| `colmap.single_camera` | 🔴 HARDCODED | `boolean` | `true` | `true` / `false` | Coi toàn bộ video/ảnh do cùng 1 camera chụp (chia sẻ thông số tiêu cự). Luôn bật cho video monocular. |
| `colmap.use_gpu` | 🟡 PROFILE | `boolean` | `false` | `true` / `false` | Bật tăng tốc SIFT extraction & matching trên GPU (nếu môi trường runtime hỗ trợ CUDA). |
| `colmap.num_threads` | 🟡 PROFILE | `integer` (luồng) | `16` | `1` – `64` | Giới hạn số luồng CPU tối đa cho COLMAP (tự động kẹp theo số CPU core của máy worker). |
| `colmap.random_seed` | 🔴 HARDCODED | `integer` | `0` | $\ge 0$ | Hạt giống ngẫu nhiên để đảm bảo tính tái lập kết quả SfM (deterministic mapping). |
| `colmap.min_registered_ratio` | 🔴 HARDCODED | `float` | `0.5` (50%) | `0.1` – `1.0` | Ngưỡng kiểm tra an toàn: mô hình lớn nhất phải đăng ký được ít nhất 50% tổng số ảnh, nếu không sẽ báo lỗi đứt chuỗi. |
| `colmap.min_registered_frames` | 🔴 HARDCODED | `integer` | `8` (hoặc `10`) | `3` – `100` | Số lượng khung hình tối thiểu cần đăng ký thành công để coi chặng SfM đạt yêu cầu. |

---

### Chặng 4: `ST-VISUAL-RECON` (Brush 3D Gaussian Splatting & SOG Compression)
* **Công cụ thực thi:** `brush_app` (Rust/WGPU/Vulkan) & `@playcanvas/splat-transform` (Node.js/WebGPU).
* **Vị trí mã nguồn:** `src/services/reconstruction/adapters/brush_runtime.py`, `src/services/reconstruction/rgb/visual/brush.py`.

| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `brush.total_train_iters` | 🟢 UI | `integer` (bước) | `30000` | `1000` – `60000` (bước 1000) | Số bước huấn luyện 3DGS. 30.000 bước là chuẩn công nghiệp; 10.000 bước cho preview nhanh; 60.000 bước cho chất lượng tối đa. |
| `brush.max_resolution` | 🟢 UI | `integer` (px) | `1280` | `480` – `3840` (bước 160) | Độ phân giải cạnh dài của ảnh nạp vào huấn luyện. GPU 4GB VRAM nên để 1280; GPU 8GB+ để 1920–3840. |
| `brush.max_splats` | 🟢 UI | `integer` (Gaussian) | `1000000` | `100000` – `8000000` | Trần số lượng hạt 3D Gaussian. Giới hạn 1 triệu hạt giúp xem mượt trên điện thoại/web; tăng lên 3–6 triệu cho cảnh lớn. |
| `brush.sh_degree` | 🟢 UI | `integer` (bậc) | `3` | `0` – `3` (bước 1) | Bậc Spherical Harmonics biểu diễn phản chiếu ánh sáng theo góc nhìn. Bậc 3 là chuẩn; bậc 0 là màu phẳng (nhẹ nhất). |
| `brush.sog_iterations` | 🟢 UI | `integer` (vòng) | `10` | `1` – `20` (bước 1) | Số vòng k-means nén file PLY sang định dạng `.sog` cho web. 10 vòng cho tỉ lệ nén ~10x với chất lượng thị giác gần như giữ nguyên. |
| `brush.eval_split_every` | 🟡 PROFILE | `integer` \| `null` | `8` (hoặc `null`) | `2` – `30` | Giữ lại mỗi ảnh thứ $N$ không train để chấm PSNR/SSIM/LPIPS độc lập. `null` nghĩa là train trên toàn bộ ảnh. |
| `brush.refine_every` | 🔴 HARDCODED | `integer` (bước) | `200` | `50` – `1000` | Tần suất nhân bản (densify) và tỉa bớt (prune) các Gaussian trong quá trình huấn luyện. |
| `brush.growth_grad_threshold` | 🔴 HARDCODED | `float` | `0.00004` | `0.00001` – `0.0001` | Ngưỡng gradient vị trí để phân tách hạt Gaussian. Giá trị nhỏ hơn làm số hạt tăng nhanh hơn. |
| `brush.growth_stop_iter` | 🔴 HARDCODED | `integer` (bước) | `15000` | `5000` – `30000` | Bước dừng sinh thêm hạt mới, chuyển sang giai đoạn tinh chỉnh màu sắc và độ đục. |
| `brush.ssim_weight` | 🔴 HARDCODED | `float` | `0.2` | `0.0` – `1.0` | Trọng số hàm mất mát cấu trúc ảnh (SSIM loss) kết hợp với L1 loss. |
| `brush.checkpoint_every` | 🔴 HARDCODED | `integer` (bước) | `2500` | `0` – `10000` | Tần suất lưu checkpoint trung gian để phục vụ khôi phục (resume) khi có sự cố. |
| `brush.timeout_seconds` | 🔴 HARDCODED | `float` (giây) | `1800` (30 phút) | `300` – `7200` | Thời gian chạy tối đa của tiến trình Brush trước khi timeout. |
| `brush.hang_timeout_seconds` | 🔴 HARDCODED | `float` (giây) | `180` (3 phút) | `30` – `600` | Thời gian tối đa không thấy xuất log tiến độ mới trước khi coi là treo GPU (deadlock). |

---

### Chặng 5: `ST-METRIC-CANONICALIZE` (MoGe-2 Metric Scale & Ground Alignment)
* **Công cụ thực thi:** MoGe-2 ViT-B (`moge-2-vitb-normal.pt`, PyTorch CUDA), RANSAC Floor Fitting, LiDAR odometry bridge.
* **Vị trí mã nguồn:** `src/services/reconstruction/rgb/canonical/auto_scale.py`, `src/services/reconstruction/adapters/moge_runner.py`, `src/services/reconstruction/rgb/canonical/metric.py`.

| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `moge.max_frames` | 🔴 HARDCODED | `integer` (frame) | `60` | `3` – `150` | Số khung hình được chọn để dự đoán chiều sâu hệ mét (metric depth). Càng nhiều frame thì ước lượng tỉ lệ càng ít nhiễu. |
| `moge.max_points` | 🔴 HARDCODED | `integer` (điểm) | `400` | `20` – `1000` | Số điểm 3D sparse trên mỗi frame dùng để tính tỉ số tương quan khoảng cách thực (m/unit). |
| `moge.device` | 🔴 HARDCODED | `string` | `"cuda"` | `"cuda"`, `"cpu"` | Thiết bị chạy mạng neural MoGe-2. |
| `moge.fallback_to_lidar` | 🔴 HARDCODED | `boolean` | `true` | `true` / `false` | Tự động ưu tiên quỹ đạo LiDAR nếu job có upload gói LiDAR (`lidar_trajectory_alignment`). |
| `auto_scale.min_pairs_per_frame`| 🔴 HARDCODED | `integer` (cặp) | `20` | `5` – `50` | Số cặp điểm 3D thưa tối thiểu trên mỗi frame để ảnh đó được tính vào ước lượng tỉ lệ. |
| `auto_scale.min_frames` | 🔴 HARDCODED | `integer` (frame) | `3` | `2` – `10` | Số ảnh tối thiểu có đủ cặp điểm để công bố một tỉ lệ mét khả tín. |
| `auto_scale.floor_normal_max_deg`| 🔴 HARDCODED | `float` (độ) | `25.0` | `5.0` – `45.0` | Góc lệch tối đa giữa pháp tuyến bề mặt và phương thẳng đứng Z để coi điểm đó nằm trên mặt sàn. |
| `auto_scale.floor_layer_m` | 🔴 HARDCODED | `float` (m) | `0.05` (5cm) | `0.01` – `0.15` | Bề dày lớp điểm sàn khi gom cụm cao độ (bằng cỡ nhiễu của điểm thưa trên sàn). |
| `auto_scale.min_floor_points` | 🔴 HARDCODED | `integer` (điểm) | `30` | `10` – `100` | Số điểm tối thiểu trên lớp sàn để công bố mặt phẳng sàn tự động. |
| `auto_scale.ransac_iterations` | 🔴 HARDCODED | `integer` (vòng) | `300` | `50` – `1000` | Số vòng lặp RANSAC để tìm mặt phẳng sàn vững chắc nhất. |
| `floor_fit.max_noise_sigma_m` | 🟡 PROFILE | `float` (m) | `0.05` (5cm) | `0.01` – `0.15` | Ngưỡng độ gồ ghề tối đa chấp nhận được của mặt sàn RANSAC trước khi đánh dấu là không chắc chắn. |

---

### Chặng 6: `ST-RGB-GEOMETRY` (Lưới va chạm Voxel, External/Floor Fill & Marching Cubes)
* **Công cụ thực thi:** `@playcanvas/splat-transform` (Node.js/WebGPU voxelizer, marching cubes & filter).
* **Vị trí mã nguồn:** `src/services/reconstruction/rgb/geometry/voxel.py`, `configs/product/geometry_indoor_v1.json`.

| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`geometry.collision_mesh`** | 🔴 HARDCODED *(Đang hardcode `smooth`)* | `choice` | **`smooth`** | **`smooth`**<br>**`faces`** | **Cờ CLI `--collision-mesh [smooth|faces]`. Kiểu bề mặt lưới va chạm (.collision.glb):**<br>• **`smooth`**: Marching Cubes tạo lưới tam giác trơn nhẵn, bo tròn góc. Khuyên dùng cho mô phỏng di chuyển nhân vật/robot không bị vấp cạnh.<br>• **`faces`**: Giữ nguyên các mặt phẳng của khối lập phương voxel (dạng khối hộp bậc thang). Khuyên dùng cho bài toán kiểm tra chiếm chỗ voxel chính xác, hoặc game phong cách khối voxel. |
| `geometry.resolution_m` | 🟡 PROFILE *(Cần đưa lên UI)* | `number` (m) | `0.05` (5cm) | `0.02` – `0.20` | Độ phân giải của ô lưới voxel. 0.05m là chuẩn va chạm nội thất; 0.10m cho nhà kho lớn; 0.02m cho vật thể nhỏ đòi hỏi chi tiết cao. |
| `geometry.opacity` | 🟡 PROFILE | `number` | `0.1` | `0.01` – `0.5` | Ngưỡng độ đục của Gaussian để tính là vật cản đặc. |
| **`geometry.external_fill_size_m`** | 🟡 PROFILE *(Cần đưa lên UI)* | `number` (m) | `1.6` | `0.0` – `5.0` | **Kích thước hộp lấp đầy bên ngoài (`--voxel-external-fill`):**<br>Dùng cho **cảnh trong nhà (interior scenes)**. Thuật toán sẽ lấp đầy phần thể tích rỗng bên ngoài biên nhìn để đóng kín phòng, ngăn camera/robot nhìn xuyên thấu qua các bức tường chưa quét hết. Đặt `0.0` để tắt khi quay cảnh ngoài trời. |
| `geometry.floor_fill_size_m` | 🔴 HARDCODED | `number` (m) | `0.0` (tắt) | `0.0` – `5.0` | Dùng cho **cảnh ngoài trời (exterior scenes)** (`--voxel-floor-fill`). Lấp đầy các cột voxel từ dưới đáy lên sàn để tạo chân đế vững chắc cho địa hình. |
| `geometry.capsule_radius_m` | 🟡 PROFILE | `number` (m) | `0.461` | `0.1` – `0.8` | Bán kính hình viên nhộng khoét rỗng không gian di chuyển dọc theo quỹ đạo camera (`--voxel-carve`). |
| `geometry.capsule_height_m` | 🟡 PROFILE | `number` (m) | `0.308` | `0.2` – `2.0` | Chiều cao hình viên nhộng khoét rỗng không gian di chuyển dọc theo quỹ đạo camera (`--voxel-carve`). |
| `geometry.max_seed_relocation_m`| 🟡 PROFILE | `number` (m) | `1.0` | `0.1` – `3.0` | Ngưỡng dịch chuyển tối đa cho phép để tìm lại điểm mầm điều hướng khi mầm ban đầu rơi vào vật cản. |
| `geometry.seed_floor_clearance_m`| 🟡 PROFILE | `number` (m) | `0.05` (5cm) | `0.01` – `0.2` | Khoảng cách nâng điểm mầm lên phía trên mặt sàn để tránh chạm đất. |
| `geometry.crop_margin_m` | 🟡 PROFILE | `number` (m) | `6.0` | `2.0` – `20.0` | Khoảng biên nới rộng ra ngoài quỹ đạo camera để cắt lưới làm việc (`--filter-box`). |
| `geometry.crop_below_floor_m` | 🟡 PROFILE | `number` (m) | `0.5` | `0.1` – `2.0` | Khoảng cắt bỏ bên dưới mặt sàn (loại bỏ các đốm Gaussian nhiễu dưới lòng đất). |
| `geometry.crop_height_m` | 🟡 PROFILE | `number` (m) | `4.0` | `2.0` – `10.0` | Chiều cao trần cắt lưới (tính từ sàn). |
| `geometry.cleanup` | 🟡 PROFILE | `choice` | `floaters` | `floaters`, `cluster` | Thuật toán dọn các đám điểm Gaussian lơ lửng: `floaters` lọc theo mật độ lân cận; `cluster` giữ lại cụm lớn nhất từ tâm mầm. |
| `geometry.cluster_resolution_m` | 🟡 PROFILE | `number` (m) | `0.05` | `0.02` – `0.20` | Độ phân giải ô lưới dùng cho bộ lọc cụm (cluster filter). |
| `geometry.cluster_opacity` | 🟡 PROFILE | `number` | `0.1` | `0.01` – `0.5` | Ngưỡng độ đục tối thiểu khi lọc cụm. |
| `geometry.cluster_min_contribution`| 🟡 PROFILE | `number` | `0.004` | `0.001` – `0.02` | Mức đóng góp tối thiểu của Gaussian vào thể tích để được giữ lại. |
| `geometry.max_gaussian_scale_log`| 🟡 PROFILE | `number` \| `null` | `1.0` | `0.5` – `3.0` | Giới hạn log-scale tối đa của Gaussian để tránh các hạt khổng lồ làm phình lưới voxel. |

---

### Chặng 7: `ST-OBJECT-EXTRACT` (Tách vật thể SAM2, Vá nền LaMa & Lưới lồi CoACD)
* **Công cụ thực thi:** SAM2 (Meta), SAMPro3D / FlashSplat lifting, LaMa Inpainting (TorchScript), CoACD (Collision-Aware Approximate Convex Decomposition).
* **Vị trí mã nguồn:** `src/services/orchestration/scene/objectify.py`, `src/services/scene/association/lift_runner.py`, `src/services/scene/sampro3d/consolidate.py`, `src/services/reconstruction/rgb/inpaint/inpaint_runner.py`, `src/services/simulation/colliders/convex_runner.py`.

#### 7.1. Phân đoạn 2D-3D & Nhấc nhãn vật thể (SAM2 + Lift Runner)
| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`scene.max_objects`** | 🔴 HARDCODED *(Cần đưa lên UI)* | `integer` (vật) | `60` | `5` – `100` | Số lượng vật thể ứng viên tối đa cần tách khỏi căn phòng. |
| `scene.prompts_per_object` | 🔴 HARDCODED | `integer` (điểm) | `4` | `1` – `8` | Số điểm gợi ý (farthest point prompts) trên ảnh camera đưa vào SAM2 cho mỗi vật thể. |
| `scene.sam_batch` | 🔴 HARDCODED | `integer` | `32` | `4` – `64` | Kích thước lô vật thể hỏi SAM2 đồng thời. Hệ thống tự động giảm nửa nếu gặp lỗi CUDA Out-Of-Memory. |
| `scene.min_score` | 🔴 HARDCODED | `float` | `0.6` | `0.3` – `0.9` | Ngưỡng tin cậy của mặt nạ SAM2 để chấp nhận là vật thể hợp lệ. |
| `scene.max_area` | 🔴 HARDCODED | `float` | `0.35` (35%) | `0.1` – `0.8` | Diện tích tối đa của mặt nạ trên khung hình (tránh việc SAM2 nhận nhầm cả mảng tường hoặc sàn thành 1 vật thể). |
| `scene.min_contribution` | 🔴 HARDCODED | `float` | `0.05` | `0.01` – `0.2` | Tỉ lệ đóng góp tối thiểu của Gaussian vào các pixel thuộc vật thể khi render. |
| `scene.box_margin_m` | 🔴 HARDCODED | `number` (m) | `0.15` (15cm) | `0.05` – `0.5` | Khoảng nới biên tối thiểu của hộp bao vật thể để thu gom các Gaussian viền ngoài. |
| `scene.box_margin_ratio` | 🔴 HARDCODED | `float` | `0.2` (20%) | `0.05` – `0.5` | Tỉ lệ nới biên theo kích thước cạnh hộp bao vật thể. |
| `scene.majority` | 🔴 HARDCODED | `float` | `0.5` (50%) | `0.3` – `0.8` | Tỉ lệ đóng góp đa số để gán dứt khoát một Gaussian thuộc về vật thể thay vì nền. |
| `scene.min_footprint_m` | 🔴 HARDCODED | `number` (m) | `0.25` (25cm) | `0.1` – `1.0` | Kích thước cạnh đáy tối thiểu để coi một cụm điểm là vật thể độc lập (bỏ qua rác vụn). |
| `scene.max_footprint_m` | 🔴 HARDCODED | `number` (m) | `2.5` | `1.0` – `5.0` | Kích thước cạnh đáy tối đa (tránh gán nhầm kệ hàng liền khối hoặc vách ngăn). |
| `scene.max_object_height_m` | 🔴 HARDCODED | `number` (m) | `2.2` | `0.5` – `4.0` | Chiều cao tối đa của vật thể có thể nhấc rời. |

#### 7.2. Vá nền 3D Gaussian Splatting (LaMa Inpainting — `inpaint_runner.py`)
| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `inpaint.max_new_gaussians` | 🔴 HARDCODED | `integer` (hạt) | `400000` | `50000` – `1000000` | Giới hạn số lượng Gaussian mới được gieo để vá nền ở các vùng bị vật thể che khuất. |
| `inpaint.behind_object_m` | 🔴 HARDCODED | `number` (m) | `0.05` (5cm) | `0.01` – `0.2` | Khoảng cách thụt lùi của bề mặt vá vào phía sau vật thể (để vật thể không bị dính vào nền). |
| `inpaint.width` | 🔴 HARDCODED | `integer` (px) | `640` | `320` – `1280` | Độ phân giải chiều ngang khi render góc nhìn để thực hiện vá 2D qua LaMa. |
| `inpaint.stride_px` | 🔴 HARDCODED | `integer` (px) | `2` | `1` – `4` | Bước nhảy điểm ảnh khi gieo lại Gaussian mới từ ảnh 2D đã vá sang không gian 3D. |
| `inpaint.view_step` | 🔴 HARDCODED | `integer` (frame) | `1` | `1` – `5` | Bước lấy mẫu góc nhìn camera khi chạy vòng lặp vá nền tuần tự. |
| `inpaint.min_hole_px` | 🔴 HARDCODED | `integer` (px) | `40` | `10` – `200` | Diện tích lỗ thủng tối thiểu trên ảnh để kích hoạt mạng nơ-ron vá ảnh. |
| `inpaint.max_depth_m` | 🔴 HARDCODED | `number` (m) | `30.0` | `5.0` – `100.0` | Khoảng cách độ sâu tối đa để chấp nhận gieo hạt Gaussian vá nền. |
| `inpaint.scale_factor` | 🔴 HARDCODED | `float` | `0.7` | `0.2` – `1.5` | Hệ số co giãn kích thước của các Gaussian mới được gieo thêm. |
| `inpaint.opacity` | 🔴 HARDCODED | `float` | `0.9` | `0.5` – `1.0` | Độ đục gán cho các Gaussian mới được gieo để lấp đầy nền. |

#### 7.3. Phân rã khối lồi va chạm (CoACD — `convex_runner.py`)
| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`coacd.threshold`** | 🔴 HARDCODED | `float` | `0.08` | `0.01` – `0.2` | Dung sai độ lõm (concavity threshold) của CoACD. Giá trị càng nhỏ thì hình dạng va chạm càng bám sát chi tiết phức tạp của vật (ghế có chân, tay vịn). |
| **`coacd.max_convex_hull`** | 🔴 HARDCODED | `integer` (khối) | `8` | `1` – `32` | **Số khối lồi tối đa cho mỗi vật thể:** Isaac Sim và PhysX yêu cầu rigid body động phải là tập các khối lồi. Giá trị 8 là cân bằng tốt giữa độ chính xác va chạm và tốc độ mô phỏng. |
| `coacd.preprocess_resolution` | 🔴 HARDCODED | `integer` | `30` | `20` – `100` | Độ phân giải tiền xử lý làm mịn bề mặt đa tạp của vật thể trước khi phân rã. |
| `coacd.voxel_m` | 🔴 HARDCODED | `number` (m) | `0.04` (4cm) | `0.01` – `0.1` | Độ phân giải ô lưới voxel khi đóng kín ruột đám điểm Gaussian trước khi chạy CoACD. |
| `coacd.min_opacity` | 🔴 HARDCODED | `float` | `0.3` | `0.1` – `0.8` | Độ đục tối thiểu của Gaussian để lấy tâm điểm tạo lưới chiếm chỗ ban đầu. |
| `coacd.min_points` | 🔴 HARDCODED | `integer` (điểm) | `30` | `10` – `100` | Số điểm tối thiểu của vật thể để tạo collider; ít hơn sẽ bỏ qua vì là đốm nhiễu. |

---

### Chặng 8: `ST-SIMULATION-READY` (OpenUSD Packaging & Isaac Sim Physics)
* **Công cụ thực thi:** OpenUSD (`usd-core`), NVIDIA PhysX / Isaac Sim, Mesh Carving (`carve.py`), `hybrid_runner.py`.
* **Vị trí mã nguồn:** `src/services/simulation/usd/builder.py`, `src/services/simulation/usd/hybrid_runner.py`, `src/services/simulation/colliders/carve.py`.

| Mã tham số | Hiện trạng | Kiểu & Đơn vị | Giá trị mặc định | Khoảng hợp lệ | Ý nghĩa & Hướng dẫn sử dụng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `simulation.export_mode` | 🔴 HARDCODED | `choice` | `hybrid` | `hybrid`<br>`legacy_box` | Phương thức đóng gói USD: `hybrid` xuất đầy đủ ParticleField (Gaussian visual) + Convex Colliders; `legacy_box` chỉ xuất hộp va chạm sơ khai. |
| `simulation.ground_plane` | 🔴 HARDCODED | `boolean` | `true` | `true` / `false` | Tự động sinh sàn phẳng vô hạn phân tích (Analytic Ground Plane $200\times 200\text{ m}$) trong file USD stage gốc. |
| `simulation.static_friction` | 🔴 HARDCODED | `float` | `0.5` | `0.0` – `2.0` | Hệ số ma sát nghỉ (static friction) gán cho vật liệu vật lý (PhysicsMaterial) của vật thể. |
| `simulation.dynamic_friction`| 🔴 HARDCODED | `float` | `0.4` | `0.0` – `2.0` | Hệ số ma sát trượt (dynamic friction) gán cho vật liệu vật lý. |
| `simulation.restitution` | 🔴 HARDCODED | `float` | `0.0` (không nảy) | `0.0` – `1.0` | Hệ số đàn hồi va chạm (restitution) của vật thể. |
| `simulation.carve_margin_m` | 🔴 HARDCODED | `number` (m) | `0.05` (5cm) | `0.01` – `0.20` | Khoảng nới biên khi khoét bỏ phần mesh môi trường trùng lặp tại vị trí đặt vật thể (`carve.py`), tránh việc hai collider tĩnh và động đè lên nhau gây lỗi mô phỏng. |
| `simulation.meters_per_unit` | 🔴 HARDCODED | `float` | `1.0` | `1.0` | Chuẩn OpenUSD theo hệ mét ($1\text{ unit} = 1\text{ m}$). |
| `simulation.up_axis` | 🔴 HARDCODED | `string` | `"Z"` | `"Z"` | Trục thẳng đứng chuẩn của stage OpenUSD (Z-up). |

---

## 3. Kiến trúc đề xuất các bộ Preset theo Kịch bản sử dụng

Để người dùng không bị "ngợp" trước hàng chục thông số kỹ thuật, hệ thống sẽ gom thành **3 Preset kịch bản trực quan**:

### Preset 1: `video_walkthrough` (Đi bộ quay liên tục — Khuyên dùng cho người mới)
* **Kịch bản:** Người dùng cầm điện thoại đi bộ chậm, quay lia máy liên tục quanh phòng hoặc dọc hành lang.
* **Cấu hình tự động:**
  - `colmap.matching_mode` = **`sequential`** (cửa sổ overlap = 10) $\rightarrow$ Chạy siêu nhanh, xong trong 1–2 phút.
  - `brush.total_train_iters` = `30000`, `brush.max_resolution` = `1280`.
  - `geometry.collision_mesh` = **`smooth`**, `geometry.external_fill_size_m` = `1.6`.
  - `scene.max_objects` = `40`.

### Preset 2: `video_orbital_360` (Quay vòng tròn 360° / Nhảy góc máy)
* **Kịch bản:** Video quét quanh đồ vật hoặc phòng theo vòng tròn 360° (điểm kết thúc trùng điểm xuất phát), hoặc các video có đoạn lia nhanh bị nhảy góc.
* **Cấu hình tự động:**
  - `colmap.matching_mode` = **`sequential_vocab_tree`** (kích hoạt loop detection và từ điển Vocab Tree) $\rightarrow$ Tự động khâu các vòng quay xa nhau lại thành 1 mô hình duy nhất, chống gãy mô hình.
  - `colmap.sequential_overlap` = `15`.
  - `brush.total_train_iters` = `30000`.
  - `geometry.collision_mesh` = **`smooth`**, `geometry.external_fill_size_m` = `1.6`.
  - `scene.max_objects` = `60`.

### Preset 3: `photo_collection` (Tập ảnh tĩnh độc lập / Chụp bằng máy ảnh)
* **Kịch bản:** Tải lên tập ảnh chụp rời rạc từ máy ảnh DSLR (như dataset Mip-NeRF 360), không có thứ tự quay thời gian mượt mà.
* **Cấu hình tự động:**
  - `colmap.matching_mode` = **`exhaustive`** $\rightarrow$ So khớp chéo toàn bộ các cặp ảnh để tìm liên kết không gian toàn cục.
  - `colmap.max_image_size` = `2000`, `colmap.max_num_features` = `16384`.
  - `brush.total_train_iters` = `40000`, `brush.max_resolution` = `1920`.
  - `geometry.collision_mesh` = **`smooth`** (hoặc tùy chọn **`faces`** nếu cần voxel dạng khối).
  - `scene.max_objects` = `60`.

---

## 4. Tài liệu kỹ thuật tham chiếu & Bằng chứng kiểm chứng (Technical References & Evidence)

Qua đối chiếu trực tiếp mã nguồn mở từ GitHub và tài liệu chính thức:

### 4.1. PlayCanvas `@playcanvas/splat-transform` (Voxel & Collision Mesh)
* **Kho lưu trữ:** [playcanvas/splat-transform](https://github.com/playcanvas/splat-transform)
* **Thông số `--collision-mesh` (`CollisionMeshShape: "smooth" | "faces"`):**
  * `"smooth"` (Mặc định): Áp dụng thuật toán Marching Cubes kết hợp gộp đa giác đồng phẳng không tổn hao (lossless coplanar merge). Cho ra lưới tam giác mượt, số lượng đa giác thấp, phù hợp với chuyển động trơn tru trong mô phỏng vật lý.
  * `"faces"`: Xuất các mặt phẳng hộp lập phương voxel thẳng trục tọa độ (axis-aligned). Khối lượng hình học thể hiện trung thực lưới rời rạc, số lượng đa giác cao hơn, phù hợp cho bài toán kiểm tra chiếm chỗ (occupancy check) hoặc game voxel.
* **Cờ lấp đầy và khoét rỗng thể tích:**
  * `--voxel-external-fill [size]`: Flood fill từ ngoài biên với độ giãn nở `size` (mặc định 1.6m) để bịt kín lỗ thủng trên tường/cửa sổ cho cảnh trong nhà (interior).
  * `--voxel-floor-fill [size]`: Độn đặc cột voxel từ đáy lên mặt sàn cho cảnh ngoài trời (exterior / terrain), tránh việc địa hình bị rỗng chân.
  * `--voxel-carve`: Dùng hình viên nhộng quét từ vị trí mầm (`--seed-pos`) bằng thuật toán BFS để khoét rỗng không gian đi lại, ngăn nhân vật/camera bị kẹt trong khối đặc.

### 4.2. COLMAP Structure-from-Motion (Matching Modes & Vocab Tree)
* **Tài liệu chính thức:** [colmap.github.io](https://colmap.github.io/tutorial.html#feature-matching-and-view-selection)
* **Cờ CLI cho Loop Detection trong `sequential_matcher`:**
  * `--SequentialMatching.loop_detection 1`: Kích hoạt bộ phát hiện vòng lặp.
  * `--SequentialMatching.vocab_tree_path <path.bin>`: Đường dẫn bắt buộc tới file từ điển thị giác (`vocab_tree_clustering_flickr100k_words256K.bin`, dung lượng ~112 MB từ `https://demuc.de/colmap/`).
  * `--SequentialMatching.loop_detection_period <N>`: Chu kỳ truy vấn từ điển (mặc định sau mỗi 10 ảnh).
  * `--SequentialMatching.loop_detection_num_images <K>`: Số ảnh ứng viên tương đồng trích xuất từ từ điển (mặc định 30–50 ảnh).
  * `--SequentialMatching.loop_detection_min_index_distance <D>`: Khoảng cách chỉ số tối thiểu (tránh lãng phí truy vấn vào các ảnh lân cận tức thời).
* **Bằng chứng hiệu năng (Kaggle IMC Benchmark):** Từ điển 256K từ đạt trung bình ~189 inliers/cặp ảnh, hoàn tất trong 2–3 phút cho tập ảnh hàng trăm frame, giải quyết triệt để vấn đề đứt chuỗi khi camera quay lặp lại góc nhìn 360°.

### 4.3. CoACD (Collision-Aware Approximate Convex Decomposition)
* **Kho lưu trữ:** [SarahWeiii/CoACD](https://github.com/SarahWeiii/CoACD)
* **Thông số cốt lõi (`coacd.run_coacd`):**
  * `threshold` (Concavity): Ngưỡng độ lõm tối đa (0.01 – 1.0, mặc định của tác giả là 0.05; Real2Sim đang dùng 0.08). Càng nhỏ thì phân tách càng chi tiết, bám sát các chân ghế, cạnh bàn.
  * `max_convex_hull`: Số lượng khối lồi tối đa cho phép (Real2Sim đặt 8 để tối ưu hiệu năng PhysX/Isaac Sim).
  * `preprocess_resolution`: Độ phân giải làm mịn bề mặt đa tạp (20 – 100, Real2Sim đặt 30).
  * `voxel_m`: Kích cỡ voxel (0.04m) khi đóng kín thể tích rỗng của đám hạt Gaussian trước khi đưa vào CoACD.

### 4.4. OpenUSD & Isaac Sim Integration (NVIDIA PhysX)
* **Tài liệu chính thức:** [NVIDIA Isaac Sim Documentation](https://docs.omniverse.nvidia.com/isaacsim/latest/index.html)
* **Đặc tính va chạm và vật lý:**
  * RigidBody động trong PhysX không thể dùng Triangle Mesh trực tiếp (nếu gán Triangle Mesh sẽ tự động rơi về một khối Convex Hull bao ngoài, làm mất rãnh và khe hở giữa các chân ghế/vật thể). Do đó, CoACD tạo ra cụm convex hulls là giải pháp chuẩn công nghiệp.
  * Việc khoét phần mesh tĩnh của môi trường (`carve.py` với `margin_m = 0.05`) ngăn chặn hiện tượng trùng lặp collider, tránh sinh ra xung lực vô hạn (infinite collision impulse / jitter) khi khởi động mô phỏng vật lý.
