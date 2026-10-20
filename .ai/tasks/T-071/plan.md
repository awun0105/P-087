# T-071: Cấu hình xử lý theo video thật — ít đứt chuỗi COLMAP, không phải ngồi canh job

Yêu cầu của chủ dự án (2026-10-20): production đã chạy trên máy thuê RTX A5000 (24 GB VRAM, ≥32 GB RAM, ổ 100 GB,
`STUDIO_WORKERS=3`). Bộ chọn preset tự động phải (1) bao quát đúng các kiểu quay video, (2) ít thất bại giữa chừng,
(3) chất lượng tốt, (4) người dùng không phải canh job. Bản này là thiết kế để agent khác sửa; mọi quyết định đã chốt,
chỗ nào còn để chủ dự án quyết thì ghi rõ **[QUYẾT ĐỊNH]**.

Kết quả rà soát làm căn cứ (phiên 2026-10-20, không sửa code):

- Kịch bản `video_loop_360` chọn `colmap.matching_mode=sequential_vocab_tree`, nhưng image GPU
  (`Dockerfile.gpu`) và `worker.env` không có từ điển COLMAP → job thất bại ở bước COLMAP với `VOCAB_TREE_MISSING`
  sau khi đã thuê máy và tách frame.
- `scale_for_machine` (`src/services/orchestration/processing/recommender.py`) nội suy cả thông số không có trong
  công thức tài nguyên (`sampling.sample_fps`, `colmap.sequential_overlap`, `brush.total_train_iters`,
  `brush.sog_iterations`), sàn tìm kiếm là `spec.min` của schema, và hai lượt tìm (SFM rồi SPLAT) nối tiếp nên lượt
  đầu ăn hết ngân sách đĩa. Chạy thử máy 24 GB VRAM / 32 GB RAM / 20 GB đĩa, mục tiêu `machine_maximum` trả về
  1.000 bước, 480 px, 100.000 Gaussian, 1 vòng SOG mà không báo lỗi.
- `machine_maximum` thay toàn bộ số của kịch bản bằng preset `maximum` toàn cục (6 fps, 1.200 frame, 3.200 px, 60.000
  bước, 3.840 px, 6 triệu Gaussian) → mất tinh chỉnh theo kịch bản, vượt ngưỡng 3 triệu Gaussian mà viewer cảnh báo.
- Video tải lên bị thu về 720p mặc định (tối đa 1080p) trên trình duyệt (`UnifiedInputFlow.tsx` `VIDEO_PRESETS`), nên
  `colmap.max_image_size` 1.600–3.200 và `brush.max_resolution` 1.920–3.840 không có tác dụng; ước lượng VRAM vẫn tính
  theo 3.840 px nên báo sai. Bộ gợi ý không đọc thời lượng/độ phân giải video dù đã có trong
  `ServerVideoPreparationVerification.observed_video`.
- Mặc định khi người dùng không chọn kịch bản là preset `minimum_quality` (300 frame). Video dài hơn 100 giây bị thưa
  frame (`prepare_cli.target_frames` + `frame_stride`) trong khi `colmap.sequential_overlap` giữ nguyên theo số ảnh,
  nên cửa sổ ghép ảnh co lại theo thời gian → đứt chuỗi.
- COLMAP thất bại (`COLMAP_NO_MODEL`, `COLMAP_REGISTRATION_LOW` khi dưới 50% ảnh) là lỗi cứng, không thử lại. Resume
  cache (`src/services/reconstruction/resume.py`) chỉ giữ `sparse/`, không giữ `database.db`, nên thử lại chỉ có thể
  làm ngay trong cùng lượt chạy COLMAP.
- `product_preview_timeout_seconds` mặc định 36.000 s (10 giờ); hạn tự tính (`expected_duration.py`) chỉ có khi đã ≥3
  lượt đo cùng công cụ cùng GPU.

## Thiết kế

