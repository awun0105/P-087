# PR-02 — Representation Lifecycle, Visual Conservation & Hide/Show Correctness

Date: 2026-10-14. Status: implementation and automated verification complete locally; browser/Isaac acceptance **UNVERIFIED**. No push, remote branch, GitHub PR, merge, or master update.

## Baseline and scope

Branch `codex/pr02-representation-lifecycle`, clean baseline `73fa65bc594f37982db4e6cd85ad307ce1e7d345`, isolated managed worktree. The original checkout remains on `codex/browser-collider-frame-correctness` at that same baseline with its six uncommitted PR-01 files. SHA-256 comparisons confirmed all six remained unchanged.

PR-02 does not contain PR-01. Integration testing after PR-01 is committed/combined is still required. No edits to segmentation, Gaussian lifting/splitting or membership correction algorithms, source collision ownership, carving, TSDF, CoACD, reconstruction, browser collider loading, or object transform editing algorithms.

## Validated causes and corrected assumptions

* Studio's old Hide called backend `hide` and changed `active`, a SceneIR revision, and export state. Gaussian visibility and orange outlines did not consistently share that condition; Candidate outlines remained because Candidate was considered placed independently of `active`.
* `set_object_active` previously allowed Candidate activation and recorded disabling as `last_scene_operation=delete`. The legacy HTTP action name `hide` is retained for compatibility, with an explicit strict boolean and confirmed-only simulation semantics.
* `_hybrid_layers` skipped every inactive object before checking Pending. Candidate and Ignored source Gaussians were consequently omitted. Its remaining Pending path used current object translation, losing immutable extraction pose after Move.
* `environment.visual_master_ref` in objectify is **background_inpainted PLY**, not the complete source. Complete source and immutable label bytes are bound by `environment.membership`.
* Existing Delete/Restore/Duplicate lifecycle commands already distinguish tombstones, restored Candidate/Confirmed state, and independent duplicates. Their algorithms did not need replacement. Collision source preservation/removal remains the existing ownership implementation.

## Implementation and flow

`scene_representations` is a pure policy projection. It resolves SOURCE / OBJECT / OMIT independently of viewport visibility. SOURCE pose comes only from existing `source_collision.source_transform`, with source geometry and extraction revision context checked. Objectify's supported source PLY axes are world-aligned; nonidentity source rotation produces `SOURCE_ROTATION_UNSUPPORTED`, never an invented rotation/SH bake.

Scene GET and edit DTOs carry `representations` without changing or re-checksumming SceneIR. Studio consumes this projection. A required SOURCE visual uses `source:<object_id>` at extraction pose A. A URL-less editing entity and outline stay at current pose B for a Pending preview/gizmo. There is one Gaussian representation and no independent Pending rigid body. Ignored source remains visible without an outline/gizmo. Missing source policy/pose displays a blocker and cannot render the Gaussian at a guessed current pose.

Viewport Hide/Show uses job-scoped `hiddenIds`, hides Gaussian and outline, retains list selection, and sends no API mutation. Delete and merged-secondary tombstones prune hidden IDs when accepting a scene. The separate confirmed-only simulation button sends an explicit boolean against the current revision/CAS. Browser physics object inputs remain independent of viewport hiding.

`representation_issues` is read-only. It verifies membership label checksum/count/map/context, complete source checksum, object source PLY checksum/layout/count, world positions recovered using immutable source translation, and exact non-position attributes (opacity, scale, quaternion, SH and other fields). It checks original background rows before appended inpaint rows against current membership and declared fill count. It rejects using the full source as background. A `NO_SOURCE_GAUSSIANS` claim is allowed only when sealed membership proves no owned rows. No source files or labels are rewritten.

