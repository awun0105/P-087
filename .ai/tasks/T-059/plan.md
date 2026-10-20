# T-059: Endpoint tiến trình hợp nhất, nhẹ, có 304

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md` (từ vựng, mục "Làm song song").

## Goal
Một request `GET /api/v1/jobs/{job_id}/pipeline` trả đủ để trang scene biết: danh sách bước thật từ đầu tới khi scene dùng
được, bước nào ai đang làm, chờ gì, việc tiếp theo. Request này đủ nhẹ để poll mỗi 3 giây, và trả 304 khi không có gì đổi.
Danh sách scene dùng cùng hàm "việc tiếp theo".

## Context (đã kiểm trong code)
- Trang scene hiện cần tới 6 lời gọi: `/jobs/{id}/progress` (`src/api/studio/scenes.py:424`), `/jobs/{id}/anonymization`,
  `/jobs/{id}/scene/objectify` (`src/api/product/scene.py:311`), `/jobs/{id}/scene`, `/jobs/{id}/review-state`,
  `/jobs/{id}/validation-runs`.
- `JobProgress` chỉ biết tới OBJECT_EXTRACT (`jobs/progress.py:32-47`). `studio_pipeline` chèn LIDAR_INGEST và
  LIDAR_CALIBRATION_QA nhưng **không** chèn LIDAR_ODOMETRY dù runner ghi stage này (`runner.py:1452-1575`) và frontend
  `stagesFor` có xử lý.
- Bước tách vật bị frontend ghi đè thành "failed" với mã bịa `OBJECTIFY_FAILED` khi `awaiting_choice`
  (`frontend/src/features/studio/scene/useObjectify.ts:184-196`).
- `/scenes` có ba cờ riêng `awaiting_anonymization_review`, `awaiting_object_choice`, `geometry_review` (`scenes.py:409-411`).
- Có sẵn sau các task trước: `object_geometry_view` (T-055), `list_marks` (T-056), mốc `scene_operation` (T-057),
  `next_action` + `pending_candidates` (T-058), đệm SceneIR/JobManifest theo checksum (T-053).

## Thiết kế
1. `src/services/orchestration/pipeline/models.py`:
   ```python
   StepActor = Literal["system", "user"]
   StepState = Literal["pending", "queued", "running", "waiting", "succeeded", "failed", "cancelled", "skipped"]
   TimingSource = Literal["recorded", "inferred", "none"]
   class PipelineStep(BaseModel):
       step_id: StageId; actor: StepActor; state: StepState
       started_at: datetime | None = None; completed_at: datetime | None = None; timing_source: TimingSource = "none"
       phase: ObjectifyPhase | None = None; error: ExecutionError | None = None; note: str | None = None
   class PipelineWait(BaseModel):
       kind: Literal["user", "queue", "resources", "runtime", "scene_operation"]; step_id: StageId | None; since: datetime | None
   class PipelineView(BaseModel):
       job_id: str; scene_revision: str | None; usable: bool
       steps: list[PipelineStep]; current_step: StageId | None; wait: PipelineWait | None; next_action: NextAction
       progress: JobProgressResponse       # đúng shape của /progress, để trang chỉ poll một chỗ
       objectify: ObjectifyState | None    # None khi job chưa có scene
       version: str                        # dùng làm ETag
   ```
2. `src/services/orchestration/pipeline/view.py`:
   - `def build_pipeline_view(registry, settings, job_id, *, user, now=None) -> PipelineView` — chỉ ghép, không tự tính lại
     quy tắc của nơi khác.
   - Hàm thuần `def compose_steps(progress: JobProgress, job: JobManifest, marks: list[StepMark], objectify: ObjectifyState | None,
     geometry: ObjectGeometryState | None) -> list[PipelineStep]` để test không cần DB.
3. Quy tắc `compose_steps`:
   - Bước job lấy từ `progress.stages` theo thứ tự. `studio_pipeline` (progress.py) sửa để chèn `LIDAR_ODOMETRY` khi job có
     artifact hoặc đang ở stage đó (cùng cách LIDAR_INGEST).
   - Chèn `ANONYMIZATION_REVIEW` ngay sau `FRAME_EXTRACT` khi `sanitized_frame_stage(job)` khác `None`. Trạng thái:
     `waiting` khi `progress.waiting_for == "anonymization_review"`, `succeeded` khi có acceptance, còn lại `pending`.
   - `actor="user"` cho `ANONYMIZATION_REVIEW`, `METRIC_CANONICALIZE`, `OBJECT_CONFIRM`; còn lại `system`.
   - Trạng thái bước hệ thống đang chờ máy (`waiting_for` ∈ {resources, runtime} hoặc job QUEUED) → `queued`, không phải
     `waiting`.
   - Thời gian: lấy mốc `pipeline` của attempt hiện tại; không có thì attempt cũ gần nhất có mốc (bước được tái dùng); có
     mốc → `timing_source="recorded"`. Không có mốc → `started_at`/`completed_at` của `progress` → `"inferred"`. Không có gì →
     `"none"`.
   - `OBJECT_EXTRACT` khi `objectify.awaiting_choice` và không có yêu cầu đang chạy: `failed`, `error = ExecutionError(
     error_code="OBJECTIFY_AWAITING_CHOICE", stage_id=OBJECT_EXTRACT, human_message="Tách theo vật chưa thành công sau các
     lần thử. Chạy lại tách theo vật hoặc dùng hộp ứng viên.", retryable=bool(objectify.retryable))`. Yêu cầu
     objectify/boxes đang chạy → `running` với `phase`.
   - Khi `geometry` khác `None` và `OBJECT_EXTRACT` đã xong, thêm hai bước:
     - `OBJECT_CONFIRM` (user): `waiting` khi Draft và không có yêu cầu geometry đang chờ/chạy; `succeeded` khi có yêu cầu
       geometry đang chờ/chạy hoặc scene `ready`. `started_at` = `completed_at` của OBJECT_EXTRACT; `completed_at` = mốc
       `queue.started_at` sớm nhất trong các run `scene_operation` có `run_id` bắt đầu bằng `"geometry:"`; không có mốc mà
       yêu cầu hiện tại là geometry → `objectify.requested_at` (`inferred`).
     - `SCENE_DECOMPOSE` (system): theo yêu cầu geometry mới nhất — `queued`/`running` (kèm `phase`), `failed` khi
       Draft + geometry `failed`/`cancelled` trên revision hiện tại (`error_code="OBJECT_GEOMETRY_BUILD_FAILED"`,
       `human_message` = lỗi của yêu cầu, `retryable` theo yêu cầu), `succeeded` khi `ready`, còn lại `pending`. Thời gian từ
       mốc `operation` của run geometry thành công mới nhất.
   - Dựng lại vùng / membership trên scene `ready`: `SCENE_DECOMPOSE` giữ `succeeded`; `wait = PipelineWait(kind=
     "scene_operation", step_id=SCENE_DECOMPOSE, since=objectify.started_at or requested_at)`.
   - `current_step` = bước đầu tiên ở `running`/`queued`/`waiting`/`failed`; không có → `None`.
   - `usable` = job `SUCCEEDED` và (`geometry is None` hoặc `"ready"`) và không `awaiting_choice`.
4. `next_action`: dựng `NextActionFacts` từ dữ liệu đã có. `pending_candidates`, `PackageFacts`, `review_status` **chỉ**
   đọc khi job `SUCCEEDED` và scene đã `ready` hoặc thiếu khoá (dùng `current_package`, `review_state`; đọc lỗi thì
   `package=None` → `scene_ready`, không làm hỏng cả view).
5. **Nhẹ khi poll:**
   - Tính `version` = sha256 rút gọn của `(job_manifest_checksum, attempt mới nhất, scene head checksum hoặc "",
     payload hàng đợi tách vật (chuỗi JSON), số dòng + mốc mới nhất của r2s_step_marks của job, payload r2s_resource_waits
     của job, gói/duyệt nếu đã đọc)`. Các phần này đọc bằng truy vấn rẻ trước khi dựng view.
   - `If-None-Match` khớp `version` → 304 **trước** khi dựng view (sau kiểm quyền như `/progress`).
   - Thân đi qua gzip (T-053).
   - Ngân sách: tối đa 6 transaction cho một lần dựng đầy đủ; 304 tối đa 3. Đếm bằng test.
6. Route `GET /jobs/{job_id}/pipeline` đặt cạnh `/progress` trong `src/api/studio/scenes.py`, cùng
   `Depends(require_contributor)` và cùng cách lọc lỗi theo người dùng (`filter_manifest_errors`) như `/progress`. Tách
   thân `/progress` thành hàm `job_progress_response(registry, job_id, user) -> JobProgressResponse` dùng cho cả hai.
   `/progress`, `/scene/objectify` giữ nguyên.
7. `/scenes`: `SceneSummary` thêm `next_action: NextActionKind | None = None`, tính bằng `next_action()` với
   `pending_candidates=None`, `package=None`, `waiting_for` từ `awaiting_metric_confirmation` / `awaiting_anonymization_review`
   có sẵn, `scene_operation` từ bản ghi hàng đợi. Ba cờ cũ giữ nguyên (frontend chuyển ở T-062).

## Steps
1. `tests/test_orchestration/test_pipeline_view.py` cho `compose_steps` (thuần):
   `test_video_job_steps_in_order`, `test_lidar_odometry_step_present`, `test_anonymization_review_step_inserted_and_waiting`,
   `test_metric_step_is_user_and_waiting`, `test_resource_wait_is_queued_not_waiting`,
   `test_recorded_marks_preferred_over_inferred`, `test_reused_stage_takes_mark_from_earlier_attempt`,
   `test_legacy_job_without_marks_is_inferred` (Review Focus 3), `test_awaiting_choice_marks_object_extract_failed`,
   `test_draft_adds_confirm_waiting_and_build_pending`, `test_geometry_running_shows_phase`,
   `test_geometry_failed_on_current_revision`, `test_region_rebuild_keeps_build_succeeded_and_sets_wait`,
   `test_legacy_scene_without_geometry_key_has_no_review_steps` (Review Focus 2), `test_usable_flag`.
   Cài thiết kế 1, 3. Commit `feat(pipeline): compose one ordered step list from job, marks and scene state`.
2. `build_pipeline_view` + route + `job_progress_response`. Test API `tests/test_api/test_pipeline_route.py`:
   `test_pipeline_view_matches_progress_payload` (trường `progress` bằng đúng `/progress`), `test_pipeline_304_when_unchanged`,
   `test_pipeline_version_changes_on_stage_progress`, `test_pipeline_version_changes_on_objectify_phase`,
   `test_pipeline_requires_contributor`, `test_pipeline_filters_errors_like_progress`,
   `test_pipeline_transaction_budget` (≤ 6 đầy đủ, ≤ 3 khi 304), `test_package_read_failure_falls_back_to_scene_ready`.
   Commit `feat(api): serve the unified pipeline view with 304 support`.
3. `/scenes` thêm `next_action`. Test `test_scene_list_next_action_kinds` (QUEUED, chờ mét, chờ bản che, Draft, geometry
   đang chạy, ready → `scene_ready`). Commit.
4. Kiểu frontend: thêm `PipelineView`, `PipelineStep`, `NextAction`… vào `frontend/src/lib/contracts/studio.ts` và
   `next_action?` vào `SceneSummary`; `npm run typecheck`. Commit.
5. Đo (in-process, bản sao DB): `/pipeline` đầy đủ và 304 cho một job Draft và một job ready, 50 lần. Mục tiêu: đầy đủ
   ≤ 25 ms warm, 304 ≤ 8 ms. Ghi report.

## Acceptance criteria
1. Một request đủ để vẽ dòng tiến trình, đầu trang, chuông.
2. Không đổi shape của `/progress`, `/scene/objectify`, `/scenes` (chỉ thêm trường).
3. Job và scene cũ: dòng tiến trình đủ, không có hàng Duyệt vật/Tạo mesh khi scene thiếu khoá.
4. Số đo đạt mục tiêu hoặc report giải thích.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_pipeline_view.py tests/test_api/test_pipeline_route.py tests/test_orchestration/test_next_action.py tests/test_orchestration/test_job_progress.py tests/test_api/test_scene_routes.py <test /scenes> -q
cd frontend && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md` (kèm số đo), `status.md`.

## Bổ sung 20/10: trạng thái máy GPU (phối hợp phiên deploy)
- Phiên deploy làm `src/services/orchestration/gpu/status.py` với `gpu_capacity(database, settings) -> GpuCapacity`
  (`state: "off"|"starting"|"ready"|"draining"|"blocked"|"unmanaged"`, `since`, `expected_startup_seconds`, …) và route
  riêng `GET /api/v1/gpu/status`. **Không sửa các file đó.** Đợi commit của họ (họ nhắn tên commit); chưa có thì bỏ qua
  phần này và ghi report.
- `PipelineView` thêm `gpu: GpuCapacity | None = None`, chỉ đọc khi job `QUEUED` hoặc `progress.waiting_for` ∈
  {`resources`, `runtime`}. `version` chỉ gồm `gpu.state` và `gpu.since` (không gồm thời gian đã trôi / còn lại).
- Test: `test_pipeline_includes_gpu_capacity_only_while_waiting_for_a_worker`, `test_gpu_elapsed_time_does_not_change_version`.
