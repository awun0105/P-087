# Object pipeline evidence — implementation handoff

Branch: `mvp-pipeline-v2`. Local commits only; no push or merge. This change records decisions;
it does not improve segmentation quality, alter thresholds, retrain a scene or repair geometry.

## Implementation

- SAM2 records generated mask scores, visible-point counts and view/prompt identity. Segmentation
  records IoU/min-points/NMS decisions, prompt support/voting, overlap merges, floor/cluster filtering
  and final instance decisions. Accepted/rejected means the existing algorithm's decision, not ground truth.
- Stable membership digests join prompt groups to seed indexes; seed-to-candidate bindings join these
  to object IDs. Membership records floor removal, contribution/spatial filtering, tiny-object returns
  to background, object counts and conservation totals.
- ObjectGS records numeric-label/object mapping, pinned runtime/config metadata, training/export phase
  starts/completions/failures and surface finite/triangle/watertight checks. Strict collider validation
  records component/open-component counts and each component's actual CoACD decomposition metadata.
- Collider results distinguish CoACD, convex hull fallback, hull merging to satisfy the existing part
  budget, explicit AABB fallback and failure. Scene collider provenance now names the actual method.
  No fallback has been added to the strict ObjectGS path.
- Each retry attempt seals `ObjectPipelineEvidence` through the existing artifact publisher, including
  failed/cancelled attempts. The manifest binds job, unique run, input SceneIR revision, config checksum,
  bundle checksum and source artifact references. Producer success is called `produced`; it does not
  claim that a new SceneIR revision has been published. Successful results reference evidence in provenance.
- A failed evidence write logs an explicit warning and cannot replace the pipeline's original result/error.
  Provider log tails are bounded and scrubbed for local paths/credentials. Raw scratch provider logs retain
  their existing behavior and are not copied in full into artifacts.

## Limits and retention

Per stage: 1 MiB JSONL events, 2 MiB compressed mask samples and at most 32 unique samples.
Events/reason totals continue after the JSONL quota; coverage records omitted decisions/samples.
Mask samples are deterministic first retained masks, not representative statistical sampling.
The collector reads at most 8 MiB of stage files, prioritizing metadata before mask blobs, and seals
at most 16 MiB per attempt including JSON/base64 overhead. Provider tails are at most 8 KiB/file,
256 KiB total before sanitization. Truncated/incomplete evidence is explicitly reported.

Masks are losslessly packed big-endian and zlib compressed, with independent packed-bit SHA-256.
Full raster buffers, Gaussian score matrices and all training intermediates are not duplicated.
Retention follows existing job artifact storage/deletion; no separate retention daemon or database exists.

Evidence sealing runs on normal completion, Python failure and controlled cancellation. Hard power loss
or SIGKILL can leave only scratch JSONL; it cannot execute the final publication step. Existing runs,
including the paused Room process, do not gain historical evidence. A future authorized pipeline run
is needed for real-scene evidence; no GPU run was started for this implementation.

## Read evidence

Use the same registry/artifact environment as the local worker (for this workstation it is configured
in `scripts/gpu/studio.env`). Run from the repository root with that environment exported:

```bash
.venv/bin/python scripts/scene/diagnose_object.py --job-id JOB_ID
.venv/bin/python scripts/scene/diagnose_object.py --job-id JOB_ID \
  --checksum sha256:CHECKSUM --object-id candidate-001 \
  --output /tmp/object-report.md --export-masks /tmp/object-masks
# Alternative: an explicit reference saved in the attempt workspace
.venv/bin/python scripts/scene/diagnose_object.py --reference PATH_TO_evidence-ref.json
```

Listing does not silently choose the latest attempt. Select its immutable checksum and check the input
revision. The report can still be read after scratch cleanup because it uses the published artifact.
This is an administrator CLI using the configured local artifact resolver, not a new browser/API feature;
remote-only artifacts must first be available to that resolver. Mask export verifies checksum and bounded
zlib decompression before producing PNGs. Objects rejected before candidate ID assignment must be inspected
by prompt/instance/seed in the run-level report.

The report identifies the first *recorded* rejection/warning, not the first proven quality defect.
Missing coverage, quota omissions or early producer failure can prevent a complete per-object join.
Semantic correctness still needs image/mask inspection and independent quality evaluation.