### Nguyên tắc
- COLMAP là nơi lỗi nhiều nhất và rẻ hơn Brush nhiều lần: mua an toàn ở COLMAP (cửa sổ ghép ảnh tính theo **giây**,
  nhiều điểm đặc trưng, khép vòng khi có từ điển, thang thử lại tự động), giữ Brush ở mức chuẩn.
- Bộ gợi ý nhận **sự thật của video** (thời lượng, độ phân giải) và **sự thật của worker** (VRAM/RAM/đĩa, có từ điển
  hay không), không chỉ câu trả lời của người dùng.
- Chỉ thu nhỏ những thông số có trong công thức tài nguyên; thông số quyết định độ ổn định không bao giờ bị hạ thầm.
- Mọi quyết định của bộ gợi ý trả về dạng `notes` để giao diện nói thẳng với người dùng.

### A. Bộ gợi ý và bộ thu nhỏ theo máy (API, không cần image mới)

A1. `ScenarioPreferences` (`processing/models.py`):
- `target_capacity: Literal["standard", "high_quality"]` thay cho ba mức cũ. Không giữ tương thích giá trị cũ (chỉ
  giao diện gọi; cập nhật `frontend/src/lib/contracts/studio.ts` cùng lúc).
- Thêm `video: VideoFacts | None = None` với `VideoFacts(duration_seconds: float > 0, display_width: int ≥ 16,
  display_height: int ≥ 16, frame_rate: float | None)`. Giao diện lấy từ
  `video_preparation_verification.observed_video` của file video trong candidate đang chọn
  (`duration_seconds = duration_ticks × time_base`). `photo_set` gửi `video=None` và thêm `photo_count: int | None`.
- `input_type` giữ ba giá trị; thêm `"video_object_orbit"` **không** cần — quét một vật thể vẫn là
  `subject_scope=single_object`.

A2. `recommend_preset` trả `Recommendation(name, params, notes: list[str], fallbacks: list[str])`; API
`ProcessingSuggestion` thêm `notes: list[str]`. Thứ tự tính:
1. Chọn catalog entry như hiện tại (`select_preset_name`).
2. Áp override theo kịch bản như hiện tại (ghép ảnh, số vật, lấp sàn/tường, mặt sàn).
3. **Theo worker:** nếu `colmap.matching_mode == "sequential_vocab_tree"` mà
   `capability.colmap_vocab_tree_available` không phải `True` → đổi thành `"sequential"`, ghi note
   "Máy xử lý chưa có từ điển khép vòng; dùng ghép liên tiếp, thang thử lại sẽ dùng ghép mọi cặp nếu đứt chuỗi".
4. **Theo video** (chỉ khi `video` có):
   - `wanted = ceil(duration_seconds × sampling.sample_fps)`;
     `sampling.max_frames = clamp(wanted, 60, cap)` với `cap` là `sampling.max_frames` của kịch bản (sau bước 5 nếu
     `high_quality`). Làm tròn lên bội của 10 (step của schema).
   - Nếu `wanted > cap`: `effective_fps = cap / duration_seconds`; ghi note
     "Video {m} phút {s} giây: lấy {effective_fps:.1f} khung hình mỗi giây (tối đa {cap} ảnh)".
     Đặt `colmap.sequential_overlap = clamp(ceil(OVERLAP_SECONDS[name] × effective_fps), overlap_kịch_bản, 30)` —
     tức không bao giờ thấp hơn kịch bản, chỉ tăng khi fps hiệu dụng thấp. `OVERLAP_SECONDS`:
     walkthrough 5, orbital 7, single_object 7, outdoor 4.
   - `long_edge = max(display_width, display_height)`; `colmap.max_image_size = min(kịch bản, snap_up(long_edge,
     160))`; `brush.max_resolution = min(kịch bản, snap_up(long_edge, 160))`, cả hai kẹp trong [min, max] của
     schema. Ghi note khi bị hạ: "Video {w}×{h}: độ phân giải huấn luyện {x} px".
   - `photo_set` với `photo_count > 300` → note "Bộ ảnh {n} ảnh: ghép mọi cặp sẽ mất nhiều giờ; nên dưới 300 ảnh"
     (không đổi chế độ; vocab-tree matcher thuần chưa nối vào pipeline).
