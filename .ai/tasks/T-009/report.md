# T-009 report

## Outcome

Thêm mode `geometry` vào durable objectify queue. Worker gọi `build_object_geometry` với base revision, admission/lease commit guard, cancellation event và progress callback. Lỗi `ObjectGeometryBuildError` giữ thông điệp và retryable trong state; scene vẫn là Draft nếu chưa commit.

Route `POST /api/v1/jobs/{job_id}/scene/geometry/build` trả 202 queued với operation_id/base_revision/phase null; ready → 422, stale/busy → 409. Route có contributor dependency, ownership guard đúng operation, cùng quota/audit GPU như route membership hiện có. Envelope lỗi giữ `{detail}`.

Extraction của job `auto` tạo/publish Draft trước rồi enqueue geometry bằng actor hệ thống. `required` không enqueue. Retry extraction giữ operation geometry đang queued/running trên cùng revision.

## Changed files

- `src/services/orchestration/scene/objectify_queue.py`: mode, Draft gate, geometry worker dispatch, progress và retryable projection.
- `src/api/product/scene.py`: body model và route geometry/build.
- `src/services/orchestration/scene/extraction.py`: auto Draft + enqueue.
- `tests/test_orchestration/test_scene_objectify_queue.py`: request/worker/admission/cancel/retry/lease tests.
- `tests/test_api/test_scene_v2_routes.py`: 202/409/422/401 và response envelope.
- `tests/test_api/test_role_matrix.py`: đăng ký route authenticated.
- `tests/test_orchestration/test_scene_extraction.py`: auto/required cho shell và objectgs, giữ config và queue operation khi retry.
- `.ai/tasks/T-009/report.md`, `.ai/status.md` chỉ dòng T-009.

Frontend `ObjectifyMode` đã có `geometry` trong commit đồng thời của T-013 `815cb30b`. T-009 kiểm type/lint trên file đó và không chép lại hay commit phần UI/region của agent khác.

## Verification

Đúng nhóm Tests required, chạy ngoài sandbox sau khi xác định thread wakeup của AnyIO bị treo trong sandbox:

```bash
.venv/bin/python -m pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py tests/test_orchestration/test_scene_extraction.py -q
```

**88 passed in 8.15s**, không skip. Không chạy full suite.

```bash
.venv/bin/ruff check src/services/orchestration/scene/objectify_queue.py src/api/product/scene.py src/services/orchestration/scene/extraction.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py tests/test_orchestration/test_scene_extraction.py
.venv/bin/ruff format --check src/services/orchestration/scene/objectify_queue.py src/api/product/scene.py src/services/orchestration/scene/extraction.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py tests/test_orchestration/test_scene_extraction.py
```

`All checks passed!`; `7 files already formatted`. `git diff --check`: sạch.

`graphify update .`: exit 0; **25.133 nodes, 77.981 edges, 811 communities**. Đã cập nhật graph.json/graph.html/GRAPH_REPORT.md (gitignored). Không chạy LLM label.

Trong `frontend/`:

```bash
npm run typecheck
npx eslint src/lib/api/studio.ts
```

Type generation và `tsc --noEmit` exit 0; eslint exit 0. Kiểm typecheck lần cuối sau khi các commit frontend đồng thời đã xuất hiện cũng exit 0.

### Red → green

1. Geometry request: 2 failed vì `_Record` chưa nhận geometry; thêm mode/Draft gate/phase null → 2 passed.
2. Geometry worker: 5 failed/2 passed vì mode mới đi vào nhánh boxes, chưa gọi service và chưa yêu cầu GPU. Nối dispatch, phase, typed error/retryable và admission → toàn bộ queue file 37 passed. Test lease loss gọi recovery sau khi chứng minh CAS bị fence, đúng lifecycle hiện có.
3. Route: 5 failed do 404 trước khi có route. Sau nối route: 5 passed khi chạy ngoài sandbox; role matrix 6 passed. Toàn bộ nhóm cuối 88 passed.
4. Auto: 2 failed/2 passed vì chưa chuyển auto sang Draft/enqueue. Nối extraction → file extraction 5 passed.
5. Frontend type đã được T-013 bổ sung đồng thời; kiểm typecheck/eslint xanh, không có assertion hay logic UI do T-009 thêm.

