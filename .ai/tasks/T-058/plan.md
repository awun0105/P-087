# T-058: Hàm thuần "việc tiếp theo"

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md` (bảng `NextActionKind`).

## Goal
Một hàm thuần duy nhất ở backend quyết định "ai đang phải làm gì tiếp" cho một scene. Thay cho chuỗi `if` đang nằm rải ở
chuông, dòng tiến trình, banner, đầu trang và danh sách.

## Context (đã kiểm trong code)
Quy tắc hiện đang ở frontend, phải giữ nguyên thứ tự ưu tiên:
- `frontend/src/features/studio/scene/NextAction.tsx:114-200`: đang dựng (geometry/region) → lỗi job → hủy → chờ tài
  nguyên → chờ xem bản đã che → chờ xác nhận mét → đang chờ worker → scene xong: Draft + Tạo mesh lỗi trên revision này →
  Draft (đếm vật chờ) → chờ chọn cách tách vật → còn ứng viên chưa xác nhận → RELEASED → READY_FOR_REVIEW → đã có gói →
  preflight FAIL / sẵn sàng tạo gói.
- Đếm vật chờ (`NextAction.tsx:163`): `state == "CANDIDATE"` và `provenance.review` không phải `IGNORED`/`DELETED`.
- `sceneStatus.ts` và `ProgressTab.tsx:69-113` có các biến thể khác của cùng quy tắc.

## Thiết kế
Module `src/services/orchestration/pipeline/next_action.py` (tạo package `pipeline/` với `__init__.py`):
```python
NextActionKind = Literal[...]   # đúng danh sách trong file kế hoạch tổng
@dataclass(frozen=True)
class SceneOperationFacts:
    status: ObjectifyStatus; mode: ObjectifyMode; on_current_revision: bool
@dataclass(frozen=True)
class PackageFacts:
    exists_for_revision: bool; preflight_failed: bool
@dataclass(frozen=True)
class NextActionFacts:
    job_status: JobStatus
    waiting_for: WaitingFor | None
    failure_retryable: bool | None          # None = không có lỗi
    awaiting_object_choice: bool
    object_geometry: ObjectGeometryState | None   # từ object_geometry_view
    scene_operation: SceneOperationFacts | None
    pending_candidates: int | None          # None = không đọc (danh sách)
    package: PackageFacts | None            # None = không đọc
    review_status: str | None               # SceneRevisionStatus của revision hiện tại
class NextAction(BaseModel):
    kind: NextActionKind; step_id: StageId | None; owner: Literal["system", "user"]; pending_count: int | None = None
def next_action(facts: NextActionFacts) -> NextAction
def pending_candidates(scene: SceneIR) -> int
```
Quy tắc theo thứ tự (trả ở quy tắc đầu tiên khớp; `owner="system"` chỉ cho `wait_system`):
1. `QUEUED` → `wait_system` (step = None).
2. `RUNNING`: `waiting_for == "anonymization_review"` → `review_anonymization` (ANONYMIZATION_REVIEW);
   `"metric_confirmation"` → `confirm_metric` (METRIC_CANONICALIZE); khác → `wait_system`.
3. `FAILED` → `retry_job` nếu `failure_retryable` else `job_failed`. `CANCELLED` → `job_cancelled`.
4. `SUCCEEDED`:
   a. `scene_operation.status ∈ {queued, running}` → `wait_system`, step = SCENE_DECOMPOSE nếu mode ∈
      {geometry, region, membership}, OBJECT_EXTRACT nếu mode ∈ {objectify, boxes}.
   b. `object_geometry == "awaiting_review"`: nếu `scene_operation` là geometry, `failed`/`cancelled`,
      `on_current_revision` → `retry_geometry` (SCENE_DECOMPOSE); ngược lại `review_objects` (OBJECT_CONFIRM,
      `pending_count = pending_candidates`).
   c. `awaiting_object_choice` → `choose_object_method` (OBJECT_EXTRACT).
   d. `pending_candidates` > 0 → `confirm_objects` (OBJECT_CONFIRM, `pending_count`).
   e. `package is None` → `scene_ready`.
   f. `review_status == "RELEASED"` → `released`; `"READY_FOR_REVIEW"` → `await_review`;
      `package.exists_for_revision` → `review_package`; `package.preflight_failed` → `fix_preflight`; khác →
      `create_package`.

## Steps
1. `tests/test_orchestration/test_next_action.py`: một test cho **mỗi** quy tắc (16 kind) và các test thứ tự:
   `test_running_geometry_beats_draft`, `test_failed_geometry_on_old_revision_is_review_objects`,
   `test_draft_beats_object_choice`, `test_list_without_package_facts_returns_scene_ready`,
   `test_released_beats_package`. `test_pending_candidates_ignores_ignored_and_deleted` dùng SceneIR fixture
   (`tests/fixtures/scene_ir/scene.json`) sửa provenance. FAIL. Cài. PASS. Commit
   `feat(pipeline): decide the next action in one pure function`.

## Acceptance criteria
1. Hàm thuần, không đọc DB/file; 100% nhánh có test.
2. Thứ tự khớp chuông hiện tại; chỗ lệch (draft trước chọn cách tách vật) ghi rõ trong report.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_next_action.py -q
.venv/bin/ruff check src/services/orchestration/pipeline tests/test_orchestration/test_next_action.py
.venv/bin/ruff format --check src/services/orchestration/pipeline tests/test_orchestration/test_next_action.py
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