5. **`high_quality`** = giá trị kịch bản nhân hệ số, kẹp theo schema: `sampling.max_frames ×1.5`,
   `colmap.max_num_features ×1.5` (trần 16.384), `brush.total_train_iters +10.000`, `brush.max_splats ×1.5`
   (trần 4.000.000 — viewer), `brush.sog_iterations` giữ. Không đụng fps, overlap, độ phân giải (đã kẹp theo video).
6. `scale_for_machine` mới (A3).

A3. `scale_for_machine` viết lại:
- `RESOURCE_KEYS = ("sampling.max_frames", "colmap.max_image_size", "colmap.max_num_features",
  "brush.max_resolution", "brush.max_splats")` — đúng các khóa `estimate_gb` dùng. Mọi khóa khác giữ nguyên.
- Sàn = giá trị của preset `minimum_quality` (không phải `spec.min`), riêng `sampling.max_frames` sàn =
  `min(minimum_quality, giá trị đã tính theo video)` để video ngắn không bị đẩy lên 300.
- **Một lần bisection chung** cho cả năm khóa với cùng `t ∈ [0,1]` giữa sàn và mục tiêu, kiểm `_fits` trên cả
  VRAM/RAM/đĩa; bỏ hai lượt SFM/SPLAT nối tiếp. Giữ 24 vòng và `interpolate` + snap theo step.
- Ngân sách: như hiện tại (mốc rảnh nếu có, không thì tổng máy). Sàn không vừa → `RecommendationUnavailableError`
  (giữ). `capability is None` → trả sàn kèm note "Chưa có số đo máy xử lý; dùng mức an toàn".
- Khi `t < 1` ghi note "Máy xử lý giới hạn {tài nguyên}: giảm {khóa} xuống {giá trị}" cho từng khóa bị hạ.
- `maximum_for_machine` (dùng cho `presets["machine_maximum"]` trong `/processing/options`) chuyển sang gọi cùng bộ
  bisection này với mục tiêu = preset `maximum`; xóa `_search` cũ. Test
  `test_four_and_twenty_four_gb_workers_scale_training_separately_from_ram` đổi kỳ vọng: máy 4 GB VRAM vẫn phải nhỏ
  hơn máy 24 GB ở ba khóa Brush, `sampling.max_frames` có thể khác nhau (không còn tách trục).

A4. `MachineCapability` thêm `colmap_vocab_tree_available: bool | None = None` (None = worker cũ chưa báo). Worker đo
trong `capability.py` khi báo cấu hình: `get_vocab_tree_path(format)` theo phiên bản COLMAP của runtime (đọc từ
`colmap --version` một lần, cùng cách `colmap.py::_vocabulary` chọn faiss/flann) và `verify_vocab_tree` đạt.

A5. `configs/product/processing_presets_v1.json` — giá trị mới (chỉ liệt kê khóa đổi; khóa khác giữ nguyên):

| Preset | sample_fps | max_frames | max_image_size | max_num_features | sequential_overlap | matching_mode | total_train_iters | max_resolution | max_splats |
|---|---|---|---|---|---|---|---|---|---|
| minimum_quality (sàn) | 3 | 300 | 1280 | 8192 | 10 | sequential | 30000 | 1280 | 1000000 |
| maximum (trần) | 6 | 1500 | 1920 | 16384 | 30 | sequential | 50000 | 1920 | 4000000 |
| video_indoor_walkthrough | 3 | 800 | 1920 | 12288 | 15 | sequential_vocab_tree | 30000 | 1920 | 2000000 |
| video_indoor_orbital_360 | 3 | 600 | 1920 | 8192 | 20 | sequential_vocab_tree | 30000 | 1920 | 2000000 |
| video_single_object | 3 | 300 | 1920 | 8192 | 20 | sequential | 30000 | 1920 | 1500000 |
| video_outdoor_forward | 4 | 800 | 1920 | 16384 | 12 | sequential | 30000 | 1920 | 3000000 |
| photo_collection_indoor | 3 | 600 | 1920 | 12288 | 10 | exhaustive | 30000 | 1920 | 2000000 |
| photo_collection_outdoor | 3 | 800 | 1920 | 16384 | 10 | exhaustive | 30000 | 1920 | 3000000 |

