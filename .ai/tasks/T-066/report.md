# T-066 report: ảnh frame thu nhỏ

## Đã làm
- Route `GET /jobs/{job_id}/frames/thumbnail?artifact_uri=&artifact_checksum=&width=` (`src/api/product/artifacts.py`): kiểm
  allow-list bằng `authorized_artifact` như route content, `width` chỉ 160/320/640 (khác → 422), JPEG chất lượng 80 giữ tỉ lệ,
  `Cache-Control: private, max-age=31536000, immutable`, ETag, 304 không đọc file. Ảnh không đọc được → 415.
- `artifacts/thumbnails.py`: đệm bộ nhớ (256 ảnh) + đĩa (`cache/thumbnails/` cạnh đệm Walk của T-052), khoá theo khoá đệm
  để không tạo trùng. Đệm dẫn xuất, xoá được bất kỳ lúc nào.
- Frontend: lưới Frames dùng ảnh 320 px (`srcSet` 160/320/640); bấm ảnh mở ảnh gốc trong khung lớn, có nút đóng.
- Route mới đã khai báo trong `test_role_matrix`.

## Đo (job-a14981f78f85, 48 frame PNG 3114×2075)
| | Tổng byte lưới |
|---|---|
| Trước (ảnh gốc) | 362,9 MB |
| Sau (JPEG 320 px) | ≈ 0,7 MB (≈ 14 KB/ảnh) |

Tạo lần đầu ≈ 0,2 s/ảnh (chủ yếu giải mã PNG), sau đó lấy từ đệm.

## Kiểm thử
`tests/test_api/test_frame_thumbnails.py` (5), `test_scene_routes.py` xanh; `frontend/tests/frame-thumbnails.test.tsx`.
`test_role_matrix::test_every_route_is_classified_exactly_once` vẫn đỏ vì các route demo-sessions chưa khai báo (có từ trước
Sprint 8, không thuộc task này).