### Sandbox diagnosis

Lượt API trong sandbox treo mà không hoàn tất test. Lượt chẩn đoán với `-o faulthandler_timeout=20` cho thấy worker AnyIO chờ queue, event loop chờ selector. Đã dừng hai lượt treo bằng Ctrl-C, không coi là PASS. Chạy cùng 5 test API ngoài sandbox → 5 passed trong 0,36 s; nhóm Tests required ngoài sandbox → 88 passed.

## Acceptance evidence

- Request Draft có mode geometry, operation_id và revision snapshot; không cần checkpoint SAM2.
- Worker success gọi service qua admission/commit_guard, ghi các phase shell/quality/collider/environment/publish rồi done, result_revision là scene Ready mới. Callback lưu chuỗi bất kỳ nên phase objectgs của T-008 cũng được truyền nguyên trạng.
- Queued/running cancel giữ scene Draft. Running cancel kiểm CAS bị từ chối ngay cả trước khi polling event, rồi xác nhận event được bật.
- Build lỗi có tên Ghế 1 và retryable=False trong state; gửi yêu cầu mới sau sửa có operation_id mới và chạy done.
- Lease hết hạn: CAS không thể commit; recovery đánh dấu failed. Resource wait giữ operation_id, requeue và không gọi build.
- GPU required vẫn True dù box-candidate path CPU-only; dùng profile scene operation hiện có.
- HTTP 202 queued/409 stale/409 busy/422 ready/401 anonymous; role matrix guard passed.
- Auto shell/objectgs đều publish Draft rồi queue geometry, giữ refinement/sam_batch/CoACD/inpaint config; required không queue. Job config niêm phong không bị sửa.

Các test worker/build wiring dùng service/provider thay thế và registry/DB thật trong fixture; không phải bằng chứng GPU/live deployment/browser hoặc ObjectGS E2E.

## Decisions and deviations

1. Auto: direct `objectify()` vẫn giữ hành vi cũ khi nhận auto. `extract_scene` truyền config thực thi với `geometry_review=required` để tạo Draft, giữ tất cả knob khác từ sealed job, rồi provenance ghi lại lựa chọn auto và xếp build sau publication. Không đổi `_publish_draft`, không đổi chữ ký objectify_with_retry và không bỏ mất config nhóm coacd/inpaint.
2. Tái dùng `operation_profile_for_job(..., gpu_required=True)`, cùng profile scene operation dùng cho nhánh boxes có GPU. Đây là estimate finalize hiện có, có thể bảo thủ; không bịa một mức VRAM inpaint nhỏ. Nếu chưa có estimate, cơ chế resource admission vẫn fail closed/chờ như trước.
3. Tạo `ObjectGeometryAlreadyReadyError` nội bộ kế thừa ObjectifyRequestError để route phân biệt 422 ready với 409 busy mà không so chuỗi thông điệp. Không thêm code vào HTTP body.
4. Đặt body model GeometryBuildRequest trong route module, chỉ có expected_scene_revision; không mở rộng body objectify cũ để tránh gửi geometry vào endpoint tách vật cũ.
5. Frontend type được commit bởi T-013 trong lúc T-009 chạy. Thử stage hunk riêng đã không áp dụng vì commit đó đã có sẵn; index không đổi. Không commit thêm vì không còn diff type thuộc T-009. Các commit T-013 không được tính là commit T-009.
6. Actor tự enqueue là `system`. Các request thủ công ghi user_id hoặc local như route membership. Retry extraction chỉ tái dùng geometry operation đang queued/running có cùng base_revision; không thay yêu cầu của mode khác.

## Commits T-009

- `b7253a94` Mark T-009 in progress
- `297f7ad1` Accept geometry requests only for the current draft revision
- `42c973c4` Run geometry builds through durable worker leases and admission
- `c32ed6ba` Expose authorized geometry build requests with draft and conflict responses
- `3b109112` Queue automatic geometry builds after publishing reviewed extraction

