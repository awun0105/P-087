# Benchmark worker/runtime provenance fix — 2026-10-18

## Outcome

Fixed only audit findings F1 and F3, as requested.

- Runner benchmark snapshots now probe the executing worker directly using the existing capability probe. A newer heartbeat from another worker cannot supply this snapshot. OSError/ValueError from the probe leaves machine=null and still publishes the timing snapshot.
- Tool timing selection accepts the compatible worker software checksum in addition to a legacy job's full checksum only when the existing ExecutionProfile.accepts_runtime rule authorizes that job. Existing job/config/time-window filters remain in place. An incompatible worker profile does not authorize unrelated telemetry.

## Scene impact

No Gaussian, mesh, collider, SceneIR, transform, source input, runtime database or existing immutable benchmark artifact was changed. No service was restarted and no pipeline was rerun. Existing snapshots remain historical records; regenerated benchmark calculations for compatible legacy jobs may now include previously omitted telemetry. Future runner snapshots use the current executing worker's measurements once the running worker loads this code. Existing in-memory worker processes were not reloaded by these edits.

## Changed files

- `src/services/orchestration/jobs/runner.py`: current-worker probe in _record_benchmark with unavailable-machine fallback.
- `src/services/orchestration/benchmark.py`: compatible legacy runtime selection in _tool_timings.
- `tests/test_orchestration/test_benchmark_provenance.py`: five cases covering two workers, probe failure, modern/legacy runtime, incompatible runtime, wrong job/config and out-of-window telemetry.
- This report and tests.txt; graphify generated artifacts updated as required.

## Verification

New regression suite on old source, after correcting a fixture database URL typo: **3 failed, 2 passed**. Failures reproduced wrong worker selection, invalid fallback to another worker, and omitted legacy telemetry.

Focused checks after the fix:

```text
.venv/bin/python -m pytest tests/test_orchestration/test_benchmark_provenance.py tests/test_orchestration/test_pipeline_timing.py tests/test_orchestration/test_machine_runtime_provenance.py tests/test_orchestration/test_observed_budget.py tests/test_orchestration/test_value_scorecard.py tests/test_orchestration/test_capability.py -q -ra
98 passed in 0.95s
```

Final run added worker cleanup and real-prepare integration coverage:

```text
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 nice -n 15 .venv/bin/python -m pytest tests/test_orchestration/test_benchmark_provenance.py tests/test_orchestration/test_pipeline_timing.py tests/test_orchestration/test_machine_runtime_provenance.py tests/test_orchestration/test_observed_budget.py tests/test_orchestration/test_value_scorecard.py tests/test_orchestration/test_capability.py tests/test_orchestration/test_worker_cleanup.py tests/integration/test_studio_processing_job.py -q -ra
129 passed in 8.13s; 0 failed, 0 skipped

.venv/bin/ruff check src/ tests/
All checks passed!
.venv/bin/ruff format --check src/ tests/
724 files already formatted
git diff --check
exit 0
```

This is local focused/backend integration evidence, not a live multi-worker deployment acceptance run. The other audit findings (budget accounting, time completeness and cost limitations) are outside this change.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: _record_benchmark, build_benchmark, _tool_timings, capability.probe, ExecutionProfile.accepts_runtime and machine_runtime_checksum; graphify query first.
- impact: runner preview/finalize/failure/prepare recording paths; build_benchmark callers including benchmark collector and integration tests. Signatures and exported schema unchanged.
- understand: executing worker → snapshot; legacy full checksum ↔ compatible software identity → tool timing selection.
- minimal-code: rung 2 — existing worker probe and runtime compatibility rule; 12 inserted / 2 removed production lines across two files.
- checks: final 129 passed, no skips; Ruff/format/diff clean. Frontend typecheck/eslint/vitest n/a — no frontend changes.
- DevTools: n/a — no rendered UI behavior change.
- Git/runtime: no commit, push, branch change, restart or existing artifact/database mutation.
