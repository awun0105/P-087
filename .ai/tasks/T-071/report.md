# T-071: Báo cáo thực hiện (phần A–E, chưa có image GPU mới)

## Tóm tắt
Đã làm đủ các phần A, B, C, D, E trên nhánh `develop`, chia thành 9 commit, chưa push. Không build image, không đụng production, `deploy/`, `.github/` hay `admission.py`. Chủ dự án đã chốt hai điểm: C3 = có, D5 = có.

## A. Bộ gợi ý và bộ thu nhỏ theo máy
- `src/services/orchestration/processing/models.py:19` thêm `VideoFacts` (thời lượng > 0, cạnh ảnh ≥ 16, số khung/giây > 0 hoặc để trống).
- `models.py:30` `ScenarioPreferences`: còn hai mức `standard`/`high_quality`; thêm `video` và `photo_count`. Giá trị cũ (`balanced`, `machine_maximum`, `minimum_quality`) bị từ chối.
- `models.py:207` `MachineCapability.colmap_vocab_tree_available` (None = worker cũ chưa báo).
- `models.py:131`: kiểm `fixed.colmap.accept_registered_ratio_after_retry` phải nằm trong (0, `min_registered_ratio`].
- `src/services/orchestration/processing/resources.py:41` `RESOURCE_KEYS`: đúng năm khóa mà công thức tài nguyên dùng.
- `resources.py:267` `resource_budget`: dùng mốc lúc máy rảnh nếu có, không thì tổng máy; mốc rảnh thiếu số đo thì trả None.
- `resources.py:280` `fit_to_budget`: một lần chia đôi chung (24 vòng) cho cả năm khóa.
- `resources.py:316` `maximum_for_machine`: dùng chung bộ chia đôi đó, đích là preset `maximum`, sàn là `minimum_quality`. Đã xóa hàm `_search` cũ tách hai trục.
- `src/services/orchestration/processing/recommender.py`: viết lại theo đúng thứ tự A2.
  - `recommend_preset` (dòng 189) trả về `Recommendation(name, params, notes, fallbacks)`.
  - Mức chất lượng cao (dòng 92): số frame ×1,5; số điểm đặc trưng ×1,5 (trần 16.384); số bước +10.000; số Gaussian ×1,5 (trần 4 triệu). Không đụng fps, overlap, độ phân giải.
  - Worker không có từ điển (dòng 220): đổi `sequential_vocab_tree` thành `sequential` và thêm ghi chú.
  - Theo video (dòng 106): số frame theo thời lượng thật (sàn 60, làm tròn lên bội của 10). Cửa sổ ghép ảnh tính theo giây (`OVERLAP_SECONDS`, dòng 30), không bao giờ thấp hơn kịch bản, trần 30. Độ phân giải không vượt cạnh dài của video.
  - Bộ ảnh trên 300 ảnh: thêm ghi chú.
  - `scale_for_machine` (dòng 145): chỉ thu nhỏ năm khóa tài nguyên. Không có số đo máy thì trả sàn kèm ghi chú "Chưa có số đo máy xử lý; dùng mức an toàn". Khi phải giảm thì ghi "Máy xử lý giới hạn …: giảm … xuống …".
- `src/services/orchestration/processing/capability.py:199,209`: worker đọc phiên bản COLMAP một lần mỗi tiến trình, kiểm từ điển đúng định dạng và đúng checksum; `probe` (dòng 280) gửi cờ này lên.
- `src/api/studio/processing.py:46,107`: `/processing/suggest` trả thêm `notes`. `/processing/options` giữ nguyên hình dạng.
- Bảng A5 đã đưa vào `configs/product/processing_presets_v1.json`:
  - trần `colmap.max_image_size` và `brush.max_resolution` là 1920, trần `brush.max_splats` là 4 triệu;
  - thêm `fixed.colmap.accept_registered_ratio_after_retry = 0.35`;
  - `resource_model.note` ghi ngày đổi và lý do.

