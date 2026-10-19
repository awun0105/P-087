# Production Web Performance — PERF-01

Status: implemented and verified locally; production acceptance remains open.

Scope authorized in the 2026-10-16 conversation: begin with a reproducible baseline and optimize preview verification, then report before/after evidence. This task does not complete the broader production performance program. Starting branch: `mvp-pipeline-v2`; starting HEAD: `9c36b419b38782b94c30d84d214a92ff75d14fae`. Existing unrelated worktree changes were preserved. The user subsequently requested a scoped PERF-01 commit. Push and deployment were not requested or performed.

During execution, other work advanced HEAD to `b2d78260` through three T-036 commits affecting runtime-qualification scripts, their test and `.ai` reports/status. Those commits do not overlap PERF-01 files. This task did not create those commits or modify the unrelated changes.

## Outcome

Repeated `ProjectRegistry.get_preview()` calls no longer rehash unchanged visual, camera and SOG payloads. The small preview JSON and its job/input/attempt linkage are checked on every call. Publication consumption through the default `load_job_preview()` and all existing `ArtifactResolver.require()` / `require_uri()` calls remain strict.

The opt-in resolver path retains successful verification for at most 512 dependency versions per resolver, guarded by a lock for cache access. A cache entry binds logical URI, expected checksum, device, inode, size, mtime_ns and ctime_ns. Changed/missing files, changed checksums and unsafe paths are not accepted using an old cache entry. Mutation detected across a hash is rejected. Errors are never cached. Cold remote payloads still pass through the existing fetch/checksum path.

This is a process-local optimization for ordinary local filesystem caches that report file changes in stat metadata. It is not a durable receipt, remote-object freshness check, protection against silent storage corruption with unchanged metadata, or a replacement for strict validation at actual artifact consumption/publication. Process restarts, cache eviction and changed payloads require hashing again. Concurrent cold misses may both hash; there is no global hash lock or single-flight queue.

No shared schema, database migration, persisted state, API response, readiness policy, source geometry, training preset or renderer quality changed.

## Before/after evidence

Run from the repository root:

```bash
.venv/bin/python -m scripts.benchmark.preview_readiness --out /tmp/preview-readiness.json
```

The command writes opaque 128 MiB source and 16 MiB SOG payloads in a temporary directory, plus small camera/preview JSON, then performs five strict reads and five registry reads. The first read is separated from the median of the four subsequent reads. It does not read the configured runtime DB or production data. Payloads are not valid rendered 3D assets.

| Measurement | Before | After |
| --- | ---: | ---: |
| First registry preview read | 482.690 ms | 434.265 ms |
| Subsequent registry reads, median | 471.3195 ms | 1.176 ms |
| Bytes hashed per subsequent registry read | 150,996,408 | 1,462 |
| Strict consumer reads, subsequent median | 497.152 ms | 458.918 ms |
| Bytes hashed per strict consumer read | 150,996,408 | 150,996,408 |

Raw samples: [before](evidence/preview-before.json), [after](evidence/preview-after.json). The reliable work reduction is removal of repeated large payload hashing. Timings are local warm-filesystem samples, not production SLOs. The first read still performs full verification; its timing difference is not claimed as an improvement. The fixture excludes DB/auth, HTTP/proxy, remote storage, browser decoding and GPU rendering. Endpoint and page latency are not 1.176 ms merely because this isolated path is.

## Changed files

- `src/services/orchestration/artifacts/store.py`: bounded opt-in verification reuse; existing strict verification shares the unchanged local fetch/resolve helper.
- `src/services/orchestration/projects/preview.py`: explicit reuse option, strict by default.
- `src/services/orchestration/projects/registry.py`: opt preview reads into reuse.
- `scripts/benchmark/preview_readiness.py`: repeatable temporary fixture baseline with elapsed time and bytes hashed.
- `tests/test_orchestration/test_preview_verification_cache.py`: invalidation, corruption, strict-consumer and bounded-cache regressions.
- This report and its two JSON evidence files.

## Verification

Red baseline: 12 failing new tests, 4 passing; repeated preview metadata loads performed 8 checksum checks across two calls rather than the expected 5. Failures for the new resolver method/limit were expected before implementation.

Green focused command:

```bash
.venv/bin/pytest tests/test_orchestration/test_preview_verification_cache.py tests/test_orchestration/test_artifact_store.py tests/test_orchestration/test_artifact_remote.py tests/test_orchestration/test_artifact_download_links.py tests/integration/test_product_rec_preview.py tests/test_orchestration/test_job_progress.py tests/test_api/test_studio_routes.py tests/test_orchestration/test_pipeline_timing.py -q
```

Result: **117 passed in 8.93s**, including 16 new cases. Coverage includes equal-size writes, restored mtime, replacement inode, deletion, changed expected checksum, separate roots, unsafe symlink targets, failed verification, writes during hashing, remote eviction/corruption, cache capacity, repeated metadata and input-lineage verification, corruption of each dependency, and strict consumption after the cache is warm. Remote cases use an in-memory object store; they do not qualify live R2/S3.

Static checks:

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/ruff check scripts/benchmark/preview_readiness.py
.venv/bin/ruff format --check scripts/benchmark/preview_readiness.py
git diff --check
```

All passed. `graphify update .` completed with AST-only extraction (26,944 nodes, 83,829 edges); no semantic relabeling was requested. No frontend files were changed, so tsc/eslint/vitest and rendered-UI DevTools checks are not applicable to this task. The benchmark command also executed successfully before and after the source change.

## Remaining work and acceptance

The next scoped task is bounded server-side scene pagination/latest-job batching and a lightweight Overview aggregation. Follow with PostgreSQL connection reuse if PostgreSQL is the deployed backend, the polling visibility race, frontend/viewer profiling, and hosting/load tuning. These are not implemented by PERF-01.

Production acceptance requires the deployed revision, URL/access and deployment topology, then measurements of first/repeated navigation, auth/scenes/progress requests, viewer first frame/frame times, CPU/RAM/I/O, DB connection wait/query time and concurrent use while the pipeline runs. No production URL or deployment access was supplied for this task, so these measurements remain unverified. PRD NFR-02 requires baseline measurement before locking the interaction target; this report does not introduce a new product SLO.

Rollback: revert only the opt-in on `ProjectRegistry.get_preview()` to restore strict dependency hashing for all preview reads. The change has no migration or stored cache to reverse.

## Pre-flight — GUIDE.md Rule 13

- codegraph: explored preview loader, registry getter/publication/allow-list, artifact resolver, callers and related tests before edits; graphify query/explain used for preview lineage.
- impact: registry reads affect scenes/progress readiness, artifact authorization/stage views, export/evaluation and benchmark readers. Worker publication uses the strict default. Strict resolver callers retain the existing behavior; their common resolve/fetch body was extracted without a semantic change.
- understand: source and contract tracing covered worker publication → committed JobManifest → preview identity → dependencies → product readiness/download. `UNVERIFIED: understand-anything — no callable tool exposed`; CodeGraph, graphify and current PRD/architecture/shared contract were used instead.
- minimal-code: rung 2/3 — reuse resolver fetch/checksum behavior plus stdlib OrderedDict/Lock/stat; no new dependency, persistent cache, schema or service.
- checks: Ruff source/tests and benchmark clean; format clean; focused pytest 117 passed; benchmark before/after recorded; tsc/eslint/vitest n/a for Python-only changes.
- DevTools: n/a — UI-free service change. Production HTTP/browser/GPU acceptance is unverified.
