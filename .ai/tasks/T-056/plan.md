# T-056: Bảng mốc bước, ghi từ pipeline job

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Mỗi bước của pipeline job có mốc bắt đầu và kết thúc **được ghi lúc xảy ra**, kể cả bước chờ người (xem bản đã che, xác nhận
tỉ lệ mét). Tiến trình và telemetry sau này đọc mốc này thay vì suy ra từ thứ tự journal.

## Context (đã kiểm trong code)
- `jobs/progress.py:231-239` suy "bước trước xong vì bước sau đã bắt đầu"; `benchmark.py:184-199` đoán stage thuộc attempt
  nào bằng so mốc. Lý do: StageArtifact của preview chỉ commit cùng receipt cuối attempt.
- Worker đã phát dòng JSON StageArtifact: `preview_worker.py:196-201` (`_start` RUNNING, `_complete` stage đã xong),
  `finalize.py:272-282`. Runner chỉ đọc dòng RUNNING (`runner.py:197-211`, `_StageProgress.poll`).
- Mọi revision job đi qua **một** chỗ commit: `ProjectPersistence.save_job(manifest, reference, event, *, expected=...)`
  (`projects/persistence.py:144`), trong một transaction.
- Chờ người:
  - Xem bản đã che: bắt đầu khi frame set đã che được commit (`progress.sanitized_frame_stage(job)`) và job đang chờ
    (`awaiting_anonymization_review`); kết thúc khi có StageArtifact `PRIVACY_GATE` loại `SanitizationAcceptance`.
  - Xác nhận mét: bắt đầu khi revision chuyển `current_stage` sang `METRIC_CANONICALIZE` (`record_preview`); kết thúc khi
    có StageArtifact `METRIC_CANONICALIZE` (`registry.py:1283-1286`).
- Migration cuối v25 (`jobs/database.py:463-472`).

## Thiết kế
1. `StageId` thêm `ANONYMIZATION_REVIEW = "ST-ANONYMIZATION-REVIEW"` (chỉ cho mốc và màn tiến trình; không ghi vào
   StageArtifact). Thêm vào union `StageId` ở `frontend/src/lib/contracts/api.ts`.
2. Migration v26:
   ```sql
   CREATE TABLE r2s_step_marks (
     job_id TEXT NOT NULL, run_kind TEXT NOT NULL, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
     started_at TEXT, completed_at TEXT, outcome TEXT,
     PRIMARY KEY (job_id, run_kind, run_id, step_id))
   ```
   Xoá job (`projects/deletion.py`) xoá cả dòng của job ở bảng này, giống cách `r2s_value_events` được xoá.
3. Module `src/services/orchestration/jobs/step_marks.py`:
   ```python
   RunKind = Literal["pipeline", "scene_operation"]
   MarkOutcome = Literal["succeeded", "failed", "cancelled"]
   class StepMark(BaseModel):  # extra="forbid"
       job_id: str; run_kind: RunKind; run_id: str; step_id: str
       started_at: datetime | None; completed_at: datetime | None; outcome: MarkOutcome | None
   @dataclass(frozen=True)
   class MarkWrite:
       kind: Literal["start", "finish", "close"]; step_id: str | None; at: datetime; outcome: MarkOutcome | None = None
   def apply_marks(tx: RuntimeTransaction, job_id: str, run_kind: RunKind, run_id: str, writes: Iterable[MarkWrite]) -> None
   def record_marks(database: RuntimeDatabase, job_id: str, run_kind: RunKind, run_id: str, writes: Iterable[MarkWrite]) -> None
   def list_marks(database: RuntimeDatabase, job_id: str) -> list[StepMark]
   def marks_for_revision(previous: JobManifest | None, current: JobManifest, event: JobAttemptRecord) -> list[MarkWrite]
   ```
   - `apply_marks`: `start` upsert giữ `started_at` cũ nếu có (mốc sớm nhất thắng); `finish` upsert giữ
     `completed_at`/`outcome` cũ nếu có; `close` = `UPDATE ... SET completed_at=?, outcome=? WHERE ... AND completed_at IS
     NULL AND started_at IS NOT NULL`.
   - `record_marks`: tự mở transaction; lỗi → `logger.warning` có `job_id`, không ném.
   - `marks_for_revision` (thuần), `run_id = str(event.attempt)`:
     - **R1**: `event.status == RUNNING` và (`previous is None` hoặc `previous.status != RUNNING` hoặc
       `previous.current_stage != current.current_stage`) → `start(current.current_stage, event.stage_started_at or
       event.recorded_at)`; cùng stage nhưng có `event.stage_started_at` → cũng `start`.
     - **R2** StageArtifact mới (so bộ `(stage_id, artifact_type, artifact_uri, status, completed_at)` với `previous`):
       có `started_at` → `start`; có `completed_at` và status SUCCEEDED/FAILED/CANCELLED → `finish`. Ngoại lệ:
       `SanitizationAcceptance` → `finish(ANONYMIZATION_REVIEW, completed_at, "succeeded")`.
     - **R3**: `awaiting_anonymization_review(current)` và chưa ở `previous` →
       `start(ANONYMIZATION_REVIEW, sanitized_frame_stage(current).completed_at or event.recorded_at)`.
     - **R4**: `current.status` FAILED/CANCELLED mà `previous` chưa → `close(event.recorded_at, outcome)`.