## Findings for the next segmentation improvement

1. Prior SAM2 NPZs retained sparse support and scores but not rejected mask decisions or bounded visual masks.
2. Filtering/merge/background decisions were not linked across prompt, seed and published object IDs.
3. Legacy collider metadata could claim CoACD after convex-hull fallback. Only metadata is corrected here.
4. Existing ObjectGS receipts/logs are reused; successful mesh export alone does not prove correct object ownership,
   complete geometry, browser collision quality or Isaac Sim acceptance.

The paused Room run, Brush/COLMAP/3DGS and scene rev-100 with 60 objects were not changed. Thermal monitoring
remains local operational tooling; no thermal policy was added to production code.

## Verification

Final command results are recorded below after completion. CPU fixture SAM2/lift comparisons verify exact
NPZ/label/summary equality; they use fake predictors/rasterization and do not validate GPU inference.
Real CoACD CPU tests exercise decomposition and injected fallback geometry equality. ObjectGS lifecycle tests
use a controlled subprocess fixture, not training on a GPU. No browser or Isaac Sim acceptance is claimed.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: explored objectify/_seeds/_run, SAM2 runner/pipeline, segment/_surviving_records, lift,
  ObjectGS prepared/runtime functions and convex_parts/surface_parts/build_one; checked affected callers.
- impact: objectify retries/extraction, isolated scene producers, collider metadata and artifact provenance;
  new read-only diagnostic CLI. No render state, UI command, geometry algorithm or threshold changes.
- understand: UNVERIFIED — understand-anything tools unavailable. Manually traced producer request → isolated
  runtime → result/receipt → membership/object bindings → artifact publication and retry/cancel boundaries.
- minimal-code: reused stdlib bounded JSONL/zlib, existing Pydantic/ProductArtifactRef and publisher/resolver;
  reused ObjectGS receipts/logs and current validation computations. No new service/database/UI.
- checks: see executable verification results below; ESLint/Vitest related tests n/a, no frontend files changed.
- DevTools: n/a — UI-free instrumentation/reporting. Browser/GPU/Isaac behavior remains unverified.

### Executed checks (2026-10-15)

- `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest tests/test_scene tests/test_simulation tests/test_contracts tests/test_orchestration/test_object_diagnostics.py tests/test_orchestration/test_scene_extraction.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_scene_editor.py -q`
  → **688 passed in 69.09s**. Log: `/tmp/p087-evidence-final-regression.log` (local, temporary).
- `ruff check src/ tests/ scripts/scene/diagnose_object.py` → **All checks passed**.
- `ruff format --check src/ tests/ scripts/scene/diagnose_object.py` → **643 files already formatted**.
- `.venv/bin/python scripts/check_contract_mirror.py` → **PASS**, 5 enums / 6 models match.
- `npm run typecheck` in `frontend/` → **PASS**, route type generation and `tsc --noEmit`, exit 0.
- `.venv/bin/python scripts/scene/diagnose_object.py --help` → **PASS**. CLI replay/report after scratch
  removal is also covered in the 688-test suite using the real filesystem artifact store.
- `git diff --check` → **PASS**.
- `graphify update .` → **PASS**, 23,938 nodes / 74,246 edges / 783 communities. Extractor reports 37
  code files without symbols; this is graph coverage, not evidence that all runtime call paths are known.

The tests include checksum/job mismatch rejection, exact mask restoration, corrupt mask rejection,
failure/cancellation durability, log bounds/redaction, write-failure isolation, quota accounting,
per-object linkage, ObjectGS lifecycle fixtures and strict/legacy collider regression.
- After the final view-identity metadata adjustment, reran
  `pytest tests/test_scene/test_diagnostic_runners.py -q` → **1 passed in 2.58s**; array equality still holds.

Local implementation commits: `f9c1a42e` (segmentation evidence foundation), `512923ef` (durable attempt
artifacts, runner instrumentation and read-only reports). Documentation is committed separately.

## Refinement follow-up (2026-10-15)

The opt-in algorithm and its synthetic quality evaluation are documented in the
[segmentation refinement handoff](../2026-10-15-segmentation-refinement/HANDOFF.md).
Existing evidence now includes refinement decisions and per-object prompt-list merge events.
The evidence artifact format, quotas and publication/cancellation semantics are unchanged.
