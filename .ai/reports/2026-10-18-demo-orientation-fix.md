# Demo 3DGS orientation fix — 2026-10-18

## Outcome

Sample demos now carry the same confirmed SfM-to-display rotation used by the Studio preview. The demo viewer applies it consistently to the Gaussian scene and recording cameras. Metric Z-up scenes ignore this raw-SfM display rotation to avoid applying it twice. Legacy demo bundles without the optional field remain readable.

The defect was missing display-orientation metadata in demo export and its frontend handoff. Raw SOG bytes and camera poses were already correct; neither reconstruction nor camera files needed rewriting.

## Changed files

- `src/services/orchestration/jobs/stage_views.py`: extract the existing confirmed-preview rotation into `preview_display_rotation`; retain source-visual and camera-reference matching.
- `src/services/orchestration/samples/models.py`: optional finite unit quaternion on the demo manifest.
- `src/services/orchestration/samples/export.py`: persist the shared confirmed display rotation during export.
- `frontend/src/lib/contracts/studio.ts`: parse and validate the optional quaternion.
- `frontend/src/features/studio/SampleScene.tsx`, `SceneWorkspace.tsx`, `scene/PreviewScene.tsx`: forward the rotation to both scene rendering and initial recording-camera placement.
- `tests/test_orchestration/test_preview_orientation.py`, `test_sample_export.py`, `tests/test_api/test_sample_routes.py`, `frontend/tests/preview-scene-camera.test.tsx`: matching provenance, missing poses, export persistence, malformed quaternions, full sample-viewer handoff, legacy fallback, and metric-scene protection.

## Local sample publication

Published replacement bundles through the exporter and existing publication lock/unpublish lifecycle. Old bundles were unpublished, with their original manifests and artifact files preserved. Each replacement has the same 14 artifact files and original camera arrays as its predecessor.

| Source job | New active sample | Cameras | Confirmed floor-up residual after display rotation |
| --- | --- | ---: | ---: |
| `job-f9f14e7fbfb1` | `drjohnson-f9f14e7f-d7be7c91-aligned` | 263 | 2.23e-16 |
| `job-bfc7d73f0dbf` | `mip-nerf-360-room-images-4-bfc7d73f-024f857c-aligned` | 311 | 4.56e-16 |
| `job-7c9820b4834f` | `playroom-7c9820b4-784cdd45-aligned` | 149 | 2.46e-16 |

Residual is the Euclidean difference between the rotated confirmed floor normal and display up `[0, 1, 0]`. Before the fix, the corresponding up-axis errors were 95.46°, 26.50°, and 42.10°.

Verified the fresh sample API list and each manifest, streamed each public SOG endpoint, and checked its checksum against the original. Original manifest checksums and original artifact inventories were checked after publication. Evidence: `/tmp/p087-aligned-demo-publication.json`, `/tmp/p087-aligned-api-samples.json`, `/tmp/p087-demo-camera-audit.json`.

## Runtime

Verified no queued/running jobs before restarting the native Studio stack with its existing configuration. Production frontend build passed; Studio on port 3010 and API on port 8010 returned HTTP 200. The sample list and an aligned sample scene route returned HTTP 200. Runtime parent PID at handoff: `662396`; log: `/tmp/p087-demo-orientation-stack.log`.

Open `http://localhost:3010/new/try-demo`, reload the list, and open a replacement sample. An already-open old sample URL points to its unpublished bundle.

No Cloudflare deployment or commit/push was performed for this fix. No reconstruction was rerun. DevTools was not used for this implementation or verification, per user instruction; live browser/GPU visual acceptance is unverified. Exact recording-camera roll replay remains a separate existing limitation.

## Verification

| Command / check | Result |
| --- | --- |
| `.venv/bin/pytest tests/test_orchestration/test_preview_orientation.py tests/test_orchestration/test_sample_export.py tests/test_api/test_sample_routes.py -q --tb=short` | **63 passed** |
| `vitest run tests/preview-scene-camera.test.tsx tests/source-frame.test.ts tests/studio-demo-showcase.test.tsx tests/studio-sample-pipeline.test.tsx tests/import-scene-page.test.tsx --reporter=dot` (frontend) | **54 passed**, 5 files |
| Final rerun `vitest run tests/preview-scene-camera.test.tsx --reporter=dot` after adding the supplied-rotation metric guard assertion | **14 passed** |
| `tsc --noEmit --incremental false` (frontend) | Passed |
| ESLint on four changed TS source files and the changed frontend test, `--max-warnings=0` | Passed, including final rerun |
| Scoped Ruff check and format check on six changed Python files | Passed |
| `.venv/bin/ruff check src/ tests/` | Passed |
| `.venv/bin/ruff format --check src/ tests/` | 723 already formatted; one pre-existing failure in `tests/test_orchestration/test_prepared_queue.py` |
| Wider frontend run including `studio-inspection.test.tsx` | 73 passed, 2 failed on existing LiDAR label expectations |
| Untouched `HEAD` snapshot: `studio-inspection.test.tsx` | 19 passed, same 2 failed; baseline log `/tmp/p087-demo-camera-baseline-inspection.log` |
| Untouched `HEAD` copy: format check of `test_prepared_queue.py` | Same existing formatting failure |
| `graphify update .` | Completed; generated graph is ignored |
| `git diff --check` | Passed before report; rerun at handoff |

## Pre-flight gate report

1. **codegraph:** Used graphify query and CodeGraph to trace demo export, Studio confirmed orientation, sample component handoff, and viewer/camera transforms before edits.
2. **minimal-code:** Reused the Studio rotation calculation; added one optional manifest field and a small prop handoff. Kept artifact coordinates, units, and original data intact.
3. **checks:** Focused backend/frontend regressions, type/lint checks, production build, local artifact/API checks completed. Existing unrelated suite/format failures are recorded above.
4. **report:** This document records the change, local publication, evidence, and limits. Work remains uncommitted.
