# T-045 report

## Outcome

A1: pipeline nhận trực tiếp PNG, JPG và JPEG, gồm đuôi viết hoa và một bộ ảnh trộn định dạng. Các bản sao đưa vào COLMAP và Brush giữ nguyên byte ảnh nguồn. Tên ảnh trong camera pose và sparse model giữ đúng đuôi định dạng.

A2–A4: đã có lệnh nạp một scene dataset thành project/job, ghép MP4 chỉ để phát lại, và nối worker dataset qua quality → privacy self-attestation → image refs. `InputManifest` của job chỉ khai báo ảnh; worker không đọc MP4. Preset được chọn theo scene. Video xem lại hiện trên trang tiến trình, endpoint project và bundle xuất mẫu có nhãn rõ ràng.

Phần A đã code, test focused và commit. T-045 còn `in-progress`: các kiểm tra acceptance tổng hợp và Phần B đang chờ. Chưa chạy scene. Lựa chọn dung lượng là C: chạy tuần tự, xuất mẫu lên USB; chưa chuyển/xoá artifact laptop vì chưa có job kết thúc.

## Scope decision

Chỉ dẫn chủ dự án ngày 2026-10-17 yêu cầu sửa pipeline để nhận JPG hoặc PNG rồi commit, thay thế quyết định chuyển JPG thành PNG lúc nạp trong plan trước đó. Phạm vi A1 vượt ngưỡng 6 file đã được cho phép bằng chỉ dẫn này; plan được cập nhật tương ứng.

Adapter TorWIC giữ hợp đồng PNG theo layout normalized riêng của TorWIC. Các boundary pipeline dùng chung nhận `image/png` và `image/jpeg`.

Chủ dự án chỉ đạo dùng `self_attested` cho batch dataset. Project khai báo `public_or_synthetic`, chủ sở hữu dataset, mục đích `kiểm thử nội bộ`; video ghép nằm ở `display_video_ref`, tách biệt khỏi `InputManifest.files`.

## Changed files — A1

- `src/services/reconstruction/rgb/frames/manifest_frames.py`, `frame_extraction.py`: chọn cả PNG và JPEG.
- `src/services/reconstruction/rgb/frames/frame_set.py`: dùng chung quy tắc tên frame với đuôi PNG/JPG/JPEG.
- `src/services/reconstruction/rgb/preflight/ffmpeg_probe.py`: quality probe đọc JPEG và PNG. Bộ cùng định dạng dùng symlink; bộ trộn định dạng dùng PPM giải mã tạm chỉ để đo chất lượng vì FFmpeg image2 giữ một codec cho cả chuỗi. Ảnh pipeline và nguồn không bị ghi lại. Thư mục đo tạm tự dọn khi thành công hoặc có lỗi.
- `src/services/reconstruction/adapters/colmap_input.py`, `colmap_model.py`, `colmap.py`: giữ đuôi khi chép, parse JPEG và xác minh tên ảnh của model có trong input đã stage trước khi publish.
- `src/services/reconstruction/rgb/pose/camera_pose.py`: vẫn buộc đúng frame ID và tên an toàn, thêm JPG/JPEG cạnh PNG.
- `src/services/reconstruction/adapters/brush_input.py`: giữ byte/đuôi nguồn và kiểm tên trùng camera pose.
- `tests/test_reconstruction/test_rec02a_frame_extraction.py`, `test_rec03_colmap.py`: hồi quy định dạng, byte, tên và model không trỏ ảnh có đuôi khác input.
- `.ai/tasks/T-045/plan.md`, `.ai/status.md`, report này: ghi chỉ dẫn mới và tiến độ.

## Changed files — A2–A4

- `src/services/orchestration/projects/dataset_video.py`: ghép danh sách ảnh theo tên thành H.264/yuv420p, 3 fps, cạnh dài tối đa 1920, kích thước chia hết cho 2; xác minh số frame bằng ffprobe.
- `scripts/datasets/import_image_scene.py`: lệnh một scene/job; từ chối thư mục có sidecar COLMAP/NeRF, dùng Reviewer credentials từ `R2S_REVIEWER_EMAIL`/`R2S_REVIEWER_PASSWORD` mà không in ra, lưu video dưới dạng display-only, gán preset trong cấu hình theo scene và tạo job owner-bound.
- `src/services/orchestration/projects/registry.py`, `projects/models.py`, `projects/privacy.py`: publish ảnh gốc vào input manifest, video riêng vào display ref, hỗ trợ project dataset tự khai và dispatch theo chỉ đạo.
- `src/services/reconstruction/prepare_cli.py`: dataset đi qua quality và self-attested gate; `image_refs` giữ nguyên ảnh nguồn, không decode/timestamp video.
- `src/api/studio/scenes.py`, `api/schemas.py`, `samples/export.py`, `samples/models.py`: endpoint video playback, export chọn video display và nhãn `Video ghép từ ảnh gốc, chỉ để xem lại`.
- `frontend/src/features/studio/ScenePage.tsx`, `scene/ProgressTab.tsx`, `showcase/registry.tsx`, `lib/contracts/*`: phát video display ở Studio và gắn nhãn trong replay mẫu.
- Tests mới: `test_dataset_video.py`, `test_dataset_import_cli.py`, `test_display_video_model.py`; mở rộng `test_rec_prepare_input.py`, `test_project_registry.py`, `test_sample_export.py`, `test_studio_routes.py`, `studio-demo-showcase.test.tsx`.