Preflight adds `REPRESENTATION_INCOMPLETE` when relevant. Capability reports include explicit SOURCE blockers, require hybrid mode for inactive SOURCE visuals, and derive physical/exported objects only from OBJECT disposition. `_hybrid_layers` repeats integrity verification before runner execution; SOURCE goes into environment `extra_gaussians` at A, OBJECT keeps its current pose and collider, OMIT emits neither. Capability/cache contract is `usd-export-capabilities-v3`; stale v2 reports/packages cannot be reused or admitted by the low-level builder.

## State matrix

Previously the principal export filter was `active`; Pending/Ignore therefore disappeared and Move was reused as source pose. After PR-02:

| Lifecycle | Gaussian representation | Independent object/collider | Viewport Hide effect |
| --- | --- | --- | --- |
| Pending Candidate | SOURCE at extraction A | No; editable outline at current B | Hide source and outline locally |
| Ignored Candidate | SOURCE at extraction A | No; no outline/gizmo | Hide source locally |
| Confirmed active | OBJECT at current pose | Existing collider/physics | Hide render/outline; simulation unchanged |
| Confirmed inactive | OMIT | No exported object | Source is not restored |
| Deleted | OMIT | None | Tombstone remains auditable |
| Merged secondary | OMIT | None | Hidden ID pruned; primary represents union |
| Restored Candidate | SOURCE | No | Local visibility can be shown again |
| Restored Confirmed | OBJECT active | Existing collider/physics | Local visibility independent |
| Duplicate | OBJECT at duplicate pose | Independent object; no source claim | Independent local visibility |

Legacy unsplit scenes without separate object Gaussians retain their global visual path. Per-object hiding cannot erase rows baked into a legacy global visual. Split legacy scenes without trustworthy membership/pose fail readiness with explicit blockers; this PR does not regenerate or guess legacy assets.

## Local implementation commits

| SHA | Message / scope |
| --- | --- |
| `941412fd` | Define source and object visual representation policies — pure resolver/state matrix |
| `c94fec6e` | Separate confirmed simulation activation from hide and delete — strict bool, domain validation, regression |
| `6cd788e5` | Keep viewport visibility local and separate from simulation activation — Gaussian/outline visibility |
| `73fbf639` | Project immutable source visual poses into Studio representation overlays — API projection/source A vs preview B |
| `a9cd885f` | Conserve pending source Gaussians in hybrid USD and block unverified representations — exporter/preflight/capability/cache |
| `f0d8f970` | Validate source background conservation and reject missing Studio source metadata — background, merge/empty/stale evidence regressions |

This handoff is committed separately after those tested implementation steps. `git log 73fa65bc..HEAD` gives the complete log including its own documentation commit.

## Verification evidence

All commands below ran from the PR-02 worktree, with frontend commands in `frontend/`.

```bash
.venv/bin/pytest \
 tests/test_scene/test_representation_composition.py \
 tests/test_scene/test_editing_review.py \
 tests/test_scene/test_editing_v2.py \
 tests/test_scene/test_object_membership.py \
 tests/test_scene/test_scene_rush_pipeline.py \
 tests/test_api/test_scene_routes.py \
 tests/test_simulation/test_representation_conservation.py \
 tests/test_simulation/test_usd_capabilities.py \
 tests/test_simulation/test_preflight.py \
 tests/test_orchestration/test_simulation_package.py \
 tests/test_simulation/test_collision_edit_composition.py \
 tests/test_simulation/test_usd.py \
 tests/test_simulation/test_simulation_config_override.py -q
# 193 passed, 35.46 s; no skips/failures

.venv/bin/ruff check src/ tests/
# All checks passed
.venv/bin/ruff format --check src/ tests/
# 613 files already formatted

./node_modules/.bin/vitest run
# 65 files passed, 552 tests passed, 30.01 s
./node_modules/.bin/tsc --noEmit
# exit 0
./node_modules/.bin/eslint \
 src/features/studio/ObjectReviewView.tsx \
 src/features/studio/MetricSceneView.tsx \
 src/lib/contracts/api.ts tests/object-review.test.tsx
# exit 0

git diff --check
# exit 0

graphify update .
# AST-only update completed: 23225 nodes, 72206 edges, 735 communities
```

