# RunPod auto provisioning — implementation report

## Outcome

Đã implement controller RunPod và tích hợp vào queue/worker hiện có. Đây là code và automated-test evidence trong workspace; **chưa deploy, chưa tạo Pod thật, chưa xác nhận cloud 0 → 1 → 0**.

Provisioning và CPU lane mặc định tắt. Không đọc/đổi production secrets, không gọi API tạo tài nguyên trả phí, không push/merge/commit. Bucket đích theo xác nhận của user là `real2sim`; việc áp private config và xác minh cloud vẫn thuộc bước deploy được ủy quyền sau.

Base commit là `45cd6f43d9a5276b3287975b403edc2ad213d2df`. Workspace đã có thay đổi deployment/distributed-demo trước task này. Các thay đổi đó được giữ lại; diff với HEAD không phải toàn bộ là thay đổi của GPU task.

## Implemented

| Hạng mục | Kết quả |
| --- | --- |
| Durable state | Migration 25 thêm `r2s_gpu_control` và `r2s_gpu_history`. Một control row giữ leader lease, create intent, generation token, Pod, pinned profile, worker markers, idle/drain state và estimated expenditure. History giữ kết quả qua restart. |
| Cold start | Catalog checksum + pinned image/ExecutionProfile có sẵn trước heartbeat đầu tiên. API chọn catalog matching config/seed; input qualification registry có thể đi kèm catalog. `/ready` phân biệt control-plane readiness với compute availability. |
| Work inventory | Main và registered demo schemas: pipeline preview/finalize, scene operations, registration, validation, imports; chờ người dùng không phải GPU demand. Closed demo vẫn được kiểm tra active work. Scanner không copy recording hoặc tải geometry để đếm việc. |
| Resource selection | Approved GPU types, acceptable CUDA versions, resource floors và evidence reference trong profile; live inventory quotes trước create. Persisted resource waits loại profile thiếu VRAM/RAM/disk; có thể chọn profile lớn hơn đã qualify. |
| RunPod adapter | REST list/get/create/start/stop/delete; GraphQL read-only quote; sanitized errors, bounded request timeout, Retry-After và fail-closed malformed responses. |
| Duplicate prevention | DB row lock/leader lease + intent persist trước HTTP. Lost create response không dẫn tới POST lặp; reconcile/adopt bằng intent/name/token/image. Late response không ghi đè leader mới. |
| Claim/drain safety | Pipeline lease acquisition, registration, validation, scene và import claims dùng main control-row gate trong chính transaction claim. Scoped demo giữ nguyên search_path nhưng đọc control state ở public. |
| Publication protection | Actual claim đánh dấu worker busy; marker tồn tại đến khi synchronous operation/publication trả về. Empty polling không reset idle. Existing leases, fencing, CAS và checksum publication được giữ. |
| Idle cleanup | Idle mặc định 240 giây, đóng claim gate, scan lại rồi terminate và confirm absence trước tạo replacement. New demand trước irreversible terminate có thể hủy drain. |
| Crash/reconciliation | Startup timeout, worker heartbeat loss, controller restart, provider errors, stale leader, changed release catalog và reappearing historic owned Pod đều có handling. Historic resource vẫn được reconcile khi queue rỗng/provisioning disabled. |
| Cost guards | Explicit hourly/total budget, max1 Pod, startup/idle/soft lifetime limits, bounded provision attempts, disable/drain/resume. Estimated cost và phase duration được persist. Healthy jobs không bị kill vì soft budget/lifetime. |
| Supervisor | Controller/optional CPU worker chạy ngoài GPU, cùng Railway API container, không phụ thuộc HTTP. Child failure được supervisor phát hiện; controller loop retry lỗi DB tạm thời thay vì làm hết Railway restart retries. |
| CPU lane | Opt-in subprocess cho registration/CPU imports và CPU scene path đã khai báo; dependency/headroom preflight, CPU affinity/address-space budget, existing operation admission. Bị chặn nếu chưa có qualification reference. |
| Outage policy | Live provisioning bị chặn nếu không có approved outage policy reference. Có CLI `watchdog` cho independent host/scheduler, không tạo Pod mới. Chưa triển khai watchdog bên ngoài thật. |

