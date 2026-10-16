# T-045 report

## Outcome

A1: pipeline nhận trực tiếp PNG, JPG và JPEG, gồm đuôi viết hoa và một bộ ảnh trộn định dạng. Các bản sao đưa vào COLMAP và Brush giữ nguyên byte ảnh nguồn. Tên ảnh trong camera pose và sparse model giữ đúng đuôi định dạng.

T-045 vẫn `in-progress`: A2–A4 và Phần B còn dở. Chưa khởi động lại stack hoặc chạy scene.

## Scope decision

Chỉ dẫn chủ dự án ngày 2026-10-17 yêu cầu sửa pipeline để nhận JPG hoặc PNG rồi commit, thay thế quyết định chuyển JPG thành PNG lúc nạp trong plan trước đó. Phạm vi A1 vượt ngưỡng 6 file đã được cho phép bằng chỉ dẫn này; plan được cập nhật tương ứng.

Adapter TorWIC giữ hợp đồng PNG theo layout normalized riêng của TorWIC. Các boundary pipeline dùng chung nhận `image/png` và `image/jpeg`.

## Changed files — A1

- `src/services/reconstruction/rgb/frames/manifest_frames.py`, `frame_extraction.py`: chọn cả PNG và JPEG.
- `src/services/reconstruction/rgb/frames/frame_set.py`: dùng chung quy tắc tên frame với đuôi PNG/JPG/JPEG.
- `src/services/reconstruction/rgb/preflight/ffmpeg_probe.py`: quality probe đọc JPEG và PNG. Bộ cùng định dạng dùng symlink; bộ trộn định dạng dùng PPM giải mã tạm chỉ để đo chất lượng vì FFmpeg image2 giữ một codec cho cả chuỗi. Ảnh pipeline và nguồn không bị ghi lại. Thư mục đo tạm tự dọn khi thành công hoặc có lỗi.
- `src/services/reconstruction/adapters/colmap_input.py`, `colmap_model.py`, `colmap.py`: giữ đuôi khi chép, parse JPEG và xác minh tên ảnh của model có trong input đã stage trước khi publish.
- `src/services/reconstruction/rgb/pose/camera_pose.py`: vẫn buộc đúng frame ID và tên an toàn, thêm JPG/JPEG cạnh PNG.
- `src/services/reconstruction/adapters/brush_input.py`: giữ byte/đuôi nguồn và kiểm tên trùng camera pose.
- `tests/test_reconstruction/test_rec02a_frame_extraction.py`, `test_rec03_colmap.py`: hồi quy định dạng, byte, tên và model không trỏ ảnh có đuôi khác input.
- `.ai/tasks/T-045/plan.md`, `.ai/status.md`, report này: ghi chỉ dẫn mới và tiến độ.

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