Frontend emits the existing Multiple instances of Three.js warning in viewer tests; tests still pass. jsdom substitutes the 3D canvas and is not actual browser rendering evidence.

The conservation suite has 19 passing tests, including 60 inactive Candidates, Move→Ignore, Delete/Restore policy, merged-label union emitted once, verified empty membership, absent/corrupt/stale source/pose/context/labels/attributes/background, and a **real local USD runner** test. The real runner writes 61 environment Gaussian particles, no object bodies, and reads generated `UsdVol.ParticleField3DGaussianSplat` positions/count/SH degree back with pxr. Byte-level fixtures also compare every original Gaussian attribute and preserve source/labels bytes. This is structural USD proof only, not physics or Isaac rendering acceptance.

## Acceptance matrix

| AC | Automated evidence | Remaining acceptance |
| --- | --- | --- |
| AC-01 Viewport Hide | PASS jsdom: Gaussian and outline both hide/show; other object unchanged; no API request/save revision | UNVERIFIED actual Studio `candidate-006` / WebGL |
| AC-02 Candidate conservation | PASS 60-candidate byte fixture + real USD ParticleField count/positions | UNVERIFIED production 60-candidate job |
| AC-03 Ignore != Delete | PASS state policy and Move→Ignore source request; deleted/restored policy | UNVERIFIED manual browser/Isaac |
| AC-04 Confirmed Hide | PASS local viewport state separated from strict confirmed simulation toggle/CAS; candidate activation rejected | UNVERIFIED live browser physics |
| AC-05 Correct source pose | PASS immutable A used after Move to B then Ignore; no independent Pending object | UNVERIFIED Isaac display |
| AC-06 No silent loss | PASS specific `REPRESENTATION_INCOMPLETE` FAIL and capability blockers for missing/corrupt/stale evidence, wrong background/full-source reuse | UNVERIFIED deployed artifact inventory |
| AC-07 Data integrity | PASS source/labels byte checks, existing CAS/revision tests, six original PR-01 SHA-256 matches; producer/correction algorithms unchanged | No real jobs mutated |
| AC-08 Regression | PASS 193 backend + 552 frontend, full Python lint/format, TS typecheck/scoped ESLint | Browser/Isaac explicitly UNVERIFIED |

## Gate report and review notes

* **codegraph:** Original repository index queried for policy consumers, edit commands, scene DTOs, preflight, export capability, `_hybrid_layers`, and low-level builder/callers before source changes. Isolated worktree initially had no CodeGraph/graphify index; current code was read directly there. Required `graphify update .` completed using AST only after changes. No `understand-anything` review tool was available; that tool-specific gate is UNVERIFIED.
* **minimal-code:** Existing fields and source artifacts reused; only API projections/pure policy/integrity added. SOURCE rotation/layout unsupported cases block explicitly. No alternate source reconstruction or lifecycle migration introduced.
* **checks:** Commands/results above; failures during implementation (test routing, old capability version assertions, USD reader API typo) were fixed before the relevant commits. The final run has no failures.
* **report:** This committed handoff contains causes, behavior, tests, acceptance limits and commit evidence.

Integrity checks read source PLY/membership and compare per-object rows. Export/preflight cost scales with source size and required objects; measure memory/runtime on a production-size job before deployment. Strict background validation relies on the current producer/correction layout: original background rows followed by a declared number of inpaint rows. Unknown/stale layouts are blocked, not flattened or regenerated. Source rotations require a separate supported SH-aware representation if future producers introduce them.

PR-03 still owns effective collision composition/Walk parity. PR-04 still owns multipart/static collider browser physics. PR-01 frame correctness is not included here. No Node/Ammo/pxr pass is claimed as complete browser/Isaac acceptance. Chrome DevTools inventory exposed only `about:blank`; no authenticated Studio acceptance session was run. Runtime/dependency symlinks are local tooling only and not committed.
