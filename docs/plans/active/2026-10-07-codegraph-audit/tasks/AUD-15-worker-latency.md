# AUD-15 — Đo và giảm worker latency theo stage

## Metadata và goal

- PLANNED; P1; EX-PRODUCT + EX-REC; SCENE/SIM quality consumers.
- Canonical PRODUCT-02/08/09, REC-02/03/04/11. REUSE pipeline_runtime benchmark,
  processing telemetry/observed budget và existing retry cache.
- Goal: giảm thời gian xử lý không cần thiết, giữ selected quality và đo đúng
  queue, compute, publication, user waiting, time-to-first-preview và full job.
- [Agent guide](../AGENT_GUIDE.md), [Gemini evidence](../GEMINI_FINDINGS.md),
  [AUD-16](AUD-16-fast-preview.md).

## Baseline và scope

PipelineRuntimeBenchmark/build_benchmark đã tồn tại. total_seconds hiện lấy
min(start) đến max(completed stage); record RUNNING không chứng minh full job.
Hai local attempts có Brush ~42,6–45 phút nhưng chưa geometry/object finalization.
max_frames=300 là config cap. Không có evidence cho mọi job 300–500 frames mất
40–45 phút hoặc 7k iterations luôn 5 phút.

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

Proposed extension của benchmark hiện có: measurement completeness, actual frames,
per-stage queue/active compute/I/O or publication/user-wait intervals, cache hit
identity và first usable visual ref/time. Chốt serialization trong S1, giữ đọc
schema 1.0; missing observation là null/unknown, không là zero. Ghi wall time
và critical path riêng; không cộng durations của stages overlap làm full elapsed.
Không suy GPU billing từ toàn bộ user waiting; cost estimate cần measured allocation.

Cache key phải bao gồm source byte/logical identity phù hợp, preparation/selection
config, pose/frame binding, tool/runtime version và stage parameters. Cached output
phải verify checksum/required files trước reuse; config mismatch/missing/corrupt
artifact không được đánh dấu hit. Existing retry cache là baseline để đánh giá.
Observed estimator dùng measured supported profiles, không gán estimated time
thành progress percent thật hoặc sửa user-selected config.

## Dependencies

S1 độc lập. S2 dùng resource invariants hiện có; operation admission extensions
theo AUD-07 nếu optimization chạm heavy operations. S3 phối hợp AUD-12 quality
protocol và AUD-16 preview timings; không đợi full Fast Preview để đo pipeline cũ.

## Sprint AUD-15.S1 — Complete timing và frozen benchmark protocol

**Input:** current benchmark/journals + actual input/frame/config/runtime refs.
**Output:** compatible timing extension, stage dependency map và reproducible protocol.
**Contract:** partial attempt khác terminal job; unknown khác zero; actual frames
khác cap; queue/metric confirmation wait khác active computation.

Implement: instrument missing boundaries qua existing stage lifecycle, correct
stage attribution khi errors; map frame → pose → train → metric/finalization
dependencies bằng source thực. Record first verified/published SOG time và timing
coverage. Freeze hardware/power mode/tool/profile/data split; choose bottleneck
và numeric improvement target từ baseline trước optimization, không đoán speedup.
Tests: incomplete timestamps, retry/cached stage, human wait, overlapping intervals,
failed/cancelled attempts, old schema, actual frame cap and timing serialization.
**Exit:** [ ] reproducible stage/elapsed metrics; [ ] target/quality guard frozen.

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

Pending — actual frames/input/config/tool/hardware, completeness, queue/compute/
publish/wait, cold/warm distribution, target, quality evidence và remaining bottlenecks.