4. `save_job`: trong transaction có sẵn, sau khi ghi revision và event, gọi
   `apply_marks(tx, manifest.job_id, "pipeline", str(event.attempt), marks_for_revision(expected, manifest, event))`. Lỗi
   làm hỏng commit (cùng transaction), không nuốt.
5. Runner: `_StageProgress.__init__` đọc số attempt một lần (`registry.persistence.list_attempts(job_id)[-1].attempt`).
   `poll()` gặp dòng SUCCEEDED/FAILED có `completed_at` → `record_marks(... [MarkWrite("finish", stage_id, completed_at,
   outcome)])`. Dòng RUNNING giữ hành vi cũ.
6. Không đổi `progress.py`; T-059 dùng mốc khi có, suy luận cũ khi không.
7. Hiệu năng: `list_marks` một truy vấn theo khoá chính (tiền tố `job_id`), không cần index thêm.

## Steps
1. `tests/test_orchestration/test_step_marks.py` cho `marks_for_revision`: `test_claim_starts_current_stage`,
   `test_stage_change_starts_new_stage_with_worker_time`, `test_new_succeeded_artifact_finishes_stage`,
   `test_existing_artifact_is_not_written_again`, `test_sanitization_acceptance_finishes_anonymization_review`,
   `test_entering_anonymization_wait_starts_review_at_frame_completion`,
   `test_metric_wait_starts_when_stage_becomes_metric`, `test_failed_revision_closes_open_marks`. Cài phần thuần. Commit
   `feat(progress): derive recorded step marks from each job revision`.
2. Migration + `apply_marks`/`record_marks`/`list_marks`. Test `test_start_keeps_earliest_time`,
   `test_finish_keeps_first_completion`, `test_close_only_touches_open_started_marks`,
   `test_record_marks_logs_and_swallows_database_errors`; `test_runtime_migrations.py` thêm kiểm v26 trên DB v25 có dữ liệu.
   Commit `feat(db): add step marks table`.
3. Nối `save_job` và xoá job. Test `test_job_lifecycle_records_marks` (fixture như `test_pipeline_timing.py`: claim, hai
   `record_stage_progress`, `record_preview`, xác nhận mét → mốc đủ, METRIC có đủ hai mốc), `test_deleting_job_removes_marks`.
   Commit.
4. Runner (thiết kế 5) + `test_stage_progress_poll_records_completion`. Commit.
5. `StageId` frontend, `npm run typecheck`. Commit.

## Acceptance criteria
1. Mỗi lần chuyển stage, mỗi stage xong, mỗi bước chờ người đều có mốc.
2. Mốc trong `save_job` cùng transaction; mốc từ runner lỗi không làm hỏng job.
3. Job cũ đọc tiến trình như trước.
4. Report ghi: có migration v26, API và worker deploy cùng lúc.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_step_marks.py tests/test_orchestration/test_runtime_migrations.py tests/test_orchestration/test_job_progress.py tests/test_orchestration/test_pipeline_timing.py tests/test_orchestration/test_anonymization_review.py -q
.venv/bin/python -m pytest <test xoá job> -q
cd frontend && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
