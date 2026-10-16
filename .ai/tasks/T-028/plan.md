# T-028: Đo thời gian máy cho hàng đợi tách vật

## Goal
Các mode của hàng đợi tách vật (`objectify`, `membership`, `geometry`, `region`) hiện **không** ghi `ResourceUsage`, nên
phút máy của job đếm thiếu. Sau task này mỗi lần chạy xong (hoặc hỏng/hủy) của mode nào cũng ghi một bản ghi
`scene.<mode>`, và `processing_seconds` cộng đủ các lượt `scene.*` đã hoàn tất.

## Context
- `.ai/architecture.md` §15.1 (bảng metric: phút máy là metric chính) và §15.2 (dòng "Đo máy cho hàng đợi tách vật":
  tool `scene.<mode>`, cùng `attempt_id` = `operation_id`, `processing_seconds` cộng cả các bản ghi này).
- §15.3 quy tắc 6: mọi số ghi rõ nguồn (`measured` / `unavailable`), không đoán.
- Đã kiểm tra trên code hiện tại:
  - `src/services/orchestration/scene/objectify_queue.py:712` `process_next`: `uses_gpu` ~755, `request = OperationAdmissionRequest(...operation_id=...)` ~761,
    `workspace = root / f"{mode}-{uuid}"` ~782, khối dispatch `if running.mode in {"membership","geometry","region"}` ~788–831,
    dựng `outcome` dict ~834–864, `finally` ~866 (heartbeat stop, release reservation), `_finish` ~872.
  - `src/services/orchestration/jobs/runner.py:315` `_resource_sampler` (riêng tư, nhận `_Attempt`) và `:281` `_persist_usage`
    (INSERT vào `r2s_resource_usage`). Queue không dùng lại được hai hàm này.
  - `src/services/orchestration/processing/telemetry.py`: `Outcome` :33, `ResourceContext` :~40, `ResourceUsage` :53,
    `ResourceSampler` :159, `sampled_section` :253 (thread nền, `on_error` cho lỗi đo, join khi thoát).
  - `src/services/orchestration/processing/observed.py:71` `processing_seconds`: hiện lấy lượt `completed` gần nhất theo
    `(job_id, tool)` — đúng cho tool pipeline, **sai** cho `scene.*` (chạy Tạo mesh hai lần sẽ chỉ đếm một lần).
  - `observed_budget` (observed.py:91) chỉ đọc bản ghi có `tool` trong `PHASE_TOOLS` và `params is not None`; bản ghi `scene.*`
    không đặt `params` nên không ảnh hưởng ngân sách VRAM/RAM. Giữ nguyên tính chất này.
  - `api/studio/scenes.py:354` dùng `processing_seconds(load_usages(...))` cho cột thời gian máy của scene.
- Đã chốt (không đổi trong task này, ghi vào report): `evaluation/scorecard.py` (`_ram_metric`, `_vram_metric`) và
  `benchmark.py` (`_tool_timings`) chọn bản ghi theo `config_checksum`/job. Bản ghi `scene.*` mang `config_checksum` riêng
  của mode. **Architect đã chốt:** hai chỗ này mô tả lượt chạy pipeline của một attempt, nên **giữ nguyên, không đưa `scene.*`
  vào**. Thời gian máy và đỉnh RAM/VRAM của `scene.*` chỉ được đọc ở bảng giá trị T-032. Engineer vẫn ghi vào report việc đã
  kiểm rằng hai thẻ không đổi số.

## Files
- Tạo: `src/services/orchestration/processing/usage_recording.py`
  - `build_sampler(settings, context, workspace) -> ResourceSampler | None` (tách từ `runner._resource_sampler`, phần sau khi đã có `context`).
  - `record_usage(database, usage) -> None` (tách từ `runner._persist_usage`).
- Sửa: `src/services/orchestration/jobs/runner.py` — gọi hai hàm trên thay cho phần code đã tách; không đổi hành vi.
- Sửa: `src/services/orchestration/scene/objectify_queue.py` — bọc khối dispatch trong `sampled_section`, ghi bản ghi trong `finally`.
- Sửa: `src/services/orchestration/processing/observed.py` — `processing_seconds` (quy tắc cộng dồn `scene.*`).
- Test: `tests/test_orchestration/test_scene_objectify_queue.py`, `tests/test_orchestration/test_observed_budget.py`,
  và chạy lại `tests/test_orchestration/test_resource_telemetry.py` (bảo vệ phần tách ở runner).

## Steps
1. **Tách helper dùng chung** (không đổi hành vi): tạo `processing/usage_recording.py` với `build_sampler` và `record_usage`;
   `runner.py` chuyển sang gọi hai hàm này. Chạy `test_resource_telemetry.py` và `test_studio_processing_job.py`, phải xanh
   như trước. Commit (chỉ đúng các path đã sửa).
