# T-027: Nhật ký sự kiện giá trị

## Goal
Bảng append-only ghi mọi sự kiện cần cho metric giá trị (architecture §15.2–15.3): `scene_edit` tự ghi khi publish revision,
`operator_time` và `walk_session` do trình duyệt gửi.

## Context
§15. `SceneEditor.publish_next(job_id, expected_revision, scene, operation, *, commit_guard)` (`scene/editor.py:382`) là điểm
publish duy nhất (15 nơi gọi). Migration theo danh sách phiên bản trong `jobs/database.py` (hiện tới 19). Quyền giống route
sửa scene: `require_contributor` + `authorize_job_mutation`.

## Files
- Tạo: `src/services/orchestration/value/events.py`, `src/services/orchestration/value/__init__.py`
- Sửa: `src/services/orchestration/jobs/database.py` (migration 20), `src/services/orchestration/scene/editor.py`
- Tạo: `src/api/studio/value.py` (router), đăng ký router như các router studio khác
- Test: `tests/test_orchestration/test_value_events.py`, `tests/test_api/test_value_routes.py`, `tests/test_api/test_role_matrix.py`

## Interfaces
```python
EventKind = Literal["scene_edit", "operator_time", "walk_session"]
class ValueEvent(BaseModel):  # extra="forbid"
    event_id: str; job_id: str; at: datetime; kind: EventKind; actor_id: str | None; payload: JsonObject
def record_event(database, job_id, kind, payload, *, actor_id=None, at=None) -> None   # lỗi DB: log warning, không raise
def list_events(database, job_id, kinds: set[EventKind] | None = None) -> list[ValueEvent]  # theo `at` tăng dần

HUMAN_OPERATIONS: frozenset[str]   # thao tác do người bấm (move, rotate, confirm, ignore, label, region edit, collider, ...)
SYSTEM_OPERATIONS: frozenset[str]  # objectify, object_geometry_build, membership rebuild, physics_enrich, ...
def operation_origin(op: str) -> Literal["human", "system", "unknown"]
```
`scene_edit.payload = {operation, origin, scene_revision, previous_revision}`; ghi **sau** khi publish thành công (không ghi
khi CAS/commit_guard từ chối).

API (JSON, 204 khi nhận):
```
POST /api/v1/jobs/{job_id}/value-events/operator-time
  {session_key: str(8..64), surface: "studio"|"progress"|"evaluation"|"other",
   started_at, ended_at, active_seconds}
POST /api/v1/jobs/{job_id}/value-events/walk-session
  {scene_revision, started_at, ended_at, outcome: "completed"|"aborted"}
```
Từ chối 422: `ended_at ≤ started_at`; `ended_at − started_at > 300 s`; `active_seconds > ended_at − started_at` hoặc < 0;
thời điểm lệch tương lai > 60 s; lô `operator_time` chồng thời gian với lô trước cùng `session_key` (đọc lô cuối của session).
`walk_session` dài tối đa 2 giờ. `actor_id` lấy từ user đăng nhập, không lấy từ body.

## Steps
1. Migration 20: `r2s_value_events(event_id TEXT PK, job_id TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
   actor_id TEXT, payload TEXT NOT NULL)` + `INDEX(job_id, at)`. `events.py` record/list + test. Commit.
2. Bảng phân loại operation: liệt kê mọi giá trị `operation` truyền vào `publish_next` (codegraph: mọi nơi gọi, cả giá trị lấy
   từ command kind). Test quét AST của `src/` lấy mọi chuỗi literal truyền làm `operation` và mọi kind của command editor, khẳng
   định mỗi cái thuộc đúng một bảng. Commit.
3. `publish_next` ghi `scene_edit` sau khi publish thành công (cần `database`: dùng persistence đã có của registry; registry không
   có persistence → không ghi). Test: publish → 1 sự kiện đúng origin; CAS thất bại → 0 sự kiện; DB ghi lỗi → publish vẫn thành công. Commit.
4. Router + hai route + role matrix (Guest job người khác 403, Viewer không có quyền sửa 403). Test các luật từ chối. Commit.

## Acceptance criteria
1. Ghi lỗi nhật ký không làm hỏng publish hay route chính.
2. Mọi operation trong `src/` được phân loại; thêm operation mới mà quên phân loại thì test đỏ.
3. Route từ chối đúng 5 luật ở trên; `actor_id` không giả được qua body.
4. Không đổi hành vi publish (test editor hiện có vẫn PASS).

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_value_events.py tests/test_api/test_value_routes.py \
  tests/test_api/test_role_matrix.py tests/test_scene/test_scene_editor.py -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```
(Nếu tên file test editor khác, tìm bằng codegraph và ghi vào report.)

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Frontend (T-029), tổng hợp (T-032).