- `schema.max` của `sampling.max_frames` giữ 2000; `colmap.sequential_overlap` max 30; `brush.max_resolution` max hạ
  3840 → 1920 (video vào tối đa 1080p); `colmap.max_image_size` max hạ 3200 → 1920 cùng lý do; `brush.max_splats` max
  hạ 8.000.000 → 4.000.000. `resource_model.note` ghi thêm ngày đổi và lý do.
- Đi bộ trong nhà dùng khép vòng vì gần như luôn quay lại chỗ cũ; worker chưa có từ điển thì A2 bước 3 tự hạ về
  `sequential`.
- `fixed.colmap.min_registered_ratio` giữ 0.5 (xem C3).

A6. `/processing/suggest` trả `notes`; `/processing/options` giữ nguyên hình dạng, `presets` vẫn gồm
`minimum_quality`, `maximum`, các kịch bản và `machine_maximum`.

### B. Từ điển COLMAP có sẵn trên worker (cần image GPU mới + chứng nhận lại)

B1. Đóng từ điển vào image: `Dockerfile.gpu` thêm bước tải `vocab_tree_*_flickr100K_words256K.bin` đúng định dạng với
COLMAP trong image (≥3.12 → faiss, ngược lại flann; `scripts/assets/download_vocab_tree.py --format …`), đặt tại đường
dẫn mặc định `data/checkpoints/colmap/` mà `vocab_tree.py` đọc, kiểm sha256 ghim trong `vocab_tree.py`. 112 MB, chấp
nhận tăng image. Không dùng cách fetch lúc khởi động (EgoBlur) vì file cố định theo phiên bản COLMAP của image.
B2. Preflight chứng nhận (`scripts/gpu/*preflight*`, catalog release) thêm mục "từ điển COLMAP: có, checksum khớp,
định dạng khớp COLMAP"; mục này bắt buộc đạt.
B3. `worker.env` không cần biến mới (dùng đường dẫn mặc định). Khi image mới lên: catalog mới, chứng nhận A5000, cập
nhật secret watchdog theo quy trình trong memory `prod-deploy-gcp-vm`.

### C. Thang thử lại COLMAP ngay trong lượt chạy (`src/services/reconstruction/adapters/colmap.py`)

C1. Sau `mapper`, nếu `_models` rỗng **hoặc** mô hình tốt nhất dưới ngưỡng (`min_registered_frames` /
`min_registered_ratio`) thì chạy thang trên cùng `database.db` (đặc trưng đã trích, không trích lại; matcher chạy lại
chỉ thêm cặp vào DB):
- Bậc 1: `sequential_matcher` với `overlap = min(30, overlap × 2)`, bật khép vòng nếu từ điển có trên worker
  (`get_vocab_tree_path` đúng định dạng; nếu không thì không bật). `mapper --output_path sparse_r1`.
- Bậc 2 (chỉ khi số ảnh ≤ 400): `exhaustive_matcher`, `mapper --output_path sparse_r2`.
- Dừng ở bậc đầu tiên đạt ngưỡng. Mỗi bậc gọi `self.deps.process.run` như lệnh thường; `_models` đọc thư mục của bậc
  đó (tham số hóa đường dẫn `sparse`).