## Pre-flight (GUIDE.md Rule 13)

- codegraph: đọc queue request/state/process_next, admission profile, extraction, route membership/objectify và frontend ObjectifyMode trước sửa; đã đọc review T-007 và plan T-009.
- impact: callers request gồm API và test; process_next được worker_cli gọi. Geometry build service giữ nguyên chữ ký T-007. TypeScript consumers gồm ObjectifyNotice/useObjectify/requestObjectify; đã typecheck toàn frontend.
- understand: request → snapshot → lease/admission → service progress/cancel/fenced commit → terminal state; extraction auto → Draft publication → queued geometry. Đã dùng graphify query. UNVERIFIED: understand-anything explain/domain không có tool trong session; dùng codegraph và tài liệu.
- minimal-code: rung 2 — dùng chung durable queue, progress callback với membership, ResourceAdmission và build service đã accepted; không thêm queue riêng.
- checks: pytest 88 passed, ruff check/format sạch, TypeScript typecheck và eslint sạch.
- DevTools: n/a — T-009 không sửa rendered UI; API được kiểm qua ASGI, không claim browser acceptance.

## Architect review

Không có quyết định contract cần chốt thêm. T-008, T-010/T-011 và UI T-013 không được triển khai trong task này.


## Round 2 — Required change từ review

### Outcome và changed files

- `src/services/orchestration/scene/extraction.py`: bắt `ObjectifyRequestError`, `SceneError`, `ArtifactStoreError` quanh bước đọc queue/enqueue geometry sau `publish_initial`. Ghi warning chứa job_id và lý do; tiếp tục trả `StageArtifact` SUCCEEDED với reference Draft đã publish. Lỗi publication vẫn truyền ra như trước.
- `tests/test_orchestration/test_scene_extraction.py`: thêm hai trường hợp auto shell/ObjectGS với `request()` raise `ObjectifyRequestError`. Kiểm stage SUCCEEDED, Draft rev-001 còn được đọc từ registry, queue idle và warning có job_id/lý do. Giữ các trường hợp auto enqueue thành công, retry không xếp trùng và required không enqueue.
- `.ai/status.md`: chỉ dòng T-009 chuyển in-progress rồi implemented.

### Verification

Test-first, trước sửa source:

```bash
.venv/bin/python -m pytest tests/test_orchestration/test_scene_extraction.py -q
```

**2 failed, 5 passed in 1.00s**: cả shell và ObjectGS bị `ObjectifyRequestError` truyền ra từ request sau publication.

Sau sửa, chạy cùng lệnh: **7 passed in 0.96s**, không skip. Không chạy full suite.

```bash
.venv/bin/ruff check src/services/orchestration/scene/extraction.py tests/test_orchestration/test_scene_extraction.py
.venv/bin/ruff format --check src/services/orchestration/scene/extraction.py tests/test_orchestration/test_scene_extraction.py
```

`All checks passed!`; `2 files already formatted`. `git diff --check`: sạch.

### Decisions và pre-flight

- Không đổi contract, schema, artifact hay queue lifecycle. Catch bao gồm `state()` vì bước này cũng chạy sau publication và có thể phát sinh SceneError/ArtifactStoreError. Không xử lý suggestion refactor config ngoài phạm vi Required change.
- codegraph: đọc extract_scene, queue state, các lớp lỗi và callers extract_scene; caller chính là jobs/runner._extract_scene_stage. Đã chạy graphify query để định hướng.
- understand: thay đổi cục bộ vào flow đã đọc, Draft publication → auto queue → StageArtifact; không cần tra business context mới.
- minimal-code: dùng các lớp lỗi và logger hiện có, không thêm helper hay fallback.
- checks: pytest 7 passed; ruff check/format sạch. DevTools n/a — service không sửa UI. Đây là fixture proof, không phải GPU/live deployment evidence.
- Architect: không có quyết định cần chốt thêm.

### Commits Round 2

- `c547184b` Mark T-009 review fix in progress
- `afe537e1` Preserve extraction success when automatic geometry enqueue fails