## B. Từ điển COLMAP có sẵn trong image
- `configs/runtime/pins.env:22`: `COLMAP_VOCAB_FORMAT=faiss` (image ghim là COLMAP 4.x, từ 3.12 trở lên dùng FAISS).
- `Dockerfile.gpu:73-84`: chép `vocab_tree.py` và script tải, đọc định dạng từ `pins.env`, tải về đúng đường dẫn mặc định `<repo>/data/checkpoints/colmap/` mà `vocab_tree.py` đọc, kiểm lại bằng `--check-only`, rồi xóa file khóa. Script chỉ công bố file khi đúng kích thước và sha256 ghim trong `vocab_tree.py`; sai thì build lỗi. Bước này nằm trước `COPY . .`; thư mục `data/` không vào build context nên lớp code không đè lên file. Image tăng khoảng 72 MB (bản FAISS).
- `scripts/kaggle/preflight.py:114,262`: mục bắt buộc "Từ điển COLMAP". Mục này kiểm file có mặt, đúng checksum, và đúng định dạng theo phiên bản COLMAP thật của binary. Nếu có đặt `PRODUCT_COLMAP_VOCAB_TREE` thì dùng đường dẫn đó. Mục này không đạt thì máy GPU không khởi động worker (entrypoint chạy với `set -e`).
- `src/services/reconstruction/adapters/vocab_tree.py:40,48`: thêm `vocabulary_format` và `file_format`, dùng chung cho REC-03, worker và preflight.

## C. Thang thử lại COLMAP trong cùng một lượt chạy
- `src/services/reconstruction/adapters/colmap.py:295` `_retry_ladder`: chạy khi `mapper` lần đầu không ra mô hình nào, hoặc mô hình tốt nhất dưới ngưỡng. Thang dùng lại `database.db`, không trích đặc trưng lại.
  - Bậc 1: ghép liên tiếp với overlap = max(overlap, min(30, overlap × 2)). Chỉ bật khép vòng khi binary có cờ khép vòng và worker có từ điển (`_loop_vocabulary`, dòng 357). Thiếu từ điển thì chạy không khép vòng, không báo lỗi. Từ điển sai định dạng vẫn là lỗi cứng.
  - Bậc 2: ghép mọi cặp, chỉ khi số ảnh không quá 400 (`EXHAUSTIVE_RETRY_MAX_IMAGES`, dòng 76).
  - Dừng ở bậc đầu tiên đạt ngưỡng. Không bậc nào đạt thì giữ bậc có nhiều ảnh nhất.
  - Bậc được chọn được đổi tên thành `sparse/` (mô hình lần đầu chuyển sang `sparse_r0/`), nên resume cache lưu đúng mô hình đó; khóa cache không đổi.
  - Config ghép mọi cặp (bộ ảnh) không chạy thang. Job dựng bám quỹ đạo và job dùng lại cache cũng không chạy thang.
- `src/services/reconstruction/adapters/colmap_runtime.py:198,204,237`: thêm `mapper_command(output)` và `retry_matching_command(overlap, loop_detection)`; `_matching_command` nhận `overlap` và `loop_detection` tường minh. Bộ canh treo theo dõi thêm thư mục `sparse_r1` và `sparse_r2` (dòng 40).
- `src/services/reconstruction/rgb/pose/camera_pose.py:52` `ColmapConfig.accept_registered_ratio_after_retry`: để trống thì không ghi ra JSON, nên config cũ giữ nguyên bytes và checksum. Không được lớn hơn `min_registered_ratio`.
- `camera_pose.py:114,149,151`: `ColmapRetryStep`; trong `CameraPoseArtifact` thêm `retry_ladder` và `registration_warning` (chỉ ghi ra JSON khi có). Bước kiểm artifact nhận mô hình dưới `min_registered_ratio` chỉ khi có cảnh báo và tỉ lệ ≥ 0,35. `registered_ratio` vẫn có sẵn trong payload.
- C3 (đã chốt: có): sau thang thử lại, mô hình có ≥ 35% ảnh và ≥ `min_registered_frames` được nhận kèm `registration_warning`. Dưới mức đó vẫn báo `COLMAP_REGISTRATION_LOW`, `details` có thêm `retry_ladder`. Lỗi `COLMAP_NO_MODEL` cũng có `retry_ladder`.
- Hiển thị cho người dùng:
  - `src/services/orchestration/jobs/stage_views.py:49-51`: lớp camera có `registered_ratio`, `retry_count`, `registration_warning`;
  - `src/services/reconstruction/views.py:36`: hàm `pose_registration` đọc ba số này từ artifact;
  - `src/services/orchestration/evaluation/scorecard.py:153`: bảng đánh giá ghi "warn" thay vì "fail" khi mô hình được nhận kèm cảnh báo, và thêm chỉ số "Đã tự thử lại ghép ảnh (n lần)";
  - `src/services/orchestration/evaluation/advice.py`: thêm khuyến nghị "vùng thiếu ảnh có thể bị mờ hoặc thủng";
  - `src/services/reconstruction/quality.py:33`: `PoseQuality` có thêm `retry_steps`, `registration_warning`, `accept_registered_ratio`.