2. **Đo trong queue**: trong `process_next`, sau khi đã có `request` (admit thành công) và `workspace`:
   - Tạo `ResourceContext` với: `job_id=job_id`, `attempt_id=request.operation_id`, `tool=f"scene.{running.mode}"`,
     `config_checksum=config_checksum`, `runtime_manifest_checksum=job.runtime_manifest_checksum`, `params=None`,
     `shared_gpu=admission.shares_gpu()` (bọc try; lỗi thì `None`). `gpu_name` để sampler tự điền.
   - `sampler = build_sampler(settings, context, workspace)`; `workspace.mkdir(parents=True, exist_ok=True)` trước khi lấy mẫu.
   - Bọc khối dispatch (~788–831) bằng `with sampled_section(sampler, on_error=<log warning, không raise>):`.
   - Trong `finally` (trước khi release reservation): map `outcome["status"]` → `Outcome` (xem Interfaces), gọi
     `sampler.finish(...)` rồi `record_usage(...)`, mọi lỗi bắt và log warning, không đổi `outcome`.
   Commit.
3. **Quy tắc `processing_seconds`**: tool không bắt đầu bằng `scene.` giữ nguyên quy tắc lượt gần nhất; tool `scene.*` cộng
   dồn mọi lượt `completed`. Cập nhật docstring (ghi rõ hai quy tắc và lý do: mỗi lần Tạo mesh là một việc thật). Thêm test.
   Commit.
4. **Xác minh**: chạy lệnh ở "Tests required"; `graphify update .`; ghi `report.md` (gồm mục kết quả kiểm tra scorecard/benchmark
   ở Context); cập nhật `status.md` theo `role-engineer`.

## Interfaces

Mapping outcome của queue → `Outcome` của bản ghi (dựa trên `outcome["status"]` đã dựng trong queue, trước `_finish`):

| `outcome["status"]` | `ResourceUsage.outcome` | Tính vào `processing_seconds` |
| --- | --- | --- |
| `done` | `completed` | có |
| `cancelled` | `cancelled` | không |
| `failed` (kể cả lease lost / reservation lost) | `failed` | không |

Quy tắc `processing_seconds` (observed.py):

```python
def processing_seconds(usages: Iterable[ResourceUsage]) -> dict[str, float]:
    # Tool pipeline (không bắt đầu bằng "scene."): mỗi (job_id, tool) chỉ lấy lượt completed gần nhất.
    # Tool "scene.*": cộng dồn mọi lượt completed.
    # Chỉ outcome == "completed" được tính. Trả {job_id: tổng giây}.
```

Helper mới (`processing/usage_recording.py`):

```python
def build_sampler(settings: Settings, context: ResourceContext, workspace: Path) -> ResourceSampler | None: ...
def record_usage(database: RuntimeDatabase, usage: ResourceUsage) -> None:
    # INSERT INTO r2s_resource_usage(usage_id, job_id, recorded_at, payload); lỗi DB: log warning, không raise
```

Không đổi schema `ResourceUsage`, không đổi bảng `r2s_resource_usage`.

## UI/UX
Không có thay đổi UI trong task này.

## Acceptance criteria
1. Một lần Tạo mesh (`geometry`, test double) tạo đúng 1 `ResourceUsage` có `tool == "scene.geometry"`, `attempt_id == operation_id`,
   `duration_seconds > 0`, được ghi vào `r2s_resource_usage`.
2. Hai lần dựng lại vùng (`region`) → `processing_seconds` cộng cả hai lượt; tool pipeline (`preview`/`finalize`) vẫn chỉ lấy lượt mới nhất.
3. Huỷ và lỗi ghi `outcome` = `cancelled` / `failed` tương ứng và **không** cộng vào `processing_seconds`.
4. Lỗi đo (sampler raise trong `sample`, hoặc `build_sampler` trả `None`) không làm hỏng việc dựng: kết quả và `outcome` của job không đổi.
5. `observed_budget` cho cùng kết quả trước và sau task (bản ghi `scene.*` không có `params` nên không vào ngân sách).
6. Hành vi của runner không đổi: test cũ của `test_resource_telemetry.py` và `test_studio_processing_job.py` xanh.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_observed_budget.py -q
.venv/bin/python -m pytest tests/test_orchestration/test_resource_telemetry.py tests/integration/test_studio_processing_job.py -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```
- Test double cho sampler: monkeypatch `build_sampler` trong queue để trả stub ghi lại `sample`/`finish`; ít nhất một test
  dùng `ResourceSampler` thật với workspace tạm để chứng minh `duration_seconds > 0` và bản ghi được lưu.
- Test lỗi đo: stub `sample` raise, job vẫn `done`.

## Commit
Theo Steps (3 commit). Stage đúng path đã sửa (Codex cũng sửa cùng cây). Không thêm Co-Authored-By hay dòng "Generated with Claude Code".

## Out of scope
- Không đổi tool pipeline (`preview`, `finalize`, `scene_extract`) và cách tính ngân sách của chúng.
- Không đổi `scorecard.py` / `benchmark.py` (Architect đã chốt, xem Context).
- Không đo phút công người hay sự kiện Walk (T-027, T-029).
- Không tính chi phí theo giờ GPU (T-032).
- Ghi nhận giới hạn: nếu `_finish` bị fence sau khi kết quả đã commit, bản ghi vẫn theo outcome của tool, không suy ngược từ trạng thái job.