Không thay PostgreSQL queue bằng hệ thống khác, không chuyển Serverless, không sửa landing hoặc custom auth, không mở anonymous GPU jobs.

## Files

### New modules

- `src/services/orchestration/gpu/__init__.py`
- `src/services/orchestration/gpu/config.py`
- `src/services/orchestration/gpu/catalog.py`
- `src/services/orchestration/gpu/classification.py`
- `src/services/orchestration/gpu/state.py`
- `src/services/orchestration/gpu/provider.py`
- `src/services/orchestration/gpu/workload.py`
- `src/services/orchestration/gpu/controller.py`
- `src/services/orchestration/gpu/worker.py`
- `src/services/orchestration/gpu/cpu_worker.py`
- `src/services/orchestration/gpu/supervisor.py`
- `scripts/cloud/runpod_controller.py`
- `scripts/cloud/gpu_catalog.py`

### Existing integration points changed

- `src/config.py`, `src/main.py`: catalog setting and readiness.
- `src/services/orchestration/inputs/assembly.py`: qualified input registry from sealed release.
- `src/services/orchestration/projects/registry.py`: cold-start profile selection.
- `src/services/orchestration/jobs/database.py`: additive migration 25.
- `src/services/orchestration/jobs/lease.py`, `registration_operations.py`, `worker_cli.py`: managed claim/worker lifecycle.
- `src/services/orchestration/review/validation_queue.py`: validation claim gate.
- `src/services/orchestration/scene/objectify_queue.py`: shared classifier, gate, CPU-compatible selection.
- `src/services/orchestration/uploads/scene_imports.py`: shared classifier, gate, CPU-compatible selection without GPU head-of-line blocking.
- `src/services/orchestration/samples/session_worker.py`: release-aware demo dispatch and CPU demo child support.
- `scripts/studio/container_entrypoint.py`: supervised CPU control processes.
- `scripts/studio/deploy_env.py`: enablement validation and credential separation.
- `scripts/gpu/docker_entrypoint.sh`: native preflight before a managed worker starts.
- `deploy/studio/production.env.example`, generated `api.env.example`: disabled defaults and policy settings. Examples regenerated through the existing renderer.

### Tests and operations

- `tests/test_gpu/test_runpod_lifecycle.py`
- `tests/test_gpu/test_runpod_postgres.py`
- `tests/test_packaging/test_deploy_env.py`: credential boundary/enablement checks; updated existing fixture expectations for STUDIO_WORKERS=1 and pinned demo archive.
- `deploy/studio/RUNPOD_AUTOPROVISION.md`: deployment, catalog, cost limitations, outage procedure, CLI and acceptance gates.
- This directory: report and evidence logs.

## Reused versus new

Reused: RuntimeDatabase transaction/migration adapter; existing durable job/operation queues; job/runtime identity and software checksum; scene revision/CAS; lease renewal and recovery; ResourceAdmission; immutable ArtifactRemote publishers; demo registry/schema isolation; env renderer; native preflight.

New: RunPod provider transport, durable GPU lifecycle/ownership ledger, release catalog, workload adapters, control-row claim gate, whole-operation worker marker, cost guards, independent watchdog command, supervisor and optional CPU lane.

Vast CLI behavior remains available. Its main-only workload counter and in-memory idle timer were not reused as the RunPod controller's correctness boundary.

## Verification — actual recorded results

User sau cùng yêu cầu **không chạy lại test**. Từ yêu cầu đó trở đi chỉ đọc kết quả đã chạy trước đó, hoàn thiện tài liệu và dọn container test do task tạo. Không khởi chạy pytest mới.