- `reconstruction_commands` / `_matching_command` (`colmap_runtime.py`) nhận `overlap` và `loop_detection` tường
  minh để tái dùng cho bậc 1; thêm hàm `retry_matching_command(config, match, *, overlap, loop_detection)`.
- Vocab cho bậc 1 khi config gốc là `sequential`: dùng lại `_vocabulary` với một bản `config` sao chép có
  `matching_mode="sequential_vocab_tree"`; thiếu từ điển thì bậc 1 chạy không khép vòng (không ném
  `VOCAB_TREE_MISSING`).
C2. Payload pose (`_payload`) thêm `retry_ladder: [{step, matching_mode, overlap, registered_frames, input_frames}]`
và `registered_ratio`; `select_sparse_model` nhận mô hình của bậc thành công. Resume cache key không đổi (thang là
hàm tất định của config + frame set); `store_colmap` lưu thư mục sparse của bậc thành công dưới tên `sparse/`
(đổi tên trước khi lưu).
C3. Sau thang vẫn dưới ngưỡng → `COLMAP_REGISTRATION_LOW` như cũ, `details` thêm `retry_ladder` để người dùng và log
thấy đã thử gì. **[QUYẾT ĐỊNH]** Có chấp nhận mô hình ≥35% ảnh (và ≥ `min_registered_frames`) kèm cảnh báo
"vùng thiếu sẽ mờ" thay vì thất bại hay không. Thiết kế này **không** làm việc đó; nếu chủ dự án đồng ý, thêm
`fixed.colmap.accept_registered_ratio_after_retry: 0.35` và cờ `registration_warning` trong pose payload → giao diện.
C4. Lỗi khép vòng khi có từ điển nhưng định dạng sai (`VOCAB_TREE_INCOMPATIBLE`) vẫn là lỗi cứng (lỗi deploy).
C5. Thời gian: `product_preview_timeout_seconds` mặc định 36.000 → 14.400 (4 giờ; A5000 với cấu hình trần ở A5 chạy
dưới 2 giờ). Hạn tự tính theo `expected_duration` vẫn ưu tiên khi đủ mẫu. `worker.env` production đặt
`PRODUCT_PREVIEW_TIMEOUT_SECONDS=14400`.

### D. Giao diện (`ProcessingSettings.tsx`, `useProcessingForm.ts`, `UnifiedInputFlow.tsx`)

D1. Khi bước "Thông số xử lý" mở với tuyến video: tự gọi `/processing/suggest` ngay với
`{input_type:"video_continuous", environment:"indoor", subject_scope:"full_room", target_capacity:"standard",
video:<observed_video>}`; giá trị khởi đầu là gợi ý đó, không còn là `minimum_quality`. Bộ câu hỏi hiện bốn lựa chọn
đã chọn sẵn. Có draft khôi phục (`restored`) thì giữ draft như hiện nay, nhưng vẫn gửi `video` khi người dùng đổi
kịch bản.
D2. "Mức xử lý" còn hai lựa chọn: "Chuẩn (khuyên dùng)" và "Chất lượng cao hơn (lâu hơn, nặng hơn)". Bỏ "Tối thiểu
cho máy này" và "Tối đa cho máy này" khỏi lựa chọn chính; hai preset đó chỉ còn trong `options.presets` cho phần nâng
cao (nút preset ẩn như hiện nay khi có `onScenario`).
D3. Dưới dòng "Đã áp dụng" hiện danh sách `notes` (từng dòng, giọng cảnh báo khi là giảm thông số). Có hạn tự tính
(`expected_duration`, nếu API trả) thì hiện "Thời gian dự kiến ≈ … phút"; **không** bịa số khi API không có.
D4. `scenarioLabel` map `standard → "Chuẩn"`, `high_quality → "Chất lượng cao hơn"`.
D5. **[QUYẾT ĐỊNH]** Mặc định độ phân giải tải lên 720p → 1080p (`VIDEO_PRESETS`, hai chỗ `preset: "720p"` trong
`UnifiedInputFlow.tsx`). Thiết kế khuyến nghị 1080p vì chất lượng scene tăng rõ, đổi lại file tải lên lớn hơn
(~8 Mbps). Nếu đồng ý, đổi mặc định và chữ "mặc định" trong `VIDEO_PRESETS`.
D6. Giao diện tiến trình: khi pose payload có `retry_ladder` không rỗng, bước COLMAP hiện "Đã tự thử lại ghép ảnh
({n} lần)".

