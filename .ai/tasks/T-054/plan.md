# T-054: Danh sách scene và stage-views nhẹ

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Trang danh sách scene poll mỗi 4–20 s mà không quét cả bảng. Trang xem bước lấy danh sách lớp xem trong một request rẻ.

## Context (đã kiểm trong code)
- `list_scenes` (`src/api/studio/scenes.py:370-418`): với mỗi project gọi `registry.list_jobs` (mỗi job một
  `get_job` có băm manifest), `deps.preview_ready` mỗi job, `_awaiting_object_choice` và `_geometry_review` (đọc SceneIR khi
  trượt đệm), cộng `processing_seconds(load_usages(...))` đọc **mọi** dòng usage, `job_requesters` đọc mọi dòng audit,
  `queue.py:86-98` quét `LIKE` bảng sự kiện. Đo: 28 transaction mỗi lần, 31 ms warm, 588 ms lần đầu (~77 MB băm).
  Frontend poll 4 s khi có scene đang chạy (`ImportedScenesHome.tsx:107`, `ScenesHome.tsx:98`), 20 s khi không.
- Chỉ job mới nhất của mỗi project được hiển thị (`latest = max(jobs, key=started_at)`), nhưng mọi job đều bị nạp.
- `stage_views` (`src/services/orchestration/jobs/stage_views.py:114-196`): mỗi lần gọi băm lại frame set, bundle, camera
  pose (`require`), đọc metric confirmation. 20–26 ms. Kết quả chỉ đổi khi manifest job đổi.
- `processing_seconds`, `billed_usages` ở `processing/observed.py:86-117`.

## Thiết kế
1. `ProjectPersistence.latest_jobs(project_ids: Sequence[str]) -> dict[str, JobManifest]`: **một** truy vấn lấy
   `manifest_ref` của job mới nhất mỗi project (theo cột thời gian bắt đầu có trong `r2s_jobs`; nếu không có cột, dùng
   `json_extract` trên payload hiện có — đọc schema bảng trước). Manifest qua đệm của T-053.
   `list_scenes` dùng hàm này; `registry.list_jobs(project_id)` chỉ còn gọi khi cần quyền xoá project của khách
   (`can_delete_project` cho role guest) — giữ đúng hành vi.
2. `processing/observed.py`: `processing_seconds_for(database, job_ids: Sequence[str]) -> dict[str, float]` lọc bằng SQL
   theo `job_id IN (...)`, áp cùng quy tắc `billed_usages` (lượt `completed`; tool pipeline lấy lượt mới nhất theo
   `(job, tool)`; `scene.*` cộng hết). Test so khớp với `processing_seconds(load_usages(...))` trên cùng dữ liệu.
3. `job_requesters`/`job_requester_actors`: chỉ cho `job_ids` của các job đang hiển thị.
4. `deps.preview_ready(registry, job_id)`: đệm theo `job_manifest_checksum` (preview chỉ đổi khi manifest đổi).
5. `stage_views(registry, job_id)`: đệm kết quả theo `(job_id, job_manifest_checksum)` dùng `ParsedArtifactCache` của
   T-053 (khoá `("stage-views:"+job_id, checksum)`); trong lúc dựng dùng `require_unchanged` thay `require`.
   Endpoint `GET /jobs/{id}/stage-views` thêm `ETag` = checksum manifest + 304.

## Steps
1. Test `tests/test_orchestration/test_observed_usage_sql.py`: `test_sql_processing_seconds_matches_python_rule` (fixture
   usage nhiều job, nhiều tool, có lượt failed, có `scene.*` nhiều lượt) và `test_only_requested_jobs_are_read`. Cài thiết
   kế 2. Commit `perf(usage): sum processing time per job in SQL`.
2. Test `test_latest_jobs_one_query` (đếm `tx.execute`), `test_latest_jobs_picks_newest_per_project`. Cài thiết kế 1.
   Commit.
3. Test API `tests/test_api/` (file có test `/scenes`: `grep -rln "\"/scenes\"\|/api/v1/scenes" tests/test_api`):
   `test_scene_list_transactions_bounded` — 10 project × 3 job → số transaction ≤ 8 bất kể số project (đếm bằng wrapper
   `RuntimeDatabase.transaction`); test hiện có về cờ `awaiting_*`, `geometry_review`, `processing_seconds` vẫn xanh. Cài
   thiết kế 1, 3, 4. Commit `perf(api): build the scene list from latest jobs only`.
4. Test `test_stage_views_cached_per_manifest`, `test_stage_views_etag_304`. Cài thiết kế 5. Commit.
5. Đo trước/sau `list_scenes` và `stage_views` (in-process, bản sao DB), lần đầu và warm. Mục tiêu: `/scenes` warm ≤ 10 ms,
   lần đầu ≤ 150 ms; stage-views warm ≤ 3 ms.

## Acceptance criteria
1. `/scenes` không đọc toàn bộ bảng usage/audit/sự kiện; số transaction không tăng theo số project.
2. Kết quả danh sách và stage-views giống hệt trước khi sửa (test so sánh).

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_observed_usage_sql.py <test /scenes> <test stage-views> tests/test_orchestration/test_observed_budget.py -q
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md` (kèm số đo), `status.md`.