| Lượt đã hoàn tất | Kết quả | Phạm vi |
| --- | --- | --- |
| Focused new lifecycle + PostgreSQL tests cuối cùng, đã khởi chạy trước yêu cầu ngừng rerun | **53 passed in 4.18s** | Có test mới nhất về persisted resource wait loại profile nhỏ. Bao gồm 3 test PostgreSQL thật. |
| Broad focused regression trước thay đổi cuối về resource-wait profile filtering | **309 passed in 34.08s** | GPU/Vast, leases, admission, registration, validation, import, scene queue, runtime selection, demo API, artifacts, release recovery, env rendering, input resolution. Log: `pytest.log`. Không nhận đây là broad regression đã rerun sau patch cuối. |
| Ruff check / format của các file mới và integration paths | Pass ở các lượt đã thực hiện | `checks.log` ghi lượt 30 files; sau các patch cuối đã chạy Ruff targeted và format trên GPU modules/test tương ứng. Không chạy lại từ yêu cầu ngừng rerun. |
| Bash syntax + git diff whitespace | Pass ở lượt đã thực hiện | `checks.log`; không phải runtime/deployment proof. |
| CodeGraph / graphify | Source/callers traced; graph updated | `codegraph-callers.txt`; AST-only update, không dùng LLM để bịa hành vi. |

Hai lượt test có overlap; **không cộng 309 + 53** thành số test khác nhau.

Commands đã chạy:

```bash
R2S_GPU_TEST_DATABASE_URL=<disposable-local-db> .venv/bin/pytest -q \
  tests/test_gpu/test_runpod_lifecycle.py tests/test_gpu/test_runpod_postgres.py \
  --disable-warnings --maxfail=2
```

```bash
R2S_GPU_TEST_DATABASE_URL=<disposable-local-db> .venv/bin/pytest -q \
  tests/test_gpu/test_runpod_lifecycle.py tests/test_gpu/test_runpod_postgres.py \
  tests/test_gpu/test_gpu_autoscaler.py tests/test_gpu/test_gpu_autoscaler_runtime.py \
  tests/test_orchestration/test_job_lease.py tests/test_orchestration/test_resource_admission.py \
  tests/test_orchestration/test_registration_worker.py tests/test_orchestration/test_validation_queue.py \
  tests/test_orchestration/test_import_queue.py tests/test_orchestration/test_scene_objectify_queue.py \
  tests/test_orchestration/test_worker_runtime_selection.py tests/test_api/test_demo_sessions.py \
  tests/test_orchestration/test_artifact_remote.py tests/test_orchestration/test_release_sealing_recovery.py \
  tests/test_packaging/test_deploy_env.py tests/test_reconstruction/test_input_assembly_resolution.py \
  --disable-warnings --maxfail=3
```

PostgreSQL acceptance dùng image `postgres:16-alpine` local, DB riêng `r2s_gpu_test`, port chỉ bind 127.0.0.1. Các case kiểm chứng: 2 controller tạo đúng 1 Pod qua fake provider; transaction claim chặn drain; demo schema không ghi main queue và demo demand được đếm khi main rỗng. Đây là PostgreSQL lock/scope evidence thật, không phải RunPod thật.

Container `r2s-runpod-tests-20261019` đã được đối chiếu exact container ID của task rồi xóa cùng anonymous volume. Không đụng local Studio DB, Supabase hoặc container khác.

Các failure ở lượt trung gian đã xử lý: fixture env cũ còn giả định STUDIO_WORKERS=3/chưa pin demo archive; SQLite URI bị urlunsplit làm sai trong worker initialization test. Kết quả final nêu trên là sau các sửa này.

## Acceptance boundaries and remaining blockers

