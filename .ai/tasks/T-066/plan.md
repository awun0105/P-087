# T-066: Ảnh frame thu nhỏ

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Bước "Frame đã chọn" hiện lưới ảnh nhỏ tải tức thì; bấm một ảnh mới tải ảnh gốc.

## Context (đã kiểm trong code và dữ liệu)
- `stage_views` (`src/services/orchestration/jobs/stage_views.py:114-127`) trả tối đa `MAX_FRAMES` (48) ref ảnh frame gốc.
  Giao diện đặt thẳng vào `<img>` (lazy) trong lưới 6 cột.
- Ảnh gốc: `job-a14981f78f85` PNG 3114×2075, 7–8 MB/ảnh (311 frame = 2,35 GB); `job-f9f14e7fbfb1` 0,6 MB; `job-bfc7d73f0dbf`
  0,25 MB. Không có ảnh thu nhỏ.
- Ảnh được tải qua `/jobs/{id}/artifacts/content` (sau T-051 có cache immutable).
- Pillow có trong môi trường Python (kiểm `import PIL` trong `.venv`; nếu không có, dùng OpenCV đã có và ghi report).

## Thiết kế
1. Route mới `GET /jobs/{job_id}/frames/thumbnail?artifact_uri=&artifact_checksum=&width=320` trong
   `src/api/product/artifacts.py`: kiểm allow-list như route content (dùng `authorized_artifact`), `width` ∈ {160, 320, 640}.
   Tạo JPEG chất lượng 80 giữ tỉ lệ, lưu đệm đĩa theo `(checksum, width)` cạnh đệm của T-052 (cùng thư mục cache, thư mục con
   `thumbnails/`), trả `Cache-Control: private, max-age=31536000, immutable`, `ETag`, 304. Tạo ảnh trong threadpool,
   khoá theo khoá đệm để không tạo trùng.
2. Không thêm artifact vào pipeline; ảnh thu nhỏ là đệm dẫn xuất, xoá được bất kỳ lúc nào.
3. Frontend: lưới dùng URL thu nhỏ (`width=320`, `srcSet` 160/320/640); bấm ảnh mở ảnh gốc trong khung xem lớn.

## Steps
1. `tests/test_api/test_frame_thumbnails.py`: `test_thumbnail_is_small_jpeg` (fixture PNG 3000×2000 → JPEG, cạnh rộng 320),
   `test_thumbnail_requires_allow_list`, `test_thumbnail_cached_on_disk` (lần hai không gọi Pillow),
   `test_thumbnail_304`, `test_invalid_width_rejected`. Cài thiết kế 1. Commit
   `perf(api): serve cached frame thumbnails`.
2. Frontend + test trong `studio-inspection.test.tsx` hoặc file mới `frame-thumbnails.test.tsx`: lưới dùng URL thu nhỏ; bấm
   mở ảnh gốc. Commit.
3. Đo: tổng byte lưới 48 ảnh của `job-a14981f78f85` trước/sau (tính từ kích thước file). Mục tiêu: ≤ 3 MB.

## Acceptance criteria
1. Lưới frame không tải ảnh gốc.
2. Người không có quyền không lấy được ảnh thu nhỏ.

## Tests required
```
.venv/bin/python -m pytest tests/test_api/test_frame_thumbnails.py tests/test_api/test_artifact_http_cache.py -q
cd frontend && ./node_modules/.bin/vitest run <test lưới frame> && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
