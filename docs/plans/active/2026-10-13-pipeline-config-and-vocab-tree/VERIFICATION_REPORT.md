# CFG-15 verification — 2026-10-13

Configuration now flows from scenario preferences through the suggestion API, sealed job artifacts and typed resolution to native tool commands. The wizard and advanced controls share this configuration. CFG-02 through CFG-14 have separate commits and task evidence.

## Scope and changes

- `tests/integration/test_config_pipeline_e2e.py`: four HTTP integration cases, indoor/outdoor × smooth/faces, use real scene creation and command builders. Both COLMAP flag namespaces enable loop detection and reference the staged vocabulary. Indoor uses external fill 1.6; outdoor uses floor fill 1.6. Scene and simulation values survive dispatch.
- `tests/integration/test_direct_upload_minio.py`: successful upload fixtures now contain real FFmpeg MP4 content. A valid MP4 free box exercises multipart upload. Previous random and seven-byte payloads correctly failed content validation; production validation remains intact.
- Task status and this report record the acceptance evidence. `src/models/contracts/manifests.py` was not modified by this task.

## Executable evidence

Logs are under `tasks/reports/`.

| Check | Result | Log |
| --- | --- | --- |
| Simulated configuration E2E | 4 passed | CFG15-E2E-VERIFICATION.log |
| Default complete backend suite | 2984 passed, 30 opt-in cases skipped | CFG15-BACKEND-REGRESSION.log |
| Configured complete backend suite | 3013 passed, one KISS-ICP case skipped | CFG15-BACKEND-CONFIGURED.log |
| Explicit KISS-ICP supplement for that skipped case | 1 passed, pinned runtime 1.3.0 | CFG15-KISS-ICP.log |
| Ruff check, entire src/tests | Clean | CFG15-RUFF-CHECK.log |
| Ruff format check, entire src/tests | 609 files already formatted | CFG15-RUFF-FORMAT.log |
| Complete frontend Vitest | 539 passed, 65 files | CFG15-FRONTEND-REGRESSION.log |
| Frontend typecheck | Exit 0 | CFG15-TYPECHECK.log |
| Frontend production build | Exit 0 | CFG15-PRODUCTION-BUILD.log |
| Native splat codec coverage | 83 passed, one GPU case initially skipped | CFG15-NATIVE-CODEC.log |
| Native GPU coverage | 2 passed | CFG15-NATIVE-GPU.log |
| Isolated MinIO/PostgreSQL coverage | 25 passed | CFG15-LOCAL-SERVICES.log |
| Offline LiDAR CLI and deterministic output | 2 passed | CFG15-OFFLINE-LIDAR.log |
| Both pinned vocabulary asset checksums | Valid | CFG15-VOCAB-ASSETS.log |

All 3014 collected backend cases were exercised successfully across the configured complete run and its one-case KISS-ICP supplement. This is not a single zero-skip run. Other supplemental suite counts overlap the complete suite and must not be added together. The isolated offline runtime uses the hashed `requirements-offline.lock.txt`, including Open3D 0.19.0. MinIO and PostgreSQL use disposable local containers and private temporary credentials; no credentials belong in committed evidence.

## Acceptance boundaries

The configuration E2E simulates native execution after validating actual generated commands. Supplemental native codec, GPU and LiDAR tests run their real tools on synthetic fixtures. These establish local integration and regression coverage, not full reconstruction of a user scene, cloud deployment, provider availability, Isaac runtime or production performance.

CFG-13/14 contain actual Chrome wizard and read-only sample checks. They used an isolated local API without a reconstruction worker. The production build compiles successfully; it does not establish authenticated deployed UX acceptance. Existing unrelated metric/viewer/upload changes remain outside the CFG-15 commit.

## Pre-flight — GUIDE.md Rule 13

- codegraph: current command builders, job dispatch, upload validation and integration-test relationships inspected; graphify queries used and AST graph updated after source changes.
- impact: test-only additions and corrected success fixtures; no shared production symbol changed in CFG-15.
- understand: preferences → suggestion → scene creation → sealed configuration → native command generation. UNVERIFIED: understand-anything plugin unavailable; current source and executable HTTP tests supplied the flow evidence.
- minimal-code: reused existing API fixtures, typed resolvers, command builders and FFmpeg; no production abstraction or validation bypass added.
- checks: complete backend/static/frontend results above are terminal and successful. HTTPX emitted 15 existing cookie deprecation warnings, with no failures.
- DevTools: n/a for CFG-15 test/document changes; CFG-13/14 record local browser evidence and its limits.
