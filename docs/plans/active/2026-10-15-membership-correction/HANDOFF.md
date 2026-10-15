# Visual Gaussian membership correction → regeneration — implementation handoff

Branch `mvp-pipeline-v2`, local commits only (no push/merge/PR). Implementation and automated CPU/fixture
verification are complete. Real GPU, browser-on-ObjectGS-scene and Isaac acceptance are NOT done; they
require running the full pipeline on a new capture.

## Commits

| Commit | Scope |
| --- | --- |
| `7971957a`, `dcac0974` | Surface cleanup → evidence-gated repair → quality gate before strict CoACD; raw/processed surface, repair/quality reports, checksums, provenance ([surface handoff](../2026-10-15-objectgs-surface-quality/HANDOFF.md)). |
| `f31f3bfa` | Revision- and source-checksum-bound selection of source Gaussian rows; read-only preview. |
| `59ec9370` | `OBJECTGS_RETRAIN_REQUIRED` block replaced by queued `membership` regeneration with fenced SceneIR publication. |
| `b644cce8` | Studio Box/Brush/Lasso editor (SuperSplat selection tools) mapped to immutable source PLY rows. |
| `99054d5a` | New routes classified in the role matrix (contributor + job-owner guard). |

## Implemented flow

1. Studio `ObjectReviewView` → "Chỉnh vùng Gaussian · Box / Brush / Lasso" (ObjectGS scenes only; legacy keeps ROI
   correction). `GaussianMembershipEditor` opens the bundled SuperSplat editor with `membershipSource=<sha256>`;
   the editor loads only the immutable source PLY and verifies its checksum before use.
2. Selection is exported through SuperSplat's Morton upload permutation (`sourceFileRows`) and instance
   `sourceRow` indirection (`vendor/supersplat/src/source-selection.ts`) → exact original PLY rows. Moved/rotated
   poses never determine ownership.
3. `POST /scene/membership/preview` (read-only) returns added/removed counts, affected objects, protected
   (floor/background-locked) and wrong-owner rows, remaining Gaussians per object. Apply stays disabled until a
   preview for the identical command succeeds; ownership change invalidates the preview.
4. `POST /scene/membership/regenerate` (202) enqueues `mode=membership` on the existing objectify queue: lease,
   `operation_id`-scoped cancel, revision fence, retry by re-opening the editor.
5. Worker (`membership_regeneration.py`): new membership labels → corrected per-view masks from source rows (no
   SAM rerun) → existing ObjectGS producer → surface export → cleanup/repair/QA → strict CoACD → object-aware
   environment collision → atomic SceneIR publish. Any failure/cancel/stale revision leaves the active scene
   untouched; no stale artifact is reported as new output.
6. `ObjectifyNotice` shows phase, failure/cancel and "scene hiện tại được giữ"; Studio reloads only after success.

Reused unchanged: ObjectGS runner/producer, CoACD convex runner, effective collision compositor (shared by
Walk and USD), SceneIR revision/publication, objectify queue + cancellation, SuperSplat selection tools.
Pose-only Move/Rotate still edits SceneIR without training.

Design note: regeneration re-runs the existing shared multi-label ObjectGS model (the upstream trains one model
for all labels), not a separate model per affected object. Object IDs and edited poses are preserved.

## Verification (2026-10-15)

- Backend `pytest tests`: 3216 passed, 28 skipped (after role-matrix fix). Correction-focused suites: 50 passed,
  0 skipped — includes real isolated CoACD on a corrected fixture → new SceneIR → collision compositor → OpenUSD
  with bounds matching Move/Rotate and no double carving.
- `ruff check` / `ruff format --check`: PASS.
- Frontend vitest: 637/637 PASS; `object-review.test.tsx` "hủy selection … conflict 409" is timing-flaky under
  full-suite load (pre-existing, passes on rerun). `npm run typecheck` PASS; `npm run lint` 0 errors (7 old warnings).
- SuperSplat vendor eslint PASS; `npm run build:editor` PASS (rebuilds `public/editor`, gitignored).

Tests added: `test_membership_selection.py`, `test_membership_regeneration.py`, queue/route/diagnostic cases,
`source-selection.test.ts`, `gaussian-membership-editor.test.tsx`; lifecycle (Move/Rotate/Hide/Delete/Restore keep
Gaussian+collider bound) in `object-review.test.tsx`.

## Not accepted (needs a new scene)

- ObjectGS GPU retrain after correction, real mask quality, real surface passing QA (the saved 8,000-iteration
  Room surface is still rejected: open mesh).
- Browser interaction with Box/Brush/Lasso on an ObjectGS scene (only legacy Room rev-100 was available).
- Walk physics feel and Isaac Sim loading of the regenerated USD.

## End-to-end run on a new scene

1. `cd frontend && npm run build:editor` (once per SuperSplat change), start API/worker/Studio as in RUNTIME.md.
2. Process the new capture with `geometry_method=objectgs` so the scene has `object_aware_collision_ref`.
3. Studio → select object → "Chỉnh vùng Gaussian" → Box/Brush/Lasso add/remove → Preview → Apply.
4. Watch the notice phases; verify new revision, surface/QA report, collider parts, environment collision.
5. Move/Rotate → Walk; export USD and open in Isaac. Test Cancel mid-run and a forced QA failure: old revision
   must remain active.