- C5: `src/config.py:75` `product_preview_timeout_seconds` mặc định đổi từ 36000 thành 14400. Đổi luôn ở `scripts/gpu/docker_entrypoint.sh`, `scripts/gpu/studio.env.example` và `.env.example`. Test cũ yêu cầu "giới hạn preview ≥ COLMAP 14400 + Brush 21600" (T-043) mâu thuẫn với C5, nên đã viết lại thành: preview = 14400 và giới hạn COLMAP ≤ preview.

## D. Giao diện
- D1: `frontend/src/features/studio/useProcessingForm.ts:27` `videoFactsFromObserved` (đổi `duration_ticks × time_base` ra giây).
  - Dòng 207: khi mở bước cấu hình với tuyến video, tự gọi gợi ý với kịch bản mặc định (`ProcessingSettings.tsx:30`) và video do server đo. Mỗi video chỉ gọi một lần.
  - Có draft khôi phục thì giữ draft; mọi lần đổi kịch bản vẫn gửi `video`. Bộ ảnh gửi `video: null`.
  - Dòng 124: bộ giá trị đã có ước lượng đúng (từ gợi ý hoặc ước lượng mặc định) thì không gọi ước lượng lại.
  - `frontend/src/features/studio/UnifiedInputFlow.tsx:397`: truyền video vào hook.
- D2 và D4: `frontend/src/features/studio/ProcessingSettings.tsx:231` chỉ còn hai lựa chọn "Chuẩn (khuyên dùng)" và "Chất lượng cao hơn (lâu hơn, nặng hơn)". Dòng 206 đổi nhãn thành "Chuẩn" / "Chất lượng cao hơn".
- D3: `ProcessingSettings.tsx:119` danh sách ghi chú dưới dòng "Đã áp dụng"; ghi chú báo giảm thông số hoặc giới hạn thì hiện màu cảnh báo. Không hiện thời gian dự kiến vì API không trả số này, không bịa số.
- D5 (đã chốt: có): mặc định 1080p ở `UnifiedInputFlow.tsx:62,156,666`, chữ "mặc định" và câu giới thiệu đổi theo; `CaptureGuide.tsx` cũng sửa chữ. Không đổi `VIDEO_NORMALIZATION_PROFILE_V1.default_preset` vì profile đó có checksum.
- D6 và C3: `frontend/src/features/studio/StageViewer.tsx:65,94` ở bước camera hiện "Đã tự thử lại ghép ảnh (n lần)" và "Vùng thiếu ảnh có thể bị mờ hoặc thủng (COLMAP dựng được vị trí cho x% ảnh)".
- Hợp đồng `frontend/src/lib/contracts/studio.ts`: thêm `VideoFacts`, `notes` (server cũ không gửi thì coi là rỗng), `colmap_vocab_tree_available`, và ba trường của lớp camera (có kiểm kiểu khi đọc).

## E. Kiểm thử (kết quả chạy thật)
- Backend nhắm đích:
  - recommender, preset, config, API tùy chọn, e2e, REC-03, chế độ ghép, tài sản từ điển: 203 đạt;
  - các test thang thử lại: 63 đạt;
  - đánh giá và chỉ số chất lượng: 28 đạt;
  - hướng hiển thị preview: 6 đạt;
  - tài sản từ điển: 18 đạt.