`graphify update .`: exit 0; 25.205 nodes, 78.255 edges, 823 communities. Đã cập nhật graph.json/graph.html/GRAPH_REPORT.md; không chạy LLM label.

## Round 3 — Runtime gate trước auto config

- Đã đọc review Round 3 và CodeGraph `extract_scene`/`test_objectify_draft.py`; caller chính vẫn là jobs runner.
- `extraction.py`: khởi tạo auto_geometry=False; chỉ load sealed config, tính auto và tạo execution override trong nhánh objectify sau runtime gate. Nhánh auto giữ nguyên Draft/enqueue và warning khi enqueue lỗi.
- `test_objectify_draft.py`: job giả có config_checksum, registry giả có resolver, stub config None; runtime-gate test cấm đọc config.
- Trước sửa: nhóm 3 file **2 failed, 53 passed in 7.75s**. Sau sửa fixture, trước sửa source: Draft file **1 failed, 10 passed** đúng lỗi thứ tự gate.
- Sau sửa:
  `.venv/bin/python -m pytest tests/test_scene/test_objectify_draft.py tests/test_orchestration/test_scene_extraction.py tests/test_orchestration/test_scene_objectify_queue.py -q`
  → **55 passed in 7.76s**, không skip, không full suite.
- `.venv/bin/ruff check src/services/orchestration/scene/extraction.py tests/test_scene/test_objectify_draft.py` → All checks passed.
- `.venv/bin/ruff format --check src/services/orchestration/scene/extraction.py tests/test_scene/test_objectify_draft.py` → 2 files already formatted. `git diff --check` sạch.
- Commits: `111324b6` status in-progress; `62e6288a` runtime ordering + fixture regression.
- Pre-flight: CodeGraph/source/callers đã đọc; sửa thứ tự cục bộ, không đổi contract/artifact, không thêm abstraction; service-only nên DevTools n/a. Không có quyết định cần Architect chốt. T-010 đang dở được giữ riêng.
- `graphify update .`: exit 0; 25.261 nodes, 78.551 edges, 809 communities; không chạy LLM label.

## Round 4 — Fixture ObjectGS còn thiếu field

Đã đọc mục Review T-009 — Round 3 mới bổ sung và CodeGraph toàn bộ `test_objectgs_required_stage.py`.
Sửa duy nhất fixture `test_required_objectgs_failure_never_publishes_a_legacy_scene`: job giả có job_id/config_checksum,
registry giả có runtime_resolver, `extraction.load_job_config` trả None. Giữ nguyên assertions ObjectifyError và không publication.
Không sửa production source hoặc assertion để bỏ qua lỗi.

Chạy đủ sáu file theo review, trước sửa: **1 failed, 96 passed in 16.74s**; đúng nhánh runtime_available=True thiếu job_id.
Sau sửa:

```bash
.venv/bin/python -m pytest tests/test_scene/test_objectify_draft.py tests/test_scene/test_objectgs_required_stage.py \
  tests/test_orchestration/test_scene_extraction.py tests/test_orchestration/test_scene_objectify_queue.py \
  tests/test_scene/test_objectgs_objectify_flow.py tests/test_scene/test_objectify_config_override.py -q
```

**97 passed in 15.83s, 0 failed**, không skip; không full suite.

```bash
.venv/bin/ruff check tests/test_scene/test_objectgs_required_stage.py src/services/orchestration/scene/extraction.py tests/test_scene/test_objectify_draft.py
.venv/bin/ruff format --check tests/test_scene/test_objectgs_required_stage.py src/services/orchestration/scene/extraction.py tests/test_scene/test_objectify_draft.py
```

`All checks passed!`; `3 files already formatted`.

Commits riêng: `a48ffc1f` status in-progress; `e7d692bc` fixture fix. Không có quyết định Architect cần chốt.
Pre-flight: fixture-only, đã đọc CodeGraph/source, sáu file test và ruff xanh; không đổi shared contract/runtime; DevTools n/a.

`graphify update .`: exit 0; 25.280 nodes, 78.588 edges, 849 communities; không chạy LLM label. `git diff --check` sạch.
