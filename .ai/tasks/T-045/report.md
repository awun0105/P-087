# T-045 report

## Outcome

Phần A bị dừng tại ý 1 theo ngưỡng quyết định trong plan. Không có thay đổi code nào được giữ lại và không có commit T-045.

CodeGraph trace cho thấy hỗ trợ JPEG giữ nguyên byte vượt quá khoảng 6 file sản phẩm:

1. `src/services/reconstruction/rgb/frames/manifest_frames.py` và `frame_extraction.py` chỉ chọn `image/png`.
2. `src/services/reconstruction/rgb/preflight/ffmpeg_probe.py` chỉ nhận frame có đuôi `.png` và tạo chuỗi symlink `.png` cho FFmpeg.
3. `src/services/reconstruction/adapters/colmap_input.py` luôn chép frame thành `.png`.
4. `src/services/reconstruction/adapters/colmap_model.py` chỉ parse tên ảnh `.png`.
5. `src/services/reconstruction/rgb/pose/camera_pose.py` ràng buộc `image_name` thành `<frame_id>.png`.
6. `src/services/reconstruction/adapters/brush_input.py` luôn chép frame thành `.png`.

`src/services/reconstruction/adapters/torwic_frame_source.py` hiện cũng buộc `image/png`, có thể cần cập nhật tùy quyết định về adapter dùng chung. Chuyển JPEG thành PNG sẽ vi phạm yêu cầu giữ nguyên byte, nên chưa chọn cách đó.

## Verification

- Test hồi quy tạm `test_jpeg_dataset_frames_keep_bytes_and_extension_through_colmap` đã đỏ trên code cũ: `FRAME_INPUT_MISMATCH` tại `RGBFrameExtractor._image_frames`, do lọc `image/png`.
- Các thay đổi production và test thử đã được thu hồi. Không chạy test sau khi thu hồi vì không còn thay đổi sản phẩm.
- Không chạy `graphify update .` vì không giữ thay đổi code.

## Decision needed

**cần Architect:** chốt một trong hai hướng trước khi tiếp tục A1:

- Cho phép mở rộng phạm vi quá 6 file sản phẩm để hỗ trợ JPEG nguyên byte qua quality probe, REC-03/COLMAP, camera-pose contract và Brush; hoặc
- Điều chỉnh yêu cầu cho phép tạo PNG dẫn xuất cho pipeline từ JPEG nguồn.

Chưa bắt đầu A2–A4 hoặc Phần B. Stack chưa được khởi động lại; không thực hiện đo USB hay chạy scene.