## Commits — A2–A4

- `cec33009 Compose replay video from ordered dataset images` (A4).
- `d146100d Keep dataset replay video separate from pipeline input` (A3).
- `834d7a46 Run dataset image projects through image reference preparation` (A2).

## Verification — A2–A4 (focused)

`tests/test_reconstruction/test_rec_prepare_input.py`, `test_dataset_import_cli.py`, `test_project_registry.py`, `test_display_video_model.py`, `test_studio_routes.py`: `95 passed`.

`tests/test_orchestration/test_dataset_video.py`: `2 passed`; kiểm H.264, yuv420p, đúng 3 fps, frame count và giới hạn kích thước.

`tests/test_orchestration/test_sample_export.py`: `39 passed`; bundle dùng video display và không đọc image manifest như video.

Frontend `vitest run tests/studio-demo-showcase.test.tsx`: `14 passed`; `npm run typecheck`: PASS. Ruff `check`: PASS; `ruff format --check`: `28 files already formatted`. Contract mirror: PASS — `5 enum, 9 model`. Lệnh tests required Phần A theo plan: `1331 passed, 5 skipped in 194.76s`. `graphify update .`: PASS — 27.720 nodes, 86.636 edges, 823 communities.

Red evidence A2: `test_dataset_preparation_uses_image_refs_and_never_decodes_display_video` fail trên nhánh video-only với `RGB_INPUT_SHAPE_UNSUPPORTED`; `test_dataset_project_uses_images_as_input_and_keeps_display_video_separate` fail khi registry chưa có dataset importer. A4 tests mới phụ thuộc module video composer chưa có ở code cũ.

Phần A chỉ xác nhận local tests/FFmpeg synthetic; chưa chứng minh COLMAP/Brush GPU trên 9 scene thật. Stack cần restart trước job scene kế tiếp để nạp ba commit mới nhất; chưa có job mới nào được tạo.

## Verification — A1

Đỏ trên code cũ (`b0ec2c4a`):

```
.venv/bin/python -m pytest tests/test_reconstruction/test_rec02a_frame_extraction.py -k 'image_formats or camera_pose_rejects' -q
3 failed, 5 passed, 10 deselected
```

Ba ca JPG, JPEG và mixed fail tại `RGB_MANIFEST_SELECTION_MISMATCH`. Ca PNG và kiểm từ chối tên không hợp lệ pass. Sau khi nới định dạng, test bổ sung `test_model_image_format_must_match_staged_source` đỏ vì model có tên JPG trên input PNG vẫn được publish; thêm kiểm tên staged source đã sửa lỗi đó.

Xanh:

```
.venv/bin/python -m pytest tests/test_reconstruction/test_rec02_quality.py tests/test_reconstruction/test_rec02a_frame_extraction.py tests/test_reconstruction/test_rec03_colmap.py tests/test_reconstruction/test_rec04_brush.py tests/test_reconstruction/test_rec_prepare_input.py tests/test_reconstruction/test_rec06_math.py tests/test_reconstruction/test_rec06_auto_scale.py tests/test_reconstruction/test_frame_sanitization.py -q
153 passed, 5 skipped in 28.90s
```

5 skip thuộc `test_real_splat_codec`: cần runtime `REC04_TEST_SPLAT_MODULE` riêng. FFmpeg/ffprobe thật đã đọc ảnh synthetic; COLMAP process là fixture, không chứng minh chạy GPU COLMAP hoặc Brush training thật.

`check_contract_mirror.py`: PASS — 5 enum, 9 model khớp Pydantic.

Ruff chạy trên đúng 9 file sản phẩm và 2 file test Python liệt kê ở trên: `ruff check` → `All checks passed!`;
`ruff format --check` → `11 files already formatted`. `git diff --check` trên các file T-045 → exit 0.

`graphify update .` → exit 0, cập nhật 27.673 nodes, 86.444 edges, 877 communities. Graph lưu tại `graphify-out/` theo cấu hình repo.

## Pre-flight (GUIDE.md Rule 13) — A1

- codegraph: đọc và trace manifest frames, extraction, frame set, FFmpeg probe, COLMAP adapter/model, camera pose, Brush input và các test/caller liên quan.
- impact: REC-02 quality/preparation → REC-03 pose publication/resume → REC-04 input; caller metric/canonical pose được kiểm bằng test REC-06. Không đổi shared API schema.
- understand: source trace REC-02 → REC-03 → REC-04 và plan; UNVERIFIED công cụ understand-anything vì không có tool trong phiên.
- minimal-code: dùng lại resolver, checksum, FFmpeg và parser; một helper tên ảnh dùng chung cho COLMAP, camera pose và Brush.
- checks: 153 passed, 5 skipped; ruff check/format sạch; contract mirror PASS; graphify update thành công. TypeScript/eslint/vitest n/a — không sửa frontend.
- DevTools: n/a — sửa service không có UI.