| Gate | Evidence hiện có | Còn thiếu / cách giải quyết |
| --- | --- | --- |
| Cold start 0 → 1 | API creates job from catalog with zero previous worker; mocked controller creates one Pod | Native worker/image + actual GPU stage chưa chạy. |
| Concurrent controllers | Real local PostgreSQL row-lock test, durable intent, stale-response tests | Supabase/Railway rollout/network acceptance chưa chạy. |
| Safe drain 1 → 0 | Lease/publication marker, empty polling, new work during grace/drain and mock delete confirmation | Live long reconstruction/upload interruption test chưa chạy. |
| Worker and controller crashes | Tests for expired worker, valid remaining lease, create timeout/adoption, stale leader, DB outage, historic resource cleanup | Provider interruptions và full control-plane outage thật chưa thử. |
| GPU image | Pinned digest/capability contract, native preflight wiring | Chưa build/qualify image mới. Local disk khoảng 2 GB free tại audit, không đủ coi là GPU build host. Dùng builder đủ disk; không tự thuê builder/GPU. |
| Isaac | Queue and lifecycle aware; unsupported kinds stay blocked | `scripts/gpu/make_runtime_manifest.py:65–66` vẫn đánh dấu Isaac/OpenUSD UNVERIFIED; reconstruction Dockerfile không cài Isaac. Cần image/launcher/profile qualified trước khi bật validation. |
| CPU lane capacity | Code preflight and insufficient-headroom test; disabled default | `gpu/cpu_worker.py:23` không chứng minh native job + API latency/RAM trên Railway. Cần benchmark đúng image/resources; nếu không đủ, dùng separate CPU worker sau approval. |
| Control-plane outage | `gpu/config.py:37` blocks live enablement without approved policy; external watchdog CLI exists | Chưa có independent watchdog được triển khai hoặc approved operator procedure reference. Không claim orphan cleanup khi Railway và DB đều down. |
| Spending | Explicit positive hourly/total budget required; no assumed account limit | User báo credit có nhưng chưa duyệt USD/giờ và tổng ngân sách. Chặn P8. |
| R2/Supabase | User xác nhận bucket real2sim, DB active | Chưa live verify credentials/access trong task. Worker will verify R2 on real boot; không giả local MemoryObjectStore là R2 proof. |
| Demo bootstrap P0 | `samples/release.py:225` staging ZIP + extract cùng volume. ZIP hiện tại 3,373,872,210 bytes; tổng uncompressed ZIP members 3,964,444,243 bytes; combined conservative archive metadata footprint 7,338,316,453 bytes | Không phải measured runtime disk peak. Giải quyết staging/volume/cache riêng và đo peak thực trước deploy 3 scene. GPU task không sửa bootstrap. |
| Release bundle | Source đã đổi so với bundle trước | Rebuild source bundle sau khi chốt; không deploy source ZIP cũ và coi nó có autoscaler mới. |

## Cost and emergency limitations

- Bình thường GPU compute ở idle kỳ vọng 0 sau confirmed termination. API/controller CPU/RAM, DB, R2 và registry vẫn có thể có phí.
- Quote/estimate guard không phải hard provider cap. REST create có thể allocate giá khác quote; controller kiểm lại trước claim nhưng không thể xóa startup charges đã phát sinh.
- Budget/lifetime là soft drain: không kill healthy work để giữ con số tuyệt đối.
- Unknown create hoặc ownership không rõ sẽ chặn tạo thêm và yêu cầu reconciliation; không tự xóa tài nguyên chỉ vì trùng prefix.
- Khi control plane và/hoặc DB mất kết nối, không có guarantee cleanup độc lập nếu chưa có approved external operating procedure. Public provisioning mặc định bị chặn ở gate này.

## Next authorized boundary

Code và test evidence local đã có. Không cần credentials mới để review implementation. P8 chỉ thực hiện khi có approved image digest/resource qualification, budget cụ thể, outage policy và authorization chạy cloud. Không tự commit/push/deploy trong task này.

## Pre-flight — GUIDE.md Rule 13

- codegraph: worker dispatch, queue claims, lease acquire, runtime registry/job_profile, container startup and affected callers traced; caller output saved.
- impact: all durable worker claim paths, main/demo schemas, API runtime availability, deployment startup. Local/unmanaged mode preserved behind disabled defaults.
- understand: source-traced upload → durable queues → admission/claim → worker → R2 publication → terminal CAS; dedicated understand-anything tool unavailable.
- minimal-code: reused RuntimeDatabase, existing queue/recovery/admission/publication contracts; stdlib transport, existing Pydantic and dotenv. No replacement queue/provider SDK framework.
- checks: actual outcomes and snapshot limits above. TypeScript/ESLint/Vitest n/a for this backend task; existing unrelated frontend dirt preserved.
- DevTools: n/a — no rendered UI change. No browser/GPU/Isaac/cloud acceptance claimed.