### E. Kiểm thử

- `tests/test_orchestration/test_preset_recommender.py`: viết lại cho hai mức; thêm case (a) máy 24/32/20 GB không
  bao giờ trả về dưới sàn `minimum_quality` ở bất kỳ khóa nào; (b) `sample_fps`, `sequential_overlap`,
  `total_train_iters`, `sog_iterations` không đổi sau thu nhỏ; (c) video 300 s @3 fps với cap 800 → 800 frame,
  overlap = ceil(5 × 800/300) = 14 ≥ 15 → 15 (không thấp hơn kịch bản); video 600 s → overlap 20 (walkthrough);
  (d) video 20 s → max_frames 60; (e) 720p → max_image_size 1280, max_resolution 1280 và ước lượng VRAM giảm;
  (f) worker không có từ điển → `sequential` + note; (g) `capability=None` → sàn + note.
- `tests/test_orchestration/test_processing_presets_schema.py`: bảng A5 hợp lệ, mọi preset trong [min,max] mới.
- `tests/test_reconstruction/test_rec03_colmap.py` + `test_colmap_matching_modes.py`: thang thử lại — bậc 1 chạy khi
  mapper lần đầu không ra model; bậc 2 chỉ khi ≤400 ảnh; dừng ở bậc đầu đạt; payload có `retry_ladder`; cache lưu
  sparse của bậc thành công; không có từ điển thì bậc 1 không bật khép vòng.
- `tests/test_orchestration/test_processing_config.py`: `colmap_vocab_tree_available` đi qua `MachineCapability`.
- Frontend: `processing-settings.test.tsx`, `ux-processing-form.test.tsx`, `unified-input-flow.test.tsx` — tự gợi ý
  khi mở bước, hai mức, hiện notes, không gọi evaluate thừa sau suggest.
- Kiểm thử thật trên A5000 sau image mới: ba video (đi bộ 3 phút trong nhà, quay vòng một vật, ngoài trời 4 phút) với
  mức "Chuẩn"; ghi `registered_ratio`, `retry_ladder`, thời gian từng bước vào `.ai/tasks/T-071/report.md`. Đây là
  lúc điều chỉnh lại bảng A5 nếu cần — các số trong bảng là điểm xuất phát, không phải số đo.

### F. Thứ tự làm và đưa lên

1. A + D (API + frontend, không cần image mới) → deploy API và Studio trước; worker cũ chưa báo
   `colmap_vocab_tree_available` nên mọi kịch bản tự về `sequential` — an toàn.
2. B + C + C5 → build image GPU từ commit cuối, chứng nhận A5000 (preflight có mục từ điển), catalog mới, worker.env,
   secret watchdog, rồi push theo quy trình `prod-deploy-gcp-vm`.
3. Chạy ba video thử (E), viết report, chỉnh bảng A5 nếu số đo cho thấy cần.
4. Cập nhật `docs/execution/CONFIG_CATALOG.md` (đang lỗi thời: ghi `matching_mode` gán cứng) và `docs/PIPELINE.md`
   phần chọn thông số.

### Ngoài phạm vi (ghi để không lan)
- Vocab-tree matcher thuần cho bộ ảnh lớn, spatial matcher, hierarchical mapper.
- Đổi `eval_split_every` (Brush giữ 1/8 ảnh để đánh giá, không huấn luyện) — cân nhắc ở task riêng.
- Lọc mờ `blur_exclude_gt` trong `upload_quality_v2.json`.
