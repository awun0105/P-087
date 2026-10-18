# Audit benchmark, timing, configuration, hardware and cost — 2026-10-18

## Conclusion

The measurement system is implemented but not complete enough to treat every displayed figure as an end-to-end benchmark or historical infrastructure cost. Four correctness issues were reproduced with current production functions. Additional cost/configuration limitations are distinguished below from defects. No production source or tests were modified during this audit.

Scope: current working tree, backend collectors/projections, benchmark persistence, value metrics, configuration/runtime provenance, GPU budget and frontend metric/operator-time tests. Live evidence was read from local SQLite using mode=ro and referred artifacts. No pipeline, cloud or Isaac execution was used as evidence.

## Reproduced correctness issues

### F1 — P1: runtime snapshot can identify another worker's hardware

- `src/services/orchestration/jobs/runner.py:690` calls global `latest_capability(database)` rather than selecting the worker executing the attempt.
- `src/services/orchestration/processing/capability.py:255-266` reads all worker rows and selects the most recent fresh heartbeat, with no job/worker binding.
- Probe: worker A/T4 is the stipulated execution context; worker B/A40 heartbeats one second later. `_record_benchmark` receives B/A40 for the snapshot. This is a deterministic multi-worker reproduction, not an assertion that a local T2000 run used an A40.
- Impact: hardware snapshots, CPU/RAM/VRAM denominators and grouping by GPU can be wrong in multi-worker deployments. A later immutable snapshot preserves the wrong attribution.
- Correction boundary: attach the executing worker's capability to the attempt, then retain it in historical snapshots. Do not query the globally newest worker to describe a run.

### F2 — P1: GPU-hour cap forgets failed/cancelled/timeout execution

- `src/services/orchestration/processing/gpu_budget.py:19-21` uses `billed_usages`; `processing/observed.py:96-105` discards non-completed records and retains only the latest completed pipeline run per tool.
- `_gpu_budget_at_start` in `jobs/runner.py:243-254` uses that value to decide whether another execution may start.
- Probe: a previous failed GPU preview consumed 2 hours; cap is 1 hour. The function returns `(0.0, 1)` and allows another execution when no duration estimate is available.
- Impact: the configured per-scene limit does not cap actual cumulative execution across retries. Repeated failures can consume additional hours without appearing in the spent total. CPU-only completed usages also enter this budget function; the value-cost function applies a different GPU-name filter.
- Correction boundary: distinguish cumulative resource consumption for enforcement from the selected successful-run metric for comparing reconstructions. Include failed, cancelled, timeout and interrupted execution in cumulative accounting, with an explicit policy for unknown telemetry.

### F3 — P2: valid telemetry of supported legacy jobs is filtered out

- `_tool_timings`, `src/services/orchestration/benchmark.py:284-286`, requires the usage runtime checksum to equal `JobManifest.runtime_manifest_checksum`.
- Current sampler in `jobs/runner.py:405-410` deliberately writes `machine_runtime_checksum`, which is the worker software checksum; supported legacy jobs can carry the full hardware-inclusive checksum (`jobs/profile.py:34-40,74-80`).
- Probe: one valid usage in the time window gives zero selected records for the legacy full checksum, and one record for the software checksum. The existing machine-runtime provenance tests confirm this distinction is supported.
- Impact: worker duration/count appear unavailable even though a real measured usage exists. Value metrics can still show a duration because they filter usages by job ID, so views disagree.
- Correction boundary: bind tool records to actual execution/attempt identity and the documented legacy/runtime compatibility rules without weakening config/runtime identity checks.

### F4 — P2: incomplete time measurements look like complete measured totals

- `src/services/orchestration/evaluation/scorecard.py:805-823` removes all stages whose duration is None, sums the remainder and displays it as processing time with no completeness flag.
- `src/services/orchestration/value/scorecard.py:156-161` similarly reports whatever completed tool records exist as provenance=measured. That Figure has no per-stage coverage information; `benchmark_summary:709-718` can include it in GPU-group medians.
- Probe A: missing CAMERA_POSE timing plus 30 measured seconds of VISUAL_RECON produces processing_time=30, verdict=None, with a description calling it the total time of the current attempt.
- Probe B: only a 60-second prepare record produces measured machine_minutes=1.0, note=None.
- Live example: playroom's manifest is SUCCEEDED, but telemetry contains a failed finalize and no completed finalize. The selected total is 98.36 minutes and is incomplete. This example demonstrates data coverage, not proof that the current collector generated every historical record.
- Correction boundary: expose time scope and coverage to all consumers; retain known partial durations but label them partial and exclude incomplete totals from full-pipeline comparisons by default.

## Functionality gaps / interpretation limits

