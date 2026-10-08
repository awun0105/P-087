# AUD-15 — Đo và giảm worker latency theo stage

## Metadata và goal

- IN PROGRESS; P1; EX-PRODUCT + EX-REC; SCENE/SIM quality consumers.
- Canonical PRODUCT-02/08/09, REC-02/03/04/11. REUSE pipeline_runtime benchmark,
  processing telemetry/observed budget và existing retry cache.
- Goal: giảm thời gian xử lý không cần thiết, giữ selected quality và đo đúng
  queue, compute, publication, user waiting, time-to-first-preview và full job.
- [Agent guide](../AGENT_GUIDE.md), [Gemini evidence](../GEMINI_FINDINGS.md),
  [AUD-16](AUD-16-fast-preview.md).

## Baseline và scope

PipelineRuntimeBenchmark/build_benchmark đã tồn tại. Schema 1.0 ghi benchmark khi
job còn RUNNING và suy `total_seconds` từ stage đã biết, nên không chứng minh full
job. Audit lại DB, manifests, frame inventory và ResourceUsage cho thấy
`job-6bc02e5de4ed` xử lý 50 frame thực tế (cap 300), trên Quadro T2000, với tổng
5.046,05 giây process time qua prepare/preview/metric proposal/finalize/scene
extraction. Job wall time là 57.388,70 giây; 52.338,88 giây là thời gian chờ metric
confirmation. Hai checksum input/config/runtime là
`sha256:bfa8ad…` / `sha256:55d779…` / `sha256:861c5b…`. GPU power/thermal state
không được ghi, và đây chỉ là một sample. Một benchmark cũ khác ghi Brush ~44,9 phút
ở snapshot RUNNING, cũng chỉ có 50 frame và khác identity; không phải paired run.
Vì vậy claim “40–45 phút cho toàn job 300–500 frame” và trạng thái “đạt dưới 1 giờ”
đã bị gỡ khỏi benchmark report.

Target cho paired measurement đã đóng băng: cùng input/config/runtime, 50-frame
inventory, GPU/tool identity và selected config; median `worker_process_seconds`
≤ 4.541,45 giây, tương ứng giảm tối thiểu 10% so với run mốc 5.046,05 giây; tối
thiểu ba cặp baseline/optimized. Mỗi cặp ghi power/thermal state hoặc đánh dấu chưa
kiểm soát. Mốc hiện có không đủ điều kiện so sánh paired và không chứng minh target
đạt. Không suy GPU billing từ lifecycle/worker process time.

CodeGraph: PipelineRuntimeBenchmark/build_benchmark, _record_benchmark,
job_progress/studio_pipeline, ResourceAdmission, processing telemetry/observed,
BrushAdapter, ColmapAdapter, PrepareWorker/FinalizeWorker và stage journals.
Owned: orchestration benchmark/processing/jobs, REC adapter timing/cache ports,
eval/protocols/pipeline_runtime.md, paired benchmark scripts và focused tests.
Không đổi model, iterations, frame selection/resolution hoặc max splats của final
profile để gọi đó là performance fix; không thêm duplicate benchmark subsystem.

## Input / output / data contract

Input: immutable input/config refs, attempt journals, actual frame inventory,
hardware/runtime/tool identity và telemetry. Output: versioned timing evidence,
qualified cache/reuse changes và paired latency/quality report.

Schema 1.1 của benchmark hiện có ghi measurement completeness, số frame thực tế,
stage start/end/scope, queue, user wait, process duration, worker interval union,
first verified preview và input/config/runtime identity. Partial và terminal snapshot
có URI riêng; full job wall chỉ xuất hiện khi job terminal. Chưa có nguồn đáng tin
cậy cho GPU allocation, active GPU compute, I/O, publication hoặc power; các field
giữ null thay vì suy đoán. Vẫn đọc schema 1.0. Critical path chỉ tính khi stage
tuần tự có đủ timestamp và không overlap.
Không suy GPU billing từ toàn bộ user waiting; cost estimate cần measured allocation.

Cache key phải bao gồm source byte/logical identity phù hợp, preparation/selection
config, pose/frame binding, tool/runtime version và stage parameters. Cached output
phải verify checksum/required files trước reuse; config mismatch/missing/corrupt
artifact không được đánh dấu hit. Existing retry cache là baseline để đánh giá.
Observed estimator dùng measured supported profiles, không gán estimated time
thành progress percent thật hoặc sửa user-selected config.

## Logic change và dependent updates

Risk: **Cao nếu sửa cache/stage reuse** khi chỉ sửa một phần. Logic delta: Latency optimization và reusable preparation identity.
Cần sửa đồng bộ: source/preparation/sanitization refs, processing config/resource estimate, prepare/pose/train/package stages, retry/cache reader và telemetry.
Acceptance xuyên consumer: Cache hit chỉ exact content/profile/tool/maps; fail/cancel không fake complete timing, held-out geometry/visual quality không bị silently degrade.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập. S2 dùng resource invariants hiện có; operation admission extensions
theo AUD-07 nếu optimization chạm heavy operations. S3 phối hợp AUD-12 quality
protocol trên pipeline thực; AUD-16 đã Deferred theo yêu cầu owner và không còn là dependency.

## Sprint AUD-15.S1 — Complete timing và frozen benchmark protocol

**Input:** current benchmark/journals + actual input/frame/config/runtime refs.
**Output:** compatible timing extension, stage dependency map và reproducible protocol.
**Contract:** partial attempt khác terminal job; unknown khác zero; actual frames
khác cap; queue/metric confirmation wait khác active computation.