- Toàn bộ test lần đầu: 4328 đạt, 1 lỗi. Lỗi ở `tests/integration/test_studio_processing_job.py` vì test còn kỳ vọng sàn cũ 1600; sàn mới theo A5 là 1280. Đã sửa ở commit da0d69a1.
- Chạy lại toàn bộ: `4329 passed, 41 skipped, 15 warnings in 762.61s`.
- `ruff check`: đạt. `ruff format --check`: 870 file đã đúng định dạng.
- `check_contract_mirror`: PASS — 5 enum, 9 model khớp.
- Frontend: lint 0 lỗi (7 cảnh báo đều có từ trước, không thuộc file sửa ở đây); typecheck đạt; vitest 125 file, 1121 test đạt.
- Kiểm checksum bằng file thật trên máy local:
  - `download_vocab_tree.py --format faiss --check-only` và `--format flann --check-only` đều khớp sha256 ghim;
  - kiểm file FAISS theo pin FLANN thì thoát mã 1 (đúng như mong đợi);
  - chạy thử chuỗi lệnh `RUN` của Dockerfile bằng `sh`: thành công, không tải lại vì file đã có.
- Không có `hadolint` trên máy; Dockerfile được kiểm bằng cách đọc lại và bằng test khóa thứ tự bước, đường dẫn và lệnh.

## Quyết định tự chọn hoặc chỗ kế hoạch mâu thuẫn
- Kế hoạch ghi "video 600 s → overlap 20", nhưng chính công thức của kế hoạch cho ceil(5 × 800/600) = 7, giữ sàn kịch bản thì ra 15. Đã làm theo công thức; test ghi rõ lý do.
- Sàn thu nhỏ: lấy giá trị nhỏ hơn giữa `minimum_quality` và giá trị đã tính, áp cho cả năm khóa (không chỉ số frame), để video 720p không bị đẩy lên 1280 px.
- Chỉ nhận mô hình 35% sau khi thang đã chạy, hoặc khi mô hình lấy lại từ cache. Bộ ảnh (ghép mọi cặp) không có thang nên vẫn báo lỗi như cũ.
- Đọc phiên bản COLMAP bằng `colmap -h` (cùng cách REC-03 đang dùng) thay vì `colmap --version`.
- Định dạng từ điển ghim trong `pins.env` thay vì đọc `colmap -h` lúc build, vì binary có thể không chạy được khi không có GPU; preflight kiểm lại theo binary thật.
- `maximum_for_machine` trả preset tối thiểu khi ngay cả sàn cũng không vừa máy (trước đây hạ xuống giới hạn nhỏ nhất của schema).
- Video quay liên tục giữ cách ghép của kịch bản, nên đi bộ trong nhà dùng khép vòng khi worker có từ điển.

## Chưa làm
- Cập nhật `docs/execution/CONFIG_CATALOG.md` và `docs/PIPELINE.md` (F4): ngoài phạm vi A–E được giao.
- Hiện thời gian dự kiến trên giao diện: API chưa trả số này.
- Chạy thử ba video thật trên A5000: cần image mới.

## Việc phải làm khi build image và chứng nhận lại
1. Build image GPU từ commit cuối của `develop`. Bước tải từ điển cần mạng tới github.com, khoảng 72 MB; sai checksum thì build lỗi.
2. Chạy `docker run … preflight`: mục "Từ điển COLMAP" phải hiện `OK  faiss, checksum khớp`. Nếu báo sai định dạng thì COLMAP trong image cũ hơn 3.12: đổi `COLMAP_VOCAB_FORMAT=flann` rồi build lại.
3. Chứng nhận A5000, ra catalog mới, cập nhật secret watchdog theo quy trình `prod-deploy-gcp-vm`.
4. Trong `worker.env` production đặt `PRODUCT_PREVIEW_TIMEOUT_SECONDS=14400`. Không đặt `PRODUCT_COLMAP_VOCAB_TREE`, để dùng đường dẫn mặc định đã bake.
5. Sau khi worker mới chạy, kiểm `/processing/options` có `capability.colmap_vocab_tree_available = true`. Có cờ đó thì kịch bản đi bộ trong nhà và quay vòng mới giữ khép vòng; worker cũ tự về ghép liên tiếp.
6. Deploy API và Studio, rồi chạy ba video thử (đi bộ trong nhà 3 phút, quay vòng một vật, ngoài trời 4 phút) ở mức "Chuẩn". Ghi `registered_ratio`, `retry_ladder` và thời gian từng bước vào báo cáo này, rồi chỉnh bảng A5 nếu số đo cho thấy cần.

## Commit
374f6c7c, 9c478099, ea0fee90, 887f2477, b3206850, 806f668d, 8040f3f9, 605c153f, da0d69a1.