### Cost is an estimate over selected execution, not a billing ledger

- Runtime benchmark intentionally writes `gpu_allocated_seconds=None` and `estimated_gpu_cost_usd=None` (`benchmark.py:448-450`). A supplied hourly rate alone does not enable cost there.
- Value cost instead multiplies selected completed process duration by the CURRENT `settings.benchmark_gpu_hourly_usd` (`value/scorecard.py:179-187,653`). It is correctly labelled declared, but not frozen historical spend.
- Probe: the same 1-hour usage costs $0.50 with rate 0.5 and $1.00 with rate 1.0. No job-data change is required. The historical snapshot rate is not used by `build_scorecard`.
- Failed executions, old successful reruns, provider allocation idle time, storage and transfer are not part of this estimate. A recorded GPU name establishes the host GPU, not GPU busy time. Provider cost and utilization require additional records.
- The live snapshots inspected have rate=null and estimated cost=null. Do not report that as a measured zero cost.

### Full configuration exists, but benchmark export is not a complete effective-config snapshot

- The immutable `config/processing.json`, verified by the job config checksum, includes grouped tool configuration and fixed overrides. This is a sound provenance boundary.
- `build_benchmark:382` exports only `.params`, omitting effective fields outside params, such as COLMAP num_threads/use_gpu and anonymize. In the live drjohnson configuration, effective num_threads=4 and use_gpu=false exist in `.colmap`, but not in `.params`.
- The checksum allows retrieving the full source configuration while the artifact store is available; the standalone benchmark row is not self-contained. `gpu_power_limit_watts`, active compute, I/O and publication durations are also unpopulated fields in the current builder.

### Historical job status and snapshots can disagree

- Live playroom currently has a SUCCEEDED manifest, but its saved attempt-2-terminal benchmark still says FAILED; no newer terminal snapshot was present at audit time.
- This is historical reconciliation evidence. It does not by itself prove a normal current runner transition is faulty: the run may have been repaired outside that publication path.
- Existing partial/terminal artifacts are immutable, and benchmark recording logs exceptions without failing the job. There is no completeness guarantee or automatic repair demonstrated by these records.

### Human effort is browser interaction telemetry

- Frontend operator clock, ordered sends with one retry, server interval validation and per-session overlap rejection exist. These are tested.
- This is not a complete labor ledger: network/page-close delivery can remain unrecorded; distinct sessions/users can contribute overlapping intervals. Report it as recorded active interaction, not automatically as labor saved or customer effort per accepted scene.

## What is already implemented and verified

- Stage/attempt/job timestamps, queue and user-wait separation, interval-union worker wall time, reused-stage handling, partial/terminal schema and timing issue fields.
- Resource samples include monotonic duration, outcome/exit status, peak RAM/VRAM, sample counts, process attribution, shared-GPU context and job/config/runtime identities. Null is used for unavailable observations.
- Per-job immutable processing artifacts and checksums; snapshot models; provenance labels measured/declared/unavailable; JSON/CSV/Markdown exports; benchmark selection and frontend rendering.
- LPIPS filename pairing fix from the preceding task remains tested; original drjohnson LPIPS is still pending the separate rerender task and is not supplied by this audit.

## Verification

- Core backend command in `tests.txt`: **164 passed in 12.48s**, 0 failed, 0 skipped.
- Additional evaluation, GPU budget, expected duration, processing and capability suites in `additional-tests.txt`: **91 passed in 3.63s**, 0 failed, 0 skipped.
- Frontend value card, benchmark page, operator clock/page and evaluation card: **5 files, 35 passed in 11.09s**, 0 failed, 0 skipped (`frontend-tests.txt`).
- Total: **255 backend + 35 frontend tests passed**. These are focused suites, not the full repository or live browser/cloud acceptance.
- `reproduce.py`: six synthetic probes executed against production functions; assertions confirm the observed issues/limitations, rather than asserting those behaviors are correct. Results: `reproduction-results.json`.
- Live read-only manifest/usage/snapshot summary: `live-summary.json`.
- `.venv/bin/ruff check src/ tests/`: All checks passed.
- `.venv/bin/ruff format --check src/ tests/`: 723 files already formatted.
- `git diff --check`: exit 0.

## Recommended order

1. Correct worker binding and cumulative budget enforcement.
2. Correct legacy telemetry selection and surface timing completeness consistently.
3. Define separate comparable-run time, cumulative execution time and provider allocation cost; freeze rates by scope when historical cost is required.
4. Export effective configuration and reconcile missing/stale snapshots without rewriting immutable history.

No production fix, database mutation, pipeline execution, commit, push or branch change was made in this audit. The earlier LPIPS recovery automation was left unchanged.