Implement: instrument missing boundaries qua existing stage lifecycle, correct
stage attribution khi errors; map frame → pose → train → metric/finalization
dependencies bằng source thực. Record first verified/published SOG time và timing
coverage. Freeze benchmark identity/quality guard và numeric target trước
optimization. Baseline hardware là Quadro T2000 nhưng power/thermal condition chưa
được lưu; paired acceptance yêu cầu capture hoặc đánh dấu rõ missing.
Tests: incomplete timestamps, retry/cached stage, human wait, overlapping intervals,
failed/cancelled attempts, old schema, actual frame cap and timing serialization.
**Exit:** [x] versioned partial/terminal metric contract, per-stage timing coverage,
actual frame inventory, user wait and verified preview timing; [x] target and quality
guard frozen for paired evaluation. Repeated hardware baseline/power condition remain
pending for S3 acceptance; this sprint does not claim the latency target is met.

## Sprint AUD-15.S2 — Eliminate measured redundant work

**Input:** S1 bottleneck evidence + compatible immutable stage outputs.
**Output:** minimal cache/reuse/I/O or scheduling changes with verified identities.
**Contract:** final input/config checksum và quality unchanged; no unsafe GPU overlap;
cancel terminates child before resources released; stale lease cannot publish.

Implement: select only measured hot paths, reuse verified frame/pose preparation
when keys match, avoid repeat downloads/model loads if lifecycle permits. CPU/I/O
overlap chỉ ở independent DAG nodes và trong admission budget. Không chạy Brush,
MoGe/SAM hoặc voxel memory workloads đồng thời trên T2000 chỉ vì dùng thread.
Cache miss chạy normal path có diagnostics; deterministic failure không retry loop.
Tests: cold/warm equivalence, changed input/config/tool invalidation, corrupt cache,
restart/cancel, lease conflict, bounded memory và output/checksum consistency.
**Exit:** [ ] eliminated work measured; [ ] quality/resource/recovery guards hold.

## Sprint AUD-15.S3 — Paired benchmarks và product ETA

**Input:** frozen baseline/optimized profiles + independent quality witnesses.
**Output:** repeated paired report, supported hardware envelope và truthful ETA/UI.
**Contract:** separate cold/warm and preview/final runs; queue/wait not hidden;
latency improvement cannot compensate failed geometry/obstacle quality gates.

Implement: repeat runs on fixed dataset/runtime/hardware, record distributions,
frame counts, peak resource use and partial failures. Compare quality using
existing rendering/pose/geometry protocols plus AUD-12 retention witnesses where
applicable. Update observed estimator with supported completed samples; uncertain
profile shows indeterminate waiting/ETA uncertainty. Record bottlenecks remaining
on this hardware rather than claim a universal technology impossibility.
Tests: estimator ignores incomplete/incompatible samples, UI queued/running/waiting,
paired report identity and negative quality guard; real GPU benchmark acceptance.
**Exit:** [ ] measured target met or explicit measured shortfall; [ ] no quality regression.

## Verification và DoD

```bash
.venv/bin/pytest tests/integration/test_studio_processing_job.py tests/test_orchestration/test_job_progress.py tests/test_orchestration/test_resource_telemetry.py tests/test_orchestration/test_observed_budget.py tests/test_orchestration/test_processing_config.py tests/test_reconstruction/test_rec04_brush.py -q
```

Planned tests/test_orchestration/test_pipeline_timing.py. DONE cần executed paired
benchmarks đạt target đã freeze và quality gates; unit timing fixtures không chứng
minh latency thực. Hardware-bound compute cost phải có số đo và supported envelope.

## Result / Evidence

### AUD-15.S1 — Implemented; hardware acceptance pending

- Schema 1.1 separates partial and terminal snapshots, full job wall, attempt wall,
  queue, metric-confirmation wait, per-stage intervals, critical path, ResourceUsage
  process sum/interval union, actual frame count and timing coverage. Schema 1.0
  remains readable.
- Product attempt journal now preserves `stage_started_at`, the actual extracted
  frame count and consumer-verified preview time. Prepare stages publish start/end
  timestamps. Failed/cancelled stage completion is represented from terminal event.
- `eval/protocols/pipeline_runtime.md` defines collection and paired comparison;
  `eval/results/BENCHMARK_REPORT.md` removes the unsupported “40–45 min for a full
  300–500-frame job” and “achieved” claims.
- Frozen target: same `input_manifest_checksum`, `config_checksum`,
  `runtime_manifest_checksum`, 50-frame inventory, Quadro T2000 and selected config;
  median `worker_process_seconds ≤ 4.541,45 s` (at least 10% below the one-run
  5.046,05 s baseline) over at least three baseline/optimized pairs with existing
  visual, pose, metric, collision and scene quality gates preserved.
- Baseline source: `data/studio_local/runtime.db`, job manifest and resource usage
  for `job-6bc02e5de4ed`; 50 frames, 30k Brush iterations, 1280 px, 1M max splats.
  Job lifecycle: 57.388,70 s; metric-confirmation wait: 52.338,88 s; recorded worker
  process sum: 5.046,05 s. Power/thermal state is absent; this is not paired
  acceptance. Existing different-identity snapshot is not used as a repeat.
- Tests: `tests/test_orchestration/test_pipeline_timing.py`,
  `tests/test_orchestration/test_job_progress.py`,
  `tests/integration/test_studio_processing_job.py`,
  `tests/test_reconstruction/test_rec_prepare_input.py`.
- Remaining for S3: repeat the baseline under recorded power/thermal conditions,
  run paired optimized trials, and evaluate quality gates. No quality or latency
  acceptance is claimed from unit fixtures.
