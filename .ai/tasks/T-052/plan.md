# T-052: Lưới va chạm Walk dựng một lần, trả 304

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Lưới va chạm của một revision scene chỉ được dựng một lần. Lần sau trả ngay từ đệm, hoặc 304 nếu trình duyệt đã có. Một
request dựng lưới không còn chặn mọi request khác của API trong ~1 giây.

## Context (đã kiểm trong code)
- Route `GET /jobs/{job_id}/walk-collision/{filename}` (`src/api/product/artifacts.py:128-216`). Có `scene_revision` thì
  gọi `effective_collision_for_revision` (`scene/physics_collision.py:20-34`): đọc lại scene, cấu hình job,
  `_selected_collision_source` băm GLB nguồn và file LiDAR, chạy lại kiểm eligibility, rồi `compose_effective_collision`
  (`services/scene/effective_collision.py:141`) **không có đệm**. Chỉ bước xuất GLB cuối có `lru_cache(8)`
  (`physics_collision.py:37`).
- Trả `ETag`-tương đương qua header `X-Collision-Composition: identity` nhưng `Cache-Control: private, no-cache` và không
  xử lý `If-None-Match` (dòng 206-214).
- Đo: 760–1121 ms, thân 29 MB (`job-f9f14e7fbfb1`); 330–460 ms (`job-a14981f78f85`). Chạy trong một tiến trình uvicorn
  nên chặn GIL.
- Kết quả phụ thuộc: `(job_id, scene_revision, artifact_uri/checksum nguồn, preview, frame)`, cấu hình mô phỏng của job
  (`_job_simulation_config`) — cố định theo `job.config_checksum`.

## Thiết kế
1. Module mới `src/services/orchestration/scene/collision_cache.py`:
   ```python
   @dataclass(frozen=True)
   class CollisionKey:
       job_id: str; scene_revision: str; source_checksum: str; preview: bool; frame: Literal["display","canonical"]; config_checksum: str
   @dataclass(frozen=True)
   class CollisionPayload:
       body: bytes; identity: str; shared: int; floor: int; repaired: int
   def cached_effective_collision(key: CollisionKey, build: Callable[[], CollisionPayload]) -> CollisionPayload
   ```
   Đệm hai tầng: (a) bộ nhớ, tối đa 4 mục hoặc 256 MB tổng; (b) đĩa dưới `settings.product_worker_root/../collision-cache/`
   hoặc thư mục cache cạnh `ARTIFACT_ROOT` (chọn thư mục đã có cho cache tạm; ghi lý do trong report), tên file
   `sha256(repr(key)).glb` + `.json` cho các số phụ. Ghi file bằng ghi tạm rồi `os.replace`. Có khoá theo key để hai request
   cùng lúc chỉ dựng một lần.
2. Route: dựng `CollisionKey` (revision scene đã kiểm khớp head như cũ, `config_checksum` của job), gọi
   `cached_effective_collision`. Kiểm quyền và kiểm revision **trước** khi đọc đệm.
3. HTTP: `ETag: "<identity>-<display|canonical>"`. `If-None-Match` khớp → 304 (sau kiểm quyền). Thân trả với
   `Cache-Control: private, max-age=31536000, immutable` khi có `scene_revision` (revision bất biến); nhánh không có
   `scene_revision` (xem trước theo bản tái dựng) cũng immutable vì khoá là checksum nguồn. Nén gzip khi request có
   `Accept-Encoding: gzip` (GLB nén tốt) — dùng middleware của T-053 nếu đã có, nếu chưa thì nén tại route bằng
   `gzip.compress(level=5)` và đặt `Content-Encoding`, lưu bản nén trong đệm đĩa.
4. Đệm đĩa dọn theo tuổi: file không đọc quá 7 ngày bị xoá khi khởi động API (một lần, nền).

## Steps
1. Test `tests/test_orchestration/test_collision_cache.py`: `test_build_runs_once_per_key`,
   `test_concurrent_requests_build_once` (hai luồng), `test_disk_cache_survives_process_memory_reset`,
   `test_different_frame_is_a_different_entry`, `test_memory_cache_respects_size_limit`. FAIL. Cài thiết kế 1. PASS.
   Commit `perf(scene): cache composed walk collision per scene revision`.
2. Test route trong `tests/test_api/` (file có test `walk-collision`: `grep -rln "walk-collision" tests/test_api`):
   `test_walk_collision_second_request_skips_composition` (monkeypatch `effective_environment` đếm lần gọi = 1),
   `test_walk_collision_if_none_match_returns_304`, `test_walk_collision_304_requires_permission`,
   `test_walk_collision_stale_revision_still_409`, `test_walk_collision_gzip_when_accepted`. Cài thiết kế 2, 3. Commit
   `perf(api): serve walk collision from cache with 304 and gzip`.
3. Dọn đệm (thiết kế 4) + test `test_old_cache_files_are_pruned`. Commit.
4. Đo trước/sau trên `job-f9f14e7fbfb1` (in-process như T-051): lần đầu, lần hai, 304, kích thước nén. Ghi report.
   Mục tiêu: lần hai ≤ 50 ms, 304 ≤ 10 ms, thân nén ≤ 1/3.

## Acceptance criteria
1. Cùng revision và khung: dựng đúng một lần kể cả khi API khởi động lại (đệm đĩa).
2. Đổi revision, nguồn, khung hoặc cấu hình → kết quả mới.
3. Không trả đệm khi revision không còn là head (giữ 409 như cũ).

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_collision_cache.py <test route walk-collision> tests/test_scene/ -q -k "collision"
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md` (kèm số đo), `status.md`.
